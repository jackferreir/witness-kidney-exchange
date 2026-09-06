"""Tests for `witness.coverage`.

Each `*OnlyTestCase` hand-builds a tiny market/profile/config so that exactly
one coverage branch fires, and checks every OTHER branch is False wherever
that is actually achievable given the branch definitions (a couple of
branches are logically entangled by construction -- e.g. an
unacceptable-rejection is impossible without the rejected student also being
structurally unlisted somewhere -- and those cases say so explicitly instead
of asserting something that cannot hold).
"""

from __future__ import annotations

import unittest

from witness.boston import BostonConfig, boston_immediate_acceptance
from witness.core import Market, Profile
from witness.coverage import (
    BRANCH_NAMES,
    CoverageReport,
    InstanceCoverage,
    aggregate,
    instance_coverage,
    unreached_branches,
)
from witness.da import DAConfig, deferred_acceptance
from witness.errors import ModelError
from witness.generate import (
    CAPACITY_HETEROGENEOUS,
    GeneratorConfig,
    LIST_UNIFORM,
    generate_config,
    generate_instance,
)
from witness.tiebreak import RejectTies, SingleLotteryTiebreak


def _all_false_except(cov: InstanceCoverage, *true_names: str) -> None:
    for name in BRANCH_NAMES:
        expected = name in true_names
        assert getattr(cov, name) == expected, (
            f"{name}: expected {expected}, got {getattr(cov, name)} in {cov.to_dict()!r}"
        )


class UnlistedStudentOnlyTestCase(unittest.TestCase):
    """s2 is structurally unlisted at c1, but s2's report never mentions c1
    (s2's first choice, c2, succeeds outright) -- so the trace never
    exercises "unacceptable rejection" at all, isolating the pure
    structural flag."""

    def test_only_had_unlisted_student_is_true(self):
        market = Market(
            students=("s1", "s2"),
            schools=("c1", "c2"),
            capacities={"c1": 2, "c2": 2},
            priority_classes={
                "c1": (("s1",),),  # s2 absent -> unacceptable at c1
                "c2": (("s1",), ("s2",)),
            },
        )
        profile = Profile({"s1": ("c1", "c2"), "s2": ("c2", "c1")})
        config = DAConfig(tiebreak=RejectTies())
        result = deferred_acceptance(market, profile, config)

        self.assertEqual(result.assignment.student_to_school, {"s1": "c1", "s2": "c2"})
        cov = instance_coverage(market, profile, config, result)
        _all_false_except(cov, "had_unlisted_student")
        self.assertEqual(cov.subscription, "under")  # 4 seats, 2 students


class CapacityContentionOnlyTestCase(unittest.TestCase):
    """s1 and s2 both truthfully want c1 first; c1 has one seat, so one of
    them loses "by competition" -- but the loser is fully listed everywhere
    and gets seated at c2 on their second choice, so nobody ends up
    unmatched, unlisted, or facing an unacceptable-rejection."""

    def test_only_had_capacity_contention_is_true(self):
        market = Market(
            students=("s1", "s2"),
            schools=("c1", "c2"),
            capacities={"c1": 1, "c2": 1},
            priority_classes={
                "c1": (("s1",), ("s2",)),
                "c2": (("s1",), ("s2",)),
            },
        )
        profile = Profile({"s1": ("c1", "c2"), "s2": ("c1", "c2")})
        config = DAConfig(tiebreak=RejectTies())
        result = deferred_acceptance(market, profile, config)

        self.assertEqual(result.assignment.student_to_school, {"s1": "c1", "s2": "c2"})
        cov = instance_coverage(market, profile, config, result)
        _all_false_except(cov, "had_capacity_contention")
        self.assertEqual(cov.subscription, "exact")


class LotteryTieOnlyTestCase(unittest.TestCase):
    """Both schools declare a single class containing both students (a real
    tie), but capacity is generous enough that nobody is ever rejected."""

    def test_only_had_lottery_tie_is_true(self):
        market = Market(
            students=("s1", "s2"),
            schools=("c1", "c2"),
            capacities={"c1": 2, "c2": 2},
            priority_classes={
                "c1": (("s1", "s2"),),
                "c2": (("s1", "s2"),),
            },
        )
        profile = Profile({"s1": ("c1", "c2"), "s2": ("c1", "c2")})
        config = DAConfig(tiebreak=SingleLotteryTiebreak(seed="lottery-tie-test"))
        result = deferred_acceptance(market, profile, config)

        self.assertEqual(result.assignment.student_to_school, {"s1": "c1", "s2": "c1"})
        cov = instance_coverage(market, profile, config, result)
        _all_false_except(cov, "had_lottery_tie")
        self.assertEqual(cov.subscription, "under")


