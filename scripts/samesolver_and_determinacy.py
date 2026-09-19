#!/usr/bin/env python3
"""Produces the two numbers the README actually headlines. Exists because an
earlier README cited `scripts/clustered_inference.py` for a K=2-vs-K=3
comparison that script does not contain -- the figures had been computed
ad hoc and mis-attributed. Every statistic quoted in the README's "What we
found" section should come out of this file.

ANALYSIS 1 -- SAME-SOLVER CYCLE-LENGTH EFFECT.
The clean comparison: `scripts/kidney_tiebreak_census.py` hardcodes the
exact-ILP policy regardless of cycle length, so its K=2 and K=3 runs differ
in cycle length and nothing else. (The older headline compared a Blossom
2-cycle arm against an ILP 3-cycle arm, confounding solver with cycle
length -- this project separately found that swapping tiebreak policy on
identical markets changes WHICH hospitals can manipulate, with zero overlap,
so that confound is not innocuous.) Clustered on source graph, because there
are only ~15 real compatibility graphs per pool size and everything else is
re-partitions of them.

ANALYSIS 2 -- THE DETERMINACY CONDITIONAL.
For each outcome-blind hospital the census records both `tiebreak_spread`
(range of its outcome across ALL maximum-cardinality clearings) and
`strategic_gain` (best misreport gain, exhaustive). That allows the
conditional nobody has reported:

    P(can manipulate | mechanism is determinate for it)   [spread == 0]
    P(can manipulate | mechanism is indeterminate for it) [spread  > 0]

If the first is ~0, manipulability is close to a SUBSET of indeterminacy,
which would make determinacy nearly sufficient for strategyproofness in this
class. Reported with a clustered CI and the exact count of counterexamples,
because the counterexamples are the whole story if the conditional is not 0.
"""
from __future__ import annotations

import collections
import glob
import json
import math

import numpy as np

B = 20000


def binom_two_sided(k: int, n: int) -> float:
    if n == 0:
        return 1.0
    obs = abs(k - n / 2)
    return min(1.0, sum(math.comb(n, i) for i in range(n + 1)
                        if abs(i - n / 2) >= obs - 1e-12) / 2 ** n)


def load(pattern, k_filter):
    """-> {graph: [n_checked, n_manipulable]}, plus raw rows."""
    per_graph = collections.defaultdict(lambda: [0, 0])
    rows = []
    for d in glob.glob(pattern):
        f = f"{d}/hospital_rows.jsonl"
        try:
            fh = open(f)
        except FileNotFoundError:
            continue
        for line in fh:
            r = json.loads(line)
            if r.get("status") != "ok" or r.get("k") != k_filter:
                continue
            rows.append(r)
            g = per_graph[r["member"]]
            g[0] += 1
            g[1] += r["strategic_gain"] > 0
    return per_graph, rows


def clustered_diff(a, b, rng):
    """Cluster-bootstrap CI + exact sign test on rate(b) - rate(a), graphs shared."""
    shared = sorted(set(a) & set(b))
    if len(shared) < 2:
        return None
    diffs = []
    for _ in range(B):
        pick = rng.choice(len(shared), size=len(shared), replace=True)
        na = sum(a[shared[i]][0] for i in pick); ha = sum(a[shared[i]][1] for i in pick)
        nb = sum(b[shared[i]][0] for i in pick); hb = sum(b[shared[i]][1] for i in pick)
        if na and nb:
            diffs.append(hb / nb - ha / na)
    arr = np.array(diffs)
    lo, hi = np.percentile(arr, [2.5, 97.5])
    per = {m: b[m][1] / b[m][0] - a[m][1] / a[m][0] for m in shared}
    nz = [v for v in per.values() if abs(v) > 1e-12]
    pos = sum(1 for v in nz if v > 0)
    na = sum(a[m][0] for m in shared); ha = sum(a[m][1] for m in shared)
    nb = sum(b[m][0] for m in shared); hb = sum(b[m][1] for m in shared)
    return {
        "n_graphs": len(shared), "a": (ha, na), "b": (hb, nb),
        "diff_pp": (hb / nb - ha / na) * 100, "ci": (lo * 100, hi * 100),
        "sign": (pos, len(nz), binom_two_sided(pos, len(nz))),
    }


