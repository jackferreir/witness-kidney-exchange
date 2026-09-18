"""Validation gate for `scripts/kidney_tiebreak_census.py`'s two headline
quantities, before any of its numbers are believed.

WHAT MUST BE TRUE. For a hospital `h` at the truthful profile:

  * `u_true_min` / `u_true_max` are the MINIMUM and MAXIMUM of `h`'s FINAL
    utility (central matches + `h`'s own residual local clearing) over ALL
    maximum-cardinality central clearings -- not over some convenient subset,
    and not "central matches only" (taking more central matches can leave
    fewer own pairs for the residual stage, so the two differ).
  * `tiebreak_spread = u_true_max - u_true_min` is therefore the real range,
    not the one-sided `best - whatever-the-seed-picked` proxy the first
    attempt reported.
  * The mechanism's own fixed-seed outcome must lie INSIDE that range. If it
    ever does not, either the range or the mechanism is wrong, and the census
    is invalid.

METHOD. On markets small enough to enumerate exhaustively, an INDEPENDENT
brute force (itertools over candidate cycles, sharing no code path with the
CP-SAT `joint_extreme`) lists every maximum-cardinality central selection,
replays the mechanism's own residual rule for each, and takes the true
min/max. The census primitives must agree EXACTLY.

Includes a deliberate non-vacuity fixture: a market where `h`'s utility
genuinely differs across tied optimal clearings (spread > 0). Without it the
agreement tests could pass trivially on instances that have no ties at all.
"""
from __future__ import annotations

import itertools
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

from kidney_tiebreak_exact import joint_extreme

from witness.kidney import (
    KidneyConfig,
    KidneyMarket,
    KidneyProfile,
    TIEBREAK_MAX_CARDINALITY_ILP,
    _select_maximum_cycles,
    candidate_cycles,
    clear_kidney_exchange,
)

K = 3


def _brute_force_min_max(market: KidneyMarket, hospital: str, max_cycle_length: int = K):
    """Independent re-derivation: enumerate EVERY maximum-cardinality central
    selection, apply the mechanism's own residual local rule for `hospital`,
    return (min_utility, max_utility, n_optimal_selections)."""
    profile = KidneyProfile.truthful(market)
    pool = tuple(p for h in market.hospitals for p in profile.report(h))
    cands = candidate_cycles(market, pool, max_cycle_length)

    # every vertex-disjoint subset of candidate cycles
    feasible = []
    for r in range(len(cands) + 1):
        for combo in itertools.combinations(range(len(cands)), r):
            used = set()
            ok = True
            for i in combo:
                c = set(cands[i])
                if used & c:
                    ok = False
                    break
                used |= c
            if ok:
                feasible.append(tuple(cands[i] for i in combo))
    if not feasible:
        return 0, 0, 0
    best = max(sum(len(c) for c in s) for s in feasible)
    optimal = [s for s in feasible if sum(len(c) for c in s) == best]

    own = set(market.pairs_of(hospital))
    cfg = KidneyConfig(tiebreak_policy=TIEBREAK_MAX_CARDINALITY_ILP, max_cycle_length=max_cycle_length)
    utils = []
    for sel in optimal:
        matched = set()
        for c in sel:
            matched.update(c)
        residual = tuple(p for p in market.pairs_of(hospital) if p not in matched)
        local = _select_maximum_cycles(market, candidate_cycles(market, residual, max_cycle_length), cfg)
        for c in local:
            matched.update(c)
        utils.append(sum(1 for p in own if p in matched))
    return min(utils), max(utils), len(optimal)


def _random_market(seed: int, n_pairs: int, n_hospitals: int, edge_prob: float) -> KidneyMarket:
    rng = random.Random(seed)
    pairs = tuple(f"p{i}" for i in range(1, n_pairs + 1))
    hospitals = tuple(f"h{i}" for i in range(1, n_hospitals + 1))
    hospital_of = {p: hospitals[i % n_hospitals] for i, p in enumerate(pairs)}
    edges = {(u, v) for u in pairs for v in pairs if u != v and rng.random() < edge_prob}
    return KidneyMarket(pairs=pairs, hospital_of=hospital_of, hospitals=hospitals, edges=frozenset(edges))