class IncompleteListOnlyTestCase(unittest.TestCase):
    """A single student, 3 schools, a 2-school report: incomplete (2 < 3)
    but NOT very-short (2 > 1)."""

    def test_only_had_incomplete_list_is_true(self):
        market = Market(
            students=("s1",),
            schools=("c1", "c2", "c3"),
            capacities={"c1": 1, "c2": 1, "c3": 1},
            priority_classes={"c1": (("s1",),), "c2": (("s1",),), "c3": (("s1",),)},
        )
        profile = Profile({"s1": ("c1", "c2")})
        config = DAConfig(tiebreak=RejectTies())
        result = deferred_acceptance(market, profile, config)

        self.assertEqual(result.assignment.student_to_school, {"s1": "c1"})
        cov = instance_coverage(market, profile, config, result)
        _all_false_except(cov, "had_incomplete_list")
        self.assertEqual(cov.subscription, "under")


class VeryShortListOnlyTestCase(unittest.TestCase):
    """A single student, a single school, report length 1: simultaneously
    COMPLETE (1 == n_schools) and very-short (1 <= 1) -- the only way to get
    "very short" without also being "incomplete"."""

    def test_only_had_very_short_list_is_true(self):
        market = Market(
            students=("s1",),
            schools=("c1",),
            capacities={"c1": 1},
            priority_classes={"c1": (("s1",),)},
        )
        profile = Profile({"s1": ("c1",)})
        config = DAConfig(tiebreak=RejectTies())
        result = deferred_acceptance(market, profile, config)

        self.assertEqual(result.assignment.student_to_school, {"s1": "c1"})
        cov = instance_coverage(market, profile, config, result)
        _all_false_except(cov, "had_very_short_list")
        self.assertEqual(cov.subscription, "exact")


class UnacceptableRejectionEntailsUnlistedTestCase(unittest.TestCase):
    """s2 proposes to c1 (where it is unacceptable) before being accepted at
    c2. This necessarily ALSO sets had_unlisted_student -- being rejected as
    unacceptable under UNLISTED_UNACCEPTABLE is impossible without being
    structurally absent from that school's priority classes -- so this case
    documents that entailment explicitly rather than asserting the
    impossible "unlisted=False"."""

    def test_had_school_unacceptable_rejection_implies_had_unlisted_student(self):
        market = Market(
            students=("s1", "s2"),
            schools=("c1", "c2"),
            capacities={"c1": 1, "c2": 1},
            priority_classes={
                "c1": (("s1",),),  # s2 absent -> unacceptable at c1
                "c2": (("s1",), ("s2",)),
            },
        )
        profile = Profile({"s1": ("c1", "c2"), "s2": ("c1", "c2")})
        config = DAConfig(tiebreak=RejectTies())
        result = deferred_acceptance(market, profile, config)

        self.assertEqual(result.assignment.student_to_school, {"s1": "c1", "s2": "c2"})
        cov = instance_coverage(market, profile, config, result)
        _all_false_except(cov, "had_school_unacceptable_rejection", "had_unlisted_student")
        self.assertEqual(cov.subscription, "exact")


class BostonFHandworkedTestCase(unittest.TestCase):
    """The BOS-F instance from tests/test_boston_handworked.py: students
    s1,s2,s3; schools c1 cap1, c2 cap1, c3 cap2; c2 lists only s1; every
    report is (c1,) only. placement="off" (the BostonConfig default)."""

    def _bos_f_market_and_profile(self):
        market = Market(
            students=("s1", "s2", "s3"),
            schools=("c1", "c2", "c3"),
            capacities={"c1": 1, "c2": 1, "c3": 2},
            priority_classes={
                "c1": (("s1",), ("s2",), ("s3",)),
                "c2": (("s1",),),  # s2, s3 unlisted -> unacceptable at c2
                "c3": (("s1",), ("s2",), ("s3",)),
            },
        )
        profile = Profile({s: ("c1",) for s in market.students})
        return market, profile

    def test_bos_f_coverage(self):
        market, profile = self._bos_f_market_and_profile()
        config = BostonConfig(tiebreak=RejectTies())  # placement=PLACEMENT_OFF default
        result = boston_immediate_acceptance(market, profile, config)

        self.assertEqual(
            result.assignment.student_to_school, {"s1": "c1", "s2": None, "s3": None}
        )

        cov = instance_coverage(market, profile, config, result)
        self.assertTrue(cov.had_unmatched_student)
        self.assertTrue(cov.had_unlisted_student)
        self.assertTrue(cov.had_capacity_contention)
        self.assertTrue(cov.had_very_short_list)
        self.assertEqual(cov.subscription, "under")
        # Nobody ever proposes to c2 (every report is (c1,) only), so the
        # structural unlisted-ness at c2 is never exercised as a rejection.
        self.assertFalse(cov.had_school_unacceptable_rejection)
        # All three priority classes are singletons -- no real tie anywhere.
        self.assertFalse(cov.had_lottery_tie)


