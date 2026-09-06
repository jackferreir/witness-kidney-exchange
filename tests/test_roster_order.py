"""Regression + convention tests for `witness.da.build_assignment`'s roster
ordering rule.

BACKGROUND: `build_assignment` used to build every roster with
    sorted(members, key=lambda s: priorities.rank(c, s))
unconditionally. `ResolvedPriorities.rank` returns `None` for a student a
school finds unacceptable, and `sorted()` raises `TypeError` the moment it
has to compare two `None`s (or a `None` against an `int`) -- which happens
exactly when a school ends up holding TWO OR MORE students it finds
unacceptable. Under Boston with `placement="on"` and
`placement_acceptability="ignored"`, administrative placement deliberately
produces exactly that: it fills leftover seats by capacity alone, acceptability
overridden.

BOS-F and BOS-G in `test_boston_handworked.py` both exercise
`placement_acceptability="ignored"`, but in neither instance does a single
school's placement targets ever collect two unranked students at once (BOS-F
spreads s2/s3 across c2 and c3; BOS-G places only one student at all), so
`sorted()` there never has to compare two `None`s together. Those tests pass
"by coincidence" -- they never invoke the buggy comparison. This file adds the
case they could not reach.

THE FIX (see `build_assignment`'s docstring in `witness/da.py`): the signature
gained an explicit `allow_unranked: bool = False` keyword. The default keeps
today's strict behavior (raise `MechanismError` naming the student and school
the moment ANY assigned student is unranked at their school -- DA must never
produce that, so it fails loudly). `allow_unranked=True` is the declared
opt-in for the one legitimate case (Boston placement, acceptability ignored):
ranked students first in ascending priority rank, then unranked students in
`Market.students` declared order. Boston's `boston_immediate_acceptance` only
ever passes `allow_unranked=True` when
`config.placement == "on" and config.placement_acceptability == "ignored"`.
"""

from __future__ import annotations

import inspect
import unittest

from witness.boston import (
    ACCEPTABILITY_BINDS,
    ACCEPTABILITY_IGNORED,
    PLACEMENT_ON,
    BostonConfig,
    boston_immediate_acceptance,
)
from witness.core import Market, MechanismConfig, Profile, ResolvedPriorities, resolve_priorities
from witness.da import DAConfig, build_assignment, deferred_acceptance
from witness.errors import MechanismError
from witness.oracles import is_individually_rational
from witness.tiebreak import RejectTies


def _singleton_classes(order):
    return tuple((s,) for s in order)


def _repro_market(students=("s1", "s2", "s3")):
    """The minimal reproduction from the bug report: c1 has 1 seat and a
    strict priority s1>s2>s3; c2 has 2 seats and only s1 acceptable to it.
    Every student reports only c1."""
    market = Market(
        students=students,
        schools=("c1", "c2"),
        capacities={"c1": 1, "c2": 2},
        priority_classes={
            "c1": _singleton_classes(("s1", "s2", "s3")),
            "c2": (("s1",),),  # s2, s3 unlisted -> unacceptable at c2
        },
    )
    profile = Profile({s: ("c1",) for s in students})
    return market, profile


