"""Hand-worked examples for the Boston / immediate-acceptance mechanism.

Every expected value in this file was computed by hand on paper AND
independently confirmed against a trace dump of
`witness.boston.boston_immediate_acceptance`. DO NOT change any expected
value to make a test pass: a failure here is a real finding about the
implementation, not something to paper over.

Every test asserts on BOTH the final assignment AND the recorded round trace
(proposals, all three rejection categories, accepted, seats_remaining_after)
so that a wrong rejection category or an off-by-one in remaining capacity
still gets caught even when the final matching happens to coincide.

Unless stated otherwise: BostonConfig(tiebreak=RejectTies()),
unlisted_student_policy=UNLISTED_UNACCEPTABLE (the MechanismConfig default),
placement=PLACEMENT_OFF. Priority classes are tuples of singletons (no ties
ever need breaking).
"""

from __future__ import annotations

import unittest

from witness.boston import (
    ACCEPTABILITY_BINDS,
    ACCEPTABILITY_IGNORED,
    PLACEMENT_OFF,
    PLACEMENT_ON,
    BostonConfig,
    boston_immediate_acceptance,
)
from witness.core import Market, MechanismConfig, Profile, strictly_prefers
from witness.da import DAConfig, deferred_acceptance
from witness.errors import ModelError
from witness.oracles import blocking_pairs, is_individually_rational, is_stable
from witness.tiebreak import RejectTies


def _singleton_classes(order: tuple[str, ...]) -> tuple[tuple[str, ...], ...]:
    """Turn a fully-strict order into singleton priority classes -- the shape
    Market.priority_classes expects."""
    return tuple((s,) for s in order)


