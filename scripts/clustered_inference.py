#!/usr/bin/env python3
"""Re-does this project's inference treating the SOURCE GRAPH as the unit of
clustering, instead of pretending every hospital-check is independent.

WHY THIS EXISTS. Every p-value reported so far (e.g. the K=2 size-effect's
p ~= 3e-26 over "6,300 hospitals") was computed as if each hospital-check were
an independent observation. It is not. There are only ~15 distinct REAL
compatibility graphs per pool size (see `witness.kidney_real_data`); the large
n comes from re-partitioning those same graphs into hospitals many times over.
Hospitals drawn from one graph share its compatibility structure, so the
observations are CLUSTERED. Treating them as independent understates the
standard errors and overstates significance. The effect may well be real --
within-regime replication and consistency across pool sizes both argue for it
-- but the honest number has to account for the clustering, and an economics
referee will check this first.

TWO INDEPENDENT ANSWERS, deliberately, because they fail differently:

1. CLUSTER BOOTSTRAP. Resample GRAPHS (not hospitals) with replacement, recompute
   the effect on each resample, and read a percentile CI off the bootstrap
   distribution. Makes no independence assumption across hospitals within a
   graph. Reported as a 95% CI on the large-minus-small rate difference.

2. EXACT SIGN TEST ACROSS GRAPHS. Collapse each graph to ONE number (its own
   large-hospital rate minus its own small-hospital rate), then ask: in how many
   graphs is that difference positive? Exact binomial against p=0.5. The graph
   is the unit of analysis, n = number of graphs, nothing is pooled. Extremely
   conservative and essentially assumption-free -- if the effect survives this,
   it is not a clustering artifact.

The naive (unclustered) statistic is printed alongside purely so the
overstatement is visible, never as the headline.
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import os
import sys
from collections import defaultdict

import numpy as np

LARGE_MIN = 7  # hospitals with >= this many pairs count as "large"


def exact_binom_two_sided(k: int, n: int) -> float:
    """P(|X - n/2| >= |k - n/2|) for X ~ Binom(n, 0.5)."""
    if n == 0:
        return 1.0
    obs = abs(k - n / 2)
    tot = 0.0
    for i in range(n + 1):
        if abs(i - n / 2) >= obs - 1e-12:
            tot += math.comb(n, i)
    return min(1.0, tot / (2.0 ** n))


def cochran_armitage(sizes, hits):
    n = len(sizes)
    r = sum(hits)
    if n == 0 or r == 0 or r == n:
        return None, None
    p = r / n
    sbar = sum(sizes) / n
    num = sum(s * (h - p) for s, h in zip(sizes, hits))
    var = p * (1 - p) * sum((s - sbar) ** 2 for s in sizes)
    if var <= 0:
        return None, None
    z = num / math.sqrt(var)
    return z, math.erfc(abs(z) / math.sqrt(2))


def rate_diff_large_small(rows):
    """(large-hospital rate) - (small-hospital rate), or None if a side is empty."""
    lg = [r["hit"] for r in rows if r["size"] >= LARGE_MIN]
    sm = [r["hit"] for r in rows if r["size"] < LARGE_MIN]
    if not lg or not sm:
        return None
    return sum(lg) / len(lg) - sum(sm) / len(sm)


def cluster_bootstrap_diff(by_cluster, B=10000, seed=0):
    """Percentile CI for the large-minus-small rate difference, resampling
    whole CLUSTERS (graphs) with replacement."""
    rng = np.random.default_rng(seed)
    keys = list(by_cluster)
    if len(keys) < 2:
        return None
    stats = []
    for _ in range(B):
        picked = rng.choice(len(keys), size=len(keys), replace=True)
        pooled = []
        for i in picked:
            pooled.extend(by_cluster[keys[i]])
        d = rate_diff_large_small(pooled)
        if d is not None:
            stats.append(d)
    if len(stats) < B * 0.5:
        return None
    a = np.array(stats)
    return float(np.percentile(a, 2.5)), float(np.percentile(a, 97.5)), float(a.mean())


def sign_test_across_clusters(by_cluster):
    """One number per graph: its own large-rate minus small-rate. Then an exact
    binomial sign test. The graph is the unit; nothing is pooled across graphs."""
    diffs = []
    for k, rows in by_cluster.items():
        d = rate_diff_large_small(rows)
        if d is not None:
            diffs.append(d)
    nonzero = [d for d in diffs if abs(d) > 1e-12]
    pos = sum(1 for d in nonzero if d > 0)
    p = exact_binom_two_sided(pos, len(nonzero))
    return {
        "n_graphs_usable": len(diffs),
        "n_graphs_nonzero": len(nonzero),
        "n_positive": pos,
        "median_diff": float(np.median(diffs)) if diffs else None,
        "exact_p": p,
    }


def load_size_trend(path):
    """size-trend jsonl -> rows with cluster = source-graph index (from cid)."""
    out = []
    for line in open(path):
        r = json.loads(line)
        if r.get("status") != "ok":
            continue
        parts = r["cid"].split("|")  # P|K|regime|draw|member_index|hospital
        out.append({
            "cluster": parts[4],
            "regime": r["regime"],
            "size": r["size"],
            "hit": bool(r["manipulated"]),
        })
    return out


def report_size_effect(label, rows, args):
    print(f"\n{'='*72}\n{label}   (n={len(rows)} hospital-checks)")
    if not rows:
        print("  no data")
        return
    by_cluster = defaultdict(list)
    for r in rows:
        by_cluster[r["cluster"]].append(r)
    print(f"  distinct source graphs (clusters): {len(by_cluster)}")

    z, p = cochran_armitage([r["size"] for r in rows], [r["hit"] for r in rows])
    print(f"  NAIVE (assumes independence, OVERSTATED): z={z:.2f}  p={p:.3g}" if z else "  NAIVE: n/a")

    d = rate_diff_large_small(rows)
    print(f"  point estimate: large(>={LARGE_MIN}) minus small rate = {d*100:.2f} pp" if d is not None else "  point estimate: n/a")

    ci = cluster_bootstrap_diff(by_cluster, B=args.bootstrap, seed=args.seed)
    if ci:
        lo, hi, mean = ci
        excl = "EXCLUDES 0" if (lo > 0 or hi < 0) else "includes 0"
        print(f"  CLUSTER BOOTSTRAP 95% CI on that difference: [{lo*100:.2f}, {hi*100:.2f}] pp  -> {excl}")
    else:
        print("  CLUSTER BOOTSTRAP: not computable")

    st = sign_test_across_clusters(by_cluster)
    print(f"  SIGN TEST across graphs: {st['n_positive']}/{st['n_graphs_nonzero']} graphs show large>small, "
          f"exact p={st['exact_p']:.4g}  (median within-graph diff {st['median_diff']*100:.2f} pp)"
          if st["median_diff"] is not None else "  SIGN TEST: n/a")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bootstrap", type=int, default=10000)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--scratch", type=str,
                    default="/private/tmp/claude-501/-Users-joseferreira-Desktop-Witness/"
                            "f9b9cf8e-047f-48b9-ab12-d8a275d5eefd/scratchpad")
    args = ap.parse_args()

    print("CLUSTERED RE-ANALYSIS -- source graph is the unit of clustering")
    print(f"bootstrap reps: {args.bootstrap}, seed: {args.seed}, large threshold: >={LARGE_MIN} pairs")

    for fname, label in [
        ("trend_p50k2.jsonl", "SIZE EFFECT -- K=2, P=50"),
        ("trend_p100k3.jsonl", "SIZE EFFECT -- K=3, P=100"),
        ("trend_p250k3.jsonl", "SIZE EFFECT -- K=3, P=250"),
    ]:
        path = os.path.join(args.scratch, fname)
        if os.path.exists(path):
            report_size_effect(label, load_size_trend(path), args)
        else:
            print(f"\n{label}: file not found ({path})")

    # ---- IR vs plain, clustered by graph, per pool size ----
    print(f"\n{'='*72}\nIR vs PLAIN deviation rate -- clustered by source graph")
    ir_rows = []
    for d in ["results/kidney_ir_sweep", "results/kidney_ir_p100", "results/kidney_ir_p250_power"]:
        f = os.path.join(d, "deviation_checks.jsonl")
        if os.path.exists(f):
            ir_rows += [json.loads(l) for l in open(f)]
    by_p = defaultdict(lambda: defaultdict(list))
    for r in ir_rows:
        if r.get("k") != 3:
            continue
        by_p[r["p"]][r["member"]].append(bool(r.get("confirmed")))
    rng = np.random.default_rng(args.seed)
    for P in sorted(by_p):
        clusters = by_p[P]
        keys = list(clusters)
        allhits = [h for v in clusters.values() for h in v]
        naive = sum(allhits) / len(allhits)
        boots = []
        for _ in range(args.bootstrap):
            picked = rng.choice(len(keys), size=len(keys), replace=True)
            pool = [h for i in picked for h in clusters[keys[i]]]
            if pool:
                boots.append(sum(pool) / len(pool))
        lo, hi = np.percentile(boots, [2.5, 97.5])
        print(f"  P={P}: IR rate {naive*100:.2f}%  ({len(allhits)} checks over {len(keys)} graphs)  "
              f"cluster-bootstrap 95% CI [{lo*100:.2f}, {hi*100:.2f}]%")
    print("\n(plain-arm baselines live in separate runs; comparing two arms with clustered CIs "
          "requires the paired design for P=500 -- see scripts/kidney_ir_paired.py)")


if __name__ == "__main__":
    main()
