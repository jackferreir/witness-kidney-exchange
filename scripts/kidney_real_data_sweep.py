#!/usr/bin/env python3
"""The same size-sweep question as `scripts/kidney_size_sweep.py`
("does the hospital-withholding manipulation rate decay as the market
grows?"), but against REAL compatibility-graph structure (Pansart et al.
2022, via `witness.kidney_real_data`) instead of random Erdos-Renyi edges.

WHAT IS REAL AND WHAT IS SYNTHETIC (repeated here deliberately, not just in
the loader's own docstring, since this is the script whose OUTPUT gets
quoted): the compatibility graph is real. The hospital-ownership partition
is NOT -- there are only a finite number of real graphs per size (up to 15
per pair-count, see `witness.kidney_real_data`'s module docstring), so this
script draws MANY declared-synthetic ownership partitions per real graph to
get a large enough sample -- each such draw is one legitimate independent
sample of "one synthetic partition of this same real graph," never a new
real graph and never real hospital behavior.

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

from witness.kidney import (
    TIEBREAK_LEX_SMALLEST_BY_INDEX,
    TIEBREAK_MAX_CARDINALITY_BLOSSOM,
    TIEBREAK_MAX_CARDINALITY_ILP,
    IlpTimeLimitExceeded,
    KidneyConfig,
)
from witness.kidney_real_data import load_real_kidney_market, real_instances_for_p
from witness.replay_kidney import verify_in_subprocess
from witness.runlog import record_run
from witness.search_kidney import find_hospital_manipulation


def measure_size(
    p: int,
    pairs_per_hospital: int,
    draws_per_member: int,
    ownership_seed: str,
    config: KidneyConfig,
    conf_f,
    fail_f,
) -> dict:
    members = real_instances_for_p(p)
    n_hospitals = max(1, round(p / pairs_per_hospital))

    n_checks = 0
    n_confirmed = 0
    n_verification_failures = 0
    n_edges_total = 0
    n_matched_centrally_total = 0
    n_skipped_too_hard = 0
    t0 = time.perf_counter()

    for member in members:
        for draw in range(draws_per_member):
            market, profile, meta = load_real_kidney_market(
                member, n_hospitals=n_hospitals, ownership_seed=ownership_seed, ownership_draw_index=draw,
            )
            n_edges_total += len(market.edges)
            hospital = market.hospitals[draw % n_hospitals]  # spread checks across hospitals
            try:
                w = find_hospital_manipulation(market, profile, hospital, config)
            except IlpTimeLimitExceeded as exc:
                # This one instance was too hard within budget -- SKIPPED, not
                # counted as "no manipulation found." Can only make the
                # measured rate an UNDER-count, never fabricate a hit. See
                # witness.kidney._select_maximum_cycles_ilp's own docstring.
                n_skipped_too_hard += 1
                print(f"  [skip: too hard within budget] {member} draw={draw} hospital={hospital}: {exc}", file=sys.stderr)
                continue
            n_checks += 1
            if w is None:
                continue
            d = w.to_dict()
            d["_real_data_provenance"] = meta.to_dict()
            ok, reasons = verify_in_subprocess(w.to_dict())  # verify the UNMODIFIED witness dict
            if ok:
                n_confirmed += 1
                conf_f.write(json.dumps(d) + "\n")
            else:
                n_verification_failures += 1
                fail_f.write(json.dumps({"witness": d, "reasons": list(reasons)}) + "\n")

    wall = time.perf_counter() - t0
    return {
        "p": p,
        "n_hospitals": n_hospitals,
        "pairs_per_hospital_target": pairs_per_hospital,
        "n_real_members": len(members),
        "draws_per_member": draws_per_member,
        "n_checks": n_checks,
        "n_confirmed": n_confirmed,
        "n_verification_failures": n_verification_failures,
        "n_skipped_too_hard": n_skipped_too_hard,
        "manipulation_rate": n_confirmed / n_checks if n_checks else None,
        "mean_edges_per_instance": n_edges_total / n_checks if n_checks else None,
        "wall_seconds": wall,
        "seconds_per_check": wall / n_checks if n_checks else None,
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--pairs-per-hospital", type=int, default=6)
    p.add_argument("--ownership-seed", type=str, default="kidney-real-sweep-v1")
    p.add_argument("--sizes", type=int, nargs="+", default=[50, 100, 250, 500])
    p.add_argument(
        "--draws-per-member", type=int, nargs="+", default=[10, 10, 4, 2],
        help="synthetic ownership draws per real graph, at each size in --sizes",
    )
    p.add_argument(
        "--tiebreak-policy", type=str, default=TIEBREAK_MAX_CARDINALITY_BLOSSOM,
        choices=[TIEBREAK_LEX_SMALLEST_BY_INDEX, TIEBREAK_MAX_CARDINALITY_BLOSSOM, TIEBREAK_MAX_CARDINALITY_ILP],
    )
    p.add_argument("--max-cycle-length", type=int, default=2, choices=[2, 3])
    p.add_argument(
        "--max-ilp-seconds", type=float, default=None,
        help="per-solve time cap for the ILP policy (NP-hard cycle packing has real "
             "per-instance variance); an instance that can't be proven optimal in time is "
             "SKIPPED, never counted as a false negative -- see IlpTimeLimitExceeded",
    )
    p.add_argument("--out-dir", type=str, default="results/kidney_real_data_sweep")
    args = p.parse_args()

    if len(args.sizes) != len(args.draws_per_member):
        raise SystemExit("--sizes and --draws-per-member must have the same length")

    os.makedirs(args.out_dir, exist_ok=True)
    confirmed_path = os.path.join(args.out_dir, "witnesses.jsonl")
    failures_path = os.path.join(args.out_dir, "verification_failures.jsonl")
    summary_path = os.path.join(args.out_dir, "summary.json")

    config = KidneyConfig(
        tiebreak_policy=args.tiebreak_policy, max_cycle_length=args.max_cycle_length,
        max_ilp_seconds=args.max_ilp_seconds,
    )

    # `record_run` writes RUN.json and holds an exclusive lock on out_dir.
    # This script opens its outputs with mode "w", so a second concurrent
    # launch truncates them under the first writer -- exactly what destroyed
    # results/samesolver_k3. The lock makes that impossible; RUN.json makes
    # a killed run visible instead of merely sparse.
    with record_run(args.out_dir, note=f"real-data sweep k={args.max_cycle_length}") as run:
        per_size = _sweep(args, config, confirmed_path, failures_path, summary_path)
        run["result_summary"] = {"per_size": per_size}


def _sweep(args, config, confirmed_path, failures_path, summary_path):
    per_size = []
    with open(confirmed_path, "w", encoding="utf-8") as conf_f, \
         open(failures_path, "w", encoding="utf-8") as fail_f:
        for p_val, draws in zip(args.sizes, args.draws_per_member):
            result = measure_size(
                p_val, args.pairs_per_hospital, draws, args.ownership_seed, config, conf_f, fail_f,
            )
            print(json.dumps(result, indent=2))
            per_size.append(result)

    summary = {
        "ownership_seed": args.ownership_seed,
        "pairs_per_hospital_target": args.pairs_per_hospital,
        "tiebreak_policy": args.tiebreak_policy,
        "max_cycle_length": args.max_cycle_length,
        "per_size": per_size,
        "n_total_checks": sum(r["n_checks"] for r in per_size),
        "n_total_verification_failures": sum(r["n_verification_failures"] for r in per_size),
        "n_total_skipped_too_hard": sum(r["n_skipped_too_hard"] for r in per_size),
        "honesty_note": (
            f"Compatibility graph is REAL (Pansart et al. 2022 published KEP benchmark, "
            f"max_cycle_length={args.max_cycle_length} -- see witness.kidney_real_data). Hospital "
            "ownership is SYNTHETIC (declared seeded partition), never real hospital behavior. Only "
            "up to 15 distinct real graphs exist per size, so repeated ownership draws over the SAME "
            "small set of real graphs supply the sample size -- not 15x-draws independent real graphs."
        ),
    }
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, sort_keys=True)
    print(json.dumps(summary, indent=2, sort_keys=True))
    print(f"\nwrote {summary_path}, {confirmed_path}, {failures_path}")
    return per_size


if __name__ == "__main__":
    main()
