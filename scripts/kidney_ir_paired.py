#!/usr/bin/env python3
"""PAIRED plain-vs-IR withholding comparison -- the design fix for the
differential-attrition confound found at P=500.

THE PROBLEM THIS EXISTS TO SOLVE. `scripts/kidney_ir_sweep.py` measures the
IR mechanism's deviation rate and compares it to a SEPARATELY-run plain
baseline. At P=250 that is fine (both arms skipped 0 instances). At P=500 it
is not: the IR arm's joint CP-SAT model is heavier than plain clearing's, so
75% of IR instances exceeded the per-solve cap and were skipped, while the
plain baseline (`results/kidney_k3_real_p500_supplement/summary.json`,
n_total_skipped_too_hard=0) skipped none. Comparing a rate measured on the
easiest 25% of instances against a rate measured on all of them is a
differential-attrition confound, and it biases IN FAVOUR of IR -- exactly the
hypothesis under test. A "skips can only undercount" argument is CONSERVATIVE
when the claim is "manipulations exist", and ANTI-CONSERVATIVE here, where the
claim is "IR removes manipulations". Same skip, opposite meaning.

THE FIX. Run BOTH mechanisms on the SAME (market, hospital) instance under the
SAME cap, and count an instance only when BOTH arms resolve. Identical
instances, identical filtering, so no differential attrition by construction.
What a cap then costs is GENERALISABILITY (conclusions hold for the subset of
instances solvable within it), which is stateable, rather than INTERNAL
VALIDITY (a biased comparison), which is not fixable after the fact.

Because the arms are paired on the same instances, the correct test is
McNemar's on the discordant pairs, not a two-proportion z-test.

Every plain-arm hit is re-verified by `witness.replay_kidney.verify_in_
subprocess`; every IR-arm hit by `witness.kidney_ir.verify_in_subprocess`.
Resumable: one flushed+fsynced row per instance, keyed by a stable id.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from witness.kidney import (
    IlpTimeLimitExceeded,
    KidneyConfig,
    TIEBREAK_MAX_CARDINALITY_ILP,
)
from witness.kidney_ir import find_hospital_manipulation_ir, standalone_all
from witness.kidney_ir import verify_in_subprocess as verify_ir_in_subprocess
from witness.kidney_real_data import load_real_kidney_market, real_instances_for_p
from witness.replay_kidney import verify_in_subprocess as verify_plain_in_subprocess
from witness.search_kidney import find_hospital_manipulation


def mcnemar(b: int, c: int) -> "tuple[float, float]":
    """Exact-ish McNemar on discordant counts b (plain-only hit) and c
    (IR-only hit). Returns (statistic, two-sided p)."""
    n = b + c
    if n == 0:
        return 0.0, 1.0
    # binomial two-sided exact test against p=0.5
    p = 2.0 * sum(math.comb(n, i) for i in range(0, min(b, c) + 1)) / (2.0 ** n)
    return float(b - c), min(1.0, p)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--p", type=int, default=500)
    ap.add_argument("--k", type=int, default=3)
    ap.add_argument("--draws", type=int, default=20)
    ap.add_argument("--pairs-per-hospital", type=int, default=6)
    ap.add_argument("--ownership-seed", type=str, default="ir-paired-v1")
    ap.add_argument(
        "--max-ilp-seconds", type=float, default=300.0,
        help="SAME cap applied to both arms -- this is the point of the design",
    )
    ap.add_argument("--hospitals-per-market", type=int, default=2)
    ap.add_argument("--out-dir", type=str, default="results/kidney_ir_paired_p500")
    args = ap.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)
    rows_path = os.path.join(args.out_dir, "paired_rows.jsonl")

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

    cfg = KidneyConfig(
        tiebreak_policy=TIEBREAK_MAX_CARDINALITY_ILP,
        max_cycle_length=args.k,
        max_ilp_seconds=args.max_ilp_seconds,
    )
    n_hosp = max(1, round(args.p / args.pairs_per_hospital))
    members = real_instances_for_p(args.p)

    for draw in range(args.draws):
        for mi, member in enumerate(members):
            market, profile, _meta = load_real_kidney_market(
                member, n_hospitals=n_hosp, ownership_seed=args.ownership_seed, ownership_draw_index=draw,
            )
            chosen = [market.hospitals[(draw + j) % len(market.hospitals)] for j in range(args.hospitals_per_market)]
            if not chosen:
                continue

            # standalone(h) depends only on the market (not the profile/report), and
            # find_hospital_manipulation_ir's own docstring says a caller checking
            # MULTIPLE hospitals on the SAME market should compute this ONCE and
            # reuse it -- the original bug here was recomputing it (an ILP over
            # EVERY hospital in the market, ~83 solves at P=500) on every single
            # hospital-check, doubling+ the real cost for no completeness benefit.
            # If it can't even finish once within budget, that is itself a real,
            # recordable fact about this market -- not silently retried per hospital.
            try:
                standalone_values = standalone_all(market, args.k, max_seconds=args.max_ilp_seconds)
                standalone_status = "ok"
            except IlpTimeLimitExceeded:
                standalone_values = None
                standalone_status = "skipped"

            for h in chosen:
                rid = f"{args.p}|{args.k}|{draw}|{mi}|{h}"
                if rid in done:
                    continue

                if standalone_values is None:
                    emit({
                        "id": rid, "p": args.p, "k": args.k, "draw": draw, "member": member, "hospital": h,
                        "hospital_size": len(market.pairs_of(h)),
                        "plain_status": "n/a", "plain_hit": False,
                        "ir_status": "skipped_standalone", "ir_hit": False,
                        "both_resolved": False,
                    })
                    continue

                # --- plain arm ---
                plain_status, plain_hit = "ok", False
                try:
                    w = find_hospital_manipulation(market, profile, h, cfg)
                    if w is not None:
                        ok, _ = verify_plain_in_subprocess(w.to_dict())
                        plain_hit = bool(ok)
                except IlpTimeLimitExceeded:
                    plain_status = "skipped"
                except Exception as exc:  # noqa: BLE001
                    plain_status = f"error:{type(exc).__name__}"

                # --- IR arm, SAME instance, SAME cap ---
                ir_status, ir_hit = "ok", False
                try:
                    wir, _stats = find_hospital_manipulation_ir(
                        market, profile, h,
                        max_cycle_length=args.k,
                        max_ilp_seconds=args.max_ilp_seconds,
                        standalone_values=standalone_values,
                    )
                    if wir is not None:
                        ok, _ = verify_ir_in_subprocess(wir.to_dict())
                        ir_hit = bool(ok)
                except IlpTimeLimitExceeded:
                    ir_status = "skipped"
                except Exception as exc:  # noqa: BLE001
                    ir_status = f"error:{type(exc).__name__}"

                emit({
                    "id": rid, "p": args.p, "k": args.k, "draw": draw, "member": member, "hospital": h,
                    "hospital_size": len(market.pairs_of(h)),
                    "plain_status": plain_status, "plain_hit": plain_hit,
                    "ir_status": ir_status, "ir_hit": ir_hit,
                    "both_resolved": plain_status == "ok" and ir_status == "ok",
                })

                # running report over jointly-resolved pairs only
                rows = [json.loads(l) for l in open(rows_path)]
                both = [r for r in rows if r["both_resolved"]]
                b = sum(1 for r in both if r["plain_hit"] and not r["ir_hit"])
                c = sum(1 for r in both if r["ir_hit"] and not r["plain_hit"])
                pl = sum(1 for r in both if r["plain_hit"])
                ir = sum(1 for r in both if r["ir_hit"])
                stat, pv = mcnemar(b, c)
                print(
                    f"[paired] attempted={len(rows)} both_resolved={len(both)} "
                    f"({len(both)/len(rows)*100:.0f}%) | plain {pl}/{len(both)} vs IR {ir}/{len(both)} "
                    f"| discordant b={b} c={c} McNemar p={pv:.4g}",
                    flush=True,
                )

    print("\nDONE")


if __name__ == "__main__":
    main()
