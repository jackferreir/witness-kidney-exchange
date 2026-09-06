"""Validation gate for `TIEBREAK_MAX_CARDINALITY_ILP` (see `witness.kidney`'s
module docstring, "THREE CLEARING IMPLEMENTATIONS"): before the OR-Tools
CP-SAT-based clearing is trusted at a scale the exhaustive oracle cannot
reach, it must reproduce the IDENTICAL cardinality as the independent,
from-scratch oracle (`witness.oracles_kidney`) on every 3-cycle hand
fixture AND hundreds of random small instances (2- and 3-cycles both
enabled) where both are tractable. Mirrors
`tests/test_kidney_blossom_matches_oracle.py`'s own discipline exactly.

Also pins the determinism property the module docstring claims: the SAME
market and candidate pool must produce the IDENTICAL selection across
repeated solves AND across a genuinely fresh subprocess (CP-SAT's search is
not guaranteed deterministic in general -- `num_search_workers=1` and a
fixed `random_seed` are what `_select_maximum_cycles_ilp` relies on, so this
is checked directly, not assumed).
"""

from __future__ import annotations

import random
import subprocess
import sys
import unittest

from witness.kidney import (
    KidneyConfig,
    KidneyMarket,
    KidneyProfile,
    TIEBREAK_LEX_SMALLEST_BY_INDEX,
    TIEBREAK_MAX_CARDINALITY_ILP,
    clear_kidney_exchange,
)
from witness.oracles_kidney import is_maximum_cardinality


def _random_market_k3(seed: int, n_pairs: int, n_hospitals: int, edge_prob: float) -> KidneyMarket:
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


class IlpCardinalityAgreesWithOracleOnHandFixtures(unittest.TestCase):
    """KID3-A and KID3-B's markets, cleared under the exhaustive policy AND
    the ILP policy -- cardinality must agree."""

    def test_kid3a_genuine_3_cycle(self):
        market = KidneyMarket(
            pairs=("u1", "u2", "u3"),
            hospital_of={"u1": "HA", "u2": "HB", "u3": "HC"},
            hospitals=("HA", "HB", "HC"),
            edges=frozenset({("u1", "u2"), ("u2", "u3"), ("u3", "u1")}),
        )
        profile = KidneyProfile.truthful(market)
        exhaustive = clear_kidney_exchange(market, profile, KidneyConfig(tiebreak_policy=TIEBREAK_LEX_SMALLEST_BY_INDEX, max_cycle_length=3))
        ilp = clear_kidney_exchange(market, profile, KidneyConfig(tiebreak_policy=TIEBREAK_MAX_CARDINALITY_ILP, max_cycle_length=3))
        self.assertEqual(len(exhaustive.matched_pairs), len(ilp.matched_pairs))
        self.assertEqual(len(exhaustive.matched_pairs), 3)  # non-vacuity: a real 3-cycle exists here

    def test_kid3b_competing_3_cycle_vs_2_cycle(self):
        market = KidneyMarket(
            pairs=("u1", "u2", "u3", "u4"),
            hospital_of={"u1": "HA", "u2": "HB", "u3": "HA", "u4": "HC"},
            hospitals=("HA", "HB", "HC"),
            edges=frozenset({
                ("u1", "u3"), ("u3", "u1"),
                ("u1", "u2"), ("u2", "u4"), ("u4", "u1"),
            }),
        )
        profile = KidneyProfile.truthful(market)
        exhaustive = clear_kidney_exchange(market, profile, KidneyConfig(tiebreak_policy=TIEBREAK_LEX_SMALLEST_BY_INDEX, max_cycle_length=3))
        ilp = clear_kidney_exchange(market, profile, KidneyConfig(tiebreak_policy=TIEBREAK_MAX_CARDINALITY_ILP, max_cycle_length=3))
        self.assertEqual(len(exhaustive.matched_pairs), len(ilp.matched_pairs))
        self.assertEqual(len(exhaustive.matched_pairs), 3)  # the 3-cycle wins, u3 stranded either way

    def test_ilp_selection_is_independently_confirmed_maximum(self):
        market = KidneyMarket(
            pairs=("u1", "u2", "u3", "u4"),
            hospital_of={"u1": "HA", "u2": "HB", "u3": "HA", "u4": "HC"},
            hospitals=("HA", "HB", "HC"),
            edges=frozenset({
                ("u1", "u3"), ("u3", "u1"),
                ("u1", "u2"), ("u2", "u4"), ("u4", "u1"),
            }),
        )
        profile = KidneyProfile.truthful(market)
        ilp = clear_kidney_exchange(market, profile, KidneyConfig(tiebreak_policy=TIEBREAK_MAX_CARDINALITY_ILP, max_cycle_length=3))
        pool = tuple(p for h in market.hospitals for p in profile.report(h))
        ok, reasons = is_maximum_cardinality(market, ilp.central_selection, pool, max_cycle_length=3)
        self.assertTrue(ok, msg=reasons)


