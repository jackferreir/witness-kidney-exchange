"""Tests for `witness.invariants`: the singleton-sufficiency checker.

Four things are exercised:

  A. The hand-verified BOS-B instance (same instance as
     `tests/test_boston_positive_control.py`): s1 is manipulable under Boston,
     and a singleton misreport achieves the best gain available from any
     misreport.
  B. A small generated sweep, Boston with placement OFF (the PROVED regime):
     `assert_singleton_sufficiency` must not raise anywhere in the sweep, and
     the sweep must exercise a non-zero number of manipulable cases (else the
     "does not raise" assertion would be vacuously true).
  C. `is_proved_regime`'s exact boundary: true only for Boston-placement-off.
  D. NON-VACUITY, the most important test here: a deliberately-broken
     TEST-ONLY mechanism ("second_choice_only") on which the singleton
     property PROVABLY CANNOT hold (a length-1 report can never obtain
     anything under it), to prove the checker actually detects a violation
     rather than passing by construction on every mechanism we happen to run
     it against.
"""

from __future__ import annotations

import unittest

from witness import mechanisms as mechanisms_module
from witness.boston import PLACEMENT_OFF, PLACEMENT_ON, BostonConfig
from witness.core import Market, Profile, resolve_priorities
from witness.da import Assignment, DAConfig, build_assignment
from witness.errors import MechanismError
from witness.generate import (
    MECHANISM_BOSTON_IMMEDIATE_ACCEPTANCE,
    GeneratorConfig,
    generate_config,
    generate_instance,
)
from witness.invariants import (
    assert_singleton_sufficiency,
    check_instance,
    check_singleton_sufficiency,
    is_proved_regime,
)
from witness.mechanisms import MechanismSpec, register_mechanism
from witness.tiebreak import RejectTies


def _bos_b_market() -> Market:
    return Market(
        students=("s1", "s2", "s3"),
        schools=("c1", "c2"),
        capacities={"c1": 1, "c2": 1},
        priority_classes={
            "c1": (("s3",), ("s1",), ("s2",)),
            "c2": (("s1",), ("s2",), ("s3",)),
        },
    )


def _bos_b_profile() -> Profile:
    return Profile({"s1": ("c1", "c2"), "s2": ("c2", "c1"), "s3": ("c1", "c2")})


class HandVerifiedBosBTestCase(unittest.TestCase):
    """Part A: the hand-verified BOS-B instance from
    `tests/test_boston_positive_control.py`. s1 is manipulable under Boston
    (truthfully unmatched); this asserts singleton sufficiency HOLDS for s1
    and that a length-1 misreport is among the best-achieving ones.
    """

    def test_s1_manipulable_and_singleton_achieves_best_rank(self):
        market = _bos_b_market()
        profile = _bos_b_profile()
        config = BostonConfig(tiebreak=RejectTies(), mechanism="boston_immediate_acceptance")

        check = check_singleton_sufficiency(
            market, profile, "s1", "boston_immediate_acceptance", config
        )

        self.assertTrue(check.manipulable)
        self.assertTrue(check.holds)
        self.assertIsNotNone(check.best_rank_singleton)
        self.assertEqual(check.best_rank_singleton, check.best_rank_any)
        self.assertTrue(
            any(len(r) == 1 for r in check.best_misreports),
            f"expected a length-1 misreport among the best-achieving ones, got "
            f"{check.best_misreports!r}",
        )


#: Generator config for part B: small enough (4 schools -> 65 ordered
#: subsets) that the exhaustive per-student enumeration stays fast even
#: across many instances, and `capacity=1` (the Step-3A legacy alias) keeps
#: the market over-subscribed, which is exactly the high-contention regime
#: `witness.generate`'s own docstring measures the highest Boston
#: manipulation rate in -- so a small sweep is very unlikely to be
#: accidentally vacuous (zero manipulable cases).
_SWEEP_GC = GeneratorConfig(n_students=4, n_schools=4, capacity=1, seed="invariants-sweep")
_SWEEP_N_INSTANCES = 30


