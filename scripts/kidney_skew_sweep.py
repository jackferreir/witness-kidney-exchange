#!/usr/bin/env python3
"""Does the hospital-withholding manipulation incentive concentrate in
LARGE hospitals? Same exhaustive per-hospital withholding search as
`scripts/kidney_real_data_sweep.py` / the K=3 variant behind
`results/kidney_k3_real_sweep_v2/summary.json`, on the SAME real Pansart
et al. 2022 compatibility graphs (`witness.kidney_real_data`) -- but under
SKEWED, declared, seeded ownership partitions (`witness.kidney_ownership`)
instead of the roughly-equal-size partition those two scripts always use.

WHY: real transplant centers are highly unequal (Agarwal et al. 2019: 62%
of US kidney-exchange transplants occur WITHIN a single hospital), and
hospital size is the theoretically obvious driver of the withholding
incentive this project searches for -- a hospital that can match many of
its own pairs internally has something to gain by keeping them off the
central pool; a hospital that owns one or two pairs generally cannot. The
existing sweeps cannot distinguish "the incentive is rare" from "the
incentive concentrates in large hospitals and we never built one," because
every hospital in them is roughly the same size. This script builds large
hospitals on purpose and records, for EVERY hospital it checks (not just
hospitals with a hit), that hospital's SIZE, its STANDALONE value (the most
pairs it could match using ONLY its own pairs, cycles <= K -- computed by
clearing a one-hospital sub-market of exactly its owned pairs and edges),
and whether a profitable withholding deviation exists -- so the relationship
between size and manipulability can be measured directly, broken down by
size bucket, rather than asserted.

WHAT IS REAL AND WHAT IS SYNTHETIC (same honesty requirement as
`witness.kidney_real_data` and `scripts/kidney_real_data_sweep.py`): the
compatibility graph is REAL. The hospital-ownership partition -- including
its SIZE DISTRIBUTION -- is SYNTHETIC, declared, and seeded
(`witness.kidney_ownership`), never real hospital identity or behavior.

HOW A MARKET IS BUILT: `witness.kidney_real_data.load_real_kidney_market`
is called ONCE per (member, draw) with `n_hospitals=1` purely to obtain the
REAL `pairs`/`edges` (a single-hospital call makes that loader's OWN inline
ownership partition inert -- everything lands in one hospital, which is
discarded); `witness.kidney_ownership.build_ownership` then produces the
actual (skewed or uniform) partition used to build the real `KidneyMarket`.
This reuses the existing loader's real-data parsing without modifying it
and without duplicating its zip-reading code.

EVERY COUNTED MANIPULATION replays independently
(`witness.replay_kidney.verify_in_subprocess`, a fresh subprocess) before
being counted, exactly like `scripts/kidney_real_data_sweep.py`.

COST DISCIPLINE (why per-hospital exhaustive search needs its OWN space
cap, stricter than `witness.search_kidney.DEFAULT_MAX_REPORT_SPACE`):
checking every hospital in a market (not just one per draw, as the existing
sweeps do) multiplies cost by the hospital count, and a genuinely large
hospital's `2**k` report space is the entire point of this script -- so a
hospital whose report space exceeds `--max-report-space` is SKIPPED (never
silently truncated, never counted as "no manipulation") exactly like an ILP
solve that exceeds `--max-ilp-seconds` is skipped by `find_hospital_
manipulation`'s own `IlpTimeLimitExceeded` -- both are recorded, both make
the measured rate an UNDER-count for the largest hospitals specifically,
never a fabricated one. This is the honest limitation to report alongside
any headline number: the very largest centers are the ones most likely to
be skipped, so their true rate could be even higher than what gets counted.

RESUMABLE, INCREMENTAL: every hospital-row is appended to `hospital_rows.
jsonl`, flushed and fsynced immediately, keyed by a stable `check_id`; on
startup, already-recorded `check_id`s are read back and skipped -- a run
interrupted by the laptop sleeping resumes exactly where it left off,
never re-doing or double-counting a check.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from witness.errors import ModelError
from witness.kidney import (
    TIEBREAK_LEX_SMALLEST_BY_INDEX,
    TIEBREAK_MAX_CARDINALITY_BLOSSOM,
    TIEBREAK_MAX_CARDINALITY_ILP,
    IlpTimeLimitExceeded,
    KidneyConfig,
    KidneyMarket,
    KidneyProfile,
    clear_kidney_exchange,
)
from witness.kidney_ownership import REGIME_CORE_PERIPHERY, REGIME_POWER_LAW, REGIME_UNIFORM, build_ownership
from witness.kidney_real_data import load_real_kidney_market, real_instances_for_p
from witness.replay_kidney import verify_in_subprocess
from witness.search_kidney import find_hospital_manipulation
from witness.runlog import begin_run

REGIME_CHOICES = (REGIME_UNIFORM, REGIME_POWER_LAW, REGIME_CORE_PERIPHERY)

#: Size buckets for the headline size-vs-vulnerability breakdown. Upper
#: bound inclusive; the last bucket is open-ended. Declared here as a named
#: constant, not incidental to the aggregation code below.
SIZE_BUCKETS = ((1, 2), (3, 5), (6, 10), (11, 20), (21, None))


def _bucket_for(size: int) -> str:
    for lo, hi in SIZE_BUCKETS:
        if hi is None:
            if size >= lo:
                return f"{lo}+"
        elif lo <= size <= hi:
            return f"{lo}-{hi}"
    raise AssertionError(f"size {size} matched no bucket")  # pragma: no cover - SIZE_BUCKETS starts at 1


def _regime_params_for(regime: str, p: int, args) -> dict:
    if regime == REGIME_UNIFORM:
        return {"n_hospitals": max(1, round(p / args.pairs_per_hospital))}
    if regime == REGIME_POWER_LAW:
        return {"n_hospitals": max(1, round(p / args.pairs_per_hospital)), "exponent": args.power_law_exponent}
    if regime == REGIME_CORE_PERIPHERY:
        return {
            "n_large": args.core_n_large,
            "large_size": args.core_large_size,
            "periphery_chunk": args.core_periphery_chunk,
        }
    raise ValueError(regime)  # pragma: no cover - argparse restricts choices


def _standalone_value(market: KidneyMarket, hospital: str, config: KidneyConfig):
    """The most pairs `hospital` could match using ONLY its own pairs and
    ONLY its own (real) internal edges, cycles <= config.max_cycle_length --
    by clearing a one-hospital sub-market of exactly its owned pairs.
    Returns (value, skip_reason); skip_reason is None on success."""
    owned = market.pairs_of(hospital)
    owned_set = set(owned)
    sub_edges = frozenset((u, v) for (u, v) in market.edges if u in owned_set and v in owned_set)
    sub_market = KidneyMarket(pairs=owned, hospital_of={p: hospital for p in owned}, hospitals=(hospital,), edges=sub_edges)
    sub_profile = KidneyProfile.truthful(sub_market)
    try:
        result = clear_kidney_exchange(sub_market, sub_profile, config)
    except IlpTimeLimitExceeded as exc:
        return None, f"ilp_timeout_standalone: {exc}"
    return result.utility[hospital], None


def run_one_config(
    p: int, max_cycle_length: int, regime: str, args, config: KidneyConfig, done_ids: set, rows_f, conf_f, fail_f,
) -> dict:
    members = real_instances_for_p(p)
    size_idx = args.sizes.index(p)
    draws_per_member = args.draws_per_member[size_idx]
    regime_params = _regime_params_for(regime, p, args)

    n_checked = 0
    n_confirmed = 0
    n_verification_failures = 0
    n_skipped_report_space = 0
    n_skipped_ilp_timeout = 0
    n_skipped_standalone_timeout = 0
    t0 = time.perf_counter()

    for member in members:
        base_market, _, _ = load_real_kidney_market(
            member, n_hospitals=1, ownership_seed=args.ownership_seed, ownership_draw_index=0,
        )
        for draw in range(draws_per_member):
            try:
                hospital_of, hospitals, own_meta = build_ownership(
                    base_market.pairs, args.ownership_seed, draw, regime, **regime_params
                )
            except ModelError as exc:
                print(f"  [skip config: ownership params invalid at p={p}] {regime} {regime_params}: {exc}", file=sys.stderr)
                return {
                    "p": p, "max_cycle_length": max_cycle_length, "regime": regime,
                    "regime_params": regime_params, "skipped_entirely": True, "reason": str(exc),
                }

            market = KidneyMarket(
                pairs=base_market.pairs, hospital_of=hospital_of, hospitals=hospitals, edges=base_market.edges,
            )
            profile = KidneyProfile.truthful(market)

            for hospital in sorted(hospitals, key=lambda h: len(market.pairs_of(h))):
                check_id = f"{p}|{max_cycle_length}|{regime}|{member}|{draw}|{hospital}"
                if check_id in done_ids:
                    continue

                size = len(market.pairs_of(hospital))
                standalone_value, standalone_skip = _standalone_value(market, hospital, config)
                if standalone_skip is not None:
                    n_skipped_standalone_timeout += 1

                report_space_size = (2 ** size) - 1
                row = {
                    "check_id": check_id,
                    "p": p,
                    "k": max_cycle_length,
                    "regime": regime,
                    "regime_params": regime_params,
                    "ownership_seed": args.ownership_seed,
                    "member": member,
                    "draw_index": draw,
                    "hospital": hospital,
                    "hospital_size": size,
                    "standalone_value": standalone_value,
                    "standalone_skip_reason": standalone_skip,
                    "report_space_size": report_space_size,
                    "checked": False,
                    "skip_reason": None,
                    "manipulation_found": False,
                    "gain": 0,
                    "witness_id": None,
                    "witness_verified": None,
                }

                if report_space_size > args.max_report_space:
                    row["skip_reason"] = "report_space_too_large"
                    n_skipped_report_space += 1
                else:
                    try:
                        w = find_hospital_manipulation(market, profile, hospital, config, max_space=2 ** size)
                    except IlpTimeLimitExceeded as exc:
                        row["skip_reason"] = f"ilp_timeout: {exc}"
                        n_skipped_ilp_timeout += 1
                    else:
                        row["checked"] = True
                        n_checked += 1
                        if w is not None:
                            row["manipulation_found"] = True
                            row["gain"] = w.false_utility - w.truthful_utility
                            d = w.to_dict()
                            d["_skew_sweep_ownership"] = own_meta.to_dict()
                            ok, reasons = verify_in_subprocess(w.to_dict())
                            row["witness_id"] = w.witness_id
                            row["witness_verified"] = ok
                            if ok:
                                n_confirmed += 1
                                conf_f.write(json.dumps(d) + "\n")
                                conf_f.flush()
                                os.fsync(conf_f.fileno())
                            else:
                                n_verification_failures += 1
                                fail_f.write(json.dumps({"witness": d, "reasons": list(reasons)}) + "\n")
                                fail_f.flush()
                                os.fsync(fail_f.fileno())

                rows_f.write(json.dumps(row) + "\n")
                rows_f.flush()
                os.fsync(rows_f.fileno())
                done_ids.add(check_id)

    wall = time.perf_counter() - t0
    return {
        "p": p,
        "max_cycle_length": max_cycle_length,
        "regime": regime,
        "regime_params": regime_params,
        "skipped_entirely": False,
        "n_real_members": len(members),
        "draws_per_member": draws_per_member,
        "n_checked": n_checked,
        "n_confirmed": n_confirmed,
        "n_verification_failures": n_verification_failures,
        "n_skipped_report_space_too_large": n_skipped_report_space,
        "n_skipped_ilp_timeout": n_skipped_ilp_timeout,
        "n_skipped_standalone_timeout": n_skipped_standalone_timeout,
        "manipulation_rate": n_confirmed / n_checked if n_checked else None,
        "wall_seconds": wall,
    }


def _load_done_ids(rows_path: str) -> "tuple[set, list]":
    done_ids: set = set()
    existing_rows: list = []
    if os.path.exists(rows_path):
        with open(rows_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                done_ids.add(row["check_id"])
                existing_rows.append(row)
    return done_ids, existing_rows


def _summarize(all_rows: "list[dict]") -> dict:
    by_config: dict = {}
    by_bucket: dict = {}
    for row in all_rows:
        if not row.get("checked"):
            continue
        ckey = (row["p"], row["k"], row["regime"])
        c = by_config.setdefault(ckey, {"n_checked": 0, "n_manipulable": 0})
        c["n_checked"] += 1
        if row["manipulation_found"] and row.get("witness_verified"):
            c["n_manipulable"] += 1

        bucket = _bucket_for(row["hospital_size"])
        b = by_bucket.setdefault(bucket, {"n_checked": 0, "n_manipulable": 0, "sizes": []})
        b["n_checked"] += 1
        b["sizes"].append(row["hospital_size"])
        if row["manipulation_found"] and row.get("witness_verified"):
            b["n_manipulable"] += 1

    per_config = []
    for (p, k, regime), c in sorted(by_config.items()):
        per_config.append({
            "p": p, "k": k, "regime": regime,
            "n_checked": c["n_checked"], "n_manipulable": c["n_manipulable"],
            "manipulation_rate": c["n_manipulable"] / c["n_checked"] if c["n_checked"] else None,
        })

    def _bucket_sort_key(item):
        lo = int(item[0].split("+")[0].split("-")[0])
        return lo

    per_size_bucket = []
    for bucket, b in sorted(by_bucket.items(), key=_bucket_sort_key):
        per_size_bucket.append({
            "size_bucket": bucket,
            "n_checked": b["n_checked"],
            "n_manipulable": b["n_manipulable"],
            "manipulation_rate": b["n_manipulable"] / b["n_checked"] if b["n_checked"] else None,
            "mean_size": sum(b["sizes"]) / len(b["sizes"]) if b["sizes"] else None,
        })

    return {"per_config": per_config, "per_size_bucket": per_size_bucket}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--sizes", type=int, nargs="+", default=[250, 100, 50])
    p.add_argument("--draws-per-member", type=int, nargs="+", default=[1, 2, 3],
                    help="synthetic ownership draws per real graph, aligned index-wise with --sizes")
    p.add_argument("--cycle-lengths", type=int, nargs="+", default=[3, 2], choices=[2, 3])
    p.add_argument("--regimes", type=str, nargs="+", default=list(REGIME_CHOICES), choices=list(REGIME_CHOICES))
    p.add_argument("--pairs-per-hospital", type=int, default=6,
                    help="target average hospital size for REGIME_UNIFORM/REGIME_POWER_LAW's n_hospitals")
    p.add_argument("--power-law-exponent", type=float, default=0.5)
    p.add_argument("--core-n-large", type=int, default=2)
    p.add_argument("--core-large-size", type=int, default=8)
    p.add_argument("--core-periphery-chunk", type=int, default=2)
    p.add_argument("--ownership-seed", type=str, default="kidney-skew-sweep-v1")
    p.add_argument("--max-report-space", type=int, default=2 ** 12,
                    help="a hospital whose 2**size - 1 report space exceeds this is SKIPPED, not counted "
                         "(see module docstring's COST DISCIPLINE)")
    p.add_argument("--max-ilp-seconds", type=float, default=60.0)
    p.add_argument("--out-dir", type=str, default="results/kidney_skew_sweep")
    args = p.parse_args()

    if len(args.sizes) != len(args.draws_per_member):
        raise SystemExit("--sizes and --draws-per-member must have the same length")

    os.makedirs(args.out_dir, exist_ok=True)

    # Provenance + exclusive lock: see witness/runlog.py. A second live

    # writer on one out-dir is what corrupted results/samesolver_k3.

    begin_run(args.out_dir, note="ownership skew sweep")
    rows_path = os.path.join(args.out_dir, "hospital_rows.jsonl")
    confirmed_path = os.path.join(args.out_dir, "witnesses.jsonl")
    failures_path = os.path.join(args.out_dir, "verification_failures.jsonl")
    summary_path = os.path.join(args.out_dir, "summary.json")

    done_ids, existing_rows = _load_done_ids(rows_path)
    print(f"resuming: {len(done_ids)} hospital-checks already recorded in {rows_path}", file=sys.stderr)

    per_config_results = []
    with open(rows_path, "a", encoding="utf-8") as rows_f, \
         open(confirmed_path, "a", encoding="utf-8") as conf_f, \
         open(failures_path, "a", encoding="utf-8") as fail_f:
        for max_cycle_length in args.cycle_lengths:
            tiebreak_policy = TIEBREAK_MAX_CARDINALITY_ILP if max_cycle_length == 3 else TIEBREAK_MAX_CARDINALITY_BLOSSOM
            config = KidneyConfig(
                tiebreak_policy=tiebreak_policy, max_cycle_length=max_cycle_length, max_ilp_seconds=args.max_ilp_seconds,
            )
            for p_val in args.sizes:
                for regime in args.regimes:
                    print(f"=== running p={p_val} k={max_cycle_length} regime={regime} ===", file=sys.stderr)
                    result = run_one_config(p_val, max_cycle_length, regime, args, config, done_ids, rows_f, conf_f, fail_f)
                    print(json.dumps(result, indent=2))
                    per_config_results.append(result)

                    # Regenerate the summary after EVERY config, from the full
                    # rows file on disk (not just this run's in-memory rows),
                    # so a partial/interrupted run still has an up-to-date
                    # summary.json reflecting everything recorded so far.
                    _, all_rows = _load_done_ids(rows_path)
                    summary = _summarize(all_rows)
                    summary["ownership_seed"] = args.ownership_seed
                    summary["max_report_space"] = args.max_report_space
                    summary["run_config_results"] = per_config_results
                    summary["honesty_note"] = (
                        "Compatibility graph is REAL (Pansart et al. 2022 published KEP benchmark). "
                        "Hospital ownership -- INCLUDING its size distribution -- is SYNTHETIC, declared, "
                        "and seeded (witness.kidney_ownership), never real hospital identity or behavior. "
                        "A hospital whose exhaustive report space exceeds --max-report-space is SKIPPED, "
                        "not counted as 'no manipulation' -- the largest hospitals are the likeliest to be "
                        "skipped, so any concentration-in-large-hospitals finding below is a LOWER bound."
                    )
                    with open(summary_path, "w", encoding="utf-8") as f:
                        json.dump(summary, f, indent=2, sort_keys=True)

    print(f"\nwrote {summary_path}, {rows_path}, {confirmed_path}, {failures_path}")


if __name__ == "__main__":
    main()
