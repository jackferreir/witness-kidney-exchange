"""Hand-worked examples for student-proposing Deferred Acceptance.

Every expected value in this file was computed by hand on paper AND
independently confirmed against a trace dump of `witness.da.deferred_acceptance`.
DO NOT change any expected value to make a test pass: a failure here is a
real finding about the implementation, not something to paper over.

Every test asserts on BOTH the final assignment AND the recorded trace
(step count, proposals tuple, rejection tuples, holds_after, n_proposals) so
that a wrong tiebreak that happens to produce a coincidentally-correct final
matching still gets caught.

Unless stated otherwise, every example uses tiebreak=RejectTies() (every
priority class here is a singleton, so no ties ever arise) and
unlisted_student_policy=UNLISTED_UNACCEPTABLE.
"""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

from witness.core import (
    Market,
    MechanismConfig,
    Profile,
    UNLISTED_LOWEST_CLASS,
    UNLISTED_UNACCEPTABLE,
    canonical_json,
    content_hash,
    resolve_priorities,
)
from witness.da import (
    ALL_FREE_SIMULTANEOUS,
    ONE_AT_A_TIME_DECLARED_ORDER,
    DAConfig,
    deferred_acceptance,
)
from witness.errors import TieError
from witness.tiebreak import (
    GLOBAL_SCOPE,
    MultipleLotteryTiebreak,
    RejectTies,
    SingleLotteryTiebreak,
    lottery_order,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _all_singleton_classes(order: tuple[str, ...]) -> tuple[tuple[str, ...], ...]:
    """Turn a fully-strict order ("s3 > s2 > s1") into singleton priority
    classes (("s3",), ("s2",), ("s1",)) — the shape Market.priority_classes
    expects."""
    return tuple((s,) for s in order)


class ExampleAConfig:
    """students s1,s2,s3; schools c1,c2,c3; capacities all 1; s3>s2>s1 at
    every school; everyone ranks c1,c2,c3 in that order."""

    students = ("s1", "s2", "s3")
    schools = ("c1", "c2", "c3")

    @classmethod
    def market(cls) -> Market:
        strict = _all_singleton_classes(("s3", "s2", "s1"))
        return Market(
            students=cls.students,
            schools=cls.schools,
            capacities={"c1": 1, "c2": 1, "c3": 1},
            priority_classes={c: strict for c in cls.schools},
        )

    @classmethod
    def profile(cls) -> Profile:
        ranking = ("c1", "c2", "c3")
        return Profile({s: ranking for s in cls.students})

    @classmethod
    def config(cls) -> DAConfig:
        return DAConfig(
            tiebreak=RejectTies(),
            unlisted_student_policy=UNLISTED_UNACCEPTABLE,
            proposal_policy=ALL_FREE_SIMULTANEOUS,
        )


class ExampleBConfig:
    """students s1,s2,s3; schools c1,c2; capacities 1 each; displacement
    chain, s3 ends unmatched."""

    students = ("s1", "s2", "s3")
    schools = ("c1", "c2")

    @classmethod
    def market(cls) -> Market:
        return Market(
            students=cls.students,
            schools=cls.schools,
            capacities={"c1": 1, "c2": 1},
            priority_classes={
                "c1": _all_singleton_classes(("s2", "s1", "s3")),
                "c2": _all_singleton_classes(("s1", "s3", "s2")),
            },
        )

    @classmethod
    def profile(cls) -> Profile:
        return Profile(
            {
                "s1": ("c1", "c2"),
                "s2": ("c1", "c2"),
                "s3": ("c2", "c1"),
            }
        )

    @classmethod
    def config(cls, proposal_policy=ALL_FREE_SIMULTANEOUS) -> DAConfig:
        return DAConfig(
            tiebreak=RejectTies(),
            unlisted_student_policy=UNLISTED_UNACCEPTABLE,
            proposal_policy=proposal_policy,
        )


class ExampleCConfig:
    """students s1..s4; schools c1,c2; capacities c1=2, c2=1; many-to-one."""

    students = ("s1", "s2", "s3", "s4")
    schools = ("c1", "c2")

    @classmethod
    def market(cls) -> Market:
        return Market(
            students=cls.students,
            schools=cls.schools,
            capacities={"c1": 2, "c2": 1},
            priority_classes={
                "c1": _all_singleton_classes(("s4", "s3", "s2", "s1")),
                "c2": _all_singleton_classes(("s1", "s2", "s3", "s4")),
            },
        )

    @classmethod
    def profile(cls) -> Profile:
        return Profile(
            {
                "s1": ("c1", "c2"),
                "s2": ("c1", "c2"),
                "s3": ("c1", "c2"),
                "s4": ("c2", "c1"),
            }
        )

    @classmethod
    def config(cls) -> DAConfig:
        return DAConfig(
            tiebreak=RejectTies(),
            unlisted_student_policy=UNLISTED_UNACCEPTABLE,
            proposal_policy=ALL_FREE_SIMULTANEOUS,
        )


class ExampleDConfig:
    """students s1,s2; schools c1,c2; capacities 1 each; c2 lists only s2 in
    its priority classes, so s1 is unlisted at c2. unlisted_student_policy
    changes the outcome."""

    students = ("s1", "s2")
    schools = ("c1", "c2")

    @classmethod
    def market(cls) -> Market:
        return Market(
            students=cls.students,
            schools=cls.schools,
            capacities={"c1": 1, "c2": 1},
            priority_classes={
                "c1": _all_singleton_classes(("s2", "s1")),
                "c2": (("s2",),),  # s1 listed in NO class of c2
            },
        )

    @classmethod
    def profile(cls) -> Profile:
        return Profile({"s1": ("c1", "c2"), "s2": ("c1",)})

    @classmethod
    def config(cls, unlisted_student_policy) -> DAConfig:
        return DAConfig(
            tiebreak=RejectTies(),
            unlisted_student_policy=unlisted_student_policy,
            proposal_policy=ALL_FREE_SIMULTANEOUS,
        )


class DAHandworkedTestCase(unittest.TestCase):
    def assert_step(
        self,
        step,
        *,
        index,
        proposals,
        rejected_as_unacceptable=(),
        rejected_by_competition=(),
        holds_after,
    ):
        self.assertEqual(step.index, index)
        self.assertEqual(step.proposals, proposals)
        self.assertEqual(step.rejected_as_unacceptable, rejected_as_unacceptable)
        self.assertEqual(step.rejected_by_competition, rejected_by_competition)
        self.assertEqual(step.holds_after, holds_after)

    # ------------------------------------------------------------------
    # Example A: simple cascade
    # ------------------------------------------------------------------
    def test_example_a_simple_cascade(self):
        """s1,s2,s3 all rank c1,c2,c3 in that order; s3>s2>s1 at every
        school (capacity 1 each). Round 1: everyone proposes to c1; c1 keeps
        the top-priority proposer s3 and rejects s2,s1 (in that order,
        following c1's priority/drop order s2 then s1). Round 2: s1,s2
        propose to c2 (their next choice); c2 keeps s2, rejects s1. Round 3:
        s1 proposes to c3 and is held (no competitor). Final: s1->c3,
        s2->c2, s3->c1."""
        market = ExampleAConfig.market()
        profile = ExampleAConfig.profile()
        config = ExampleAConfig.config()
        result = deferred_acceptance(market, profile, config)

        self.assertEqual(len(result.steps), 3)
        self.assert_step(
            result.steps[0],
            index=1,
            proposals=(("s1", "c1"), ("s2", "c1"), ("s3", "c1")),
            rejected_by_competition=(("s2", "c1"), ("s1", "c1")),
            holds_after=(("c1", ("s3",)),),
        )
        self.assert_step(
            result.steps[1],
            index=2,
            proposals=(("s1", "c2"), ("s2", "c2")),
            rejected_by_competition=(("s1", "c2"),),
            holds_after=(("c1", ("s3",)), ("c2", ("s2",))),
        )
        self.assert_step(
            result.steps[2],
            index=3,
            proposals=(("s1", "c3"),),
            holds_after=(("c1", ("s3",)), ("c2", ("s2",)), ("c3", ("s1",))),
        )
        self.assertEqual(result.n_proposals, 6)

        self.assertEqual(
            result.assignment.student_to_school,
            {"s1": "c3", "s2": "c2", "s3": "c1"},
        )
        self.assertEqual(result.assignment.roster("c1"), ("s3",))
        self.assertEqual(result.assignment.roster("c2"), ("s2",))
        self.assertEqual(result.assignment.roster("c3"), ("s1",))

    # ------------------------------------------------------------------
    # Example B: displacement chain, one student ends unmatched
    # ------------------------------------------------------------------
    def test_example_b_displacement_chain_all_free_simultaneous(self):
        """s1,s2 rank (c1,c2); s3 ranks (c2,c1). c1 prefers s2>s1>s3; c2
        prefers s1>s3>s2. Round 1: s1,s2 propose c1 (c1 holds s2, rejects
        s1); s3 proposes c2 (held). Round 2: s1 proposes c2; c2 prefers s1
        over its current holder s3, so s1 displaces s3 (s3 rejected).
        Round 3: s3 proposes its only remaining choice c1; c1 prefers its
        holder s2 over s3, so s3 is rejected again and now has an exhausted
        list -> unmatched. Final: s1->c2, s2->c1, s3->None."""
        market = ExampleBConfig.market()
        profile = ExampleBConfig.profile()
        config = ExampleBConfig.config(ALL_FREE_SIMULTANEOUS)
        result = deferred_acceptance(market, profile, config)

        self.assertEqual(len(result.steps), 3)
        self.assert_step(
            result.steps[0],
            index=1,
            proposals=(("s1", "c1"), ("s2", "c1"), ("s3", "c2")),
            rejected_by_competition=(("s1", "c1"),),
            holds_after=(("c1", ("s2",)), ("c2", ("s3",))),
        )
        self.assert_step(
            result.steps[1],
            index=2,
            proposals=(("s1", "c2"),),
            rejected_by_competition=(("s3", "c2"),),
            holds_after=(("c1", ("s2",)), ("c2", ("s1",))),
        )
        self.assert_step(
            result.steps[2],
            index=3,
            proposals=(("s3", "c1"),),
            rejected_by_competition=(("s3", "c1"),),
            holds_after=(("c1", ("s2",)), ("c2", ("s1",))),
        )
        self.assertEqual(result.n_proposals, 5)

        self.assertEqual(
            result.assignment.student_to_school,
            {"s1": "c2", "s2": "c1", "s3": None},
        )
        self.assertEqual(result.assignment.roster("c1"), ("s2",))
        self.assertEqual(result.assignment.roster("c2"), ("s1",))

    def test_example_b_prime_one_at_a_time_same_assignment_more_steps(self):
        """Same instance as Example B, but under
        ONE_AT_A_TIME_DECLARED_ORDER (exactly one proposer per step: the
        first free student in Market.students order). The published
        algorithm claims order independence of the final matching, so this
        must produce the IDENTICAL Assignment as Example B while taking a
        DIFFERENT (larger) number of steps: 5 one-proposal steps instead of
        3 simultaneous-round steps.

        step 1: s1 -> c1, held.
        step 2: s2 -> c1; c1 prefers s2 over s1, s1 rejected, c1 holds s2.
        step 3: s1 -> c2 (next choice), held.
        step 4: s3 -> c2 (first choice); c2 prefers holder s1, s3 rejected.
        step 5: s3 -> c1 (next/last choice); c1 prefers holder s2, s3
                rejected, now exhausted -> unmatched.
        """
        market = ExampleBConfig.market()
        profile = ExampleBConfig.profile()
        config = ExampleBConfig.config(ONE_AT_A_TIME_DECLARED_ORDER)
        result = deferred_acceptance(market, profile, config)

        self.assertEqual(len(result.steps), 5)
        self.assert_step(
            result.steps[0],
            index=1,
            proposals=(("s1", "c1"),),
            holds_after=(("c1", ("s1",)),),
        )
        self.assert_step(
            result.steps[1],
            index=2,
            proposals=(("s2", "c1"),),
            rejected_by_competition=(("s1", "c1"),),
            holds_after=(("c1", ("s2",)),),
        )
        self.assert_step(
            result.steps[2],
            index=3,
            proposals=(("s1", "c2"),),
            holds_after=(("c1", ("s2",)), ("c2", ("s1",))),
        )
        self.assert_step(
            result.steps[3],
            index=4,
            proposals=(("s3", "c2"),),
            rejected_by_competition=(("s3", "c2"),),
            holds_after=(("c1", ("s2",)), ("c2", ("s1",))),
        )
        self.assert_step(
            result.steps[4],
            index=5,
            proposals=(("s3", "c1"),),
            rejected_by_competition=(("s3", "c1"),),
            holds_after=(("c1", ("s2",)), ("c2", ("s1",))),
        )
        self.assertEqual(result.n_proposals, 5)

        self.assertEqual(
            result.assignment.student_to_school,
            {"s1": "c2", "s2": "c1", "s3": None},
        )
        self.assertEqual(result.assignment.roster("c1"), ("s2",))
        self.assertEqual(result.assignment.roster("c2"), ("s1",))

    def test_example_b_and_b_prime_agree_on_assignment_but_not_step_count(self):
        """Explicit cross-check: the two proposal policies on the identical
        instance give the SAME final Assignment but a DIFFERENT number of
        recorded steps (3 vs 5). This is exactly the order-independence
        property the module docstring says is 'relied on elsewhere and
        asserted here'."""
        market = ExampleBConfig.market()
        profile = ExampleBConfig.profile()

        result_all = deferred_acceptance(
            market, profile, ExampleBConfig.config(ALL_FREE_SIMULTANEOUS)
        )
        result_one = deferred_acceptance(
            market, profile, ExampleBConfig.config(ONE_AT_A_TIME_DECLARED_ORDER)
        )

        self.assertEqual(result_all.assignment, result_one.assignment)
        self.assertEqual(len(result_all.steps), 3)
        self.assertEqual(len(result_one.steps), 5)
        self.assertNotEqual(len(result_all.steps), len(result_one.steps))

    # ------------------------------------------------------------------
    # Example C: many-to-one, capacity 2
    # ------------------------------------------------------------------
    def test_example_c_many_to_one_capacity_two(self):
        """s1,s2,s3 rank (c1,c2); s4 ranks (c2,c1). c1 (capacity 2) prefers
        s4>s3>s2>s1; c2 (capacity 1) prefers s1>s2>s3>s4.
        Round 1: s1,s2,s3 -> c1 (c1 keeps top two by priority: s3,s2,
        rejects s1); s4 -> c2 (held).
        Round 2: s1 (rejected, next choice) -> c2; c2 prefers s1 over
        holder s4, so s4 is displaced.
        Round 3: s4 (rejected, next/last choice) -> c1; c1 prefers s4 over
        its worst current holder s2, so s2 is displaced.
        Round 4: s2 (rejected, next/last choice) -> c2; c2 prefers its
        holder s1 over s2, so s2 is rejected and now exhausted ->
        unmatched.
        Final: s1->c2, s2->None, s3->c1, s4->c1."""
        market = ExampleCConfig.market()
        profile = ExampleCConfig.profile()
        config = ExampleCConfig.config()
        result = deferred_acceptance(market, profile, config)

        self.assertEqual(len(result.steps), 4)
        self.assert_step(
            result.steps[0],
            index=1,
            proposals=(("s1", "c1"), ("s2", "c1"), ("s3", "c1"), ("s4", "c2")),
            rejected_by_competition=(("s1", "c1"),),
            holds_after=(("c1", ("s3", "s2")), ("c2", ("s4",))),
        )
        self.assert_step(
            result.steps[1],
            index=2,
            proposals=(("s1", "c2"),),
            rejected_by_competition=(("s4", "c2"),),
            holds_after=(("c1", ("s3", "s2")), ("c2", ("s1",))),
        )
        self.assert_step(
            result.steps[2],
            index=3,
            proposals=(("s4", "c1"),),
            rejected_by_competition=(("s2", "c1"),),
            holds_after=(("c1", ("s4", "s3")), ("c2", ("s1",))),
        )
        self.assert_step(
            result.steps[3],
            index=4,
            proposals=(("s2", "c2"),),
            rejected_by_competition=(("s2", "c2"),),
            holds_after=(("c1", ("s4", "s3")), ("c2", ("s1",))),
        )
        self.assertEqual(result.n_proposals, 7)

        self.assertEqual(
            result.assignment.student_to_school,
            {"s1": "c2", "s2": None, "s3": "c1", "s4": "c1"},
        )
        # c1's roster is in c1's priority order: s4 before s3.
        self.assertEqual(result.assignment.roster("c1"), ("s4", "s3"))
        self.assertEqual(result.assignment.roster("c2"), ("s1",))

    # ------------------------------------------------------------------
    # Example D: unlisted_student_policy changes the outcome
    # ------------------------------------------------------------------
    def test_example_d_unlisted_unacceptable(self):
        """s1 ranks (c1,c2); s2 ranks (c1,) only. c1 prefers s2>s1. c2's
        priority_classes list only s2 -- s1 is in NO class of c2.
        Round 1: s1,s2 -> c1; c1 keeps s2 (higher priority), rejects s1.
        Round 2: s1 (rejected, next choice) -> c2; under
        UNLISTED_UNACCEPTABLE, s1 is unacceptable to c2 (not just
        low-priority), so s1 is rejected_as_unacceptable, not held even
        though c2 has a free seat. Final: s1->None, s2->c1, roster
        c2=()."""
        market = ExampleDConfig.market()
        profile = ExampleDConfig.profile()
        config = ExampleDConfig.config(UNLISTED_UNACCEPTABLE)
        result = deferred_acceptance(market, profile, config)

        self.assertEqual(len(result.steps), 2)
        self.assert_step(
            result.steps[0],
            index=1,
            proposals=(("s1", "c1"), ("s2", "c1")),
            rejected_by_competition=(("s1", "c1"),),
            holds_after=(("c1", ("s2",)),),
        )
        self.assert_step(
            result.steps[1],
            index=2,
            proposals=(("s1", "c2"),),
            rejected_as_unacceptable=(("s1", "c2"),),
            holds_after=(("c1", ("s2",)),),
        )
        self.assertEqual(result.n_proposals, 3)

        self.assertEqual(
            result.assignment.student_to_school, {"s1": None, "s2": "c1"}
        )
        self.assertEqual(result.assignment.roster("c2"), ())

    def test_example_d_unlisted_lowest_class(self):
        """Same instance as above, but under UNLISTED_LOWEST_CLASS: c2's
        effective classes become (("s2",), ("s1",)) -- s1 joins one extra
        class below all declared classes. Round 2: s1 -> c2; now
        acceptable, and c2 has a free seat (capacity 1, currently empty),
        so s1 is held. Final: s1->c2, s2->c1, roster c2=("s1",) -- a
        DIFFERENT assignment from UNLISTED_UNACCEPTABLE."""
        market = ExampleDConfig.market()
        profile = ExampleDConfig.profile()
        config = ExampleDConfig.config(UNLISTED_LOWEST_CLASS)
        result = deferred_acceptance(market, profile, config)

        self.assertEqual(len(result.steps), 2)
        self.assert_step(
            result.steps[0],
            index=1,
            proposals=(("s1", "c1"), ("s2", "c1")),
            rejected_by_competition=(("s1", "c1"),),
            holds_after=(("c1", ("s2",)),),
        )
        self.assert_step(
            result.steps[1],
            index=2,
            proposals=(("s1", "c2"),),
            holds_after=(("c1", ("s2",)), ("c2", ("s1",))),
        )
        self.assertEqual(result.n_proposals, 3)

        self.assertEqual(
            result.assignment.student_to_school, {"s1": "c2", "s2": "c1"}
        )
        self.assertEqual(result.assignment.roster("c2"), ("s1",))

    def test_example_d_settings_disagree(self):
        """Direct side-by-side: the two unlisted_student_policy settings on
        the identical instance produce DIFFERENT final assignments, even
        though both take exactly the same number of proposals and steps."""
        market = ExampleDConfig.market()
        profile = ExampleDConfig.profile()

        result_unacceptable = deferred_acceptance(
            market, profile, ExampleDConfig.config(UNLISTED_UNACCEPTABLE)
        )
        result_lowest = deferred_acceptance(
            market, profile, ExampleDConfig.config(UNLISTED_LOWEST_CLASS)
        )

        self.assertNotEqual(result_unacceptable.assignment, result_lowest.assignment)
        self.assertEqual(
            result_unacceptable.assignment.student_to_school,
            {"s1": None, "s2": "c1"},
        )
        self.assertEqual(
            result_lowest.assignment.student_to_school,
            {"s1": "c2", "s2": "c1"},
        )
        self.assertEqual(result_unacceptable.n_proposals, 3)
        self.assertEqual(result_lowest.n_proposals, 3)
        self.assertEqual(len(result_unacceptable.steps), 2)
        self.assertEqual(len(result_lowest.steps), 2)

    # ------------------------------------------------------------------
    # Example E: edge cases
    # ------------------------------------------------------------------
    def test_example_e1_zero_capacity_rejects_everyone(self):
        """s1 ranks (c1,c2). c1 has capacity 0 -- s1's proposal to c1 is
        acceptable (c1's priority class lists s1) but is rejected purely by
        the capacity-0 competition rule (there is no seat to keep, so
        `keep` is empty and `drop` is everyone). This is recorded as
        rejected_by_competition, NOT as a separate 'no capacity' category --
        the implementation makes no such distinction. Round 2: s1 proposes
        to c2 (capacity 1) and is held. Final: s1->c2."""
        market = Market(
            students=("s1",),
            schools=("c1", "c2"),
            capacities={"c1": 0, "c2": 1},
            priority_classes={"c1": (("s1",),), "c2": (("s1",),)},
        )
        profile = Profile({"s1": ("c1", "c2")})
        config = DAConfig(tiebreak=RejectTies())
        result = deferred_acceptance(market, profile, config)

        self.assertEqual(len(result.steps), 2)
        self.assert_step(
            result.steps[0],
            index=1,
            proposals=(("s1", "c1"),),
            rejected_by_competition=(("s1", "c1"),),
            holds_after=(),
        )
        self.assert_step(
            result.steps[1],
            index=2,
            proposals=(("s1", "c2"),),
            holds_after=(("c2", ("s1",)),),
        )
        self.assertEqual(result.n_proposals, 2)

        self.assertEqual(result.assignment.student_to_school, {"s1": "c2"})
        self.assertEqual(result.assignment.roster("c1"), ())
        self.assertEqual(result.assignment.roster("c2"), ("s1",))

    def test_example_e2_empty_report_never_proposes(self):
        """s1 has an EMPTY report -- `next_choice[s1] < len(report[s1])` is
        `0 < 0`, false, so s1 is never a free proposer and ends unmatched
        without ever appearing in a proposals tuple. s2 ranks (c1,) and is
        held immediately (no competitor). Final: s1->None, s2->c1."""
        market = Market(
            students=("s1", "s2"),
            schools=("c1",),
            capacities={"c1": 1},
            priority_classes={"c1": (("s1",), ("s2",))},
        )
        profile = Profile({"s1": (), "s2": ("c1",)})
        config = DAConfig(tiebreak=RejectTies())
        result = deferred_acceptance(market, profile, config)

        self.assertEqual(len(result.steps), 1)
        self.assert_step(
            result.steps[0],
            index=1,
            proposals=(("s2", "c1"),),
            holds_after=(("c1", ("s2",)),),
        )
        self.assertEqual(result.n_proposals, 1)

        self.assertEqual(
            result.assignment.student_to_school, {"s1": None, "s2": "c1"}
        )

    # ------------------------------------------------------------------
    # Example F: determinism and replay
    # ------------------------------------------------------------------
    def _all_example_specs(self):
        """(market, profile, config) triples for every hand-worked example
        above, reused by the determinism/replay checks."""
        specs = [
            (ExampleAConfig.market(), ExampleAConfig.profile(), ExampleAConfig.config()),
            (
                ExampleBConfig.market(),
                ExampleBConfig.profile(),
                ExampleBConfig.config(ALL_FREE_SIMULTANEOUS),
            ),
            (
                ExampleBConfig.market(),
                ExampleBConfig.profile(),
                ExampleBConfig.config(ONE_AT_A_TIME_DECLARED_ORDER),
            ),
            (ExampleCConfig.market(), ExampleCConfig.profile(), ExampleCConfig.config()),
            (
                ExampleDConfig.market(),
                ExampleDConfig.profile(),
                ExampleDConfig.config(UNLISTED_UNACCEPTABLE),
            ),
            (
                ExampleDConfig.market(),
                ExampleDConfig.profile(),
                ExampleDConfig.config(UNLISTED_LOWEST_CLASS),
            ),
        ]
        return specs

    def test_f1_deterministic_across_repeated_runs(self):
        """Running deferred_acceptance twice on identical inputs gives
        equal Assignment objects, for every example above."""
        for market, profile, config in self._all_example_specs():
            with self.subTest(config=config.to_dict()):
                r1 = deferred_acceptance(market, profile, config)
                r2 = deferred_acceptance(market, profile, config)
                self.assertEqual(r1.assignment, r2.assignment)

    def test_f2_pre_resolved_priorities_match_self_resolved(self):
        """Passing a pre-resolved `priorities=` gives an identical result
        to letting DA resolve them itself."""
        for market, profile, config in self._all_example_specs():
            with self.subTest(config=config.to_dict()):
                priorities = resolve_priorities(market, config)
                r_auto = deferred_acceptance(market, profile, config)
                r_explicit = deferred_acceptance(
                    market, profile, config, priorities=priorities
                )
                self.assertEqual(r_auto.assignment, r_explicit.assignment)

    def test_f3_round_trip_through_dicts_reproduces_assignment(self):
        """Market.to_dict()/from_dict, Profile.to_dict()/from_dict,
        DAConfig.to_dict()/from_dict, then re-running DA gives an identical
        Assignment, and content_hash of the assignment dict is unchanged."""
        for market, profile, config in self._all_example_specs():
            with self.subTest(config=config.to_dict()):
                original = deferred_acceptance(market, profile, config)
                original_hash = content_hash(original.assignment.to_dict())

                market2 = Market.from_dict(market.to_dict())
                profile2 = Profile.from_dict(profile.to_dict())
                config2 = DAConfig.from_dict(config.to_dict())

                replayed = deferred_acceptance(market2, profile2, config2)
                replayed_hash = content_hash(replayed.assignment.to_dict())

                self.assertEqual(original.assignment, replayed.assignment)
                self.assertEqual(original_hash, replayed_hash)

    def test_f4_cross_process_replay_of_example_c(self):
        """Rebuild Example C from its dict form in a FRESH subprocess and
        print canonical_json of the resulting assignment; assert it equals
        the in-process value. This is the strongest determinism check: no
        shared Python process state, no import caching, nothing but the
        serialized dict form."""
        market = ExampleCConfig.market()
        profile = ExampleCConfig.profile()
        config = ExampleCConfig.config()
        in_process = deferred_acceptance(market, profile, config)
        in_process_json = canonical_json(in_process.assignment.to_dict())

        market_json = canonical_json(market.to_dict())
        profile_json = canonical_json(profile.to_dict())
        config_json = canonical_json(config.to_dict())

        script = f"""
import json
from witness.core import Market, Profile, canonical_json
from witness.da import DAConfig, deferred_acceptance

market = Market.from_dict(json.loads({market_json!r}))
profile = Profile.from_dict(json.loads({profile_json!r}))
config = DAConfig.from_dict(json.loads({config_json!r}))

result = deferred_acceptance(market, profile, config)
print(canonical_json(result.assignment.to_dict()))
"""
        proc = subprocess.run(
            [sys.executable, "-c", script],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        out_process_json = proc.stdout.strip()
        self.assertEqual(out_process_json, in_process_json)

    # ------------------------------------------------------------------
    # Example G: lottery tiebreak
    # ------------------------------------------------------------------
    def _lottery_market(self) -> Market:
        students = ("s1", "s2", "s3", "s4")
        schools = ("c1", "c2")
        all_in_one_class = (students,)
        return Market(
            students=students,
            schools=schools,
            capacities={"c1": 1, "c2": 1},
            priority_classes={c: all_in_one_class for c in schools},
        )

    def test_g1_single_lottery_same_order_at_every_school(self):
        """SingleLotteryTiebreak (STB) uses GLOBAL_SCOPE for every school's
        draw, so c1 and c2 -- each a single priority class containing all
        of s1..s4 -- resolve to the SAME order."""
        market = self._lottery_market()
        config = MechanismConfig(tiebreak=SingleLotteryTiebreak(seed="witness-test-seed"))
        priorities = resolve_priorities(market, config)
        self.assertEqual(priorities.orders["c1"], priorities.orders["c2"])

    def test_g2_multiple_lottery_different_order_per_school(self):
        """MultipleLotteryTiebreak (MTB) scopes the draw by school id, so
        c1 and c2 get independent draws of the same seed and (for this
        seed) resolve to DIFFERENT orders.

        Verified directly: lottery_order("witness-test-seed", "c1", ...)
        and lottery_order("witness-test-seed", "c2", ...) already differ,
        so no seed search was needed -- this is a property of the seed
        "witness-test-seed" itself, confirmed by running the derivation
        once and inspecting the output."""
        market = self._lottery_market()
        config = MechanismConfig(tiebreak=MultipleLotteryTiebreak(seed="witness-test-seed"))
        priorities = resolve_priorities(market, config)
        self.assertNotEqual(priorities.orders["c1"], priorities.orders["c2"])

    def test_g3_golden_value_regression_lock(self):
        """GOLDEN VALUE: lottery_order("witness-test-seed", "*GLOBAL*",
        ("s1","s2","s3","s4")) computed once by running the derivation and
        hardcoded here as a regression lock. This value was GENERATED, not
        hand-derived from the SHA-256 construction -- its only job is to
        catch a silent change to `lottery_key`/`lottery_order`'s
        derivation (e.g. an accidental change to LOTTERY_DOMAIN, the
        secondary sort key, or the hash algorithm) in a future edit."""
        result = lottery_order(
            "witness-test-seed", GLOBAL_SCOPE, ("s1", "s2", "s3", "s4")
        )
        self.assertEqual(result, ("s4", "s3", "s2", "s1"))

    def test_g4_golden_value_matches_across_process(self):
        """The same golden value, computed in a FRESH subprocess, matches
        the in-process value -- confirming the derivation depends on
        nothing but the (seed, scope, students) triple, not on process
        state."""
        script = """
from witness.tiebreak import GLOBAL_SCOPE, lottery_order
print(lottery_order("witness-test-seed", GLOBAL_SCOPE, ("s1", "s2", "s3", "s4")))
"""
        proc = subprocess.run(
            [sys.executable, "-c", script],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertEqual(
            proc.stdout.strip(), repr(("s4", "s3", "s2", "s1"))
        )

    def test_g5_reject_ties_raises_on_multi_member_class(self):
        """RejectTies refuses to order a priority class with 2+ members: it
        raises TieError rather than silently picking an order."""
        market = Market(
            students=("s1", "s2"),
            schools=("c1",),
            capacities={"c1": 1},
            priority_classes={"c1": (("s1", "s2"),)},
        )
        config = MechanismConfig(tiebreak=RejectTies())
        with self.assertRaises(TieError):
            resolve_priorities(market, config)


if __name__ == "__main__":
    unittest.main()