class GeneratedSweepPlacementOffTestCase(unittest.TestCase):
    """Part B: over a small generated sweep, Boston with placement OFF (the
    PROVED regime), `assert_singleton_sufficiency` must never raise -- and
    the sweep must exercise a non-zero number of manipulable cases, or the
    "never raises" assertion would be vacuous.
    """

    def test_holds_over_generated_sweep_and_is_non_vacuous(self):
        manipulable_count = 0
        for i in range(_SWEEP_N_INSTANCES):
            market, profile = generate_instance(_SWEEP_GC, i)
            config = generate_config(_SWEEP_GC, i, MECHANISM_BOSTON_IMMEDIATE_ACCEPTANCE)
            self.assertTrue(
                is_proved_regime(MECHANISM_BOSTON_IMMEDIATE_ACCEPTANCE, config),
                f"generate_config's Boston config at index {i} was expected to "
                f"default to placement=off (the proved regime); got "
                f"placement={getattr(config, 'placement', None)!r}",
            )

            checks = check_instance(
                market, profile, MECHANISM_BOSTON_IMMEDIATE_ACCEPTANCE, config
            )
            manipulable_count += sum(1 for c in checks if c.manipulable)

            # The function under test, part B's actual assertion: must not raise.
            assert_singleton_sufficiency(
                market, profile, MECHANISM_BOSTON_IMMEDIATE_ACCEPTANCE, config
            )

        print(
            f"generated sweep (placement off): {manipulable_count} manipulable "
            f"(instance, student) cases checked over {_SWEEP_N_INSTANCES} instances, "
            f"singleton sufficiency held in every one"
        )
        self.assertGreater(
            manipulable_count,
            0,
            "sweep produced zero manipulable cases -- the 'never raises' assertion "
            "above would be vacuous",
        )


class IsProvedRegimeTestCase(unittest.TestCase):
    """Part C: `is_proved_regime`'s exact boundary."""

    def test_true_for_boston_placement_off(self):
        self.assertTrue(
            is_proved_regime(
                "boston_immediate_acceptance", BostonConfig(placement=PLACEMENT_OFF)
            )
        )

    def test_false_for_boston_placement_on(self):
        self.assertFalse(
            is_proved_regime(
                "boston_immediate_acceptance", BostonConfig(placement=PLACEMENT_ON)
            )
        )

    def test_false_for_student_proposing_da(self):
        self.assertFalse(
            is_proved_regime("student_proposing_da", DAConfig(mechanism="student_proposing_da"))
        )

    def test_false_for_first_choice_bonus_da(self):
        self.assertFalse(
            is_proved_regime(
                "first_choice_bonus_da", DAConfig(mechanism="first_choice_bonus_da")
            )
        )


class MaxSpaceGuardTestCase(unittest.TestCase):
    """The exhaustive-enumeration guard: `check_singleton_sufficiency` must
    raise `ValueError` (propagated from `witness.search.misreport_space`)
    rather than silently enumerate a space larger than `max_space`.
    """

    def test_raises_value_error_when_space_exceeds_max_space(self):
        # 2 schools -> sum_{k=0}^{2} P(2,k) = 1 + 2 + 2 = 5 ordered subsets,
        # which exceeds max_space=4.
        market = _bos_b_market()
        profile = _bos_b_profile()
        config = BostonConfig(tiebreak=RejectTies(), mechanism="boston_immediate_acceptance")
        with self.assertRaises(ValueError):
            check_singleton_sufficiency(
                market, profile, "s1", "boston_immediate_acceptance", config, max_space=4
            )


# =============================================================================
# Part D: non-vacuity. A test-only mechanism the checker MUST flag.
# =============================================================================
#
# "second_choice_only": every student proposes to the SECOND school on their
# submitted list (a student whose list has fewer than 2 entries proposes to
# nothing and ends unmatched); each school accepts its highest-priority
# proposers up to capacity. One round, no re-proposal.
#
# This is NOT a real mechanism and is never added to witness/ -- it exists
# solely as a fixture to prove `witness.invariants` can detect a violation.
# Under it, a length-1 report can never obtain anything (it names no second
# choice), so any profitable misreport must have length >= 2, and NO
# singleton can ever achieve the best gain a longer misreport can. That makes
# singleton sufficiency PROVABLY FALSE here whenever the student is
# manipulable at all -- the opposite of the Boston-immediate-acceptance case,
# by construction.


def _second_choice_only_run(market: Market, profile: Profile, config) -> Assignment:
    priorities = resolve_priorities(market, config)
    proposals: dict = {}
    for s in market.students:
        report = profile.report(s)
        if len(report) >= 2:
            proposals[s] = report[1]
    assigned: dict = {s: None for s in market.students}
    for c in market.schools:
        applicants = [s for s in market.students if proposals.get(s) == c]
        acceptable = [s for s in applicants if priorities.rank(c, s) is not None]
        ranked = sorted(acceptable, key=lambda s: priorities.rank(c, s))
        for s in ranked[: market.capacity(c)]:
            assigned[s] = c
    return build_assignment(market, priorities, assigned, allow_unranked=False)


_SECOND_CHOICE_ONLY = "second_choice_only"


