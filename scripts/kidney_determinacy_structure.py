#!/usr/bin/env python3
"""Why might determinacy imply strategyproofness at K=2? A structural probe.

MOTIVATION. Across 64k+ outcome-blind hospitals in three regimes (real
benchmark, sparse synthetic, dense adversarial where 18% of indeterminate
hospitals DO manipulate), not one K=2 hospital whose utility is invariant
across all maximum-cardinality clearings was able to gain by misreporting.
That is now well-sampled. It is not explained.

At K=2 the central clearing is maximum matching on the undirected graph
whose edges are mutually-compatible pairs, and maximum matchings have
strong classical structure (Gallai-Edmonds): every vertex is either
ESSENTIAL -- matched by EVERY maximum matching -- or INESSENTIAL -- missed
by at least one. That dichotomy is exactly the kind of object a proof would
be built on, so the question this script asks is:

    Does a hospital's tiebreak-determinacy coincide with its pairs being
    structurally pinned (each pair always-matched or never-matched across
    optimal clearings), with no "swing" pairs?

If determinacy turns out to be EQUIVALENT to "h owns no swing pair", the
conjecture reduces to a statement about Gallai-Edmonds structure, which is
the kind of thing that can actually be proved rather than sampled. If it is
NOT equivalent, the counterexamples to the equivalence are the interesting
objects and are logged in full.

METHOD. For each hospital, classify each of its pairs by computing, over the
set of maximum-cardinality clearings, whether that pair is matched centrally
in all / some / none. "Some but not all" = a SWING pair. Then cross-tabulate
swing-pair count against tiebreak spread and against manipulability.

This is a descriptive probe, not a proof, and is labelled as such. It is
read-only with respect to every other experiment.
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ortools.sat.python import cp_model

from kidney_tiebreak_exact import central_c_star, joint_extreme

from witness.generate_kidney import KidneyGeneratorConfig, generate_kidney_instance
from witness.kidney import (
    IlpTimeLimitExceeded,
    KidneyConfig,
    ModelError,
    TIEBREAK_MAX_CARDINALITY_ILP,
    candidate_cycles,
)
from witness.search_kidney import find_best_hospital_manipulation


def pair_status(market, report_map, pair, c_star, k, max_seconds):
    """Is `pair` matched centrally in EVERY / SOME / NO maximum-cardinality
    clearing? Answered by two feasibility solves at fixed optimal cardinality:
    can an optimum include it, and can an optimum exclude it."""
    pool = tuple(p for h in market.hospitals for p in report_map[h])
    cands = candidate_cycles(market, pool, k)
    touching = [i for i, c in enumerate(cands) if pair in c]

    def feasible(force_include):
        m = cp_model.CpModel()
        x = [m.NewBoolVar(f"c{i}") for i in range(len(cands))]
        by = {}
        for i, c in enumerate(cands):
            for p in c:
                by.setdefault(p, []).append(i)
        for p in sorted(by):
            m.AddAtMostOne([x[i] for i in by[p]])
        m.Add(sum(len(cands[i]) * x[i] for i in range(len(cands))) == c_star)
        if force_include:
            m.Add(sum(x[i] for i in touching) == 1)
        else:
            m.Add(sum(x[i] for i in touching) == 0)
        s = cp_model.CpSolver()
        s.parameters.num_search_workers = 1
        s.parameters.random_seed = 0
        s.parameters.max_time_in_seconds = max_seconds
        st = s.Solve(m)
        if st in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return True
        if st == cp_model.INFEASIBLE:
            return False
        raise IlpTimeLimitExceeded("pair_status undetermined")

    if not touching:
        return "never"
    can_in = feasible(True)
    can_out = feasible(False)
    if can_in and can_out:
        return "swing"
    return "always" if can_in else "never"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--n-pairs", type=int, default=16)
    ap.add_argument("--pairs-per-hospital", type=int, default=4)
    ap.add_argument("--edge-density", type=float, default=0.30)
    ap.add_argument("--instances", type=int, default=100000)
    ap.add_argument("--hospitals-per-instance", type=int, default=4)
    ap.add_argument("--seed", type=str, default="structure-v1")
    ap.add_argument("--max-ilp-seconds", type=float, default=30.0)
    ap.add_argument("--out-dir", type=str, default=None)
    ap.add_argument(
        "--k", type=int, default=2, choices=[2, 3],
        help="K=2 is where the determinacy conjecture holds perfectly and where maximum-matching "
             "theory applies. K=3 is where it FAILS ~0.9%% of the time -- running the same "
             "structural classification there locates WHICH structural group the failures live in, "
             "which is the difference between 'it breaks sometimes' and knowing why.",
    )
    args = ap.parse_args()
    K = args.k

    out_dir = args.out_dir or f"results/determinacy_structure_k{args.k}"
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
        f.write(json.dumps(rec) + "\n"); f.flush(); os.fsync(f.fileno())

    cfg = KidneyConfig(tiebreak_policy=TIEBREAK_MAX_CARDINALITY_ILP,
                       max_cycle_length=K, max_ilp_seconds=args.max_ilp_seconds)
    n_hosp = max(1, round(args.n_pairs / args.pairs_per_hospital))
    gc = KidneyGeneratorConfig(n_pairs=args.n_pairs, n_hospitals=n_hosp,
                               edge_density=args.edge_density, seed=args.seed)

    xtab = collections.Counter()   # (has_swing, determinate, manipulable) -> count
    n_ok = 0

    for idx in range(args.instances):
        market, profile = generate_kidney_instance(gc, idx)
        report_map = {h: list(profile.report(h)) for h in market.hospitals}
        chosen = sorted(market.hospitals)[: args.hospitals_per_instance]
        # central_c_star takes a FLAT reported pool and returns
        # (c_star, candidates, elapsed); c_star is None on a proven-optimality
        # timeout, which must be skipped rather than treated as a value.
        pool = tuple(p for hh in market.hospitals for p in report_map[hh])
        try:
            c_star, _cands, _el = central_c_star(market, pool, K, args.max_ilp_seconds)
        except (IlpTimeLimitExceeded, ModelError):
            continue
        if c_star is None:
            continue

        for h in chosen:
            rid = f"{args.n_pairs}|{idx}|{h}"
            if rid in done:
                continue
            t0 = time.perf_counter()
            try:
                lo = joint_extreme(market, report_map, h, K, args.max_ilp_seconds, "min")
                hi = joint_extreme(market, report_map, h, K, args.max_ilp_seconds, "max")
                if lo["status"] != "ok" or hi["status"] != "ok":
                    emit({"id": rid, "status": "skipped_spread"}); continue
                statuses = [pair_status(market, report_map, p, c_star, K, args.max_ilp_seconds)
                            for p in market.pairs_of(h)]
                w = find_best_hospital_manipulation(market, profile, h, cfg)
            except (IlpTimeLimitExceeded, ModelError):
                emit({"id": rid, "status": "skipped"}); continue

            gain = 0
            if w is not None:
                d = w.to_dict()
                gain = d["false_utility"] - d["truthful_utility"]
            spread = hi["value"] - lo["value"]
            n_swing = sum(1 for s in statuses if s == "swing")
            rec = {"id": rid, "k": K, "instance": idx, "hospital": h,
                   "status": "ok", "tiebreak_spread": spread, "strategic_gain": gain,
                   "pair_statuses": statuses, "n_swing": n_swing,
                   "seconds": round(time.perf_counter() - t0, 2)}
            emit(rec)
            n_ok += 1
            xtab[(n_swing > 0, spread == 0, gain > 0)] += 1

            # the equivalence under test: determinate <=> no swing pair
            if (n_swing == 0) != (spread == 0):
                print(f"!!! EQUIVALENCE BROKEN: {json.dumps(rec)}", flush=True)

        if idx % 25 == 0 and n_ok:
            noswing_det = xtab[(False, True, False)] + xtab[(False, True, True)]
            noswing_tot = sum(v for kk, v in xtab.items() if kk[0] is False)
            swing_det = xtab[(True, True, False)] + xtab[(True, True, True)]
            swing_tot = sum(v for kk, v in xtab.items() if kk[0] is True)
            manip_noswing = sum(v for kk, v in xtab.items() if kk[0] is False and kk[2])
            manip_swing = sum(v for kk, v in xtab.items() if kk[0] is True and kk[2])
            print(f"[structure n={args.n_pairs}] checked={n_ok} | "
                  f"NO-swing: {noswing_tot} (determinate {noswing_det}, manipulable {manip_noswing}) | "
                  f"swing: {swing_tot} (determinate {swing_det}, manipulable {manip_swing})",
                  flush=True)

    print("\nDONE")


if __name__ == "__main__":
    main()
