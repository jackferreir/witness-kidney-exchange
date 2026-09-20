#!/usr/bin/env python3
"""Manipulation search over the couples mechanism (`witness.couples`), on
`witness.generate_couples`'s synthetic generator -- exhaustive over the
declared report space for BOTH target kinds (`witness.search_couples`:
singles embedded in a couples market, and couples' own joint ROL of pairs),
per REVIEWER.md's target-mechanism priority list ("NRMP residency match
(couples is the documented soft spot)").

Every found witness is independently re-verified via
`witness.replay_couples.verify_in_subprocess` -- a FRESH interpreter, not the
one that searched for it -- before being counted or written to the
"confirmed" output. A witness that fails replay is written to
`verification_failures.jsonl` instead and is never counted as a finding
(mirrors `scripts/negative_control.py`'s own discipline).

Kept deliberately small by default: the couple-target report space is
`n_schools ** 2` items (see `witness.search_couples.couple_misreport_space`),
so `--n-schools` above ~3 makes an exhaustive couple search too slow to be
"exhaustive and complete" in any honest sense -- this script raises loudly
(via `couple_misreport_space`'s own `max_space` check) rather than silently
truncating.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from witness.couples import CouplesConfig, STATUS_STABLE, couples_deferred_acceptance
from witness.generate_couples import CouplesGeneratorConfig, generate_couples_instance
from witness.replay_couples import verify_in_subprocess
from witness.search_couples import (
    DEFAULT_MAX_SPACE_COUPLE,
    find_couple_manipulation,
    find_single_manipulation,
)


from witness.runlog import begin_run


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--n-individuals", type=int, default=8)
    p.add_argument("--n-schools", type=int, default=2)
    p.add_argument("--couples-rate", type=float, default=0.5)
    p.add_argument("--n-instances", type=int, default=500)
    p.add_argument("--seed", type=str, default="search-couples-v1")
    p.add_argument("--list-length", type=int, default=None)
    p.add_argument("--single-max-space", type=int, default=200_000)
    p.add_argument("--couple-max-space", type=int, default=DEFAULT_MAX_SPACE_COUPLE)
    p.add_argument("--search-singles", action="store_true", default=True)
    p.add_argument("--no-search-singles", dest="search_singles", action="store_false")
    p.add_argument("--search-couples", action="store_true", default=True)
    p.add_argument("--no-search-couples", dest="search_couples", action="store_false")
    p.add_argument("--out-dir", type=str, default="results/search_couples")
    args = p.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)

    # Provenance + exclusive lock: see witness/runlog.py. A second live

    # writer on one out-dir is what corrupted results/samesolver_k3.

    begin_run(args.out_dir, note="couples manipulation search")
    confirmed_path = os.path.join(args.out_dir, "witnesses.jsonl")
    failures_path = os.path.join(args.out_dir, "verification_failures.jsonl")
    summary_path = os.path.join(args.out_dir, "summary.json")

    gc = CouplesGeneratorConfig(
        n_individuals=args.n_individuals,
        n_schools=args.n_schools,
        couples_rate=args.couples_rate,
        seed=args.seed,
        list_length=args.list_length,
    )
    config = CouplesConfig()

    n_single_targets_examined = 0
    n_couple_targets_examined = 0
    n_single_candidates_found = 0
    n_couple_candidates_found = 0
    n_confirmed_single = 0
    n_confirmed_couple = 0
    n_verification_failures = 0
    n_instances_with_couples = 0
    n_truthful_loop_detected = 0

    t0 = time.perf_counter()
    with open(confirmed_path, "w", encoding="utf-8") as conf_f, \
         open(failures_path, "w", encoding="utf-8") as fail_f:
        for i in range(args.n_instances):
            market, profile = generate_couples_instance(gc, i)
            if profile.couples:
                n_instances_with_couples += 1

            truthful_result = couples_deferred_acceptance(market, profile, config)
            if truthful_result.status != STATUS_STABLE:
                n_truthful_loop_detected += 1
                continue  # not a comparable baseline for ANY target this instance

            if args.search_singles:
                for s in profile.singles:
                    n_single_targets_examined += 1
                    w = find_single_manipulation(
                        market, profile, s, config, max_space=args.single_max_space
                    )
                    if w is None:
                        continue
                    n_single_candidates_found += 1
                    d = w.to_dict()
                    ok, reasons = verify_in_subprocess(d)
                    if ok:
                        n_confirmed_single += 1
                        conf_f.write(json.dumps(d) + "\n")
                    else:
                        n_verification_failures += 1
                        fail_f.write(json.dumps({"witness": d, "reasons": list(reasons)}) + "\n")

            if args.search_couples:
                for ci in range(len(profile.couples)):
                    n_couple_targets_examined += 1
                    try:
                        w = find_couple_manipulation(
                            market, profile, ci, config, max_space=args.couple_max_space
                        )
                    except ValueError as exc:
                        print(f"instance {i} couple {ci}: {exc}", file=sys.stderr)
                        continue
                    if w is None:
                        continue
                    n_couple_candidates_found += 1
                    d = w.to_dict()
                    ok, reasons = verify_in_subprocess(d)
                    if ok:
                        n_confirmed_couple += 1
                        conf_f.write(json.dumps(d) + "\n")
                    else:
                        n_verification_failures += 1
                        fail_f.write(json.dumps({"witness": d, "reasons": list(reasons)}) + "\n")

    wall = time.perf_counter() - t0

    summary = {
        "seed": args.seed,
        "n_individuals": args.n_individuals,
        "n_schools": args.n_schools,
        "couples_rate": args.couples_rate,
        "n_instances": args.n_instances,
        "list_length": args.list_length,
        "single_max_space": args.single_max_space,
        "couple_max_space": args.couple_max_space,
        "search_singles": args.search_singles,
        "search_couples": args.search_couples,
        "wall_seconds": wall,
        "n_instances_with_couples": n_instances_with_couples,
        "n_instances_truthful_loop_detected": n_truthful_loop_detected,
        "n_single_targets_examined": n_single_targets_examined,
        "n_couple_targets_examined": n_couple_targets_examined,
        "n_single_candidates_found": n_single_candidates_found,
        "n_couple_candidates_found": n_couple_candidates_found,
        "n_confirmed_single": n_confirmed_single,
        "n_confirmed_couple": n_confirmed_couple,
        "n_verification_failures": n_verification_failures,
        "single_manipulation_rate": (
            n_confirmed_single / n_single_targets_examined if n_single_targets_examined else None
        ),
        "couple_manipulation_rate": (
            n_confirmed_couple / n_couple_targets_examined if n_couple_targets_examined else None
        ),
        "nonvacuity": {
            "generator_produces_couples": n_instances_with_couples > 0,
            "any_candidate_found_before_verification": (
                n_single_candidates_found + n_couple_candidates_found
            ) > 0,
        },
    }

    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, sort_keys=True)
    print(json.dumps(summary, indent=2, sort_keys=True))
    print(f"\nwrote {summary_path}, {confirmed_path}, {failures_path}")


if __name__ == "__main__":
    main()
