#!/usr/bin/env python3
"""Manipulation search over the kidney-exchange mechanism (`witness.kidney`),
on `witness.generate_kidney`'s synthetic generator -- exhaustive over each
hospital's own declared report space (`witness.search_kidney`), per
`KIDNEY_EXCHANGE_SCOPE.md`'s scoped first increment.

CAVEAT, stated up front rather than only in results: this generator's
compatibility graph is ALSO synthetic (not yet the downloadable Petris et
al. benchmark named in `KIDNEY_EXCHANGE_SCOPE.md`'s data plan), so a rate
measured here characterizes this small synthetic generator, not real
kidney-paired-donation data -- exactly the same honesty this project's
other generators (`witness.generate_couples`, etc.) apply to themselves.

Every found witness is independently re-verified via
`witness.replay_kidney.verify_in_subprocess` -- a fresh interpreter -- before
being counted or written to the confirmed output.
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
    DEFAULT_MAX_CENTRAL_SPACE,
    TIEBREAK_LEX_SMALLEST_BY_INDEX,
    TIEBREAK_MAX_CARDINALITY_BLOSSOM,
    KidneyConfig,
)
from witness.replay_kidney import verify_in_subprocess
from witness.search_kidney import DEFAULT_MAX_REPORT_SPACE, find_hospital_manipulation
from witness.runlog import begin_run


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--n-pairs", type=int, default=6)
    p.add_argument("--n-hospitals", type=int, default=3)
    p.add_argument("--edge-density", type=float, default=0.3)
    p.add_argument("--n-instances", type=int, default=500)
    p.add_argument("--seed", type=str, default="search-kidney-v1")
    p.add_argument("--max-report-space", type=int, default=DEFAULT_MAX_REPORT_SPACE)
    p.add_argument("--max-central-space", type=int, default=DEFAULT_MAX_CENTRAL_SPACE)
    p.add_argument(
        "--tiebreak-policy", type=str, default=TIEBREAK_LEX_SMALLEST_BY_INDEX,
        choices=[TIEBREAK_LEX_SMALLEST_BY_INDEX, TIEBREAK_MAX_CARDINALITY_BLOSSOM],
        help="clearing implementation -- see witness.kidney's 'TWO CLEARING IMPLEMENTATIONS'",
    )
    p.add_argument("--out-dir", type=str, default="results/search_kidney")
    args = p.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)

    # Provenance + exclusive lock: see witness/runlog.py. A second live

    # writer on one out-dir is what corrupted results/samesolver_k3.

    begin_run(args.out_dir, note="kidney manipulation search")
    confirmed_path = os.path.join(args.out_dir, "witnesses.jsonl")
    failures_path = os.path.join(args.out_dir, "verification_failures.jsonl")
    summary_path = os.path.join(args.out_dir, "summary.json")

    gc = KidneyGeneratorConfig(
        n_pairs=args.n_pairs, n_hospitals=args.n_hospitals, edge_density=args.edge_density, seed=args.seed
    )
    config = KidneyConfig(max_central_space=args.max_central_space, tiebreak_policy=args.tiebreak_policy)

    n_hospital_targets_examined = 0
    n_candidates_found = 0
    n_confirmed = 0
    n_verification_failures = 0
    n_instances_with_any_edge = 0

    t0 = time.perf_counter()
    with open(confirmed_path, "w", encoding="utf-8") as conf_f, \
         open(failures_path, "w", encoding="utf-8") as fail_f:
        for i in range(args.n_instances):
            market, profile = generate_kidney_instance(gc, i)
            if market.edges:
                n_instances_with_any_edge += 1

            for h in market.hospitals:
                n_hospital_targets_examined += 1
                try:
                    w = find_hospital_manipulation(
                        market, profile, h, config, max_space=args.max_report_space
                    )
                except ValueError as exc:
                    print(f"instance {i} hospital {h}: {exc}", file=sys.stderr)
                    continue
                except Exception as exc:  # noqa: BLE001 - central clearing can raise ModelError on oversize
                    print(f"instance {i} hospital {h}: {exc!r}", file=sys.stderr)
                    continue
                if w is None:
                    continue
                n_candidates_found += 1
                d = w.to_dict()
                ok, reasons = verify_in_subprocess(d)
                if ok:
                    n_confirmed += 1
                    conf_f.write(json.dumps(d) + "\n")
                else:
                    n_verification_failures += 1
                    fail_f.write(json.dumps({"witness": d, "reasons": list(reasons)}) + "\n")

    wall = time.perf_counter() - t0

    summary = {
        "seed": args.seed,
        "n_pairs": args.n_pairs,
        "n_hospitals": args.n_hospitals,
        "edge_density": args.edge_density,
        "n_instances": args.n_instances,
        "max_report_space": args.max_report_space,
        "tiebreak_policy": args.tiebreak_policy,
        "max_central_space": args.max_central_space,
        "wall_seconds": wall,
        "n_instances_with_any_edge": n_instances_with_any_edge,
        "n_hospital_targets_examined": n_hospital_targets_examined,
        "n_candidates_found": n_candidates_found,
        "n_confirmed": n_confirmed,
        "n_verification_failures": n_verification_failures,
        "manipulation_rate": (
            n_confirmed / n_hospital_targets_examined if n_hospital_targets_examined else None
        ),
        "nonvacuity": {
            "generator_produces_edges": n_instances_with_any_edge > 0,
            "any_candidate_found_before_verification": n_candidates_found > 0,
        },
        "honesty_note": (
            "This generator's compatibility graph is synthetic, not the downloadable "
            "Petris et al. benchmark KIDNEY_EXCHANGE_SCOPE.md's data plan calls for -- "
            "this rate characterizes this small synthetic generator only."
        ),
    }

    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, sort_keys=True)
    print(json.dumps(summary, indent=2, sort_keys=True))
    print(f"\nwrote {summary_path}, {confirmed_path}, {failures_path}")


if __name__ == "__main__":
    main()
