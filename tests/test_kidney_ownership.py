"""Tests for `witness.kidney_ownership` -- the declared, seeded, tunable-
size-distribution hospital-ownership partitions built for the "large
centers withhold more" investigation (see that module's own docstring for
the full motivation).

WHAT THIS FILE MUST ESTABLISH, per the task brief:
  1. Every regime, over MANY seeds and sizes, produces a GENUINE partition
     -- every pair owned exactly once, none duplicated, none dropped --
     checked directly against the output (`assert_genuine_partition`),
     never merely trusted from the construction.
  2. `REGIME_UNIFORM` reproduces `witness.kidney_real_data.
     load_real_kidney_market`'s own existing ownership partition EXACTLY,
     given equivalent parameters (same real pairs, seed, draw_index,
     n_hospitals) -- this is the required baseline-equivalence check.
  3. The power-law and core-periphery regimes actually produce SKEWED
     sizes (large-then-small, and "few large + long 1-2 pair tail"
     respectively) -- not just "a partition," but the declared SHAPE.
  4. Mutation coverage for `assert_genuine_partition` itself: a
     deliberately broken partition (a duplicated pair, a dropped pair,
     an unowned pair) must be REJECTED, or the genuine-partition check
     could be passing vacuously (REVIEWER.md: "a property that no test
     bites on is not verified").
  5. Reproducibility (same seed/draw_index -> byte-identical partition)
     and genuine seed-sensitivity (a different draw_index actually moves
     pairs around) for the two regimes that shuffle.
"""

from __future__ import annotations

import unittest

from witness.errors import ModelError
from witness.kidney_ownership import (
    REGIME_CORE_PERIPHERY,
    REGIME_POWER_LAW,
    REGIME_UNIFORM,
    OwnershipMeta,
    assert_genuine_partition,
    build_ownership,
)
from witness.kidney_real_data import load_real_kidney_market, real_instances_for_p


def _synthetic_pairs(n: int) -> tuple:
    return tuple(f"pair{i}" for i in range(n))


class GenuinePartitionAcrossRegimesTest(unittest.TestCase):
    """Property 1: every regime, many seeds and sizes, genuine partition."""

    def test_uniform_genuine_partition_many_seeds_and_sizes(self):
        n_checks = 0
        for p in (1, 2, 3, 5, 8, 13, 21, 50, 97):
            pairs = _synthetic_pairs(p)
            for n_hospitals in sorted({1, min(p, 2), min(p, 3), p}):
                for seed in ("seedA", "seedB", "another-seed-string"):
                    for draw in (0, 1, 7):
                        hospital_of, hospitals, meta = build_ownership(
                            pairs, seed, draw, REGIME_UNIFORM, n_hospitals=n_hospitals
                        )
                        assert_genuine_partition(pairs, hospital_of, hospitals)
                        self.assertEqual(len(hospitals), n_hospitals)
                        n_checks += 1
        self.assertGreater(n_checks, 100)

    def test_power_law_genuine_partition_many_seeds_and_sizes(self):
        n_checks = 0
        for p in (2, 3, 5, 8, 13, 21, 50, 97):
            pairs = _synthetic_pairs(p)
            for n_hospitals in (1, 2, min(p, 3), min(p, 10)):
                for exponent in (0.5, 1.0, 1.8):
                    for seed in ("seedA", "seedB"):
                        for draw in (0, 1, 5):
                            hospital_of, hospitals, meta = build_ownership(
                                pairs, seed, draw, REGIME_POWER_LAW,
                                n_hospitals=n_hospitals, exponent=exponent,
                            )
                            assert_genuine_partition(pairs, hospital_of, hospitals)
                            self.assertEqual(sum(meta.hospital_sizes), p)
                            n_checks += 1
        self.assertGreater(n_checks, 200)

    def test_core_periphery_genuine_partition_many_seeds_and_sizes(self):
        n_checks = 0
        for p, n_large, large_size in (
            (5, 1, 2), (10, 1, 3), (20, 2, 5), (50, 3, 8), (97, 4, 10), (13, 1, 1),
        ):
            pairs = _synthetic_pairs(p)
            for periphery_chunk in (1, 2):
                for seed in ("seedA", "seedB"):
                    for draw in (0, 3):
                        hospital_of, hospitals, meta = build_ownership(
                            pairs, seed, draw, REGIME_CORE_PERIPHERY,
                            n_large=n_large, large_size=large_size, periphery_chunk=periphery_chunk,
                        )
                        assert_genuine_partition(pairs, hospital_of, hospitals)
                        self.assertEqual(sum(meta.hospital_sizes), p)
                        n_checks += 1
        self.assertGreater(n_checks, 40)

    def test_genuine_partition_on_real_pair_lists(self):
        """Same property, but over REAL Pansart2022 pair lists (via
        `witness.kidney_real_data`), not just synthetic index-named pairs --
        the actual pair objects `scripts/kidney_skew_sweep.py` will use."""
        members = real_instances_for_p(50)[:3]
        n_checks = 0
        for member in members:
            base_market, _, _ = load_real_kidney_market(
                member, n_hospitals=1, ownership_seed="ownership-test", ownership_draw_index=0,
            )
            pairs = base_market.pairs
            for regime, params in (
                (REGIME_UNIFORM, {"n_hospitals": 8}),
                (REGIME_POWER_LAW, {"n_hospitals": 8, "exponent": 1.2}),
                (REGIME_CORE_PERIPHERY, {"n_large": 2, "large_size": 10, "periphery_chunk": 2}),
            ):
                for draw in (0, 1, 2):
                    hospital_of, hospitals, meta = build_ownership(pairs, "real-ownership-seed", draw, regime, **params)
                    assert_genuine_partition(pairs, hospital_of, hospitals)
                    n_checks += 1
        self.assertGreater(n_checks, 20)


