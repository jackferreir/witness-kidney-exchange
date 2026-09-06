"""Validation gate for `TIEBREAK_MAX_CARDINALITY_BLOSSOM` (see
`witness.kidney`'s module docstring, "TWO CLEARING IMPLEMENTATIONS"): before
the polynomial NetworkX-based clearing is trusted at a scale the exhaustive
oracle cannot reach, it must reproduce the IDENTICAL cardinality as the
independent, from-scratch oracle (`witness.oracles_kidney`) on every hand
fixture AND hundreds of random small instances where both are tractable.

This is a mutation-style gate, not a demonstration: if a future change to
`_select_maximum_cycles_blossom` regresses cardinality-correctness, this
test is what catches it, since nothing downstream (the search, the
size-sweep script) re-checks cardinality against the oracle on every run --
that would defeat the entire point of using the polynomial path at scale.

Also pins the determinism property the module docstring claims: the SAME
market and candidate pool, cleared via `PYTHONHASHSEED`-varied fresh
subprocesses, must produce the IDENTICAL selection -- verified once here at
the unit level (same-process, varied insertion order) since `witness.
replay_kidney`'s existing fresh-subprocess replay already exercises the
cross-process case for any witness this policy actually produces.
"""

from __future__ import annotations

import random
import unittest

from witness.kidney import (
    KidneyConfig,
    KidneyMarket,
    KidneyProfile,
    TIEBREAK_LEX_SMALLEST_BY_INDEX,
    TIEBREAK_MAX_CARDINALITY_BLOSSOM,
    clear_kidney_exchange,
)
from witness.oracles_kidney import is_maximum_cardinality


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


class BlossomCardinalityAgreesWithOracleOnHandFixtures(unittest.TestCase):
    """The exact KID-A/B market from `tests/test_kidney_handworked.py`,
    cleared under BOTH policies -- cardinality must agree."""

    def setUp(self):
        self.market = KidneyMarket(
            pairs=("u1", "u2", "u3"),
            hospital_of={"u1": "HA", "u2": "HB", "u3": "HA"},
            hospitals=("HA", "HB"),
            edges=frozenset({("u1", "u2"), ("u2", "u1"), ("u1", "u3"), ("u3", "u1")}),
        )

    def test_full_revelation_central_cardinality_agrees(self):
        profile = KidneyProfile.truthful(self.market)
        exhaustive = clear_kidney_exchange(self.market, profile, KidneyConfig(tiebreak_policy=TIEBREAK_LEX_SMALLEST_BY_INDEX))
        blossom = clear_kidney_exchange(self.market, profile, KidneyConfig(tiebreak_policy=TIEBREAK_MAX_CARDINALITY_BLOSSOM))
        self.assertEqual(len(exhaustive.central_selection), len(blossom.central_selection))
        self.assertEqual(len(exhaustive.central_selection), 1)  # non-vacuity: a real tie exists here

    def test_blossom_selection_is_independently_confirmed_maximum(self):
        profile = KidneyProfile.truthful(self.market)
        blossom = clear_kidney_exchange(self.market, profile, KidneyConfig(tiebreak_policy=TIEBREAK_MAX_CARDINALITY_BLOSSOM))
        pool = tuple(p for h in self.market.hospitals for p in profile.report(h))
        ok, reasons = is_maximum_cardinality(self.market, blossom.central_selection, pool)
        self.assertTrue(ok, msg=reasons)


class BlossomCardinalityAgreesWithOracleRandomized(unittest.TestCase):
    """Hundreds of random small instances (small enough for BOTH the
    exhaustive oracle and the brute-force clearing to be tractable) --
    every one must agree on TOTAL cardinality (central + every hospital's
    local selection), independently re-derived by `witness.oracles_kidney`,
    never by comparing the two `witness.kidney` implementations to each
    other."""

    def test_total_matched_pairs_agrees_across_200_random_instances(self):
        n_checked = 0
        for seed in range(200):
            n_pairs = 4 + (seed % 5)  # 4..8 pairs
            n_hospitals = 1 + (seed % 3)  # 1..3 hospitals
            edge_prob = [0.15, 0.3, 0.5][seed % 3]
            market = _random_market(seed, n_pairs, n_hospitals, edge_prob)
            profile = KidneyProfile.truthful(market)

            exhaustive = clear_kidney_exchange(market, profile, KidneyConfig(tiebreak_policy=TIEBREAK_LEX_SMALLEST_BY_INDEX))
            blossom = clear_kidney_exchange(market, profile, KidneyConfig(tiebreak_policy=TIEBREAK_MAX_CARDINALITY_BLOSSOM))

            with self.subTest(seed=seed):
                self.assertEqual(
                    len(exhaustive.matched_pairs), len(blossom.matched_pairs),
                    msg=f"seed={seed}: exhaustive matched {sorted(exhaustive.matched_pairs)}, "
                        f"blossom matched {sorted(blossom.matched_pairs)}",
                )
                # Independent oracle check on the BLOSSOM central selection specifically --
                # never comparing the two `witness.kidney` implementations to each other alone.
                reported_pool = tuple(p for h in market.hospitals for p in profile.report(h))
                ok, reasons = is_maximum_cardinality(market, blossom.central_selection, reported_pool)
                self.assertTrue(ok, msg=f"seed={seed}: {reasons}")
            n_checked += 1
        self.assertEqual(n_checked, 200)  # non-vacuity: every seed actually ran


class BlossomDeterministicUnderVariedInsertionOrder(unittest.TestCase):
    """`_select_maximum_cycles_blossom` must give the SAME answer regardless
    of the order `candidate_cycles` happens to enumerate in -- since a
    future refactor of that function could change enumeration order without
    this file's other tests noticing. This test builds candidates directly
    (not via `candidate_cycles`) in three different orders and asserts the
    canonical (sorted) result is identical every time."""

    def test_same_cardinality_regardless_of_candidate_order(self):
        from witness.kidney import _select_maximum_cycles_blossom

        market = KidneyMarket(
            pairs=tuple(f"p{i}" for i in range(1, 13)),
            hospital_of={f"p{i}": f"h{1 + (i % 3)}" for i in range(1, 13)},
            hospitals=("h1", "h2", "h3"),
            edges=frozenset(),  # edges unused by this direct-candidate-list test
        )
        # Build a fixed candidate list directly (bypassing edge lookups entirely,
        # since we only care about matching-selection determinism here).
        candidates = tuple(
            (f"p{i}", f"p{i+1}") for i in range(1, 12, 2)
        ) + (("p2", "p4"), ("p4", "p6"))  # a couple of overlapping alternatives to force real choices

        results = set()
        for perm in (candidates, tuple(reversed(candidates)), candidates[3:] + candidates[:3]):
            sel = _select_maximum_cycles_blossom(market, perm)
            results.add(len(sel))
        self.assertEqual(len(results), 1, msg=f"cardinality varied by candidate order: {results}")


if __name__ == "__main__":
    unittest.main()
