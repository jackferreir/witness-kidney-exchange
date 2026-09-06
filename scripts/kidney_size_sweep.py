#!/usr/bin/env python3
"""Does the hospital-withholding manipulation rate decay as the market
grows? This is the actual open empirical question behind the asymptotic
strategyproofness literature (Ashlagi et al.'s kidney-exchange large-market
results, Kojima-Pathak-Roth's couples analogue): those papers PROVE the
manipulation incentive vanishes in the limit, but do not publish the FINITE-
SIZE rate curve. This script measures it, using `TIEBREAK_MAX_CARDINALITY_
BLOSSOM` (validated against the independent oracle in
`tests/test_kidney_blossom_matches_oracle.py`) to reach market sizes the
original exhaustive clearing cannot.

DESIGN: pairs-per-hospital is held FIXED (`--pairs-per-hospital`, default 6)
so each hospital's OWN report-search space (2**6 = 64 misreports) stays
cheap regardless of market size; `--n-hospitals` sweeps the TOTAL market
size instead. One hospital is checked per generated instance (each instance
is an independent draw from `witness.generate_kidney`'s seeded generator),
so `n_checks` at a given size are `n_checks` independent samples, not
`n_checks` hospitals drawn from the same few markets.

HONESTY, stated up front: `n_checks` shrinks as market size grows (clearing
cost scales worse than linearly -- see the wall-clock column). At the
largest sizes this means a SMALL sample -- zero confirmed hits at n=20 is
NOT proof the true rate is zero, only that it's small enough not to show up
in that sample. The size at which the observed rate visibly drops is the
finding; "and stays at exactly zero forever after" is not a claim this
script's sample sizes can support at the largest points -- said plainly in
the summary, not left for a reader to infer from the numbers alone.

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

from witness.generate_kidney import KidneyGeneratorConfig, generate_kidney_instance
from witness.kidney import (
    TIEBREAK_LEX_SMALLEST_BY_INDEX,
    TIEBREAK_MAX_CARDINALITY_BLOSSOM,
    TIEBREAK_MAX_CARDINALITY_ILP,
    IlpTimeLimitExceeded,
    KidneyConfig,
)
from witness.replay_kidney import verify_in_subprocess
from witness.search_kidney import find_hospital_manipulation


def measure_size(
    n_hospitals: int,
    pairs_per_hospital: int,
    edge_density: float,
    n_checks: int,
    seed: str,
    config: KidneyConfig,
    conf_f,
    fail_f,
) -> dict:
    n_pairs = n_hospitals * pairs_per_hospital
    gc = KidneyGeneratorConfig(n_pairs=n_pairs, n_hospitals=n_hospitals, edge_density=edge_density, seed=seed)

    n_confirmed = 0
    n_verification_failures = 0
    n_skipped_too_hard = 0
    t0 = time.perf_counter()
    for i in range(n_checks):
        market, profile = generate_kidney_instance(gc, i)
        hospital = market.hospitals[i % len(market.hospitals)]  # spread checks across hospitals, still 1/instance
        try:
            w = find_hospital_manipulation(market, profile, hospital, config)
        except IlpTimeLimitExceeded as exc:
            n_skipped_too_hard += 1
            print(f"  [skip: too hard within budget] instance={i} hospital={hospital}: {exc}", file=sys.stderr)
            continue
        if w is None:
            continue
        d = w.to_dict()
        ok, reasons = verify_in_subprocess(d)
        if ok:
            n_confirmed += 1
            conf_f.write(json.dumps(d) + "\n")
        else:
            n_verification_failures += 1
            fail_f.write(json.dumps({"witness": d, "reasons": list(reasons)}) + "\n")
    wall = time.perf_counter() - t0

    return {
        "n_pairs": n_pairs,
        "n_hospitals": n_hospitals,
        "pairs_per_hospital": pairs_per_hospital,
        "n_checks": n_checks,
        "n_confirmed": n_confirmed,
        "n_verification_failures": n_verification_failures,
        "n_skipped_too_hard": n_skipped_too_hard,
        "manipulation_rate": n_confirmed / n_checks if n_checks else None,
        "wall_seconds": wall,
        "seconds_per_check": wall / n_checks if n_checks else None,
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--pairs-per-hospital", type=int, default=6)
    p.add_argument("--edge-density", type=float, default=0.3)
    p.add_argument("--seed", type=str, default="kidney-size-sweep-v1")
    p.add_argument(
        "--sizes", type=int, nargs="+", default=[5, 10, 20, 40, 80],
        help="n_hospitals values to sweep (n_pairs = n_hospitals * pairs_per_hospital)",
    )
    p.add_argument(
        "--checks", type=int, nargs="+", default=[1000, 1000, 400, 100, 20],
        help="number of independent hospital-checks at each size (must match --sizes length)",
    )
    p.add_argument(
        "--tiebreak-policy", type=str, default=TIEBREAK_MAX_CARDINALITY_BLOSSOM,
        choices=[TIEBREAK_LEX_SMALLEST_BY_INDEX, TIEBREAK_MAX_CARDINALITY_BLOSSOM, TIEBREAK_MAX_CARDINALITY_ILP],
    )
    p.add_argument("--max-cycle-length", type=int, default=2, choices=[2, 3])
    p.add_argument("--max-ilp-seconds", type=float, default=None)
    p.add_argument("--out-dir", type=str, default="results/kidney_size_sweep")
    args = p.parse_args()

    if len(args.sizes) != len(args.checks):
        raise SystemExit(f"--sizes ({len(args.sizes)}) and --checks ({len(args.checks)}) must have the same length")

    os.makedirs(args.out_dir, exist_ok=True)
    confirmed_path = os.path.join(args.out_dir, "witnesses.jsonl")
    failures_path = os.path.join(args.out_dir, "verification_failures.jsonl")
    summary_path = os.path.join(args.out_dir, "summary.json")

    config = KidneyConfig(
        tiebreak_policy=args.tiebreak_policy, max_cycle_length=args.max_cycle_length,
        max_ilp_seconds=args.max_ilp_seconds,
    )

    per_size = []
    with open(confirmed_path, "w", encoding="utf-8") as conf_f, \
         open(failures_path, "w", encoding="utf-8") as fail_f:
        for n_hospitals, n_checks in zip(args.sizes, args.checks):
            result = measure_size(
                n_hospitals, args.pairs_per_hospital, args.edge_density, n_checks, args.seed,
                config, conf_f, fail_f,
            )
            print(json.dumps(result, indent=2))
            per_size.append(result)

    n_total_checks = sum(r["n_checks"] for r in per_size)
    n_total_verification_failures = sum(r["n_verification_failures"] for r in per_size)

    summary = {
        "seed": args.seed,
        "pairs_per_hospital": args.pairs_per_hospital,
        "edge_density": args.edge_density,
        "tiebreak_policy": args.tiebreak_policy,
        "max_cycle_length": args.max_cycle_length,
        "per_size": per_size,
        "n_total_checks": n_total_checks,
        "n_total_verification_failures": n_total_verification_failures,
        "honesty_note": (
            "n_checks shrinks at larger sizes (clearing cost scales worse than linearly), so "
            "zero confirmed hits at the largest sizes is NOT proof the true rate is zero -- only "
            "that it is small enough not to appear in that sample size. See this script's own "
            "module docstring."
        ),
    }
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, sort_keys=True)
    print(json.dumps(summary, indent=2, sort_keys=True))
    print(f"\nwrote {summary_path}, {confirmed_path}, {failures_path}")


if __name__ == "__main__":
    main()