class UniformMatchesKidneyRealDataTest(unittest.TestCase):
    """Property 2: REGIME_UNIFORM reproduces witness.kidney_real_data's own
    existing ownership partition exactly, given equivalent parameters."""

    def test_matches_existing_loader_byte_identical(self):
        combos = [
            (50, 8, "kidney-real-sweep-v2", 0),
            (50, 8, "kidney-real-sweep-v2", 5),
            (100, 17, "another-seed", 3),
            (250, 42, "yet-another-seed", 1),
        ]
        n_checks = 0
        for p, n_hospitals, seed, draw in combos:
            member = real_instances_for_p(p)[0]
            existing_market, _, _ = load_real_kidney_market(
                member, n_hospitals=n_hospitals, ownership_seed=seed, ownership_draw_index=draw,
            )
            base_market, _, _ = load_real_kidney_market(
                member, n_hospitals=1, ownership_seed=seed, ownership_draw_index=draw,
            )
            hospital_of, hospitals, meta = build_ownership(
                base_market.pairs, seed, draw, REGIME_UNIFORM, n_hospitals=n_hospitals
            )
            self.assertEqual(hospital_of, existing_market.hospital_of)
            self.assertEqual(hospitals, existing_market.hospitals)
            n_checks += 1
        self.assertEqual(n_checks, len(combos))


class SkewShapeTest(unittest.TestCase):
    """Property 3: the skewed regimes actually produce the declared SHAPE,
    not merely *a* valid partition."""

    def test_power_law_sizes_are_nonincreasing_and_spread_out(self):
        p = 200
        pairs = _synthetic_pairs(p)
        hospital_of, hospitals, meta = build_ownership(
            pairs, "shape-seed", 0, REGIME_POWER_LAW, n_hospitals=10, exponent=1.5,
        )
        sizes = list(meta.hospital_sizes)
        self.assertEqual(sizes, sorted(sizes, reverse=True), "power-law sizes must be rank-sorted, largest first")
        self.assertGreater(sizes[0], sizes[-1])
        self.assertGreaterEqual(sizes[0], 3 * sizes[-1])
        # compare against the uniform baseline for the same (p, n_hospitals):
        # the power-law largest hospital must own strictly more than any
        # uniform hospital would.
        _, _, uniform_meta = build_ownership(pairs, "shape-seed", 0, REGIME_UNIFORM, n_hospitals=10)
        self.assertGreater(sizes[0], max(uniform_meta.hospital_sizes))

    def test_core_periphery_shape_is_few_large_plus_1_2_tail(self):
        p = 100
        pairs = _synthetic_pairs(p)
        hospital_of, hospitals, meta = build_ownership(
            pairs, "shape-seed", 0, REGIME_CORE_PERIPHERY, n_large=3, large_size=20, periphery_chunk=2,
        )
        sizes = list(meta.hospital_sizes)
        large = sizes[:3]
        periphery = sizes[3:]
        self.assertEqual(large, [20, 20, 20])
        self.assertTrue(all(s in (1, 2) for s in periphery), f"periphery sizes must be 1 or 2, got {periphery}")
        self.assertGreater(len(periphery), 3, "the tail must actually be long, not a handful of hospitals")
        # cross-check directly against market ownership counts too
        for h, expected_size in zip(hospitals, sizes):
            actual = sum(1 for pr in pairs if hospital_of[pr] == h)
            self.assertEqual(actual, expected_size)


