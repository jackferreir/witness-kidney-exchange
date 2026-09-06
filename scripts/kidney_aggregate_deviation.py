#!/usr/bin/env python3
"""What happens if EVERY hospital that has an individually-profitable
deviation actually plays it, at the same time?

This is a FIRST-ORDER, one-shot simultaneous-deviation experiment, NOT a
Nash equilibrium computation: each deviating hospital plays the best
misreport found AGAINST THE TRUTHFUL baseline (from a full per-market
census -- see scripts/kidney_full_census.py), and we build ONE joint
profile where every such hospital plays that report simultaneously, then
clear the market once. We do NOT iterate to a fixed point (a hospital's
best response could change once others have also deviated) -- that's a
harder, genuinely different computation this script does not attempt, and
the summary says so explicitly rather than implying more than was checked.

What this DOES answer honestly, per market:
  - Aggregate effect: does total social welfare (total pairs matched) go up
    or down when every self-interested deviation fires at once?
  - Individual robustness: does each ORIGINALLY-profitable deviation still
    pay off once everyone else who had an incentive also deviates, or do
    the deviations interfere with and cancel out each other's gains?

Reuses market/profile data embedded in a full-census witness file (one row
per confirmed manipulation, `_census_provenance` identifying the market).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from witness.kidney import KidneyConfig, KidneyMarket, KidneyProfile, TIEBREAK_MAX_CARDINALITY_ILP, clear_kidney_exchange


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--census-files", nargs="+", required=True)
    p.add_argument("--max-ilp-seconds", type=float, default=120.0)
    p.add_argument("--out", type=str, required=True)
    args = p.parse_args()

    # Group confirmed deviations by market.
    by_market = defaultdict(list)
    market_cache = {}
    for path in args.census_files:
        for line in open(path, encoding="utf-8"):
            d = json.loads(line)
            prov = d["_census_provenance"]
            key = (prov["source_member"], prov["ownership_draw_index"])
            by_market[key].append(d)
            if key not in market_cache:
                market_cache[key] = (
                    KidneyMarket.from_dict(d["market"]),
                    KidneyProfile.from_dict(d["truthful_profile"]),
                    prov["declared_p"],
                )

    config = KidneyConfig(tiebreak_policy=TIEBREAK_MAX_CARDINALITY_ILP, max_cycle_length=3, max_ilp_seconds=args.max_ilp_seconds)

    results = []
    for key, hits in by_market.items():
        if len(hits) < 2:
            continue  # need at least 2 simultaneous deviators for this to be interesting
        market, truthful_profile, declared_p = market_cache[key]

        truthful_result = clear_kidney_exchange(market, truthful_profile, config)
        truthful_total_matched = len(truthful_result.matched_pairs)
        truthful_total_utility = sum(truthful_result.utility.values())

        joint_profile = truthful_profile
        deviators = []
        for hit in hits:
            h = hit["target_hospital"]
            joint_profile = joint_profile.with_report(h, hit["false_report"])
            deviators.append({
                "hospital": h,
                "predicted_solo_gain": hit["false_utility"] - hit["truthful_utility"],
                "truthful_utility": hit["truthful_utility"],
            })

        joint_result = clear_kidney_exchange(market, joint_profile, config)
        joint_total_matched = len(joint_result.matched_pairs)
        joint_total_utility = sum(joint_result.utility.values())

        for dev in deviators:
            h = dev["hospital"]
            dev["actual_utility_when_all_deviate"] = joint_result.utility[h]
            dev["actual_gain_when_all_deviate"] = joint_result.utility[h] - dev["truthful_utility"]
            dev["gain_survived"] = dev["actual_gain_when_all_deviate"] >= dev["predicted_solo_gain"]

        results.append({
            "declared_p": declared_p,
            "source_member": key[0],
            "ownership_draw_index": key[1],
            "n_simultaneous_deviators": len(deviators),
            "truthful_total_matched_pairs": truthful_total_matched,
            "joint_total_matched_pairs": joint_total_matched,
            "aggregate_matched_pairs_delta": joint_total_matched - truthful_total_matched,
            "truthful_total_utility": truthful_total_utility,
            "joint_total_utility": joint_total_utility,
            "aggregate_utility_delta": joint_total_utility - truthful_total_utility,
            "deviators": deviators,
        })

    n_markets_with_multi = len(results)
    n_deviators_total = sum(r["n_simultaneous_deviators"] for r in results)
    n_gains_survived = sum(sum(1 for d in r["deviators"] if d["gain_survived"]) for r in results)
    mean_aggregate_delta = (
        sum(r["aggregate_matched_pairs_delta"] for r in results) / len(results) if results else None
    )

    summary = {
        "n_markets_with_2plus_simultaneous_deviators": n_markets_with_multi,
        "n_deviators_total": n_deviators_total,
        "n_gains_that_survived_simultaneous_play": n_gains_survived,
        "mean_aggregate_matched_pairs_delta": mean_aggregate_delta,
        "honesty_note": (
            "FIRST-ORDER simultaneous deviation, not a Nash equilibrium: each hospital plays its best "
            "response to the TRUTHFUL baseline, not to what others are doing. A hospital whose gain did "
            "NOT survive might have a DIFFERENT profitable deviation once others have moved -- that "
            "requires iterating to a fixed point, which this script does not attempt."
        ),
        "results": results,
    }
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, sort_keys=True)
    print(json.dumps({k: v for k, v in summary.items() if k != "results"}, indent=2, sort_keys=True))
    print(f"\n{len(results)} markets had 2+ simultaneous deviators; wrote full detail to {args.out}")


if __name__ == "__main__":
    main()