def _second_choice_only_market() -> Market:
    return Market(
        students=("s1", "s2"),
        schools=("c1", "c2"),
        capacities={"c1": 1, "c2": 1},
        priority_classes={
            "c1": (("s1",), ("s2",)),
            "c2": (("s1",), ("s2",)),
        },
    )


def _second_choice_only_profile() -> Profile:
    return Profile({"s1": ("c1", "c2"), "s2": ("c1", "c2")})


class SecondChoiceOnlyNonVacuityTestCase(unittest.TestCase):
    """Part D. Registers `second_choice_only` into the real mechanism
    registry for the duration of this test class only (setUp/tearDown), so
    it never leaks into any other test.

    HAND-WORKED INSTANCE (both students truthfully report `("c1","c2")`, s1
    strictly above s2 at both schools):

      Truthful run: both students' SECOND choice is c2, so both propose to
      c2. c2's priority order is (s1, s2), capacity 1, so s1 wins c2 and s2
      is rejected with no second round -> s2 ends unmatched (None).

      s2 misreports `("c2","c1")`: s2's second choice is now c1. s1's report
      is untouched (still proposes to c2, per the search's own rule that
      only the target's report changes), so s1 still gets c2. s2 is now the
      sole proposer to c1 and is acceptable there, so s2 gets c1 -- s2's
      TRUTHFUL first choice (rank 0), strictly better than the truthful
      outcome (unmatched, WORST). This is the unique best-achieving
      misreport: with only 2 schools, the only length->=2 report whose
      SECOND entry is c1 is `("c2","c1")` itself.

      No length-1 misreport for s2 can ever beat the truthful (unmatched)
      outcome: a singleton has no second entry, so s2 always proposes to
      nothing and stays unmatched -- identical to (not better than) the
      truthful outcome. So s2 IS manipulable, but NO singleton achieves the
      best gain: singleton sufficiency is false for this exact case.

      By the same argument with the roles reversed, s1 (truthfully getting
      c2, rank 1) can reach c1 (rank 0) via the identical misreport
      `("c2","c1")` once s2's report is held fixed, and no singleton helps
      s1 either -- this instance is symmetric, both students fail. Since
      `market.students` order is `("s1","s2")`, `assert_singleton_sufficiency`
      (which stops at the first failing student) actually raises on s1, not
      s2; the test below asserts on what holds regardless of which one is
      named first.
    """

    def setUp(self) -> None:
        register_mechanism(
            MechanismSpec(
                name=_SECOND_CHOICE_ONLY,
                config_from_dict=DAConfig.from_dict,
                run=_second_choice_only_run,
            )
        )

    def tearDown(self) -> None:
        mechanisms_module._REGISTRY.pop(_SECOND_CHOICE_ONLY, None)

    def _config(self) -> DAConfig:
        return DAConfig(tiebreak=RejectTies(), mechanism=_SECOND_CHOICE_ONLY)

    def test_checker_detects_manipulable_with_no_sufficient_singleton(self):
        market = _second_choice_only_market()
        profile = _second_choice_only_profile()
        config = self._config()

        check = check_singleton_sufficiency(
            market, profile, "s2", _SECOND_CHOICE_ONLY, config
        )

        self.assertTrue(check.manipulable)
        self.assertFalse(check.holds)
        self.assertEqual(check.best_rank_any, 0.0)
        self.assertEqual(check.best_misreports, (("c2", "c1"),))
        # No singleton is profitable at all here, so best_rank_singleton is
        # None -- strictly "worse" (absent) than best_rank_any.
        self.assertIsNone(check.best_rank_singleton)

    def test_assert_singleton_sufficiency_raises_naming_target_and_misreports(self):
        market = _second_choice_only_market()
        profile = _second_choice_only_profile()
        config = self._config()

        with self.assertRaises(MechanismError) as cm:
            assert_singleton_sufficiency(market, profile, _SECOND_CHOICE_ONLY, config)

        message = str(cm.exception)
        # By symmetry of this hand-worked instance, BOTH s1 and s2 are
        # manipulable with no sufficient singleton (see the class docstring
        # for s2; s1 is the mirror case, truthfully getting c2 and reaching
        # c1 the same way) -- `market.students` order is ("s1", "s2"), so
        # `assert_singleton_sufficiency` raises on s1 first. Assert on what
        # must be true regardless of which target is named: the message
        # names SOME target explicitly, the mechanism, and the
        # best-achieving misreport that got it there.
        self.assertIn("second_choice_only", message)
        self.assertTrue(
            "target 's1'" in message or "target 's2'" in message,
            f"expected the message to name a target explicitly: {message!r}",
        )
        self.assertIn("('c2', 'c1')", message)
        print(f"non-vacuity check raised as expected: {message}")


if __name__ == "__main__":
    unittest.main()
