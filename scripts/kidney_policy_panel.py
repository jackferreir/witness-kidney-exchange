#!/usr/bin/env python3
"""SYMMETRIC policy-panel test -- the fair version of "tiebreak dominance".

WHY THIS EXISTS. The census compared two things measured on different bases:

  * tiebreak spread : the range of a hospital's outcome across EVERY
    maximum-cardinality clearing (a mathematical set, most of whose members
    no deployed program would ever select)
  * strategic gain  : the best misreport gain under ONE fixed tiebreak rule

That asymmetry flatters the spread side twice over -- it uses a larger
reference class AND it holds the tiebreak fixed while measuring strategy,
even though an adversarial check showed strategy is ITSELF tiebreak
dependent (0/135 hospitals manipulable under the ILP rule vs 4/135 under
Blossom on identical markets, with ZERO overlap). Any honest comparison has
to put both sides on the same footing.

WHAT THIS DOES. Fix a PANEL of tie-breaking rules that a real program could
plausibly run. Then measure BOTH quantities across that SAME panel:

    spread_panel(h) = max over policies of u_h(truthful)
                    - min over policies of u_h(truthful)

    gain_panel(h)   = max over policies of [ best misreport gain under that
                                             same policy ]

Both are now "max over the same panel of realizable rules", so neither side
gets a reference class the other is denied.

WHAT COUNTS AS REALIZABLE. The panel is CP-SAT under several random seeds,
plus Blossom where the cycle length permits it. Varying the solver seed is
not a contrivance: the production code pins `random_seed = 0` and
`num_search_workers = 1` (witness/kidney.py) purely to make runs
reproducible. A program that upgraded its solver, changed its thread count,
or reordered its input would land on a different -- equally optimal --
clearing. That is exactly the indeterminacy under study.

THE THIRD QUANTITY, which is the real point. For each hospital record
whether it has nonzero spread, nonzero gain, or both. If the SAME hospitals
appear on both sides, the finding is not "tiebreak beats strategy" but
something sharper: the tiebreak choice is what CREATES the strategic
opportunity. That is a different and more interesting claim, and it is
testable here rather than assertable.

Resumable, one flushed row per hospital. Skips recorded, never counted as
zero.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from witness.kidney import (
    IlpTimeLimitExceeded,
    KidneyConfig,
    KidneyMarket,
    KidneyProfile,
    ModelError,
    TIEBREAK_MAX_CARDINALITY_BLOSSOM,
    _select_maximum_cycles_blossom,
    candidate_cycles,
)
from witness.kidney_real_data import load_real_kidney_market, real_instances_for_p
from witness.search_kidney import hospital_misreport_space


def _ilp_select(market, candidates, seed, max_seconds):
    """Maximum-cardinality selection under a given solver seed. Same model as
    witness.kidney._select_maximum_cycles_ilp; only `random_seed` varies, which
    is the whole point -- it changes WHICH optimum is returned, never how good
    that optimum is. Optimality is still proven, never assumed."""
    from ortools.sat.python import cp_model

    if not candidates:
        return ()
    model = cp_model.CpModel()
    x = [model.NewBoolVar(f"c{i}") for i in range(len(candidates))]
    by_pair = {}
    for i, cyc in enumerate(candidates):
        for p in cyc:
            by_pair.setdefault(p, []).append(i)
    for p in sorted(by_pair):
        model.Add(sum(x[i] for i in by_pair[p]) <= 1)
    model.Maximize(sum(len(candidates[i]) * x[i] for i in range(len(candidates))))

    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = seed
    if max_seconds is not None:
        solver.parameters.max_time_in_seconds = max_seconds
    status = solver.Solve(model)
    if status != cp_model.OPTIMAL:
        raise IlpTimeLimitExceeded(f"seed={seed}: not proven optimal ({solver.StatusName(status)})")
    return tuple(candidates[i] for i in range(len(candidates)) if solver.Value(x[i]) == 1)


def _clear_under(market, profile, policy, k, max_seconds):
    """Full two-stage clearing under one panel policy; returns utility per hospital.
    Mirrors witness.kidney.clear_kidney_exchange's structure exactly: central
    clearing over the REPORTED pool, then each hospital's residual local clearing
    over its own TRUE pairs left unmatched."""
    pool = tuple(p for h in market.hospitals for p in profile.report(h))
    cands = candidate_cycles(market, pool, k)
    if policy == "blossom":
        central = _select_maximum_cycles_blossom(market, cands)
    else:
        central = _ilp_select(market, cands, int(policy.split(":")[1]), max_seconds)

    matched = set()
    for c in central:
        matched.update(c)
    for h in market.hospitals:
        residual = tuple(p for p in market.pairs_of(h) if p not in matched)
        lc = candidate_cycles(market, residual, k)
        local = (_select_maximum_cycles_blossom(market, lc) if policy == "blossom"
                 else _ilp_select(market, lc, int(policy.split(":")[1]), max_seconds))
        for c in local:
            matched.update(c)
    return {h: sum(1 for p in market.pairs_of(h) if p in matched) for h in market.hospitals}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--p", type=int, required=True)
    ap.add_argument("--k", type=int, default=3)
    ap.add_argument("--draws", type=int, default=8)
    ap.add_argument("--pairs-per-hospital", type=int, default=6)
    ap.add_argument("--hospitals-per-market", type=int, default=3)
    ap.add_argument("--seeds", type=int, default=4, help="number of distinct CP-SAT seeds in the panel")
    ap.add_argument("--ownership-seed", type=str, default="policy-panel-v1")
    ap.add_argument("--max-ilp-seconds", type=float, default=120.0)
    ap.add_argument("--out-dir", type=str, default=None)
    args = ap.parse_args()

    policies = [f"ilp:{s}" for s in range(args.seeds)]
    if args.k == 2:
        policies.append("blossom")  # 2-cycle only by construction

    out_dir = args.out_dir or f"results/kidney_policy_panel_p{args.p}_k{args.k}"
    os.makedirs(out_dir, exist_ok=True)
    rows_path = os.path.join(out_dir, "rows.jsonl")
    done = set()
    if os.path.exists(rows_path):
        for line in open(rows_path):
            try: done.add(json.loads(line)["id"])
            except Exception: pass
    f = open(rows_path, "a", buffering=1)

    def emit(rec):
        f.write(json.dumps(rec) + "\n"); f.flush(); os.fsync(f.fileno())

    n_hosp = max(1, round(args.p / args.pairs_per_hospital))
    members = real_instances_for_p(args.p)

    for draw in range(args.draws):
        for mi, member in enumerate(members):
            market, profile, _m = load_real_kidney_market(
                member, n_hospitals=n_hosp, ownership_seed=args.ownership_seed, ownership_draw_index=draw)
            chosen = sorted(market.hospitals)[: args.hospitals_per_market]

            # truthful utility under every panel policy -- computed once per market
            try:
                truth = {pol: _clear_under(market, profile, pol, args.k, args.max_ilp_seconds)
                         for pol in policies}
            except (IlpTimeLimitExceeded, ModelError) as exc:
                for h in chosen:
                    emit({"id": f"{args.p}|{args.k}|{draw}|{mi}|{h}", "p": args.p, "k": args.k,
                          "draw": draw, "member": member, "hospital": h,
                          "status": "skipped_truthful", "reason": str(exc)[:160]})
                continue

            for h in chosen:
                rid = f"{args.p}|{args.k}|{draw}|{mi}|{h}"
                if rid in done: continue
                t0 = time.perf_counter()
                u_true = {pol: truth[pol][h] for pol in policies}
                spread_panel = max(u_true.values()) - min(u_true.values())

                # SAME panel on the strategy side: best misreport under each policy
                gain_by_pol, failed = {}, None
                for pol in policies:
                    best = u_true[pol]
                    try:
                        for rep in hospital_misreport_space(market, h, profile.report(h)):
                            mp = profile.with_report(h, rep)
                            best = max(best, _clear_under(market, mp, pol, args.k, args.max_ilp_seconds)[h])
                    except (IlpTimeLimitExceeded, ModelError) as exc:
                        failed = str(exc)[:160]; break
                    gain_by_pol[pol] = best - u_true[pol]
                if failed:
                    emit({"id": rid, "p": args.p, "k": args.k, "draw": draw, "member": member,
                          "hospital": h, "status": "skipped_strategy", "reason": failed})
                    continue

                gain_panel = max(gain_by_pol.values())
                emit({
                    "id": rid, "p": args.p, "k": args.k, "draw": draw, "member": member,
                    "hospital": h, "hospital_size": len(market.pairs_of(h)), "status": "ok",
                    "u_true_by_policy": u_true, "gain_by_policy": gain_by_pol,
                    "spread_panel": spread_panel, "gain_panel": gain_panel,
                    # the overlap question: does tiebreak choice CREATE the opportunity?
                    "has_spread": spread_panel > 0, "has_gain": gain_panel > 0,
                    "gain_is_policy_dependent": len(set(gain_by_pol.values())) > 1,
                    "seconds": round(time.perf_counter() - t0, 2),
                })

                rows = [json.loads(l) for l in open(rows_path)]
                ok = [r for r in rows if r.get("status") == "ok"]
                if ok:
                    sp = [r["spread_panel"] for r in ok]; gn = [r["gain_panel"] for r in ok]
                    both = sum(1 for r in ok if r["has_spread"] and r["has_gain"])
                    onlys = sum(1 for r in ok if r["has_spread"] and not r["has_gain"])
                    onlyg = sum(1 for r in ok if r["has_gain"] and not r["has_spread"])
                    pdep = sum(1 for r in ok if r["gain_is_policy_dependent"])
                    print(f"[panel P={args.p} K={args.k}] n={len(ok)} | spread {sum(sp)/len(sp):.2f} "
                          f"gain {sum(gn)/len(gn):.2f} | both={both} spread_only={onlys} "
                          f"gain_only={onlyg} | gain_varies_by_policy={pdep}", flush=True)

    print("\nDONE")


if __name__ == "__main__":
    main()