class RosterOrderRegressionTestCase(unittest.TestCase):
    # ------------------------------------------------------------------
    # REGRESSION: the minimal repro no longer raises TypeError
    # ------------------------------------------------------------------
    def test_repro_no_longer_raises_and_matches_hand_worked_result(self):
        """Hand-worked expectation:

        Round 1: s1, s2, s3 all propose to c1 (their only reported choice).
        c1 has 1 seat, priority s1>s2>s3 -> c1 accepts s1, rejects s2 and s3
        by competition (FINAL).
        Round 2: s2 and s3 have exhausted lists (only ranked c1) -> no
        proposers; rounds end. Leftover: c2 has 2 seats, 0 taken.

        placement="on", placement_acceptability="ignored": unmatched students,
        in declared order (s2 then s3), scan schools in declared order
        (c1, c2). c1 has 0 remaining seats -> skip. c2 has 2 remaining seats,
        acceptability overridden -> both s2 and s3 placed at c2.

        Final: s1->c1, s2->c2, s3->c2. c2 now holds TWO students it finds
        unacceptable (s2 and s3 are both unlisted at c2) -- this is exactly
        the case BOS-F and BOS-G in test_boston_handworked.py could never
        reach, because their placement targets never left a single school
        holding two unranked students at once. By the declared convention
        (ranked students first by rank, then unranked students in
        Market.students order), c2's roster is exactly ("s2", "s3") --
        Market.students declared order, since neither is ranked at c2.
        """
        market, profile = _repro_market(("s1", "s2", "s3"))
        config = BostonConfig(
            tiebreak=RejectTies(),
            mechanism="boston_immediate_acceptance",
            placement=PLACEMENT_ON,
            placement_acceptability=ACCEPTABILITY_IGNORED,
        )

        result = boston_immediate_acceptance(market, profile, config)

        self.assertEqual(
            result.assignment.student_to_school,
            {"s1": "c1", "s2": "c2", "s3": "c2"},
        )
        self.assertEqual(result.assignment.roster("c1"), ("s1",))
        # Assert the roster tuple EXACTLY, not just the student_to_school map.
        self.assertEqual(result.assignment.roster("c2"), ("s2", "s3"))
        self.assertEqual(result.placements, (("s2", "c2"), ("s3", "c2")))
        self.assertEqual(result.placement_unplaced, ())

    # ------------------------------------------------------------------
    # ORDERING IS DECLARED, NOT INCIDENTAL
    # ------------------------------------------------------------------
    def test_unranked_roster_order_follows_declared_student_order(self):
        """Rebuild the identical market/profile/config from the regression
        test above, but with Market.students declared in the REVERSE order,
        ("s3", "s2", "s1") instead of ("s1", "s2", "s3").

        c1's priority (s1>s2>s3) and every school's acceptability are
        unaffected by Market.students order -- they come from
        `priority_classes`, a separate field. So round 1 still seats s1 at
        c1 and rejects s2, s3 by competition; placement still finds c2 has 2
        free, acceptability-overridden seats.

        What DOES change: placement now iterates unmatched students in
        ("s3", "s2", "s1") order, i.e. s3 before s2. Under the declared rule,
        c2's roster (both unranked there) follows Market.students order, so
        it comes out ("s3", "s2") -- the EXACT REVERSE of the previous test.
        This is the proof that the rule is the declared order and would fail
        under any incidental (e.g. insertion, or hash-based) ordering.
        """
        market, profile = _repro_market(("s3", "s2", "s1"))
        config = BostonConfig(
            tiebreak=RejectTies(),
            mechanism="boston_immediate_acceptance",
            placement=PLACEMENT_ON,
            placement_acceptability=ACCEPTABILITY_IGNORED,
        )

        result = boston_immediate_acceptance(market, profile, config)

        self.assertEqual(
            result.assignment.student_to_school,
            {"s1": "c1", "s2": "c2", "s3": "c2"},
        )
        self.assertEqual(result.assignment.roster("c2"), ("s3", "s2"))

    # ------------------------------------------------------------------
    # MIXED roster: ranked student first, regardless of declared order
    # ------------------------------------------------------------------
    def test_mixed_roster_puts_ranked_student_first_regardless_of_declared_order(self):
        """Build, by hand, a single school c1 with capacity 2 whose priority
        classes list only "ranked" as acceptable ("unranked" is unlisted, so
        unacceptable under the default unlisted_student_policy). Declare
        Market.students as ("unranked", "ranked") -- UNRANKED FIRST -- so
        that if roster order were naively "declared student order" for
        unranked entries mixed with ranked ones, or if the ranked/unranked
        split were not enforced, "unranked" could end up first.

        The declared rule says otherwise: ranked students come first (by
        ascending priority rank) UNCONDITIONALLY, then unranked students in
        declared order. With only one of each, the roster must be
        ("ranked", "unranked") even though Market.students lists "unranked"
        first.
        """
        market = Market(
            students=("unranked", "ranked"),
            schools=("c1",),
            capacities={"c1": 2},
            priority_classes={"c1": (("ranked",),)},  # "unranked" unlisted
        )
        config = MechanismConfig(tiebreak=RejectTies())
        priorities = resolve_priorities(market, config)
        self.assertIsNotNone(priorities.rank("c1", "ranked"))
        self.assertIsNone(priorities.rank("c1", "unranked"))

        assignment = build_assignment(
            market,
            priorities,
            {"unranked": "c1", "ranked": "c1"},
            allow_unranked=True,
        )

        self.assertEqual(assignment.roster("c1"), ("ranked", "unranked"))

    # ------------------------------------------------------------------
    # STRICT DEFAULT: build_assignment(allow_unranked=False) raises
    # ------------------------------------------------------------------
    def test_strict_default_raises_mechanism_error_naming_student_and_school(self):
        """With the default `allow_unranked=False`, handing build_assignment
        a student_to_school map that assigns an unacceptable student to a
        school must raise MechanismError, and the message must name both the
        student and the school."""
        market = Market(
            students=("s1", "s2"),
            schools=("c1",),
            capacities={"c1": 2},
            priority_classes={"c1": (("s1",),)},  # s2 unlisted -> unacceptable
        )
        config = MechanismConfig(tiebreak=RejectTies())
        priorities = resolve_priorities(market, config)
        self.assertIsNone(priorities.rank("c1", "s2"))

        with self.assertRaises(MechanismError) as ctx:
            build_assignment(market, priorities, {"s1": "c1", "s2": "c1"})

        message = str(ctx.exception)
        self.assertIn("s2", message)
        self.assertIn("c1", message)

    # ------------------------------------------------------------------
    # DA UNCHANGED: still strict, never passes allow_unranked=True
    # ------------------------------------------------------------------
    def test_da_still_strict_and_never_passes_allow_unranked_true(self):
        """deferred_acceptance must keep using build_assignment's strict
        default. Two checks:

          1. Behaviorally: run DA on an ordinary market where nothing is
             unacceptable-but-held, and confirm it completes without error.
          2. Structurally: inspect deferred_acceptance's own source and
             confirm it never spells out `allow_unranked=True` -- DA calls
             build_assignment with no allow_unranked argument at all, which
             keeps the strict False default.
        """
        market = Market(
            students=("s1", "s2"),
            schools=("c1", "c2"),
            capacities={"c1": 1, "c2": 1},
            priority_classes={
                "c1": _singleton_classes(("s1", "s2")),
                "c2": _singleton_classes(("s2", "s1")),
            },
        )
        profile = Profile({"s1": ("c1", "c2"), "s2": ("c2", "c1")})
        result = deferred_acceptance(market, profile, DAConfig(tiebreak=RejectTies()))
        self.assertEqual(
            result.assignment.student_to_school, {"s1": "c1", "s2": "c2"}
        )

        source = inspect.getsource(deferred_acceptance)
        self.assertNotIn("allow_unranked=True", source)

    # ------------------------------------------------------------------
    # IR ORACLE: still reports the unacceptable-hold violation
    # ------------------------------------------------------------------
    def test_ir_oracle_still_reports_unacceptable_hold_for_repro_result(self):
        """Placement breaking individual rationality is by design (see
        witness/boston.py's module docstring); the IR oracle must still
        detect it for the fixed repro's final assignment -- both s2 and s3
        are held by c2, which finds them unacceptable."""
        market, profile = _repro_market(("s1", "s2", "s3"))
        config = BostonConfig(
            tiebreak=RejectTies(),
            mechanism="boston_immediate_acceptance",
            placement=PLACEMENT_ON,
            placement_acceptability=ACCEPTABILITY_IGNORED,
        )
        result = boston_immediate_acceptance(market, profile, config)

        ir_ok, ir_reasons = is_individually_rational(
            market, profile, result.priorities, result.assignment
        )
        self.assertFalse(ir_ok)
        joined = " | ".join(ir_reasons)
        self.assertIn("c2", joined)
        self.assertIn("s2", joined)
        self.assertIn("s3", joined)
        self.assertIn("unacceptable", joined)


if __name__ == "__main__":
    unittest.main()