class ReproducibilityTest(unittest.TestCase):
    """Property 5: same seed/draw -> identical partition; a different draw
    actually reshuffles pairs (for the regimes that shuffle at all)."""

    def test_same_seed_and_draw_is_byte_identical(self):
        pairs = _synthetic_pairs(60)
        for regime, params in (
            (REGIME_UNIFORM, {"n_hospitals": 6}),
            (REGIME_POWER_LAW, {"n_hospitals": 6, "exponent": 1.0}),
            (REGIME_CORE_PERIPHERY, {"n_large": 2, "large_size": 10, "periphery_chunk": 2}),
        ):
            a = build_ownership(pairs, "repro-seed", 4, regime, **params)
            b = build_ownership(pairs, "repro-seed", 4, regime, **params)
            self.assertEqual(a[0], b[0])
            self.assertEqual(a[1], b[1])

    def test_different_draw_index_reshuffles_pairs(self):
        pairs = _synthetic_pairs(60)
        for regime, params in (
            (REGIME_UNIFORM, {"n_hospitals": 6}),
            (REGIME_POWER_LAW, {"n_hospitals": 6, "exponent": 1.0}),
            (REGIME_CORE_PERIPHERY, {"n_large": 2, "large_size": 10, "periphery_chunk": 2}),
        ):
            a, _, _ = build_ownership(pairs, "repro-seed", 0, regime, **params)
            b, _, _ = build_ownership(pairs, "repro-seed", 1, regime, **params)
            self.assertNotEqual(a, b, f"{regime}: draw_index 0 vs 1 produced the identical partition")

    def test_different_seed_reshuffles_pairs(self):
        pairs = _synthetic_pairs(60)
        a, _, _ = build_ownership(pairs, "seed-one", 0, REGIME_UNIFORM, n_hospitals=6)
        b, _, _ = build_ownership(pairs, "seed-two", 0, REGIME_UNIFORM, n_hospitals=6)
        self.assertNotEqual(a, b)


class MutationCoverageTest(unittest.TestCase):
    """Property 4: `assert_genuine_partition` must actually reject a broken
    partition, on every distinct way a partition can break."""

    def test_rejects_duplicated_pair_in_input_pairs(self):
        # a duplicate in `pairs` itself (the "same pair listed/owned twice"
        # shape a dict-keyed hospital_of cannot represent on its own)
        pairs = ("pair0", "pair1", "pair1", "pair2")
        hospitals = ("h1", "h2")
        hospital_of = {"pair0": "h1", "pair1": "h1", "pair2": "h2"}
        with self.assertRaises(ModelError):
            assert_genuine_partition(pairs, hospital_of, hospitals)

    def test_rejects_dropped_pair(self):
        pairs = _synthetic_pairs(4)
        hospitals = ("h1", "h2")
        hospital_of = {"pair0": "h1", "pair1": "h1", "pair2": "h2"}  # pair3 missing entirely
        with self.assertRaises(ModelError):
            assert_genuine_partition(pairs, hospital_of, hospitals)

    def test_rejects_unowned_pair_key_not_in_pairs(self):
        pairs = _synthetic_pairs(3)
        hospitals = ("h1",)
        hospital_of = {"pair0": "h1", "pair1": "h1", "pair2": "h1", "ghost_pair": "h1"}
        with self.assertRaises(ModelError):
            assert_genuine_partition(pairs, hospital_of, hospitals)

    def test_rejects_owner_not_in_hospitals(self):
        pairs = _synthetic_pairs(3)
        hospitals = ("h1",)
        hospital_of = {"pair0": "h1", "pair1": "h1", "pair2": "hUNDECLARED"}
        with self.assertRaises(ModelError):
            assert_genuine_partition(pairs, hospital_of, hospitals)

    def test_accepts_genuinely_correct_partition(self):
        pairs = _synthetic_pairs(5)
        hospitals = ("h1", "h2")
        hospital_of = {"pair0": "h1", "pair1": "h1", "pair2": "h2", "pair3": "h2", "pair4": "h1"}
        assert_genuine_partition(pairs, hospital_of, hospitals)  # must not raise


class ErrorHandlingTest(unittest.TestCase):
    def test_unknown_regime_raises(self):
        with self.assertRaises(ModelError):
            build_ownership(_synthetic_pairs(5), "s", 0, "not_a_real_regime", n_hospitals=2)

    def test_n_hospitals_exceeding_p_raises(self):
        with self.assertRaises(ModelError):
            build_ownership(_synthetic_pairs(3), "s", 0, REGIME_UNIFORM, n_hospitals=4)
        with self.assertRaises(ModelError):
            build_ownership(_synthetic_pairs(3), "s", 0, REGIME_POWER_LAW, n_hospitals=4, exponent=1.0)

    def test_core_periphery_core_exceeding_p_raises(self):
        with self.assertRaises(ModelError):
            build_ownership(_synthetic_pairs(10), "s", 0, REGIME_CORE_PERIPHERY, n_large=3, large_size=5)

    def test_missing_required_param_raises(self):
        with self.assertRaises(ModelError):
            build_ownership(_synthetic_pairs(5), "s", 0, REGIME_UNIFORM)
        with self.assertRaises(ModelError):
            build_ownership(_synthetic_pairs(5), "s", 0, REGIME_CORE_PERIPHERY, n_large=1)

    def test_unexpected_param_raises(self):
        with self.assertRaises(ModelError):
            build_ownership(_synthetic_pairs(5), "s", 0, REGIME_UNIFORM, n_hospitals=2, bogus_param=1)

    def test_empty_pairs_raises(self):
        with self.assertRaises(ModelError):
            build_ownership((), "s", 0, REGIME_UNIFORM, n_hospitals=1)


if __name__ == "__main__":
    unittest.main()
