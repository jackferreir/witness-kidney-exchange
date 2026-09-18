#!/usr/bin/env python3
"""Clustered inference for the tiebreak-sensitivity census.

WHY CLUSTERED. There are only ~15 distinct REAL compatibility graphs per pool
size (`witness.kidney_real_data`); the large row counts come from re-drawing
hospital partitions over those same graphs. Hospitals from one graph share its
compatibility structure, so rows are CLUSTERED, not independent. Treating them
as independent (as a naive t-test or proportion test would) understates the
standard errors. Every number below clusters on `member`, the source graph.

WHAT IS TESTED. The census measures, for the SAME hospital:
  * `tiebreak_spread` = u_true_max - u_true_min, the full range of that
    hospital's outcome across ALL maximum-cardinality central clearings at the
    truthful profile -- what happens to it for reasons outside its control.
  * `strategic_gain` = best achievable utility gain over all misreports
    (exhaustive, max-gain) -- what it can achieve by acting strategically.
Because both are measured on the same hospital, the comparison is PAIRED, and
the statistic of interest is the per-hospital difference `spread - gain`.

THREE ANSWERS, which fail differently:
  1. CLUSTER BOOTSTRAP on mean(spread - gain): resample GRAPHS with
     replacement, percentile CI. No independence assumption within a graph.
  2. EXACT SIGN TEST across graphs: collapse each graph to its own mean
     (spread - gain), then ask in how many graphs that is positive. The graph
     is the unit of analysis; n = number of graphs. Assumption-free and very
     conservative.
  3. AMPLIFICATION (K=3 vs K=2): the same 15 graphs are used at both cycle
     lengths, so the K=3-minus-K=2 difference in mean spread is PAIRED BY
     GRAPH, and gets its own clustered bootstrap and sign test.

The naive unclustered figure is printed alongside only so the overstatement is
visible -- never as the headline.
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import os
from collections import defaultdict

import numpy as np


def exact_binom_two_sided(k: int, n: int) -> float:
    if n == 0:
        return 1.0
    obs = abs(k - n / 2)
    tot = sum(math.comb(n, i) for i in range(n + 1) if abs(i - n / 2) >= obs - 1e-12)
    return min(1.0, tot / (2.0 ** n))


def load_cell(path):
    rows = []
    for line in open(path):
        r = json.loads(line)
        if r.get("status") != "ok":
            continue
        rows.append({
            "cluster": r["member"],
            "size": r["hospital_size"],
            "spread": r["tiebreak_spread"],
            "gain": r["strategic_gain"],
            "diff": r["tiebreak_spread"] - r["strategic_gain"],
        })
    return rows


def cluster_bootstrap_mean(by_cluster, field, B, rng):
    keys = list(by_cluster)
    if len(keys) < 2:
        return None
    stats = []
    for _ in range(B):
        pick = rng.choice(len(keys), size=len(keys), replace=True)
        vals = [r[field] for i in pick for r in by_cluster[keys[i]]]
        if vals:
            stats.append(sum(vals) / len(vals))
    a = np.array(stats)
    return float(np.percentile(a, 2.5)), float(np.percentile(a, 97.5))


def report_cell(label, rows, B, rng):
    if not rows:
        print(f"\n{label}: no data")
        return None
    by_cluster = defaultdict(list)
    for r in rows:
        by_cluster[r["cluster"]].append(r)

    spread = [r["spread"] for r in rows]
    gain = [r["gain"] for r in rows]
    diff = [r["diff"] for r in rows]
    n_gt = sum(1 for d in diff if d > 0)
    n_eq = sum(1 for d in diff if d == 0)
    n_lt = sum(1 for d in diff if d < 0)

    print(f"\n{'='*74}\n{label}  (n={len(rows)} hospitals, {len(by_cluster)} source graphs)")
    print(f"  mean spread {np.mean(spread):.3f} | mean gain {np.mean(gain):.3f} | "
          f"mean(spread-gain) {np.mean(diff):.3f}")
    print(f"  spread>gain {n_gt} ({n_gt/len(rows)*100:.1f}%) | ==  {n_eq} | spread<gain {n_lt}")

    # naive paired t-like z, for contrast only
    sd = np.std(diff, ddof=1) if len(diff) > 1 else 0.0
    if sd > 0:
        z = np.mean(diff) / (sd / math.sqrt(len(diff)))
        print(f"  NAIVE (assumes independence, OVERSTATED): z={z:.2f}  p={math.erfc(abs(z)/math.sqrt(2)):.3g}")

    ci = cluster_bootstrap_mean(by_cluster, "diff", B, rng)
    if ci:
        lo, hi = ci
        verdict = "EXCLUDES 0" if (lo > 0 or hi < 0) else "includes 0"
        print(f"  CLUSTER BOOTSTRAP 95% CI on mean(spread-gain): [{lo:+.3f}, {hi:+.3f}]  -> {verdict}")

    per_graph = {k: np.mean([r["diff"] for r in v]) for k, v in by_cluster.items()}
    nz = [v for v in per_graph.values() if abs(v) > 1e-12]
    pos = sum(1 for v in nz if v > 0)
    p = exact_binom_two_sided(pos, len(nz))
    print(f"  SIGN TEST across graphs: {pos}/{len(nz)} graphs have mean spread>gain, exact p={p:.4g}")
    return by_cluster


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bootstrap", type=int, default=20000)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--min-rows", type=int, default=500,
                    help="only analyse cells with at least this many completed rows")
    args = ap.parse_args()
    rng = np.random.default_rng(args.seed)

    print("TIEBREAK CENSUS -- CLUSTERED INFERENCE (source graph = cluster unit)")
    print(f"bootstrap reps {args.bootstrap}, seed {args.seed}, min rows per cell {args.min_rows}")

    cells = {}
    for d in sorted(glob.glob("results/kidney_tiebreak_census*")):
        f = os.path.join(d, "hospital_rows.jsonl")
        if not os.path.exists(f):
            continue
        rows = load_cell(f)
        if len(rows) < args.min_rows:
            print(f"\n[skipped: only {len(rows)} rows] {os.path.basename(d)}")
            continue
        k = 2 if "_k2_" in d else 3
        # pool size from any row's path label
        p = int(os.path.basename(d).split("_p")[-1].replace("_b", ""))
        cells[(k, p)] = rows

    by = {}
    for (k, p), rows in sorted(cells.items()):
        by[(k, p)] = report_cell(f"K={k}, P={p}", rows, args.bootstrap, rng)

    # ---- amplification: K=3 vs K=2 at the same pool size, paired BY GRAPH ----
    print(f"\n{'='*74}\nAMPLIFICATION: does allowing 3-cycles increase the spread?")
    print("(same 15 real graphs at both cycle lengths -> paired by graph)")
    for p in sorted({p for (_, p) in cells}):
        if (2, p) not in cells or (3, p) not in cells:
            print(f"  P={p}: need both K=2 and K=3 completed -- skipped")
            continue
        g2 = defaultdict(list)
        g3 = defaultdict(list)
        for r in cells[(2, p)]:
            g2[r["cluster"]].append(r["spread"])
        for r in cells[(3, p)]:
            g3[r["cluster"]].append(r["spread"])
        shared = sorted(set(g2) & set(g3))
        if len(shared) < 2:
            print(f"  P={p}: too few shared graphs")
            continue
        per_graph_delta = {m: np.mean(g3[m]) - np.mean(g2[m]) for m in shared}
        obs = float(np.mean(list(per_graph_delta.values())))

        deltas = []
        for _ in range(args.bootstrap):
            pick = rng.choice(len(shared), size=len(shared), replace=True)
            deltas.append(np.mean([per_graph_delta[shared[i]] for i in pick]))
        lo, hi = np.percentile(deltas, [2.5, 97.5])
        pos = sum(1 for v in per_graph_delta.values() if v > 1e-12)
        nz = sum(1 for v in per_graph_delta.values() if abs(v) > 1e-12)
        pval = exact_binom_two_sided(pos, nz)
        verdict = "EXCLUDES 0 -> 3-cycles amplify" if lo > 0 else ("EXCLUDES 0 -> 3-cycles reduce" if hi < 0 else "includes 0")
        m2 = np.mean([v for vs in g2.values() for v in vs])
        m3 = np.mean([v for vs in g3.values() for v in vs])
        print(f"\n  P={p} ({len(shared)} shared graphs): K=2 mean spread {m2:.3f} -> K=3 {m3:.3f}")
        print(f"    mean per-graph increase {obs:+.3f}   clustered 95% CI [{lo:+.3f}, {hi:+.3f}]  -> {verdict}")
        print(f"    sign test: {pos}/{nz} graphs show K=3 > K=2, exact p={pval:.4g}")


if __name__ == "__main__":
    main()