class IlpCardinalityAgreesWithOracleRandomized(unittest.TestCase):
    """Hundreds of random small instances (small enough for BOTH the
    exhaustive oracle and the brute-force clearing to be tractable with
    3-cycles enabled) -- every one must agree on TOTAL cardinality,
    independently re-derived by `witness.oracles_kidney`."""

    def test_total_matched_pairs_agrees_across_150_random_instances(self):
        n_checked = 0
        for seed in range(150):
            n_pairs = 4 + (seed % 3)  # 4..6 pairs (3-cycle candidate space grows fast -- see
            # bench: 7 pairs at 0.35 density already reaches 26 candidates / 2**26 subsets)
            n_hospitals = 1 + (seed % 3)
            edge_prob = [0.15, 0.25, 0.35][seed % 3]
            market = _random_market_k3(seed, n_pairs, n_hospitals, edge_prob)
            profile = KidneyProfile.truthful(market)

            exhaustive = clear_kidney_exchange(market, profile, KidneyConfig(tiebreak_policy=TIEBREAK_LEX_SMALLEST_BY_INDEX, max_cycle_length=3))
            ilp = clear_kidney_exchange(market, profile, KidneyConfig(tiebreak_policy=TIEBREAK_MAX_CARDINALITY_ILP, max_cycle_length=3))

            with self.subTest(seed=seed):
                self.assertEqual(
                    len(exhaustive.matched_pairs), len(ilp.matched_pairs),
                    msg=f"seed={seed}: exhaustive matched {sorted(exhaustive.matched_pairs)}, "
                        f"ilp matched {sorted(ilp.matched_pairs)}",
                )
                reported_pool = tuple(p for h in market.hospitals for p in profile.report(h))
                ok, reasons = is_maximum_cardinality(market, ilp.central_selection, reported_pool, max_cycle_length=3)
                self.assertTrue(ok, msg=f"seed={seed}: {reasons}")
            n_checked += 1
        self.assertEqual(n_checked, 150)  # non-vacuity: every seed actually ran


class IlpDeterministicAcrossRepeatedSolvesAndFreshProcesses(unittest.TestCase):
    """The SAME market must produce the IDENTICAL selection every time --
    both within one process (repeated solves) and across a genuinely fresh
    subprocess (a new CP-SAT solver instance, new process memory)."""

    def setUp(self):
        # KID3-C's tie -- the instance most likely to expose nondeterminism,
        # since it has a genuine tie between two 5-pair selections.
        self.market = KidneyMarket(
            pairs=("u1", "u2", "u3", "u4", "u5"),
            hospital_of={"u1": "H1", "u2": "H2", "u3": "H3", "u4": "H4", "u5": "H5"},
            hospitals=("H1", "H2", "H3", "H4", "H5"),
            edges=frozenset({
                ("u1", "u2"), ("u2", "u1"),
                ("u3", "u4"), ("u4", "u5"), ("u5", "u3"),
                ("u2", "u3"), ("u3", "u1"),
                ("u5", "u4"),
            }),
        )
        self.config = KidneyConfig(tiebreak_policy=TIEBREAK_MAX_CARDINALITY_ILP, max_cycle_length=3)

    def test_repeated_in_process_solves_agree(self):
        results = [
            clear_kidney_exchange(self.market, KidneyProfile.truthful(self.market), self.config).central_selection
            for _ in range(5)
        ]
        self.assertEqual(len(set(results)), 1, msg=f"selections varied across in-process repeats: {results}")

    def test_fresh_subprocess_reproduces_the_identical_selection(self):
        script = (
            "from witness.kidney import KidneyConfig, KidneyMarket, KidneyProfile, "
            "TIEBREAK_MAX_CARDINALITY_ILP, clear_kidney_exchange\n"
            "market = KidneyMarket(\n"
            "    pairs=('u1','u2','u3','u4','u5'),\n"
            "    hospital_of={'u1':'H1','u2':'H2','u3':'H3','u4':'H4','u5':'H5'},\n"
            "    hospitals=('H1','H2','H3','H4','H5'),\n"
            "    edges=frozenset({('u1','u2'),('u2','u1'),('u3','u4'),('u4','u5'),('u5','u3'),"
            "('u2','u3'),('u3','u1'),('u5','u4')}),\n"
            ")\n"
            "config = KidneyConfig(tiebreak_policy=TIEBREAK_MAX_CARDINALITY_ILP, max_cycle_length=3)\n"
            "res = clear_kidney_exchange(market, KidneyProfile.truthful(market), config)\n"
            "print(res.central_selection)\n"
        )
        in_process = clear_kidney_exchange(self.market, KidneyProfile.truthful(self.market), self.config).central_selection

        outputs = set()
        for _ in range(3):
            proc = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=30)
            self.assertEqual(proc.returncode, 0, msg=proc.stderr)
            outputs.add(proc.stdout.strip())
        self.assertEqual(len(outputs), 1, msg=f"selection varied across fresh subprocesses: {outputs}")
        self.assertEqual(outputs.pop(), str(in_process))


if __name__ == "__main__":
    unittest.main()