class AggregateTestCase(unittest.TestCase):
    def _cov(self, **true_names) -> InstanceCoverage:
        base = {name: False for name in BRANCH_NAMES}
        base.update(true_names)
        subscription = base.pop("subscription", "exact")
        return InstanceCoverage(subscription=subscription, **base)

    def test_aggregate_computes_correct_fractions(self):
        coverages = [
            self._cov(had_unmatched_student=True, subscription="over"),
            self._cov(had_unmatched_student=True, had_capacity_contention=True, subscription="over"),
            self._cov(subscription="exact"),
            self._cov(had_lottery_tie=True, subscription="under"),
        ]
        report = aggregate(coverages)

        self.assertEqual(report.n_instances, 4)
        self.assertAlmostEqual(report.fractions["had_unmatched_student"], 2 / 4)
        self.assertAlmostEqual(report.fractions["had_capacity_contention"], 1 / 4)
        self.assertAlmostEqual(report.fractions["had_lottery_tie"], 1 / 4)
        self.assertAlmostEqual(report.fractions["had_unlisted_student"], 0.0)
        self.assertAlmostEqual(report.fractions["had_incomplete_list"], 0.0)
        self.assertAlmostEqual(report.fractions["had_very_short_list"], 0.0)
        self.assertAlmostEqual(report.fractions["had_school_unacceptable_rejection"], 0.0)
        self.assertEqual(
            report.subscription_counts, {"over": 2, "exact": 1, "under": 1}
        )

    def test_aggregate_rejects_empty_input(self):
        with self.assertRaises(ModelError):
            aggregate([])

    def test_unreached_branches_names_zero_fraction_branches(self):
        coverages = [
            self._cov(had_unmatched_student=True, subscription="over"),
            self._cov(had_capacity_contention=True, subscription="exact"),
        ]
        report = aggregate(coverages)
        unreached = unreached_branches(report)
        self.assertEqual(
            set(unreached),
            {
                "had_unlisted_student",
                "had_lottery_tie",
                "had_incomplete_list",
                "had_very_short_list",
                "had_school_unacceptable_rejection",
            },
        )
        self.assertNotIn("had_unmatched_student", unreached)
        self.assertNotIn("had_capacity_contention", unreached)


class NarrowSettingRegressionLockTestCase(unittest.TestCase):
    """The Step-3A narrow generator's own blind spots, locked in as an
    explicit regression: complete lists, school_lists_fraction=1.0,
    n_priority_classes=1, uniform capacity, STB NEVER exercises the
    unlisted-student branch or the school-unacceptable-rejection branch,
    over a small sweep. If this ever stops being true, the WHY section of
    `witness.generate`'s docstring (and every rate measured against the old
    narrow setting) needs to be revisited, not this test weakened."""

    def test_narrow_setting_never_sees_unlisted_or_unacceptable_rejection(self):
        gc = GeneratorConfig(n_students=4, n_schools=3, capacity=1, seed="narrow-lock")
        coverages = []
        for i in range(40):
            market, profile = generate_instance(gc, i)
            config = generate_config(gc, i, "boston_immediate_acceptance")
            result = boston_immediate_acceptance(market, profile, config)
            coverages.append(instance_coverage(market, profile, config, result))

        report = aggregate(coverages)
        self.assertEqual(report.fractions["had_unlisted_student"], 0.0)
        self.assertEqual(report.fractions["had_school_unacceptable_rejection"], 0.0)


if __name__ == "__main__":
    unittest.main()