class BostonHandworkedTestCase(unittest.TestCase):
    def assert_round(
        self,
        rd,
        *,
        index,
        proposals,
        rejected_as_unacceptable=(),
        rejected_as_full=(),
        rejected_by_competition=(),
        accepted,
        seats_remaining_after,
    ):
        self.assertEqual(rd.index, index)
        self.assertEqual(rd.proposals, proposals)
        self.assertEqual(rd.rejected_as_unacceptable, rejected_as_unacceptable)
        self.assertEqual(rd.rejected_as_full, rejected_as_full)
        self.assertEqual(rd.rejected_by_competition, rejected_by_competition)
        self.assertEqual(rd.accepted, accepted)
        self.assertEqual(rd.seats_remaining_after, seats_remaining_after)

    # ------------------------------------------------------------------
    # BOS-A: Boston differs from DA, and is unstable
    # ------------------------------------------------------------------
    def test_bos_a_differs_from_da_and_is_unstable(self):
        """students s1,s2,s3; schools c1,c2; caps 1,1.
        priorities c1: s3>s1>s2   c2: s1>s2>s3
        reports s1:(c1,c2)  s2:(c2,c1)  s3:(c1,c2)

        Round 1: everyone proposes to their first choice: s1->c1, s2->c2,
        s3->c1. c1's proposers are {s1,s3}; s3 outranks s1, so c1 accepts s3
        and rejects s1 by competition (FINAL -- s1 never gets another shot at
        c1). c2's only proposer s2 is accepted.
        Round 2: s1 (rejected, next choice) proposes to c2; c2 has 0
        remaining seats, so s1 is rejected_as_full, not rejected by
        competition -- c2 never even compares priorities.
        s1's list is now exhausted; no one proposes; rounds end.

        Final: s1->None, s2->c2, s3->c1. This DISAGREES with student-proposing
        DA on the identical instance (DA gives s1->c2, s2->None, s3->c1) --
        that disagreement is the entire point of Boston. Boston's outcome is
        also NOT stable: (s1, c2) blocks it (s1 strictly prefers c2 to being
        unmatched, and c2 -- unaware s1 ever wanted it, because c2 was
        already full when s1 got there -- would in fact prefer s1 over its
        holder s2, since c2's own priority ranks s1 above s2). Boston's
        immediate, irrevocable acceptance is exactly what produces this
        blocking pair; DA's deferred acceptance would have let s1 displace
        s2 at c2.

        Placement is INERT here: caps sum to 2, exactly the number of seats
        needed, no seats are ever left over, so placement="on" changes
        nothing.
        """
        market = Market(
            students=("s1", "s2", "s3"),
            schools=("c1", "c2"),
            capacities={"c1": 1, "c2": 1},
            priority_classes={
                "c1": _singleton_classes(("s3", "s1", "s2")),
                "c2": _singleton_classes(("s1", "s2", "s3")),
            },
        )
        profile = Profile(
            {"s1": ("c1", "c2"), "s2": ("c2", "c1"), "s3": ("c1", "c2")}
        )
        config = BostonConfig(tiebreak=RejectTies())
        result = boston_immediate_acceptance(market, profile, config)

        self.assertEqual(len(result.rounds), 2)
        self.assert_round(
            result.rounds[0],
            index=1,
            proposals=(("s1", "c1"), ("s2", "c2"), ("s3", "c1")),
            rejected_by_competition=(("s1", "c1"),),
            accepted=(("s3", "c1"), ("s2", "c2")),
            seats_remaining_after=(("c1", 0), ("c2", 0)),
        )
        self.assert_round(
            result.rounds[1],
            index=2,
            proposals=(("s1", "c2"),),
            rejected_as_full=(("s1", "c2"),),
            accepted=(),
            seats_remaining_after=(("c1", 0), ("c2", 0)),
        )
        self.assertEqual(result.n_proposals, 4)
        self.assertEqual(
            result.assignment.student_to_school,
            {"s1": None, "s2": "c2", "s3": "c1"},
        )

        da_config = DAConfig(tiebreak=RejectTies())
        da_result = deferred_acceptance(market, profile, da_config)
        self.assertEqual(
            da_result.assignment.student_to_school,
            {"s1": "c2", "s2": None, "s3": "c1"},
        )
        self.assertNotEqual(
            result.assignment.student_to_school,
            da_result.assignment.student_to_school,
        )

        ir_ok, ir_reasons = is_individually_rational(
            market, profile, result.priorities, result.assignment
        )
        self.assertTrue(ir_ok, ir_reasons)
        pairs = blocking_pairs(market, profile, result.priorities, result.assignment)
        self.assertEqual(pairs, (("s1", "c2"),))
        self.assertFalse(is_stable(market, profile, result.priorities, result.assignment))

        config_on = BostonConfig(tiebreak=RejectTies(), placement=PLACEMENT_ON)
        result_on = boston_immediate_acceptance(market, profile, config_on)
        self.assertEqual(
            result_on.assignment.student_to_school,
            result.assignment.student_to_school,
        )

    # ------------------------------------------------------------------
    # BOS-B: the textbook manipulation
    # ------------------------------------------------------------------
    def test_bos_b_textbook_manipulation(self):
        """Same market as BOS-A. s1 misreports (c2,c1) instead of truthful
        (c1,c2); s2 and s3 report truthfully.

        Round 1: s1->c2, s2->c2, s3->c1. c1 accepts its only proposer s3.
        c2's proposers are {s1,s2}; c2's priority ranks s1 first, so c2
        accepts s1 and rejects s2 by competition (FINAL).
        Round 2: s2 (rejected, next choice) proposes to c1; c1 has 0
        remaining seats -> rejected_as_full. s2's list is exhausted; rounds
        end.

        Final: s1->c2, s2->None, s3->c1. By s1's TRUTHFUL preferences
        (c1,c2), c2 is s1's second choice and is still strictly better than
        being unmatched (BOS-A's truthful outcome for s1). So s1 strictly
        gains by misreporting -- the textbook Boston manipulation: rank a
        school where you have low priority ABOVE your true first choice,
        because Boston's immediate acceptance means being late to a
        first-choice school you cannot win costs you the seat you could have
        won elsewhere.
        """
        market = Market(
            students=("s1", "s2", "s3"),
            schools=("c1", "c2"),
            capacities={"c1": 1, "c2": 1},
            priority_classes={
                "c1": _singleton_classes(("s3", "s1", "s2")),
                "c2": _singleton_classes(("s1", "s2", "s3")),
            },
        )
        profile = Profile(
            {"s1": ("c2", "c1"), "s2": ("c2", "c1"), "s3": ("c1", "c2")}
        )
        config = BostonConfig(tiebreak=RejectTies())
        result = boston_immediate_acceptance(market, profile, config)

        self.assertEqual(len(result.rounds), 2)
        self.assert_round(
            result.rounds[0],
            index=1,
            proposals=(("s1", "c2"), ("s2", "c2"), ("s3", "c1")),
            rejected_by_competition=(("s2", "c2"),),
            accepted=(("s3", "c1"), ("s1", "c2")),
            seats_remaining_after=(("c1", 0), ("c2", 0)),
        )
        self.assert_round(
            result.rounds[1],
            index=2,
            proposals=(("s2", "c1"),),
            rejected_as_full=(("s2", "c1"),),
            accepted=(),
            seats_remaining_after=(("c1", 0), ("c2", 0)),
        )
        self.assertEqual(
            result.assignment.student_to_school,
            {"s1": "c2", "s2": None, "s3": "c1"},
        )

        # s1's truthful report is (c1, c2); BOS-A's truthful outcome for s1
        # was None. s1 strictly prefers this misreport's outcome (c2).
        self.assertTrue(strictly_prefers(("c1", "c2"), "c2", None))

    # ------------------------------------------------------------------
    # BOS-C: no contention, Boston == DA
    # ------------------------------------------------------------------
    def test_bos_c_no_contention_matches_da(self):
        """students s1,s2; schools c1,c2; caps 1,1.
        priorities c1: s1>s2   c2: s2>s1
        reports s1:(c1,c2)  s2:(c2,c1)

        Round 1: s1->c1, s2->c2; each is the sole proposer at their school,
        both accepted immediately. No contention anywhere, so Boston's
        immediate acceptance and DA's deferred acceptance necessarily agree.
        Final: s1->c1, s2->c2.
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
        config = BostonConfig(tiebreak=RejectTies())
        result = boston_immediate_acceptance(market, profile, config)

        self.assertEqual(len(result.rounds), 1)
        self.assert_round(
            result.rounds[0],
            index=1,
            proposals=(("s1", "c1"), ("s2", "c2")),
            accepted=(("s1", "c1"), ("s2", "c2")),
            seats_remaining_after=(("c1", 0), ("c2", 0)),
        )
        self.assertEqual(result.n_proposals, 2)
        self.assertEqual(
            result.assignment.student_to_school, {"s1": "c1", "s2": "c2"}
        )

        da_result = deferred_acceptance(market, profile, DAConfig(tiebreak=RejectTies()))
        self.assertEqual(
            da_result.assignment.student_to_school,
            result.assignment.student_to_school,
        )

    # ------------------------------------------------------------------
    # BOS-D: capacity 2, irrevocability
    # ------------------------------------------------------------------
    def test_bos_d_capacity_two_irrevocable(self):
        """students s1..s4; schools c1,c2; caps c1=2, c2=1.
        priorities c1: s4>s3>s2>s1   c2: s1>s2>s3>s4
        reports s1:(c1,c2) s2:(c1,c2) s3:(c1,c2) s4:(c2,c1)

        Round 1: s1,s2,s3 -> c1; s4 -> c2. c1 (2 seats) keeps its top two
        proposers by priority, s3 and s2, and rejects s1 by competition
        (FINAL -- no later round can revisit this, unlike DA where a later
        proposal to c2 that fails would send s1 back to try c1 again). c2
        accepts its sole proposer s4.
        Round 2: s1 (rejected, next choice) -> c2; c2 has 0 remaining seats
        -> rejected_as_full. s1 exhausted; rounds end.

        Final: s1->None, s2->c1, s3->c1, s4->c2. Roster of c1, in c1's
        priority order, is (s3, s2).

        Cross-check against DA on the IDENTICAL instance: DA gives
        s1->c2, s2->None, s3->c1, s4->c1 -- s4 ends up DISPLACING s2 out of
        c1 in DA (since c1 prefers s4 to s2, and DA lets that displacement
        happen once s4 is rejected from c2). Boston never lets that happen:
        s2 was accepted by c1 in round 1 and that acceptance is final, even
        though s4 (whom c1 prefers) proposes to c1 one round later. This is
        exactly the "no take-backs" property that distinguishes Boston from
        DA.
        """
        market = Market(
            students=("s1", "s2", "s3", "s4"),
            schools=("c1", "c2"),
            capacities={"c1": 2, "c2": 1},
            priority_classes={
                "c1": _singleton_classes(("s4", "s3", "s2", "s1")),
                "c2": _singleton_classes(("s1", "s2", "s3", "s4")),
            },
        )
        profile = Profile(
            {
                "s1": ("c1", "c2"),
                "s2": ("c1", "c2"),
                "s3": ("c1", "c2"),
                "s4": ("c2", "c1"),
            }
        )
        config = BostonConfig(tiebreak=RejectTies())
        result = boston_immediate_acceptance(market, profile, config)

        self.assertEqual(len(result.rounds), 2)
        self.assert_round(
            result.rounds[0],
            index=1,
            proposals=(("s1", "c1"), ("s2", "c1"), ("s3", "c1"), ("s4", "c2")),
            rejected_by_competition=(("s1", "c1"),),
            accepted=(("s3", "c1"), ("s2", "c1"), ("s4", "c2")),
            seats_remaining_after=(("c1", 0), ("c2", 0)),
        )
        self.assert_round(
            result.rounds[1],
            index=2,
            proposals=(("s1", "c2"),),
            rejected_as_full=(("s1", "c2"),),
            accepted=(),
            seats_remaining_after=(("c1", 0), ("c2", 0)),
        )
        self.assertEqual(
            result.assignment.student_to_school,
            {"s1": None, "s2": "c1", "s3": "c1", "s4": "c2"},
        )
        self.assertEqual(result.assignment.roster("c1"), ("s3", "s2"))

        da_result = deferred_acceptance(market, profile, DAConfig(tiebreak=RejectTies()))
        self.assertEqual(
            da_result.assignment.student_to_school,
            {"s1": "c2", "s2": None, "s3": "c1", "s4": "c1"},
        )

    # ------------------------------------------------------------------
    # BOS-E: a school with seats left accepts in a later round
    # ------------------------------------------------------------------
    def test_bos_e_later_round_fills_open_seat(self):
        """students s1,s2; schools c1,c2; caps 1,1.
        priorities c1: s1>s2   c2: s1>s2
        reports s1:(c1,c2)  s2:(c1,c2)

        Round 1: both propose to c1; c1 accepts s1 (higher priority),
        rejects s2 by competition.
        Round 2: s2 (rejected, next choice) proposes to c2; c2 has its full
        capacity available (no one has proposed to it yet) and s2 is its
        only proposer, so s2 is accepted.

        Final: s1->c1, s2->c2. No contention ever reaches c2, so this
        agrees with DA on the identical instance.
        """
        market = Market(
            students=("s1", "s2"),
            schools=("c1", "c2"),
            capacities={"c1": 1, "c2": 1},
            priority_classes={
                "c1": _singleton_classes(("s1", "s2")),
                "c2": _singleton_classes(("s1", "s2")),
            },
        )
        profile = Profile({"s1": ("c1", "c2"), "s2": ("c1", "c2")})
        config = BostonConfig(tiebreak=RejectTies())
        result = boston_immediate_acceptance(market, profile, config)

        self.assertEqual(len(result.rounds), 2)
        self.assert_round(
            result.rounds[0],
            index=1,
            proposals=(("s1", "c1"), ("s2", "c1")),
            rejected_by_competition=(("s2", "c1"),),
            accepted=(("s1", "c1"),),
            seats_remaining_after=(("c1", 0), ("c2", 1)),
        )
        self.assert_round(
            result.rounds[1],
            index=2,
            proposals=(("s2", "c2"),),
            accepted=(("s2", "c2"),),
            seats_remaining_after=(("c1", 0), ("c2", 0)),
        )
        self.assertEqual(
            result.assignment.student_to_school, {"s1": "c1", "s2": "c2"}
        )

        da_result = deferred_acceptance(market, profile, DAConfig(tiebreak=RejectTies()))
        self.assertEqual(
            da_result.assignment.student_to_school,
            result.assignment.student_to_school,
        )

    # ------------------------------------------------------------------
    # BOS-F: under-subscribed, placement branch LIVE
    # ------------------------------------------------------------------
    def _bos_f_market_and_profile(self, students):
        market = Market(
            students=students,
            schools=("c1", "c2", "c3"),
            capacities={"c1": 1, "c2": 1, "c3": 2},
            priority_classes={
                "c1": _singleton_classes(("s1", "s2", "s3")),
                "c2": (("s1",),),  # s2, s3 unlisted -> unacceptable at c2
                "c3": _singleton_classes(("s1", "s2", "s3")),
            },
        )
        profile = Profile({s: ("c1",) for s in students})
        return market, profile

    def test_bos_f_placement_off(self):
        """students s1,s2,s3; schools c1,c2,c3; caps c1=1,c2=1,c3=2 (4 seats,
        3 students -- under-subscribed overall). priorities c1: s1>s2>s3;
        c2: only s1 listed (s2,s3 UNACCEPTABLE under unlisted_student_policy
        ="unacceptable"); c3: s1>s2>s3. Everyone's report is (c1,) only.

        Round 1: all three propose to c1; c1 (1 seat) accepts s1, rejects
        s2 and s3 by competition, in that priority order.
        Round 2: s2 and s3 have exhausted lists (only ranked c1) -> no
        proposers; rounds end. Leftover seats: c2=1, c3=2.

        placement="off": leftover seats are never touched. Final:
        s1->c1, s2->None, s3->None.
        """
        market, profile = self._bos_f_market_and_profile(("s1", "s2", "s3"))
        config = BostonConfig(tiebreak=RejectTies())
        result = boston_immediate_acceptance(market, profile, config)

        self.assertEqual(len(result.rounds), 1)
        self.assert_round(
            result.rounds[0],
            index=1,
            proposals=(("s1", "c1"), ("s2", "c1"), ("s3", "c1")),
            rejected_by_competition=(("s2", "c1"), ("s3", "c1")),
            accepted=(("s1", "c1"),),
            seats_remaining_after=(("c1", 0), ("c2", 1), ("c3", 2)),
        )
        self.assertEqual(
            result.assignment.student_to_school,
            {"s1": "c1", "s2": None, "s3": None},
        )
        self.assertEqual(result.placements, ())
        self.assertEqual(result.placement_unplaced, ())

    def test_bos_f_placement_on_binds(self):
        """Same instance as test_bos_f_placement_off, but placement="on" with
        placement_acceptability="binds". Unmatched students, in declared
        order (s2 then s3), scan schools in declared order (c1,c2,c3):

          s2: c1 has 0 remaining seats -> skip. c2 has a seat, but s2 is
              unacceptable to c2 (unlisted) and acceptability BINDS -> skip.
              c3 has 2 seats and s2 IS acceptable there -> s2 placed at c3.
          s3: c1 skip (full). c2 skip (s3 unacceptable there too). c3 now
              has 1 seat left and s3 is acceptable -> s3 placed at c3.

        Final: s1->c1, s2->c3, s3->c3. placements == (("s2","c3"),
        ("s3","c3")), placement_unplaced == (). Placement seats a student at
        a school absent from their own report (report was (c1,) only), which
        is expected to break individual rationality -- that is asserted
        directly (placement breaks IR BY DESIGN, per the module docstring),
        naming both s2 and s3.
        """
        market, profile = self._bos_f_market_and_profile(("s1", "s2", "s3"))
        config = BostonConfig(
            tiebreak=RejectTies(),
            placement=PLACEMENT_ON,
            placement_acceptability=ACCEPTABILITY_BINDS,
        )
        result = boston_immediate_acceptance(market, profile, config)

        self.assertEqual(
            result.assignment.student_to_school,
            {"s1": "c1", "s2": "c3", "s3": "c3"},
        )
        self.assertEqual(result.placements, (("s2", "c3"), ("s3", "c3")))
        self.assertEqual(result.placement_unplaced, ())

        ir_ok, ir_reasons = is_individually_rational(
            market, profile, result.priorities, result.assignment
        )
        self.assertFalse(ir_ok)
        joined = " | ".join(ir_reasons)
        self.assertIn("s2", joined)
        self.assertIn("s3", joined)

    def test_bos_f_placement_on_ignored(self):
        """Same instance, placement="on" with placement_acceptability=
        "ignored": acceptability is overridden, only remaining capacity
        matters.

          s2: c1 full -> skip. c2 has 1 seat (eligibility overridden) ->
              s2 placed at c2.
          s3: c1 full -> skip. c2 now has 0 seats -> skip. c3 has 2 seats ->
              s3 placed at c3.

        Final: s1->c1, s2->c2, s3->c3. Individual rationality is violated in
        BOTH ways at once here: a student (s2, s3) assigned a school absent
        from their own report, AND a school (c2) holding a student (s2) it
        finds unacceptable.
        """
        market, profile = self._bos_f_market_and_profile(("s1", "s2", "s3"))
        config = BostonConfig(
            tiebreak=RejectTies(),
            placement=PLACEMENT_ON,
            placement_acceptability=ACCEPTABILITY_IGNORED,
        )
        result = boston_immediate_acceptance(market, profile, config)

        self.assertEqual(
            result.assignment.student_to_school,
            {"s1": "c1", "s2": "c2", "s3": "c3"},
        )
        self.assertEqual(result.placements, (("s2", "c2"), ("s3", "c3")))

        ir_ok, ir_reasons = is_individually_rational(
            market, profile, result.priorities, result.assignment
        )
        self.assertFalse(ir_ok)
        joined = " | ".join(ir_reasons)
        self.assertIn(
            "assigned 'c2', which is absent from their own report", joined
        )
        self.assertIn("holds student 's2', who is unacceptable to it", joined)

    def test_bos_f_placement_order_is_load_bearing(self):
        """Rebuild the SAME BOS-F market with Market.students declared as
        (s3, s2, s1) instead of (s1, s2, s3), and run placement="on" with
        placement_acceptability="ignored". Under "ignored" both s2 and s3
        are eligible everywhere with a seat, so whichever of them is
        processed FIRST in placement_student_order claims c2 (the single
        remaining seat there) and the other falls through to c3:

          declared order (s1,s2,s3): s2 processed first -> s2->c2, s3->c3.
          declared order (s3,s2,s1): s3 processed first -> s3->c2, s2->c3.

        These are the OPPOSITE of each other -- proof that
        placement_student_order (currently pinned to Market.students order)
        actually determines the outcome and is not a cosmetic default.

        Under "binds", by contrast, c2 is unacceptable to both s2 and s3
        regardless of order, so both can only ever reach c3 -- order does
        not bite there, and this test does not assert on that case.
        """
        market_declared, profile_declared = self._bos_f_market_and_profile(
            ("s1", "s2", "s3")
        )
        config = BostonConfig(
            tiebreak=RejectTies(),
            placement=PLACEMENT_ON,
            placement_acceptability=ACCEPTABILITY_IGNORED,
        )
        result_declared = boston_immediate_acceptance(
            market_declared, profile_declared, config
        )

        market_reordered, profile_reordered = self._bos_f_market_and_profile(
            ("s3", "s2", "s1")
        )
        result_reordered = boston_immediate_acceptance(
            market_reordered, profile_reordered, config
        )

        self.assertEqual(
            result_declared.assignment.student_to_school,
            {"s1": "c1", "s2": "c2", "s3": "c3"},
        )
        self.assertEqual(
            result_reordered.assignment.student_to_school,
            {"s1": "c1", "s2": "c3", "s3": "c2"},
        )
        self.assertNotEqual(
            result_declared.assignment.student_to_school,
            result_reordered.assignment.student_to_school,
        )

    # ------------------------------------------------------------------
    # BOS-G: placement runs and places NOBODY
    # ------------------------------------------------------------------
    def _bos_g_market_and_profile(self):
        market = Market(
            students=("s1", "s2"),
            schools=("c1", "c2", "c3"),
            capacities={"c1": 1, "c2": 1, "c3": 1},
            priority_classes={
                "c1": _singleton_classes(("s1", "s2")),
                "c2": (("s1",),),  # s2 unlisted -> unacceptable
                "c3": (("s1",),),  # s2 unlisted -> unacceptable
            },
        )
        profile = Profile({"s1": ("c1",), "s2": ("c1",)})
        return market, profile

    def test_bos_g_placement_binds_places_nobody(self):
        """students s1,s2; schools c1,c2,c3; caps all 1 (3 seats, 2
        students). priorities c1: s1>s2; c2: only s1; c3: only s1 -- s2 is
        UNACCEPTABLE at both c2 and c3. Both report (c1,) only.

        Round 1: both propose to c1; c1 accepts s1, rejects s2 by
        competition. Round 2: s2 exhausted -> no proposers; rounds end.
        Leftover seats: c2=1, c3=1.

        placement="on", "binds": s2's candidate list is EMPTY (c1 full, c2
        and c3 both find s2 unacceptable) -> s2 stays unmatched. This must
        not crash and must not force an assignment. Final: s1->c1, s2->None
        -- IDENTICAL to placement="off", with 2 seats sitting empty.
        placements == (), placement_unplaced == ("s2",). This outcome IS
        individually rational (nothing was force-placed).
        """
        market, profile = self._bos_g_market_and_profile()
        config_off = BostonConfig(tiebreak=RejectTies())
        result_off = boston_immediate_acceptance(market, profile, config_off)

        self.assertEqual(len(result_off.rounds), 1)
        self.assert_round(
            result_off.rounds[0],
            index=1,
            proposals=(("s1", "c1"), ("s2", "c1")),
            rejected_by_competition=(("s2", "c1"),),
            accepted=(("s1", "c1"),),
            seats_remaining_after=(("c1", 0), ("c2", 1), ("c3", 1)),
        )
        self.assertEqual(
            result_off.assignment.student_to_school, {"s1": "c1", "s2": None}
        )

        config_binds = BostonConfig(
            tiebreak=RejectTies(),
            placement=PLACEMENT_ON,
            placement_acceptability=ACCEPTABILITY_BINDS,
        )
        result_binds = boston_immediate_acceptance(market, profile, config_binds)

        self.assertEqual(
            result_binds.assignment.student_to_school, {"s1": "c1", "s2": None}
        )
        self.assertEqual(result_binds.placements, ())
        self.assertEqual(result_binds.placement_unplaced, ("s2",))

        ir_ok, ir_reasons = is_individually_rational(
            market, profile, result_binds.priorities, result_binds.assignment
        )
        self.assertTrue(ir_ok, ir_reasons)

    def test_bos_g_placement_ignored_places_s2(self):
        """Same instance, placement="on" with placement_acceptability=
        "ignored": s2's only constraint is remaining capacity, so s2 is
        placed at the first school with a seat, c2. Final: s1->c1, s2->c2.
        This DOES break individual rationality (s2 is assigned a school
        absent from their report, and c2 holds a student it finds
        unacceptable)."""
        market, profile = self._bos_g_market_and_profile()
        config_ignored = BostonConfig(
            tiebreak=RejectTies(),
            placement=PLACEMENT_ON,
            placement_acceptability=ACCEPTABILITY_IGNORED,
        )
        result_ignored = boston_immediate_acceptance(market, profile, config_ignored)

        self.assertEqual(
            result_ignored.assignment.student_to_school, {"s1": "c1", "s2": "c2"}
        )
        self.assertEqual(result_ignored.placements, (("s2", "c2"),))

        ir_ok, ir_reasons = is_individually_rational(
            market, profile, result_ignored.priorities, result_ignored.assignment
        )
        self.assertFalse(ir_ok, ir_reasons)

    # ------------------------------------------------------------------
    # CONVENTION TEST: A&S "propose-even-if-full" vs the "skip-full" alternative
    # ------------------------------------------------------------------
    def test_convention_ab_vs_skip_full(self):
        """This instance is where the two conventions give DIFFERENT FINAL
        ASSIGNMENTS, so it pins the DECLARED convention (round k always
        consumes the k-th listed school, full or not) rather than merely
        the trace.

        students s1..s4; schools c1,c2,c3; caps all 1.
        priorities c1: s2>s1>s4   c2: s3>s1   c3: s1>s4
        reports s1:(c1,c2,c3)  s2:(c1,)  s3:(c2,)  s4:(c1,c3)

        Round 1: proposals s1->c1, s2->c1, s3->c2, s4->c1. c1's proposers
        {s1,s2,s4}: s2 is top priority, accepted; s1 and s4 rejected by
        competition (FINAL). c2's sole proposer s3 is accepted.
        Round 2 (the DECLARED convention -- s1's list still has c2 next):
        proposals s1->c2, s4->c3. c2 has 0 remaining seats (s3 already took
        it) -> s1 is rejected_as_full, NOT allowed to skip ahead to c3 in
        this same round. c3's sole proposer s4 is accepted.
        Round 3: s1 (rejected, next/last choice) -> c3; c3 now has 0
        remaining seats (s4 took it in round 2) -> rejected_as_full. s1's
        list is exhausted; rounds end.

        Final: s1->None, s2->c1, s3->c2, s4->c3.

        Under the ALTERNATIVE "skip-full" convention (NOT implemented here,
        and never will be as a flag on this function -- see the module
        docstring), s1 would skip the already-full c2 in round 2 and
        immediately try c3 in the SAME round, before s4 ever gets a chance
        to propose there: s1 would then win c3 (c3's priority ranks s1
        above s4), giving s1->c3, s4->None instead. That instance is the
        entire point of this test: consuming round 2 on the full c2 -- the
        A&S convention this implementation follows -- is what costs s1 the
        c3 seat to s4. A "skip-full" implementation would produce s1->c3,
        s4->None here and would therefore FAIL this test.
        """
        market = Market(
            students=("s1", "s2", "s3", "s4"),
            schools=("c1", "c2", "c3"),
            capacities={"c1": 1, "c2": 1, "c3": 1},
            priority_classes={
                "c1": _singleton_classes(("s2", "s1", "s4")),
                "c2": _singleton_classes(("s3", "s1")),
                "c3": _singleton_classes(("s1", "s4")),
            },
        )
        profile = Profile(
            {
                "s1": ("c1", "c2", "c3"),
                "s2": ("c1",),
                "s3": ("c2",),
                "s4": ("c1", "c3"),
            }
        )
        config = BostonConfig(tiebreak=RejectTies())
        result = boston_immediate_acceptance(market, profile, config)

        self.assertEqual(len(result.rounds), 3)
        self.assert_round(
            result.rounds[0],
            index=1,
            proposals=(("s1", "c1"), ("s2", "c1"), ("s3", "c2"), ("s4", "c1")),
            rejected_by_competition=(("s1", "c1"), ("s4", "c1")),
            accepted=(("s2", "c1"), ("s3", "c2")),
            seats_remaining_after=(("c1", 0), ("c2", 0), ("c3", 1)),
        )
        self.assert_round(
            result.rounds[1],
            index=2,
            proposals=(("s1", "c2"), ("s4", "c3")),
            rejected_as_full=(("s1", "c2"),),
            accepted=(("s4", "c3"),),
            seats_remaining_after=(("c1", 0), ("c2", 0), ("c3", 0)),
        )
        self.assert_round(
            result.rounds[2],
            index=3,
            proposals=(("s1", "c3"),),
            rejected_as_full=(("s1", "c3"),),
            accepted=(),
            seats_remaining_after=(("c1", 0), ("c2", 0), ("c3", 0)),
        )
        self.assertEqual(
            result.assignment.student_to_school,
            {"s1": None, "s2": "c1", "s3": "c2", "s4": "c3"},
        )

    # ------------------------------------------------------------------
    # Config round-trip
    # ------------------------------------------------------------------
    def test_config_round_trip_and_validation(self):
        """BostonConfig.to_dict()/from_dict round-trips every field,
        including all four placement parameters; to_dict()["mechanism"] ==
        "boston_immediate_acceptance"; each invalid enum value raises
        ModelError."""
        config = BostonConfig(
            tiebreak=RejectTies(),
            unlisted_student_policy=MechanismConfig().unlisted_student_policy,
            placement=PLACEMENT_ON,
            placement_acceptability=ACCEPTABILITY_IGNORED,
        )
        data = config.to_dict()
        self.assertEqual(data["mechanism"], "boston_immediate_acceptance")
        self.assertEqual(data["placement"], PLACEMENT_ON)
        self.assertEqual(data["placement_acceptability"], ACCEPTABILITY_IGNORED)
        self.assertEqual(data["placement_student_order"], "declared_students")
        self.assertEqual(data["placement_school_order"], "declared_schools")

        rebuilt = BostonConfig.from_dict(data)
        self.assertEqual(rebuilt, config)
        self.assertEqual(rebuilt.to_dict(), data)

        with self.assertRaises(ModelError):
            BostonConfig(placement="sometimes")
        with self.assertRaises(ModelError):
            BostonConfig(placement_acceptability="mostly")
        with self.assertRaises(ModelError):
            BostonConfig(placement_student_order="random")
        with self.assertRaises(ModelError):
            BostonConfig(placement_school_order="random")
        with self.assertRaises(ModelError):
            BostonConfig(mechanism="")


if __name__ == "__main__":
    unittest.main()