def main():
    rng = np.random.default_rng(0)

    print("=" * 74)
    print("ANALYSIS 1 -- SAME-SOLVER CYCLE-LENGTH EFFECT (ILP both arms)")
    print("=" * 74)
    for P, k2glob, k3glob in [
        (50,  "results/kidney_tiebreak_census_k2_p50",  "results/kidney_tiebreak_census_p50"),
        (100, "results/kidney_tiebreak_census_k2_p100", "results/kidney_tiebreak_census_p100"),
        (250, "results/kidney_tiebreak_census_k2_p250", "results/kidney_tiebreak_census_p250*"),
    ]:
        a, _ = load(k2glob, 2)
        b, _ = load(k3glob, 3)
        if not a or not b:
            print(f"\nP={P}: missing an arm, skipped")
            continue
        r = clustered_diff(a, b, rng)
        if r is None:
            print(f"\nP={P}: too few shared graphs")
            continue
        print(f"\nP={P}  ({r['n_graphs']} shared graphs)")
        print(f"  K=2 (ILP): {r['a'][0]}/{r['a'][1]} = {r['a'][0]/r['a'][1]*100:.2f}%")
        print(f"  K=3 (ILP): {r['b'][0]}/{r['b'][1]} = {r['b'][0]/r['b'][1]*100:.2f}%")
        print(f"  difference: {r['diff_pp']:+.2f} pp   clustered 95% CI [{r['ci'][0]:+.2f}, {r['ci'][1]:+.2f}]")
        print(f"  sign test: {r['sign'][0]}/{r['sign'][1]} graphs K3>K2, exact p={r['sign'][2]:.4f}")

    print()
    print("=" * 74)
    print("ANALYSIS 2 -- DETERMINACY CONDITIONAL")
    print("=" * 74)
    allrows = []
    for d in glob.glob("results/kidney_tiebreak_census*"):
        try:
            fh = open(f"{d}/hospital_rows.jsonl")
        except FileNotFoundError:
            continue
        for line in fh:
            r = json.loads(line)
            if r.get("status") == "ok":
                allrows.append(r)

    det = [r for r in allrows if r["tiebreak_spread"] == 0]
    ind = [r for r in allrows if r["tiebreak_spread"] > 0]
    det_hit = sum(1 for r in det if r["strategic_gain"] > 0)
    ind_hit = sum(1 for r in ind if r["strategic_gain"] > 0)
    print(f"\n  total outcome-blind hospitals: {len(allrows)}")
    print(f"  DETERMINATE   (spread==0): {det_hit}/{len(det)} manipulable = {det_hit/len(det)*100:.3f}%")
    print(f"  INDETERMINATE (spread >0): {ind_hit}/{len(ind)} manipulable = {ind_hit/len(ind)*100:.3f}%")
    if det_hit:
        print(f"  risk ratio: {(ind_hit/len(ind))/(det_hit/len(det)):.1f}x")

    man = [r for r in allrows if r["strategic_gain"] > 0]
    also = sum(1 for r in man if r["tiebreak_spread"] > 0)
    print(f"\n  of {len(man)} manipulable hospitals, {also} ({also/len(man)*100:.1f}%) are also indeterminate")
    print(f"  COUNTEREXAMPLES (manipulable while determinate): {len(man)-also}")
    for r in man:
        if r["tiebreak_spread"] == 0:
            print(f"    {r['id']}  gain={r['strategic_gain']}  size={r['hospital_size']}  {r['member'].split('/')[-1]}")

    # clustered: is the determinate-vs-indeterminate difference real across graphs?
    ga = collections.defaultdict(lambda: [0, 0])
    gb = collections.defaultdict(lambda: [0, 0])
    for r in allrows:
        tgt = ga if r["tiebreak_spread"] == 0 else gb
        tgt[r["member"]][0] += 1
        tgt[r["member"]][1] += r["strategic_gain"] > 0
    res = clustered_diff(ga, gb, rng)
    if res:
        print(f"\n  clustered over {res['n_graphs']} graphs: indeterminate-minus-determinate "
              f"{res['diff_pp']:+.2f} pp, 95% CI [{res['ci'][0]:+.2f}, {res['ci'][1]:+.2f}]")
        print(f"  sign test: {res['sign'][0]}/{res['sign'][1]} graphs, exact p={res['sign'][2]:.4f}")


if __name__ == "__main__":
    main()
