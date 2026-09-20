#!/usr/bin/env python3
"""TIEBREAK-SENSITIVITY CENSUS -- the defensible version of the "tiebreak
dominates strategy" claim.

WHAT WAS WRONG WITH THE FIRST ATTEMPT. `scripts/kidney_tiebreak_exact.py`
computed tiebreak quantities only for hospitals that ALREADY had a confirmed
manipulation (it reads witness files). Four consequences, all fatal to a
general claim:

  1. SELECTED SAMPLE. Every measured hospital was selected on having a
     strategic option. Nothing was learned about ordinary hospitals, which
     are the overwhelming majority. "Tiebreak matters more than strategy"
     cannot be established on a sample chosen for having strategy available.
  2. ONE-SIDED MEASURE. It recorded `U_true_max` but never `U_true_min`, so
     the reported "spread" was really `best-tiebreak minus the-seed's-tiebreak`
     -- a lower bound on the true spread, described as if it were the spread.
  3. EFFECTIVELY ONE POOL SIZE. 17 of 20 resolved cases were P=250.
  4. FIRST-HIT GAIN. Witnesses came from `find_hospital_manipulation`, which
     stops at the FIRST profitable report in canonical order, biasing the
     measured gain downward toward marginal manipulations.

WHAT THIS SCRIPT DOES INSTEAD.

  * OUTCOME-BLIND SAMPLE. Hospitals are chosen by a declared, seeded rule
    BEFORE any search runs -- never by whether a manipulation exists. Both
    quantities below are then computed on the SAME hospitals, so the
    comparison is PAIRED within hospital.
  * FULL SPREAD. Both `U_true_min` and `U_true_max` over ALL maximum-
    cardinality central clearings at the TRUTHFUL profile, via the validated
    `joint_extreme` from `kidney_tiebreak_exact` (max = genuine one-shot
    joint CP-SAT; min = footprint enumeration, because a literal joint
    minimize is wrong -- local clearing is never adversarial). Spread =
    max - min, the actual quantity, not a proxy for it.
  * MAX-GAIN STRATEGY. `find_best_hospital_manipulation` (exhaustive over the
    full report space, returns the BEST misreport), not first-hit -- so the
    strategic side is measured at its maximum, the most favourable possible
    framing for the "strategy matters" side of the comparison.
  * MULTIPLE POOL SIZES, with the source graph recorded on every row so
    inference can cluster on it (there are only ~15 real graphs per pool
    size; treating hospitals as independent overstates significance --
    see `scripts/clustered_inference.py`).

Every timeout is recorded as a skip with its reason and is excluded from
analysis -- never silently counted as zero spread or zero gain. Resumable:
one flushed+fsynced row per hospital, keyed by a stable id.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from kidney_tiebreak_exact import joint_extreme  # validated primitives

from witness.kidney import (
    IlpTimeLimitExceeded,
    KidneyConfig,
    KidneyMarket,
    KidneyProfile,
    TIEBREAK_MAX_CARDINALITY_ILP,
    clear_kidney_exchange,
)
from witness.kidney_ownership import build_ownership
from witness.kidney_real_data import load_real_kidney_market, real_instances_for_p
from witness.replay_kidney import verify_in_subprocess
from witness.search_kidney import find_best_hospital_manipulation
from witness.runlog import begin_run


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--p", type=int, required=True)
    ap.add_argument("--k", type=int, default=3)
    ap.add_argument("--draws", type=int, default=6)
    ap.add_argument("--pairs-per-hospital", type=int, default=6)
    ap.add_argument("--hospitals-per-market", type=int, default=3,
                    help="outcome-blind: the first N hospitals by sorted id, fixed before any search")
    ap.add_argument("--ownership-seed", type=str, default="tiebreak-census-v1")
    ap.add_argument("--max-ilp-seconds", type=float, default=300.0)
    ap.add_argument("--out-dir", type=str, default=None)
    ap.add_argument(
        "--ownership-regime", type=str, default="default",
        choices=["default", "power_law", "core_periphery"],
        help="'default' keeps the round-robin partition from `load_real_kidney_market` -- which at "
             "the default --pairs-per-hospital gives EVERY hospital the same size, so a run using it "
             "carries NO size variation and cannot speak to whether spread scales with hospital size. "
             "The other two use `witness.kidney_ownership.build_ownership` to get a genuine size spread.",
    )
    ap.add_argument(
        "--size-cap", type=int, default=9,
        help="skip hospitals larger than this. Cost is ~2**size (both the max-gain report search and "
             "the U_min footprint enumeration are exponential in the hospital's own pair count), so an "
             "uncapped run would spend its whole budget on a handful of giant hospitals.",
    )
    ap.add_argument(
        "--per-small-size", type=int, default=2,
        help="cap on how many hospitals to take per SMALL size class per market. Large hospitals "
             "(>= --big-threshold) are all taken, because they are rare and carry the size signal.",
    )
    ap.add_argument("--big-threshold", type=int, default=7)
    args = ap.parse_args()

    out_dir = args.out_dir or f"results/kidney_tiebreak_census_p{args.p}"
    os.makedirs(out_dir, exist_ok=True)
    # Provenance + exclusive lock: see witness/runlog.py. A second live
    # writer on one out-dir is what corrupted results/samesolver_k3.
    begin_run(out_dir, note="outcome-blind tiebreak census")
    rows_path = os.path.join(out_dir, "hospital_rows.jsonl")

    done = set()
    if os.path.exists(rows_path):
        for line in open(rows_path):
            try:
                done.add(json.loads(line)["id"])
            except Exception:
                pass
    f = open(rows_path, "a", buffering=1)

    def emit(rec):
        f.write(json.dumps(rec) + "\n")
        f.flush()
        os.fsync(f.fileno())

    cfg = KidneyConfig(
        tiebreak_policy=TIEBREAK_MAX_CARDINALITY_ILP,
        max_cycle_length=args.k,
        max_ilp_seconds=args.max_ilp_seconds,
    )
    n_hosp = max(1, round(args.p / args.pairs_per_hospital))
    members = real_instances_for_p(args.p)

    regime_params = {
        "power_law": {"n_hospitals": n_hosp, "exponent": 0.8},
        "core_periphery": {"n_large": max(2, args.p // 40),
                           "large_size": min(9, args.size_cap), "periphery_chunk": 2},
    }

    for draw in range(args.draws):
        for mi, member in enumerate(members):
            market, profile, _meta = load_real_kidney_market(
                member, n_hospitals=n_hosp, ownership_seed=args.ownership_seed, ownership_draw_index=draw,
            )
            if args.ownership_regime != "default":
                # Same REAL compatibility graph, re-partitioned into hospitals of
                # genuinely differing sizes -- the default round-robin gives every
                # hospital the same size, which makes a size comparison impossible.
                hospital_of, hospitals, _om = build_ownership(
                    market.pairs, seed=args.ownership_seed, draw_index=draw,
                    regime=args.ownership_regime, **regime_params[args.ownership_regime],
                )
                market = KidneyMarket(
                    pairs=market.pairs, hospital_of=hospital_of,
                    hospitals=hospitals, edges=market.edges,
                )
                profile = KidneyProfile.truthful(market)

            # OUTCOME-BLIND selection, fixed before any search touches this market:
            # take every LARGE hospital (rare, carries the size signal) and at most
            # --per-small-size of each smaller size class, sorted by id for
            # reproducibility. Never selected on outcome.
            by_size = {}
            for h in sorted(market.hospitals):
                by_size.setdefault(len(market.pairs_of(h)), []).append(h)
            if args.ownership_regime == "default":
                chosen = sorted(market.hospitals)[: args.hospitals_per_market]
            else:
                chosen = [
                    h
                    for s, hs in sorted(by_size.items())
                    if s <= args.size_cap
                    for h in (hs if s >= args.big_threshold else hs[: args.per_small_size])
                ]
            report_map = {h: list(profile.report(h)) for h in market.hospitals}

            for h in chosen:
                rid = f"{args.p}|{args.k}|{draw}|{mi}|{h}"
                if rid in done:
                    continue
                t0 = time.perf_counter()
                size = len(market.pairs_of(h))

                rec = {
                    "id": rid, "p": args.p, "k": args.k, "draw": draw,
                    "member": member, "hospital": h, "hospital_size": size,
                }

                # --- the mechanism's actual outcome under its fixed seed ---
                try:
                    seed_result = clear_kidney_exchange(market, profile, cfg)
                    rec["seed_truthful_utility"] = seed_result.utility[h]
                except IlpTimeLimitExceeded as exc:
                    rec.update(status="skipped_seed_clear", reason=str(exc)[:200],
                               seconds=round(time.perf_counter() - t0, 2))
                    emit(rec)
                    continue

                # --- FULL tiebreak spread at the TRUTHFUL profile ---
                lo = joint_extreme(market, report_map, h, args.k, args.max_ilp_seconds, "min")
                hi = joint_extreme(market, report_map, h, args.k, args.max_ilp_seconds, "max")
                rec["u_min_status"], rec["u_max_status"] = lo["status"], hi["status"]
                if lo["status"] != "ok" or hi["status"] != "ok":
                    rec.update(status="skipped_spread",
                               reason=f"min={lo['status']} max={hi['status']}",
                               seconds=round(time.perf_counter() - t0, 2))
                    emit(rec)
                    continue
                rec["u_true_min"], rec["u_true_max"] = lo["value"], hi["value"]
                rec["tiebreak_spread"] = hi["value"] - lo["value"]

                # --- MAX-GAIN strategic opportunity (exhaustive, best misreport) ---
                try:
                    w = find_best_hospital_manipulation(market, profile, h, cfg)
                except IlpTimeLimitExceeded as exc:
                    rec.update(status="skipped_strategy", reason=str(exc)[:200],
                               seconds=round(time.perf_counter() - t0, 2))
                    emit(rec)
                    continue

                if w is None:
                    rec["strategic_gain"] = 0
                    rec["manipulation_verified"] = None
                else:
                    d = w.to_dict()
                    ok, _ = verify_in_subprocess(d)
                    rec["manipulation_verified"] = bool(ok)
                    # a manipulation that fails independent replay is NOT counted
                    rec["strategic_gain"] = (d["false_utility"] - d["truthful_utility"]) if ok else 0

                # sanity: the seed's own outcome must lie inside [u_min, u_max]
                rec["sanity_seed_in_range"] = (
                    rec["u_true_min"] <= rec["seed_truthful_utility"] <= rec["u_true_max"]
                )
                rec["status"] = "ok"
                rec["seconds"] = round(time.perf_counter() - t0, 2)
                emit(rec)

                rows = [json.loads(l) for l in open(rows_path)]
                ok_rows = [r for r in rows if r.get("status") == "ok"]
                if ok_rows:
                    sp = [r["tiebreak_spread"] for r in ok_rows]
                    gn = [r["strategic_gain"] for r in ok_rows]
                    gt = sum(1 for a, b in zip(sp, gn) if a > b)
                    eq = sum(1 for a, b in zip(sp, gn) if a == b)
                    lt = sum(1 for a, b in zip(sp, gn) if a < b)
                    bad = sum(1 for r in ok_rows if not r.get("sanity_seed_in_range", True))
                    print(
                        f"[census P={args.p}] n_ok={len(ok_rows)} skipped={len(rows)-len(ok_rows)} | "
                        f"spread>gain {gt}, =={eq}, <gain {lt} | "
                        f"mean spread {sum(sp)/len(sp):.2f} vs mean gain {sum(gn)/len(gn):.2f} | "
                        f"sanity_failures={bad}",
                        flush=True,
                    )

    print("\nDONE")


if __name__ == "__main__":
    main()
