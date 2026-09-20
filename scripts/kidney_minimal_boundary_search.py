#!/usr/bin/env python3
"""Exhaustive proof that the k=2/k>=3 boundary (MODEL.md Theorem, S:7.3) has
its first counterexample at exactly 4 pairs -- not merely the smallest one a
sampling search happened to find.

WHY EXHAUSTIVE, NOT SAMPLED. An earlier draft claimed a 6-pair example was
"minimal" because a search starting at n=6 found one there. Two of those six
pairs were inert padding, never touched by any cycle; the true minimum was 4.
"Minimal" is a claim about the ENTIRE space of n-pair markets, which sampling
cannot establish -- only enumeration can. At n=3 and n=4 the space is small
enough (every digraph, every non-trivial ownership split) to enumerate
completely in minutes. This script IS that enumeration, not an approximation
of it, and is deliberately a from-scratch brute force sharing no code with
`witness.kidney` -- packings are found by trying every subset of candidate
cycles, not by calling the mechanism's own ILP or Blossom solvers.

WHAT "DETERMINATE" MEANS HERE, precisely. A hospital h is determinate at a
report profile if every maximum-cardinality central selection gives h the
SAME utility (central-matched pairs plus its own best local recourse on
whatever remains). If h's utility varied across optimal selections, a
"gain" from withholding could just be the mechanism happening to break a tie
in h's favor -- not a genuine violation of the theorem, which is about
`U_true_max`, the BEST such utility. Restricting to determinate hospitals
makes every counterexample found here unambiguous: there was no lucky tie to
exploit, and the deviation still worked.

WHAT IS COUNTED. For every digraph on n labeled pairs and every way to split
those pairs between exactly two hospitals (both non-empty), for the
hospital named "h2" (by the ownership mask's positive side): if h2 is
determinate at the truthful profile, does ANY subset of its own pairs it
could report instead make its WORST-CASE utility (worst-case, since a
withholding hospital cannot control which of ITS OWN false report's optimal
selections gets chosen either) exceed its truthful, determinate utility?
That is exactly `U_false_min(R') > U_true_max`, i.e. a deviation that is
`STRONG` per `scripts/kidney_tiebreak_exact.py`'s own terminology --
profitable under every possible way the false report's ties could break.

RESULT, reproduced by running this file directly:

    n=3, k=2:      0 counterexamples /    342 determinate hospital-instances
    n=3, k=3:      0 counterexamples /    372 determinate hospital-instances
    n=4, k=2:      0 counterexamples / 46,976 determinate hospital-instances
    n=4, k=3:    204 counterexamples / 49,888 determinate hospital-instances

n=3 is impossible at EITHER cycle length -- not merely at k=2 -- so the
boundary is specifically about cycle length crossing from 2 to 3, not about
small markets being generically safe. n=4 is impossible at k=2 (agreeing
with the proved theorem) and populated at k=3, which is the control showing
this exhaustive method can detect a violation when one exists: the same
code, the same n, only k differs.

`tests/test_kidney_minimal_boundary.py`'s KIDMIN-A fixture is the
lexicographically-first n=4 hit this script finds, hand-verified against
`witness.oracles_kidney` separately in that file.
"""
from __future__ import annotations

import argparse
import itertools
import sys
import time


def _candidate_cycles(pairs: "tuple[str, ...]", edges: set, k: int) -> "list[tuple]":
    out = []
    for u, v in itertools.combinations(pairs, 2):
        if (u, v) in edges and (v, u) in edges:
            out.append((u, v))
    if k >= 3:
        for a, b, c in itertools.permutations(pairs, 3):
            if (a, b) in edges and (b, c) in edges and (c, a) in edges:
                out.append((a, b, c))
    return out


def _packings(cycles: "list[tuple]") -> "list[frozenset]":
    """Every vertex-disjoint subset of `cycles`, as the frozenset of pairs
    it covers. Exponential in len(cycles); fine at the sizes this script
    runs (n<=4 has few enough candidate cycles)."""
    out = []
    for r in range(len(cycles) + 1):
        for subset in itertools.combinations(cycles, r):
            used: set = set()
            ok = True
            for c in subset:
                if used & set(c):
                    ok = False
                    break
                used |= set(c)
            if ok:
                out.append(frozenset(used))
    return out


def _max_card(pairs: "tuple[str, ...]", edges: set, k: int) -> "tuple[int, list[frozenset]]":
    packings = _packings(_candidate_cycles(pairs, edges, k))
    if not packings:
        return 0, [frozenset()]
    best = max(len(p) for p in packings)
    return best, [p for p in packings if len(p) == best]


def _utility(own: "tuple[str, ...]", matched: frozenset, edges: set, k: int) -> int:
    residual = tuple(p for p in own if p not in matched)
    local_max, _ = _max_card(residual, edges, k)
    return sum(1 for p in own if p in matched) + local_max


def scan(n: int, k: int) -> "tuple[int, int]":
    """Returns (determinate_hospital_instances_checked, counterexamples).

    A "hospital-instance" is one (digraph, ownership split) pair, evaluated
    for h2 only -- h1's role is symmetric and covered by the complementary
    ownership mask elsewhere in the enumeration, so checking h2 across every
    mask already covers every hospital's position.
    """
    pairs = tuple(f"p{i}" for i in range(n))
    arcs = [(u, v) for u in pairs for v in pairs if u != v]
    checked = hits = 0

    for emask in range(1 << len(arcs)):
        edges = {arcs[i] for i in range(len(arcs)) if emask >> i & 1}
        for omask in range(1, (1 << n) - 1):  # both hospitals non-empty
            own2 = tuple(pairs[i] for i in range(n) if omask >> i & 1)
            own1 = tuple(p for p in pairs if p not in own2)

            _, truth_opts = _max_card(pairs, edges, k)
            truthful_utilities = {_utility(own2, m, edges, k) for m in truth_opts}
            if len(truthful_utilities) != 1:
                continue  # not determinate: a tie-break could already explain any gain
            u_true = truthful_utilities.pop()
            checked += 1

            for r in range(len(own2) + 1):
                for kept in itertools.combinations(own2, r):
                    pool = tuple(sorted(set(own1) | set(kept)))
                    _, false_opts = _max_card(pool, edges, k)
                    worst_case = min(_utility(own2, m, edges, k) for m in false_opts)
                    if worst_case > u_true:
                        hits += 1
                        break
                else:
                    continue
                break
    return checked, hits


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--n", type=int, nargs="+", default=[3, 4])
    ap.add_argument("--k", type=int, nargs="+", default=[2, 3])
    args = ap.parse_args()
    for n in args.n:
        for k in args.k:
            t0 = time.perf_counter()
            checked, hits = scan(n, k)
            el = time.perf_counter() - t0
            print(f"n={n} k={k}: {hits} counterexamples / {checked} determinate "
                  f"hospital-instances  ({el:.1f}s)")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
