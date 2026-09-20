#!/usr/bin/env python3
"""Tests the determinacy conjecture on SYNTHETIC graphs, to escape the two
limits that bind every result measured on the Pansart benchmark.

THE CONJECTURE. If a hospital's outcome is identical under EVERY
maximum-cardinality central clearing (tiebreak_spread == 0), can it still
gain by misreporting? On real benchmark graphs the answer so far is: never
at K=2 (0 of ~7,200), and rarely at K=3 (~0.9%, always by exactly 1).

WHY SYNTHETIC GRAPHS ARE NOT A DOWNGRADE HERE. Two hard limits bind the
benchmark-based evidence:

  1. ONLY ~15 REAL GRAPHS EXIST PER POOL SIZE. Every large row count is
     re-partitions of those same graphs, so observations are clustered and
     the honest unit of analysis is the graph. With 15 graphs an exact sign
     test cannot return a p-value below ~6e-5 NO MATTER HOW LARGE THE
     EFFECT. That ceiling is structural and no amount of extra sampling on
     the benchmark can lift it.
  2. EVERYTHING RESTS ON ONE BENCHMARK FAMILY. A property that holds across
     45 instances drawn from a single generator may be a property of that
     generator rather than of the mechanism.

Synthetic draws fix both: each draw is an INDEPENDENT graph (no clustering
ceiling -- the sign test's n is the number of graphs, and that is unbounded),
and the generator is a different family entirely, so agreement across the two
is evidence the conjecture is about the MECHANISM.

WHAT IS AND IS NOT CLAIMED. Synthetic compatibility graphs are NOT real
patient data and are weaker evidence about the real world than the benchmark
is. They are STRONGER evidence about whether the conjecture is a structural
property of maximum-cardinality clearing. The two roles are different and
both are needed; this script serves only the second.

A single determinate-yet-manipulable hospital at K=2 refutes the conjecture,
so every such case is logged in full for inspection rather than merely
counted. Skips are recorded and never counted as "no manipulation".
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from kidney_tiebreak_exact import joint_extreme

from witness.generate_kidney import KidneyGeneratorConfig, generate_kidney_instance
from witness.kidney import (
    IlpTimeLimitExceeded,
    KidneyConfig,
    ModelError,
    TIEBREAK_MAX_CARDINALITY_ILP,
    clear_kidney_exchange,
)
from witness.replay_kidney import verify_in_subprocess
from witness.search_kidney import find_best_hospital_manipulation


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--k", type=int, required=True, choices=[2, 3])
    ap.add_argument("--n-pairs", type=int, default=60)
    ap.add_argument("--pairs-per-hospital", type=int, default=6)
    ap.add_argument("--edge-density", type=float, default=0.06,
                    help="0.06 approximates the sparsity of the real Pansart graphs; "
                         "a wildly denser graph would not be a fair analogue")
    ap.add_argument("--instances", type=int, default=100000, help="independent synthetic graphs")
    ap.add_argument("--hospitals-per-instance", type=int, default=3)
    ap.add_argument("--seed", type=str, default="determinacy-synth-v1")
    ap.add_argument("--max-ilp-seconds", type=float, default=60.0)
    ap.add_argument("--out-dir", type=str, default=None)
    args = ap.parse_args()

    out_dir = args.out_dir or f"results/determinacy_synth_k{args.k}_n{args.n_pairs}"
    os.makedirs(out_dir, exist_ok=True)
    rows_path = os.path.join(out_dir, "rows.jsonl")
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

    cfg = KidneyConfig(tiebreak_policy=TIEBREAK_MAX_CARDINALITY_ILP,
                       max_cycle_length=args.k, max_ilp_seconds=args.max_ilp_seconds)
    n_hosp = max(1, round(args.n_pairs / args.pairs_per_hospital))
    gc = KidneyGeneratorConfig(n_pairs=args.n_pairs, n_hospitals=n_hosp,
                               edge_density=args.edge_density, seed=args.seed)

    n_det = n_det_manip = n_ind = n_ind_manip = n_ok = n_skip = 0

    for idx in range(args.instances):
        market, profile = generate_kidney_instance(gc, idx)
        report_map = {h: list(profile.report(h)) for h in market.hospitals}
        # outcome-blind: first N hospitals by sorted id, fixed before any search
        chosen = sorted(market.hospitals)[: args.hospitals_per_instance]

        for h in chosen:
            rid = f"{args.k}|{args.n_pairs}|{idx}|{h}"
            if rid in done:
                continue
            t0 = time.perf_counter()
            try:
                seed_u = clear_kidney_exchange(market, profile, cfg).utility[h]
                lo = joint_extreme(market, report_map, h, args.k, args.max_ilp_seconds, "min")
                hi = joint_extreme(market, report_map, h, args.k, args.max_ilp_seconds, "max")
                if lo["status"] != "ok" or hi["status"] != "ok":
                    emit({"id": rid, "status": "skipped_spread"}); n_skip += 1; continue
                w = find_best_hospital_manipulation(market, profile, h, cfg)
            except (IlpTimeLimitExceeded, ModelError) as exc:
                emit({"id": rid, "status": "skipped", "reason": str(exc)[:140]}); n_skip += 1; continue

            gain = 0
            verified = None
            if w is not None:
                d = w.to_dict()
                ok, _ = verify_in_subprocess(d)
                verified = bool(ok)
                gain = (d["false_utility"] - d["truthful_utility"]) if ok else 0

            spread = hi["value"] - lo["value"]
            rec = {"id": rid, "k": args.k, "n_pairs": args.n_pairs, "instance": idx,
                   "hospital": h, "hospital_size": len(market.pairs_of(h)), "status": "ok",
                   "seed_truthful_utility": seed_u, "u_true_min": lo["value"],
                   "u_true_max": hi["value"], "tiebreak_spread": spread,
                   "strategic_gain": gain, "manipulation_verified": verified,
                   "sanity_seed_in_range": lo["value"] <= seed_u <= hi["value"],
                   "seconds": round(time.perf_counter() - t0, 2)}
            emit(rec)
            n_ok += 1
            if spread == 0:
                n_det += 1
                if gain > 0:
                    n_det_manip += 1
                    # a K=2 case here refutes the conjecture -- log it loudly and in full
                    print(f"!!! DETERMINATE-AND-MANIPULABLE K={args.k}: {json.dumps(rec)}", flush=True)
            else:
                n_ind += 1
                n_ind_manip += gain > 0

        if idx % 25 == 0 and n_ok:
            dr = n_det_manip / n_det * 100 if n_det else 0.0
            ir = n_ind_manip / n_ind * 100 if n_ind else 0.0
            print(f"[synth K={args.k} n={args.n_pairs}] graphs={idx+1} checked={n_ok} skipped={n_skip} | "
                  f"determinate {n_det_manip}/{n_det} = {dr:.3f}% | "
                  f"indeterminate {n_ind_manip}/{n_ind} = {ir:.3f}%", flush=True)

    print("\nDONE")


if __name__ == "__main__":
    main()
