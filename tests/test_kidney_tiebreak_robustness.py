"""Validation gate for `scripts/kidney_tiebreak_robustness.py`, mirroring this
project's own `tests/test_kidney3_ilp_matches_oracle.py` discipline: before
the ILP-based tiebreak-robustness checker is trusted on real witnesses, its
utility-RANGE computation (`utility_range_for_profile`) must agree EXACTLY
with an independent brute-force re-derivation on 100+ random small markets,
plus one hand-built instance with a genuine tie where the target hospital's
utility differs across maximum-cardinality central clearings.

The brute force below shares NO CODE with `scripts/kidney_tiebreak_robustness.
py`'s ILP path (own cycle enumeration, own vertex-disjoint subset search, own
central-footprint/residual/local-max logic) and NO CODE with `witness.kidney`
itself (re-derived from the raw edge definition, exactly like `witness.
oracles_kidney` is independent of `witness.kidney`) -- it is a second,
structurally different implementation of the same question: "for a hospital
`h`, across EVERY maximum-cardinality central clearing, what utilities are
achievable?"
"""

from __future__ import annotations

import itertools
import random
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
for p in (str(PROJECT_ROOT), str(PROJECT_ROOT / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

from witness.kidney import (  # noqa: E402
    KidneyConfig,
    KidneyMarket,
    KidneyProfile,
    TIEBREAK_LEX_SMALLEST_BY_INDEX,
    clear_kidney_exchange,
)

from kidney_tiebreak_robustness import utility_range_for_profile  # noqa: E402


# ---------------------------------------------------------------------------
# Independent brute force -- own code path, no imports from witness.kidney's
# cycle/selection machinery or from the script's ILP functions.
# ---------------------------------------------------------------------------


def _bf_true_cycles(market: KidneyMarket, pool, max_cycle_length: int):
    pool = list(pool)
    cycles = []
    for u, v in itertools.combinations(pool, 2):
        if market.has_edge(u, v) and market.has_edge(v, u):
            cycles.append((u, v))
    if max_cycle_length >= 3:
        for a, b, c in itertools.combinations(pool, 3):
            if market.has_edge(a, b) and market.has_edge(b, c) and market.has_edge(c, a):
                cycles.append((a, b, c))
            if market.has_edge(a, c) and market.has_edge(c, b) and market.has_edge(b, a):
                cycles.append((a, c, b))
    return cycles


def _bf_all_max_selections(market: KidneyMarket, pool, max_cycle_length: int):
    """Every vertex-disjoint subset of true cycles over `pool` that achieves
    the GLOBAL maximum cardinality, found by brute-force subset search over
    the independently-enumerated cycle list. Returns `(best_cardinality,
    [selection, ...])`."""
    cycles = _bf_true_cycles(market, pool, max_cycle_length)
    n = len(cycles)
    best = 0
    selections = [()]
    for r in range(1, n + 1):
        for combo in itertools.combinations(range(n), r):
            used = set()
            ok = True
            covered = 0
            for i in combo:
                cyc = cycles[i]
                if any(p in used for p in cyc):
                    ok = False
                    break
                used.update(cyc)
                covered += len(cyc)
            if not ok:
                continue
            if covered > best:
                best = covered
                selections = [tuple(cycles[i] for i in combo)]
            elif covered == best:
                selections.append(tuple(cycles[i] for i in combo))
    return best, selections


def _bf_max_cardinality(market: KidneyMarket, pool, max_cycle_length: int) -> int:
    best, _ = _bf_all_max_selections(market, pool, max_cycle_length)
    return best


def _bf_utility_range(market: KidneyMarket, report_map, hospital: str, max_cycle_length: int):
    """From-scratch definitional computation: for EVERY central selection
    achieving the global maximum cardinality, compute `hospital`'s resulting
    utility (footprint from that specific selection, plus the true local
    maximum on the residual it induces), and return the (min, max, c_star)
    over all of them."""
    reported_pool = tuple(p for h in market.hospitals for p in report_map[h])
    c_star, central_selections = _bf_all_max_selections(market, reported_pool, max_cycle_length)

    h_report = report_map[hospital]
    owned = market.pairs_of(hospital)

    utilities = set()
    for sel in central_selections:
        matched = set()
        for cyc in sel:
            matched.update(cyc)
        footprint = [p for p in h_report if p in matched]
        residual = [p for p in owned if p not in matched]
        local_max = _bf_max_cardinality(market, residual, max_cycle_length)
        utilities.add(len(footprint) + local_max)
    return min(utilities), max(utilities), c_star


def _random_market(seed: int, n_pairs: int, n_hospitals: int, edge_prob: float) -> KidneyMarket:
    rng = random.Random(seed)
    pairs = tuple(f"p{i}" for i in range(1, n_pairs + 1))
    hospitals = tuple(f"h{i}" for i in range(1, n_hospitals + 1))
    hospital_of = {p: hospitals[i % n_hospitals] for i, p in enumerate(pairs)}
    edges = set()
    for u in pairs:
        for v in pairs:
            if u != v and rng.random() < edge_prob:
                edges.add((u, v))
    return KidneyMarket(pairs=pairs, hospital_of=hospital_of, hospitals=hospitals, edges=frozenset(edges))


class HandBuiltGenuineTie(unittest.TestCase):
    """3 pairs, 2 hospitals: `a` and `c` are H1's own pairs, `b` is H2's.
    Every pair of {a,b,c} is mutually compatible (a<->b, b<->c, a<->c all
    feasible 2-cycles), but only 2 of the 3 pairs can ever be matched at
    once (any 2-cycle uses up 2 of the 3 nodes) -- so central cardinality is
    always 2, achieved by THREE tied selections: {(a,b)}, {(b,c)}, {(a,c)}.
    H1's utility differs across them: {(a,b)} or {(b,c)} leaves exactly one
    of H1's own pairs stranded centrally with no local partner (utility 1);
    {(a,c)} matches BOTH of H1's pairs to each other centrally (utility 2).
    This is exactly the "genuine tie where h's utility differs across
    optimal clearings" the task requires."""

    def setUp(self):
        self.market = KidneyMarket(
            pairs=("a", "b", "c"),
            hospital_of={"a": "H1", "b": "H2", "c": "H1"},
            hospitals=("H1", "H2"),
            edges=frozenset({
                ("a", "b"), ("b", "a"),
                ("b", "c"), ("c", "b"),
                ("a", "c"), ("c", "a"),
            }),
        )
        self.report_map = {"H1": ("a", "c"), "H2": ("b",)}

    def test_brute_force_confirms_the_tie_exists(self):
        bf_min, bf_max, c_star = _bf_utility_range(self.market, self.report_map, "H1", max_cycle_length=2)
        self.assertEqual(c_star, 2)
        self.assertEqual((bf_min, bf_max), (1, 2), msg="fixture no longer exhibits a genuine tie -- fix the fixture")

    def test_ilp_range_matches_the_brute_force_tie(self):
        result = utility_range_for_profile(self.market, self.report_map, "H1", max_cycle_length=2, max_seconds=10.0)
        self.assertEqual(result["status"], "ok", msg=result)
        self.assertEqual((result["u_min"], result["u_max"]), (1, 2))

    def test_fixed_seed_mechanism_utility_lies_in_the_range(self):
        profile = KidneyProfile(reports=self.report_map)
        config = KidneyConfig(tiebreak_policy=TIEBREAK_LEX_SMALLEST_BY_INDEX, max_cycle_length=2)
        result = clear_kidney_exchange(self.market, profile, config)
        u = result.utility["H1"]
        self.assertIn(u, (1, 2))
        # Lex-smallest-by-index picks (a,b) first among {(a,b),(a,c),(b,c)}
        # (index tuples (0,1) < (0,2) < (1,2)) -- pins the specific value too.
        self.assertEqual(u, 1)


class IlpRangeMatchesBruteForceRandomized(unittest.TestCase):
    """100+ random small markets (4-7 pairs, 1-3 hospitals, K in {2,3}):
    the ILP-based `utility_range_for_profile` must agree EXACTLY with the
    independent brute force on both u_min and u_max, and the fixed-seed
    mechanism's own utility must fall inside that range."""

    def test_ranges_match_on_120_random_instances(self):
        n_checked = 0
        for seed in range(200):
            n_pairs = 4 + (seed % 4)  # 4..7
            n_hospitals = 1 + (seed % 3)  # 1..3
            edge_prob = [0.2, 0.3, 0.45][seed % 3]
            max_cycle_length = 2 if seed % 2 == 0 else 3
            market = _random_market(seed, n_pairs, n_hospitals, edge_prob)

            rng = random.Random(seed * 7919 + 3)
            report_map = {}
            for h in market.hospitals:
                owned = market.pairs_of(h)
                report_map[h] = tuple(p for p in owned if rng.random() < 0.8)
            hospital = market.hospitals[seed % n_hospitals]
            if not report_map[hospital]:
                continue  # nothing to enumerate footprints over -- degenerate, skip

            bf_min, bf_max, bf_c_star = _bf_utility_range(market, report_map, hospital, max_cycle_length)
            result = utility_range_for_profile(market, report_map, hospital, max_cycle_length, max_seconds=15.0)

            with self.subTest(seed=seed):
                self.assertEqual(result["status"], "ok", msg=f"seed={seed}: {result}")
                self.assertEqual(result["c_star"], bf_c_star, msg=f"seed={seed}: central C* disagreement")
                self.assertEqual(
                    (result["u_min"], result["u_max"]), (bf_min, bf_max),
                    msg=f"seed={seed}: ILP range ({result['u_min']},{result['u_max']}) != "
                        f"brute force ({bf_min},{bf_max})",
                )

                profile = KidneyProfile(reports=report_map)
                config = KidneyConfig(tiebreak_policy=TIEBREAK_LEX_SMALLEST_BY_INDEX, max_cycle_length=max_cycle_length)
                fixed_seed_result = clear_kidney_exchange(market, profile, config)
                fixed_u = fixed_seed_result.utility[hospital]
                self.assertTrue(
                    bf_min <= fixed_u <= bf_max,
                    msg=f"seed={seed}: fixed-seed mechanism utility {fixed_u} outside range [{bf_min},{bf_max}]",
                )
            n_checked += 1
        self.assertGreaterEqual(n_checked, 100, msg="too many degenerate seeds were skipped -- widen the range checked")


if __name__ == "__main__":
    unittest.main()
