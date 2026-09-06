"""Tests for the Step-3B wide generator, `witness.generate`.

Covers: byte-identical determinism (in-process AND fresh-subprocess), the
"never uses the stdlib `random` module" house rule (a crude source-text
guard), that every axis (`subscription`, `capacity_mode`, `list_length_mode`,
`school_lists_fraction`, `n_priority_classes`, `tiebreak_family`) actually
does what its name says, that every generated instance is internally valid,
that `generate_config` agrees with the mechanism it's asked for, and that
every invalid setting (including a contradictory subscription combination)
raises `ModelError`.
"""

from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path

from witness.boston import BostonConfig, boston_immediate_acceptance
from witness.core import (
    UNLISTED_LOWEST_CLASS,
    UNLISTED_UNACCEPTABLE,
    canonical_json,
    resolve_priorities,
)
from witness.da import DAConfig
from witness.errors import ModelError
from witness.generate import (
    CAPACITY_HETEROGENEOUS,
    CAPACITY_UNIFORM,
    LIST_COMPLETE,
    LIST_FIXED,
    LIST_SHORT,
    LIST_UNIFORM,
    MECHANISM_BOSTON_IMMEDIATE_ACCEPTANCE,
    MECHANISM_STUDENT_PROPOSING_DA,
    SUBSCRIPTION_EXACT,
    SUBSCRIPTION_OVER,
    SUBSCRIPTION_UNDER,
    TIEBREAK_MTB,
    TIEBREAK_STB,
    GeneratorConfig,
    generate_config,
    generate_instance,
    priority_tiebreak,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
GENERATE_PY = PROJECT_ROOT / "witness" / "generate.py"


class DeterminismTestCase(unittest.TestCase):
    def test_same_gc_and_index_gives_identical_market_and_profile(self):
        gc = GeneratorConfig(n_students=6, n_schools=4, seed="det", subscription="over", subscription_ratio=0.6)
        m1, p1 = generate_instance(gc, 3)
        m2, p2 = generate_instance(gc, 3)
        self.assertEqual(m1, m2)
        self.assertEqual(p1, p2)

    def test_different_index_gives_different_instance(self):
        gc = GeneratorConfig(n_students=5, n_schools=4, seed="det2")
        m0, p0 = generate_instance(gc, 0)
        m1, p1 = generate_instance(gc, 1)
        # At least the reports should differ (overwhelmingly likely, and
        # deterministic given the fixed seed above -- not a flaky check).
        self.assertNotEqual(p0.to_dict(), p1.to_dict())
        self.assertEqual(m0.students, m1.students)

    def test_determinism_in_a_fresh_subprocess(self):
        code = (
            "import sys; sys.path.insert(0, %r)\n"
            "from witness.generate import GeneratorConfig, generate_instance\n"
            "from witness.core import canonical_json\n"
            "gc = GeneratorConfig(n_students=6, n_schools=4, seed='subproc-det', "
            "subscription='under', subscription_ratio=1.5, list_length_mode='uniform', "
            "school_lists_fraction=0.6, n_priority_classes=2, capacity_mode='heterogeneous', "
            "tiebreak_family='mtb')\n"
            "m, p = generate_instance(gc, 7)\n"
            "print(canonical_json(m.to_dict()))\n"
            "print(canonical_json(p.to_dict()))\n"
        ) % str(PROJECT_ROOT)

        def run_once() -> str:
            result = subprocess.run(
                [sys.executable, "-c", code],
                cwd=str(PROJECT_ROOT),
                capture_output=True,
                text=True,
                timeout=60,
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            return result.stdout

        out1 = run_once()
        out2 = run_once()
        self.assertEqual(out1, out2)
        self.assertTrue(out1.strip(), "subprocess produced no output")

        # And the subprocess result must agree with the in-process result.
        gc = GeneratorConfig(
            n_students=6, n_schools=4, seed="subproc-det", subscription="under",
            subscription_ratio=1.5, list_length_mode="uniform", school_lists_fraction=0.6,
            n_priority_classes=2, capacity_mode="heterogeneous", tiebreak_family="mtb",
        )
        m, p = generate_instance(gc, 7)
        expected = canonical_json(m.to_dict()) + "\n" + canonical_json(p.to_dict()) + "\n"
        self.assertEqual(out1, expected)


class NoStdlibRandomTestCase(unittest.TestCase):
    def test_generate_py_never_uses_the_stdlib_random_module(self):
        text = GENERATE_PY.read_text(encoding="utf-8")
        self.assertNotIn("import random", text)
        self.assertNotIn("random.", text)


class SubscriptionTestCase(unittest.TestCase):
    def _total_seats(self, gc: GeneratorConfig, index: int) -> int:
        market, _ = generate_instance(gc, index)
        return market.total_seats()

    def test_over_gives_fewer_seats_than_students_across_sizes(self):
        for n_students, n_schools in [(3, 2), (4, 3), (7, 3), (10, 5)]:
            gc = GeneratorConfig(
                n_students=n_students, n_schools=n_schools, seed=f"over-{n_students}-{n_schools}",
                subscription=SUBSCRIPTION_OVER, subscription_ratio=0.5,
            )
            for i in range(3):
                seats = self._total_seats(gc, i)
                self.assertLess(seats, n_students, msg=(gc, i, seats))

    def test_exact_gives_seats_equal_to_students_across_sizes(self):
        for n_students, n_schools in [(3, 2), (4, 3), (7, 3), (10, 5)]:
            gc = GeneratorConfig(
                n_students=n_students, n_schools=n_schools, seed=f"exact-{n_students}-{n_schools}",
                subscription=SUBSCRIPTION_EXACT, subscription_ratio=1.0,
            )
            for i in range(3):
                seats = self._total_seats(gc, i)
                self.assertEqual(seats, n_students, msg=(gc, i, seats))

    def test_under_gives_more_seats_than_students_across_sizes(self):
        for n_students, n_schools in [(3, 2), (4, 3), (7, 3), (10, 5)]:
            gc = GeneratorConfig(
                n_students=n_students, n_schools=n_schools, seed=f"under-{n_students}-{n_schools}",
                subscription=SUBSCRIPTION_UNDER, subscription_ratio=1.5,
            )
            for i in range(3):
                seats = self._total_seats(gc, i)
                self.assertGreater(seats, n_students, msg=(gc, i, seats))


class CapacityModeTestCase(unittest.TestCase):
    def test_heterogeneous_actually_produces_at_least_two_different_capacities(self):
        gc = GeneratorConfig(
            n_students=10, n_schools=5, seed="hetero", subscription=SUBSCRIPTION_UNDER,
            subscription_ratio=2.0, capacity_mode=CAPACITY_HETEROGENEOUS,
        )
        found_variation = False
        for i in range(10):
            market, _ = generate_instance(gc, i)
            values = {market.capacity(c) for c in market.schools}
            if len(values) >= 2:
                found_variation = True
                break
        self.assertTrue(found_variation, "no heterogeneous-capacity instance found in the sweep")

    def test_uniform_mode_still_hits_the_requested_total(self):
        gc = GeneratorConfig(
            n_students=9, n_schools=3, seed="uniform-cap", subscription=SUBSCRIPTION_EXACT,
            capacity_mode=CAPACITY_UNIFORM,
        )
        market, _ = generate_instance(gc, 0)
        self.assertEqual(market.total_seats(), 9)


class ListLengthModeTestCase(unittest.TestCase):
    def test_complete_gives_full_length_for_every_student(self):
        gc = GeneratorConfig(n_students=5, n_schools=4, seed="complete", list_length_mode=LIST_COMPLETE)
        for i in range(3):
            market, profile = generate_instance(gc, i)
            for s in market.students:
                self.assertEqual(len(profile.report(s)), 4)

    def test_fixed_gives_exactly_list_length(self):
        gc = GeneratorConfig(
            n_students=5, n_schools=4, seed="fixed", list_length_mode=LIST_FIXED, list_length=2
        )
        for i in range(3):
            market, profile = generate_instance(gc, i)
            for s in market.students:
                self.assertEqual(len(profile.report(s)), 2)

    def test_short_gives_some_report_of_length_at_most_one_in_a_sweep(self):
        gc = GeneratorConfig(n_students=6, n_schools=4, seed="short", list_length_mode=LIST_SHORT)
        found = False
        for i in range(5):
            _, profile = generate_instance(gc, i)
            if any(len(r) <= 1 for r in profile.rankings.values()):
                found = True
                break
        self.assertTrue(found, "no very-short report found in the sweep")

    def test_uniform_produces_at_least_two_different_lengths_in_a_sweep(self):
        gc = GeneratorConfig(n_students=8, n_schools=5, seed="uniform-list", list_length_mode=LIST_UNIFORM)
        lengths = set()
        for i in range(5):
            _, profile = generate_instance(gc, i)
            lengths.update(len(r) for r in profile.rankings.values())
            if len(lengths) >= 2:
                break
        self.assertGreaterEqual(len(lengths), 2, f"lengths seen: {lengths!r}")


class SchoolListsFractionTestCase(unittest.TestCase):
    def test_fraction_below_one_leaves_some_student_off_some_school(self):
        gc = GeneratorConfig(n_students=8, n_schools=3, seed="frac-0.5", school_lists_fraction=0.5)
        market, _ = generate_instance(gc, 0)
        found = False
        for c in market.schools:
            listed = {s for cls in market.priority_classes[c] for s in cls}
            if any(s not in listed for s in market.students):
                found = True
                break
        self.assertTrue(found, "school_lists_fraction=0.5 left nobody off any school")

    def test_fraction_one_leaves_nobody_off(self):
        gc = GeneratorConfig(n_students=8, n_schools=3, seed="frac-1.0", school_lists_fraction=1.0)
        for i in range(3):
            market, _ = generate_instance(gc, i)
            for c in market.schools:
                listed = {s for cls in market.priority_classes[c] for s in cls}
                self.assertEqual(listed, set(market.students), msg=(c, i))


class PriorityClassesTestCase(unittest.TestCase):
    def test_more_than_one_priority_class_really_appears(self):
        gc = GeneratorConfig(
            n_students=9, n_schools=3, seed="classes", school_lists_fraction=1.0, n_priority_classes=3
        )
        market, _ = generate_instance(gc, 0)
        found = False
        for c in market.schools:
            if len(market.priority_classes[c]) >= 2:
                found = True
                break
        self.assertTrue(found, "no school with >= 2 priority classes")


class TiebreakFamilyTestCase(unittest.TestCase):
    def _market_with_shared_full_class(self, tiebreak_family: str, index: int):
        # school_lists_fraction=1.0 and n_priority_classes=1 => every school's
        # single class contains the identical SET of students -- the cleanest
        # possible setup to compare STB vs MTB resolved orders across schools.
        gc = GeneratorConfig(
            n_students=6, n_schools=3, seed="tb-family", school_lists_fraction=1.0,
            n_priority_classes=1, tiebreak_family=tiebreak_family,
        )
        market, _ = generate_instance(gc, index)
        config = generate_config(gc, index, MECHANISM_STUDENT_PROPOSING_DA)
        return market, config

    def test_stb_gives_the_same_resolved_order_at_every_school(self):
        market, config = self._market_with_shared_full_class(TIEBREAK_STB, 0)
        priorities = resolve_priorities(market, config)
        orders = {c: priorities.orders[c] for c in market.schools}
        first = orders[market.schools[0]]
        for c in market.schools[1:]:
            self.assertEqual(orders[c], first, msg=(c, orders))

    def test_mtb_gives_different_orders_at_some_pair_of_schools_in_a_sweep(self):
        found = False
        for i in range(5):
            market, config = self._market_with_shared_full_class(TIEBREAK_MTB, i)
            priorities = resolve_priorities(market, config)
            orders = [priorities.orders[c] for c in market.schools]
            if len(set(orders)) >= 2:
                found = True
                break
        self.assertTrue(found, "MTB gave the same order at every school in every swept instance")


class ValidityTestCase(unittest.TestCase):
    def test_every_generated_instance_is_internally_valid_across_many_settings(self):
        configs = [
            GeneratorConfig(n_students=6, n_schools=4, seed="v1"),
            GeneratorConfig(n_students=6, n_schools=4, seed="v2", subscription="over", subscription_ratio=0.4),
            GeneratorConfig(n_students=6, n_schools=4, seed="v3", subscription="under", subscription_ratio=1.8),
            GeneratorConfig(n_students=6, n_schools=4, seed="v4", list_length_mode="fixed", list_length=1),
            GeneratorConfig(n_students=6, n_schools=4, seed="v5", list_length_mode="short"),
            GeneratorConfig(n_students=6, n_schools=4, seed="v6", list_length_mode="uniform"),
            GeneratorConfig(n_students=6, n_schools=4, seed="v7", school_lists_fraction=0.3, n_priority_classes=2),
            GeneratorConfig(n_students=6, n_schools=4, seed="v8", capacity_mode="heterogeneous"),
            GeneratorConfig(n_students=6, n_schools=4, seed="v9", tiebreak_family="mtb"),
            GeneratorConfig(n_students=6, n_schools=4, seed="v10", unlisted_student_policy=UNLISTED_LOWEST_CLASS,
                             school_lists_fraction=0.5),
            GeneratorConfig(n_students=4, n_schools=3, seed="v11", capacity=1),
        ]
        for gc in configs:
            for i in range(4):
                market, profile = generate_instance(gc, i)
                profile.validate_against(market)  # must not raise


class GenerateConfigTestCase(unittest.TestCase):
    def test_da_config_mechanism_matches(self):
        gc = GeneratorConfig(n_students=4, n_schools=3, seed="cfg")
        config = generate_config(gc, 0, MECHANISM_STUDENT_PROPOSING_DA)
        self.assertIsInstance(config, DAConfig)
        self.assertEqual(config.to_dict()["mechanism"], MECHANISM_STUDENT_PROPOSING_DA)

    def test_boston_config_mechanism_matches(self):
        gc = GeneratorConfig(n_students=4, n_schools=3, seed="cfg")
        config = generate_config(gc, 0, MECHANISM_BOSTON_IMMEDIATE_ACCEPTANCE)
        self.assertIsInstance(config, BostonConfig)
        self.assertEqual(config.to_dict()["mechanism"], MECHANISM_BOSTON_IMMEDIATE_ACCEPTANCE)

    def test_unknown_mechanism_raises(self):
        gc = GeneratorConfig(n_students=4, n_schools=3, seed="cfg")
        with self.assertRaises(ModelError):
            generate_config(gc, 0, "not_a_mechanism")

    def test_generated_config_actually_runs_boston(self):
        gc = GeneratorConfig(n_students=4, n_schools=3, seed="cfg-run", subscription="over", subscription_ratio=0.5)
        market, profile = generate_instance(gc, 0)
        config = generate_config(gc, 0, MECHANISM_BOSTON_IMMEDIATE_ACCEPTANCE)
        boston_immediate_acceptance(market, profile, config)  # must not raise


class BackwardCompatibilityTestCase(unittest.TestCase):
    def test_legacy_capacity_field_gives_uniform_capacity(self):
        gc = GeneratorConfig(n_students=4, n_schools=3, capacity=1, seed="legacy")
        market, _ = generate_instance(gc, 0)
        self.assertEqual(set(market.capacities.values()), {1})
        self.assertEqual(market.total_seats(), 3)
        self.assertLess(market.total_seats(), len(market.students))  # matches the WHY note

    def test_priority_tiebreak_always_returns_single_lottery_tiebreak(self):
        from witness.tiebreak import SingleLotteryTiebreak

        gc = GeneratorConfig(n_students=4, n_schools=3, capacity=1, seed="legacy", tiebreak_family=TIEBREAK_MTB)
        tb = priority_tiebreak(gc, 0)
        self.assertIsInstance(tb, SingleLotteryTiebreak)


class ValidationTestCase(unittest.TestCase):
    def test_invalid_subscription_raises(self):
        with self.assertRaises(ModelError):
            GeneratorConfig(n_students=4, n_schools=3, subscription="sideways")

    def test_invalid_capacity_mode_raises(self):
        with self.assertRaises(ModelError):
            GeneratorConfig(n_students=4, n_schools=3, capacity_mode="lopsided")

    def test_invalid_list_length_mode_raises(self):
        with self.assertRaises(ModelError):
            GeneratorConfig(n_students=4, n_schools=3, list_length_mode="whatever")

    def test_invalid_unlisted_student_policy_raises(self):
        with self.assertRaises(ModelError):
            GeneratorConfig(n_students=4, n_schools=3, unlisted_student_policy="whatever")

    def test_invalid_tiebreak_family_raises(self):
        with self.assertRaises(ModelError):
            GeneratorConfig(n_students=4, n_schools=3, tiebreak_family="whatever")

    def test_over_with_ratio_at_least_one_raises(self):
        with self.assertRaises(ModelError):
            GeneratorConfig(n_students=4, n_schools=3, subscription=SUBSCRIPTION_OVER, subscription_ratio=1.0)

    def test_under_with_ratio_at_most_one_raises(self):
        with self.assertRaises(ModelError):
            GeneratorConfig(n_students=4, n_schools=3, subscription=SUBSCRIPTION_UNDER, subscription_ratio=0.9)

    def test_exact_with_ratio_not_one_raises(self):
        with self.assertRaises(ModelError):
            GeneratorConfig(n_students=4, n_schools=3, subscription=SUBSCRIPTION_EXACT, subscription_ratio=1.2)

    def test_fixed_list_length_out_of_range_raises(self):
        with self.assertRaises(ModelError):
            GeneratorConfig(n_students=4, n_schools=3, list_length_mode=LIST_FIXED, list_length=99)
        with self.assertRaises(ModelError):
            GeneratorConfig(n_students=4, n_schools=3, list_length_mode=LIST_FIXED, list_length=-1)

    def test_school_lists_fraction_out_of_range_raises(self):
        with self.assertRaises(ModelError):
            GeneratorConfig(n_students=4, n_schools=3, school_lists_fraction=1.5)
        with self.assertRaises(ModelError):
            GeneratorConfig(n_students=4, n_schools=3, school_lists_fraction=-0.1)

    def test_n_priority_classes_below_one_raises(self):
        with self.assertRaises(ModelError):
            GeneratorConfig(n_students=4, n_schools=3, n_priority_classes=0)

    def test_legacy_capacity_below_one_raises(self):
        with self.assertRaises(ModelError):
            GeneratorConfig(n_students=4, n_schools=3, capacity=0)


if __name__ == "__main__":
    unittest.main()