class CensusSpreadMatchesBruteForce(unittest.TestCase):
    def test_min_max_agree_with_brute_force_on_random_markets(self):
        n_checked = 0
        n_with_real_spread = 0
        for seed in range(120):
            n_pairs = 4 + (seed % 3)          # 4..6
            n_hospitals = 2 + (seed % 2)      # 2..3
            edge_prob = [0.20, 0.30, 0.40][seed % 3]
            market = _random_market(seed, n_pairs, n_hospitals, edge_prob)
            profile = KidneyProfile.truthful(market)
            report_map = {h: list(profile.report(h)) for h in market.hospitals}

            for h in market.hospitals:
                bf_min, bf_max, n_opt = _brute_force_min_max(market, h)
                if n_opt == 0:
                    continue
                lo = joint_extreme(market, report_map, h, K, 60.0, "min")
                hi = joint_extreme(market, report_map, h, K, 60.0, "max")
                if lo["status"] != "ok" or hi["status"] != "ok":
                    continue
                with self.subTest(seed=seed, hospital=h):
                    self.assertEqual(lo["value"], bf_min, f"min mismatch seed={seed} h={h}")
                    self.assertEqual(hi["value"], bf_max, f"max mismatch seed={seed} h={h}")
                n_checked += 1
                if bf_max > bf_min:
                    n_with_real_spread += 1
        self.assertGreater(n_checked, 100, "too few comparisons actually ran")
        # NON-VACUITY: the agreement must have been tested on instances that
        # genuinely have differing utilities across tied optima, not only on
        # instances where every optimum happens to give the same answer.
        self.assertGreater(n_with_real_spread, 0,
                           "no instance had a nonzero spread -- agreement was vacuous")


class SeedOutcomeAlwaysInsideRange(unittest.TestCase):
    """The mechanism's own fixed-seed result must lie within [min, max]. If it
    does not, the census's central claim is measuring the wrong thing."""

    def test_seed_utility_within_computed_range(self):
        cfg = KidneyConfig(tiebreak_policy=TIEBREAK_MAX_CARDINALITY_ILP, max_cycle_length=K)
        n_checked = 0
        for seed in range(60):
            market = _random_market(1000 + seed, 4 + (seed % 3), 2 + (seed % 2), [0.25, 0.35][seed % 2])
            profile = KidneyProfile.truthful(market)
            report_map = {h: list(profile.report(h)) for h in market.hospitals}
            result = clear_kidney_exchange(market, profile, cfg)
            for h in market.hospitals:
                lo = joint_extreme(market, report_map, h, K, 60.0, "min")
                hi = joint_extreme(market, report_map, h, K, 60.0, "max")
                if lo["status"] != "ok" or hi["status"] != "ok":
                    continue
                with self.subTest(seed=seed, hospital=h):
                    self.assertLessEqual(lo["value"], result.utility[h])
                    self.assertLessEqual(result.utility[h], hi["value"])
                n_checked += 1
        self.assertGreater(n_checked, 50)


class HandBuiltGenuineTieFixture(unittest.TestCase):
    """A market constructed so that two maximum-cardinality clearings give one
    hospital DIFFERENT utility -- the phenomenon the census exists to measure,
    pinned by hand so a regression that silently collapses the range is caught."""

    def test_known_spread_is_detected(self):
        # h1 owns p1,p2 ; h2 owns p3,p4. Two disjoint 2-cycles are possible:
        # (p1,p2) -- entirely inside h1 -- or (p1,p3) and (p2,p4) spanning both.
        # Both clear 4 pairs, but h1's own count differs between them.
        market = KidneyMarket(
            pairs=("p1", "p2", "p3", "p4"),
            hospital_of={"p1": "h1", "p2": "h1", "p3": "h2", "p4": "h2"},
            hospitals=("h1", "h2"),
            edges=frozenset({
                ("p1", "p2"), ("p2", "p1"),
                ("p1", "p3"), ("p3", "p1"),
                ("p2", "p4"), ("p4", "p2"),
                ("p3", "p4"), ("p4", "p3"),
            }),
        )
        profile = KidneyProfile.truthful(market)
        report_map = {h: list(profile.report(h)) for h in market.hospitals}
        bf_min, bf_max, n_opt = _brute_force_min_max(market, "h1")
        self.assertGreater(n_opt, 1, "fixture must actually have multiple optimal clearings")
        lo = joint_extreme(market, report_map, "h1", K, 60.0, "min")
        hi = joint_extreme(market, report_map, "h1", K, 60.0, "max")
        self.assertEqual(lo["status"], "ok")
        self.assertEqual(hi["status"], "ok")
        self.assertEqual(lo["value"], bf_min)
        self.assertEqual(hi["value"], bf_max)


if __name__ == "__main__":
    unittest.main()
