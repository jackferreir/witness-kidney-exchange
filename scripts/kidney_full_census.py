#!/usr/bin/env python3
"""Full per-market census: search EVERY hospital in a set of already-
generated real-data markets (pulled from existing witness files' embedded
`market`/`truthful_profile` fields, not freshly generated), using the
MAXIMUM-gain search (`find_best_hospital_manipulation`), not stop-at-first.

WHY THIS EXISTS: every prior kidney sweep script tested exactly ONE hospital
per generated market instance (to bound cost). That means the reported
rates are a systematic UNDER-count of the true per-market manipulation
rate -- confirmed directly: a plain individual-rationality check against
existing witness data found 29 hospitals, never previously searched, that
are OWED a manipulation for free (reporting nothing beats truthful
reporting whenever a hospital's truthful utility is below its own
standalone value). This script closes that gap by searching every hospital
in every market it's given, and also reports the actual GAIN SIZE per hit,
not just its existence.

Markets are DEDUPED by (source_member, ownership_draw_index, n_hospitals)
across every witness file given, since many hits share a market (only the
target hospital differs).

Every found witness is independently re-verified via
`witness.replay_kidney.verify_in_subprocess` before being counted.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from witness.kidney import IlpTimeLimitExceeded, KidneyConfig, KidneyMarket, KidneyProfile, TIEBREAK_MAX_CARDINALITY_ILP
from witness.replay_kidney import verify_in_subprocess
from witness.search_kidney import find_best_hospital_manipulation
from witness.runlog import begin_run


def load_distinct_markets(witness_files):
    seen = {}
    for path in witness_files:
        for line in open(path, encoding="utf-8"):
            d = json.loads(line)
            prov = d.get("_real_data_provenance")
            if prov is None:
                continue
            key = (prov["source_member"], prov["ownership_draw_index"], prov["n_hospitals"])
            if key in seen:
                continue
            seen[key] = {
                "market": KidneyMarket.from_dict(d["market"]),
                "profile": KidneyProfile.from_dict(d["truthful_profile"]),
                "declared_p": prov["declared_p"],
                "source_member": prov["source_member"],
                "ownership_draw_index": prov["ownership_draw_index"],
            }
    return seen


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--witness-files", nargs="+", required=True)
    p.add_argument("--only-p", type=int, nargs="+", default=None, help="restrict to these declared_p values")
    p.add_argument("--max-markets", type=int, default=None, help="cap number of markets processed (per --only-p value)")
    p.add_argument("--max-ilp-seconds", type=float, default=90.0)
    p.add_argument("--out-dir", type=str, required=True)
    args = p.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)

    # Provenance + exclusive lock: see witness/runlog.py. A second live

    # writer on one out-dir is what corrupted results/samesolver_k3.

    begin_run(args.out_dir, note="full census aggregation")
    confirmed_path = os.path.join(args.out_dir, "witnesses.jsonl")
    failures_path = os.path.join(args.out_dir, "verification_failures.jsonl")
    summary_path = os.path.join(args.out_dir, "summary.json")

    config = KidneyConfig(
        tiebreak_policy=TIEBREAK_MAX_CARDINALITY_ILP, max_cycle_length=3, max_ilp_seconds=args.max_ilp_seconds,
    )

    markets = load_distinct_markets(args.witness_files)
    if args.only_p is not None:
        markets = {k: v for k, v in markets.items() if v["declared_p"] in args.only_p}

    # group by declared_p, apply --max-markets per group
    by_p = {}
    for k, v in markets.items():
        by_p.setdefault(v["declared_p"], []).append((k, v))
    selected = []
    for p_val, items in sorted(by_p.items()):
        if args.max_markets is not None:
            items = items[: args.max_markets]
        selected.extend(items)

    print(f"{len(selected)} markets selected across P values {sorted(by_p)}", file=sys.stderr)

    n_hospital_checks = 0
    n_confirmed = 0
    n_verification_failures = 0
    n_skipped_too_hard = 0
    gains = []
    t0 = time.perf_counter()

    with open(confirmed_path, "w", encoding="utf-8") as conf_f, \
         open(failures_path, "w", encoding="utf-8") as fail_f:
        for key, entry in selected:
            market = entry["market"]
            profile = entry["profile"]
            for h in market.hospitals:
                n_hospital_checks += 1
                try:
                    w = find_best_hospital_manipulation(market, profile, h, config)
                except IlpTimeLimitExceeded as exc:
                    n_skipped_too_hard += 1
                    print(f"  [skip] P={entry['declared_p']} {entry['source_member']} hospital={h}: {exc}", file=sys.stderr)
                    continue
                if w is None:
                    continue
                gain = w.false_utility - w.truthful_utility
                d = w.to_dict()
                d["_census_provenance"] = {
                    "declared_p": entry["declared_p"],
                    "source_member": entry["source_member"],
                    "ownership_draw_index": entry["ownership_draw_index"],
                }
                ok, reasons = verify_in_subprocess(w.to_dict())
                if ok:
                    n_confirmed += 1
                    gains.append(gain)
                    conf_f.write(json.dumps(d) + "\n")
                else:
                    n_verification_failures += 1
                    fail_f.write(json.dumps({"witness": d, "reasons": list(reasons)}) + "\n")
            elapsed = time.perf_counter() - t0
            print(
                f"  ...done P={entry['declared_p']} {entry['source_member']} draw={entry['ownership_draw_index']} "
                f"(checks so far={n_hospital_checks}, confirmed={n_confirmed}, elapsed={elapsed:.0f}s)",
                file=sys.stderr,
            )

    wall = time.perf_counter() - t0
    from collections import Counter
    summary = {
        "witness_files": args.witness_files,
        "only_p": args.only_p,
        "max_markets_per_p": args.max_markets,
        "max_ilp_seconds": args.max_ilp_seconds,
        "n_markets": len(selected),
        "n_hospital_checks": n_hospital_checks,
        "n_confirmed": n_confirmed,
        "n_verification_failures": n_verification_failures,
        "n_skipped_too_hard": n_skipped_too_hard,
        "manipulation_rate": n_confirmed / n_hospital_checks if n_hospital_checks else None,
        "gain_distribution": dict(sorted(Counter(gains).items())),
        "mean_gain_among_hits": sum(gains) / len(gains) if gains else None,
        "max_gain_observed": max(gains) if gains else None,
        "wall_seconds": wall,
        "honesty_note": (
            "This is a FULL per-market census (every hospital searched, not one per market), using the "
            "MAX-gain search. Markets are real-compatibility-graph (Pansart et al. 2022) with synthetic "
            "ownership, reused from prior sweeps' saved witness files. This is expected to find a HIGHER "
            "rate than prior single-hospital-per-market sweeps, since those undercounted by construction."
        ),
    }
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, sort_keys=True)
    print(json.dumps(summary, indent=2, sort_keys=True))
    print(f"\nwrote {summary_path}, {confirmed_path}, {failures_path}")


if __name__ == "__main__":
    main()
