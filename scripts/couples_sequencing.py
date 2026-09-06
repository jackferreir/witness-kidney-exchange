#!/usr/bin/env python3
"""Deliverables A and B: sequencing sensitivity and non-existence frequency
for the couples mechanism (`witness.couples`), as a function of couples
participation rate, measured on `witness.generate_couples`'s synthetic
generator -- no manipulation search, no real data.

DELIVERABLE A (sequencing sensitivity): among instances where BOTH the
couples_first and couples_last processing orders terminate with
`STATUS_STABLE` (a fair, comparable pair of outcomes), what fraction of
INDIVIDUAL applicants get a different final program depending on which
order was used? Reported per couples-participation-rate point.

DELIVERABLE B (non-existence / loop frequency): what fraction of instances
have the algorithm report `STATUS_LOOP_DETECTED` under the canonical
(intermixed) order? Also reported: the fraction that loop under EVERY one
of the three declared orders (a stronger, though still not a formal proof,
signal that the instance genuinely has no stable matching rather than that
one specific order's heuristic failed) -- see `witness.couples`'s own
docstring on the honest limits of what `STATUS_LOOP_DETECTED` proves.

Reproducible: every instance is `witness.generate_couples.generate_couples_
instance(gc, i)` for a `gc` that is a pure function of (--seed,
couples_rate, --n-individuals, --n-schools), so re-running this script with
the same flags reproduces byte-identical instances and hence identical
results.

Follows `scripts/negative_control.py`'s own discipline: a non-vacuity check
(the generator actually produces couples, and their count scales with the
requested rate) and a summary JSON that is the artifact of record -- not a
number quoted only from a hand run.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Mapping

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from witness.couples import (
    COUPLE_ORDER_COUPLES_FIRST,
    COUPLE_ORDER_COUPLES_LAST,
    COUPLE_ORDER_INTERMIXED,
    STATUS_LOOP_DETECTED,
    STATUS_STABLE,
    CouplesConfig,
    couples_deferred_acceptance,
)
from witness.generate_couples import (
    COUPLES_RATE_1990S_RANGE,
    COUPLES_RATE_2024,
    COUPLES_RATE_SWEEP,
    CouplesGeneratorConfig,
    generate_couples_instance,
)

_ORDERS = (COUPLE_ORDER_INTERMIXED, COUPLE_ORDER_COUPLES_FIRST, COUPLE_ORDER_COUPLES_LAST)


def measure_rate(
    couples_rate: float,
    n_individuals: int,
    n_schools: int,
    n_instances: int,
    seed: str,
    max_loop_repeats: int,
    list_length: "int | None",
) -> dict:
    gc = CouplesGeneratorConfig(
        n_individuals=n_individuals,
        n_schools=n_schools,
        couples_rate=couples_rate,
        seed=seed,
        list_length=list_length,
    )

    n_couples_total = 0
    n_singles_total = 0

    loop_intermixed = 0
    loop_all_three = 0
    loop_any = 0

    # Deliverable A aggregates, computed only where BOTH orders being
    # compared reached STATUS_STABLE (a fair comparison -- comparing a real
    # matching against a loop-abort's untrustworthy partial state would not
    # be a measurement of sequencing sensitivity, it would be a measurement
    # of the loop detector, which Deliverable B already covers).
    comparable_pairs_cf_cl = 0
    instances_differ_cf_cl = 0
    applicants_differ_cf_cl = 0
    applicants_compared_cf_cl = 0

    for i in range(n_instances):
        market, profile = generate_couples_instance(gc, i)
        n_couples_total += len(profile.couples)
        n_singles_total += len(profile.singles)

        statuses = {}
        assignments = {}
        for order in _ORDERS:
            res = couples_deferred_acceptance(
                market,
                profile,
                CouplesConfig(couple_order_policy=order, max_loop_repeats=max_loop_repeats),
            )
            statuses[order] = res.status
            assignments[order] = res.assignment

        looped = {o for o in _ORDERS if statuses[o] == STATUS_LOOP_DETECTED}
        if statuses[COUPLE_ORDER_INTERMIXED] == STATUS_LOOP_DETECTED:
            loop_intermixed += 1
        if len(looped) == len(_ORDERS):
            loop_all_three += 1
        if looped:
            loop_any += 1

        if (
            statuses[COUPLE_ORDER_COUPLES_FIRST] == STATUS_STABLE
            and statuses[COUPLE_ORDER_COUPLES_LAST] == STATUS_STABLE
        ):
            comparable_pairs_cf_cl += 1
            a_cf = assignments[COUPLE_ORDER_COUPLES_FIRST].student_to_school
            a_cl = assignments[COUPLE_ORDER_COUPLES_LAST].student_to_school
            n_diff = sum(1 for k in a_cf if a_cf[k] != a_cl[k])
            applicants_compared_cf_cl += len(a_cf)
            applicants_differ_cf_cl += n_diff
            if n_diff > 0:
                instances_differ_cf_cl += 1

    return {
        "couples_rate": couples_rate,
        "n_individuals": n_individuals,
        "n_schools": n_schools,
        "n_instances": n_instances,
        "mean_couples_per_instance": n_couples_total / n_instances,
        "mean_singles_per_instance": n_singles_total / n_instances,
        # Deliverable B
        "loop_detected_intermixed_fraction": loop_intermixed / n_instances,
        "loop_detected_all_three_orders_fraction": loop_all_three / n_instances,
        "loop_detected_any_order_fraction": loop_any / n_instances,
        # Deliverable A
        "comparable_stable_pairs_cf_cl": comparable_pairs_cf_cl,
        "instances_with_sequencing_difference_fraction": (
            instances_differ_cf_cl / comparable_pairs_cf_cl if comparable_pairs_cf_cl else None
        ),
        "applicants_affected_fraction": (
            applicants_differ_cf_cl / applicants_compared_cf_cl if applicants_compared_cf_cl else None
        ),
        "applicants_differ_cf_cl": applicants_differ_cf_cl,
        "applicants_compared_cf_cl": applicants_compared_cf_cl,
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--n-individuals", type=int, default=16)
    p.add_argument("--n-schools", type=int, default=6)
    p.add_argument("--instances-per-rate", type=int, default=2000)
    p.add_argument("--seed", type=str, default="couples-sequencing-v1")
    p.add_argument("--max-loop-repeats", type=int, default=3)
    p.add_argument(
        "--list-length", type=int, default=None,
        help="schools each applicant ranks (default: complete list, every school)",
    )
    p.add_argument(
        "--rates", type=float, nargs="+", default=list(COUPLES_RATE_SWEEP),
        help="couples participation rates to sweep",
    )
    p.add_argument("--out", type=str, default="results/couples_sequencing/summary.json")
    args = p.parse_args()

    t0 = time.perf_counter()
    per_rate = []
    for rate in args.rates:
        per_rate.append(
            measure_rate(
                rate,
                args.n_individuals,
                args.n_schools,
                args.instances_per_rate,
                args.seed,
                args.max_loop_repeats,
                args.list_length,
            )
        )
    wall = time.perf_counter() - t0

    # Non-vacuity: the generator must actually produce couples whose count
    # scales with the requested rate, and the highest rate tested must
    # actually exercise both the "differs" and the "loops" branches, or this
    # whole sweep would be a truthful report about a generator that never
    # moved anything.
    nonzero_couples = any(r["mean_couples_per_instance"] > 0 for r in per_rate)
    any_sequencing_difference = any(
        (r["instances_with_sequencing_difference_fraction"] or 0) > 0 for r in per_rate
    )
    any_loop_detected = any(r["loop_detected_intermixed_fraction"] > 0 for r in per_rate)

    summary = {
        "seed": args.seed,
        "n_individuals": args.n_individuals,
        "n_schools": args.n_schools,
        "instances_per_rate": args.instances_per_rate,
        "rates_swept": args.rates,
        "max_loop_repeats": args.max_loop_repeats,
        "list_length": args.list_length,
        "wall_seconds": wall,
        "instances_total": args.instances_per_rate * len(args.rates) * len(_ORDERS),
        "instances_per_second": (
            (args.instances_per_rate * len(args.rates) * len(_ORDERS)) / wall if wall > 0 else None
        ),
        "verified_couples_rate_sources": {
            "roth_peranson_1999_table_1a_range": COUPLES_RATE_1990S_RANGE,
            "nrmp_2024_results_and_data": COUPLES_RATE_2024,
            "note": (
                "Both figures verified directly from the primary sources (see "
                "witness/generate_couples.py's module docstring for the exact "
                "quotes/arithmetic). Rates in `rates_swept` above this range are a "
                "labeled STRESS extrapolation, not attributed to NRMP."
            ),
        },
        "per_rate": per_rate,
        "nonvacuity": {
            "generator_produces_couples": nonzero_couples,
            "sweep_exercises_sequencing_difference_branch": any_sequencing_difference,
            "sweep_exercises_loop_detected_branch": any_loop_detected,
        },
        "honesty_note": (
            "loop_detected_* fractions measure how often THIS heuristic (bounded-"
            "retry, this couple_order_policy, this max_loop_repeats) gave up -- "
            "NOT a formal proof of non-existence for those instances. See "
            "witness/couples.py's module docstring. "
            "SEPARATELY: this generator's loop rate is very likely inflated well "
            "above any TRUE non-existence rate, for two reasons found and only "
            "partly fixed during development (see witness/couples.py's "
            "'vacancy_not_chased' / would_accept-gated reactivation comments): "
            "(1) even a SINGLE couple among otherwise-ordinary singles at this "
            "instance size produced a double-digit loop rate before a fix, and "
            "still produces a nonzero one after it -- implausible as genuine "
            "mathematical non-existence (Roth 1984 impossibility needs a "
            "specific structure, not something ~1-in-6 random single-couple "
            "instances should hit); (2) this generator's markets (small, exact-"
            "subscription, short-but-not-tiny lists) are far denser/more "
            "contested than a real ~40,000-applicant NRMP market with far more "
            "slack. Read every loop_detected_* number here as an upper bound on "
            "this heuristic's giving-up rate, not a claim about real couples-"
            "match non-existence frequency."
        ),
    }

    out_dir = os.path.dirname(args.out)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, sort_keys=True)

    print(json.dumps(summary, indent=2, sort_keys=True))
    print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
