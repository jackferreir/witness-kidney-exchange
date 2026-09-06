"""Hand-worked examples for the couples-generalized applicant-proposing
algorithm (witness.couples) and its independent stability oracle
(witness.oracles_couples).

Every expected value in CPL-A, CPL-B, and CPL-C was derived BY HAND from
Roth & Peranson (1999)'s conceptual design (Section III.A) and Appendix C
formal definitions, BEFORE being checked against the implementation -- and
CPL-B's oracle assertions were independently verified against the exact
Appendix C blocking clause via a standalone, non-algorithmic enumeration
of all 5 candidate matchings (never by running `witness.couples` itself).
DO NOT change an expected value to make a test pass: a disagreement here is
a finding about the implementation.

CPL-A  a normal case where a stable matching exists: a couple's joint
       proposal displaces a single, who then resettles elsewhere. No loop.
CPL-B  Roth (1984)'s core impossibility, minimal instance: NO stable
       matching exists, under ANY processing order, by the formal
       definition itself. Pins that the algorithm's loop-detector reports
       this rather than silently returning an unstable matching, AND
       (separately, via the independent oracle) that none of the 5
       candidate matchings survive the Appendix C definition.
CPL-C  `couple_order_policy` provably CAN change who matches where --
       the couples analogue of `tests/test_reserves_handworked.py`'s RES-B
       for `ReserveConfig.precedence`. Unlike `DAConfig.proposal_policy`,
       there is no proof of invariance to disprove here; this is a direct
       demonstration.
"""

from __future__ import annotations

import unittest

from witness.core import Market
from witness.couples import (
    COUPLE_ORDER_COUPLES_FIRST,
    COUPLE_ORDER_COUPLES_LAST,
    STATUS_LOOP_DETECTED,
    STATUS_STABLE,
    Couple,
    CouplesConfig,
    CouplesProfile,
    couples_deferred_acceptance,
)
from witness.errors import ModelError
from witness.oracles import blocking_pairs as flat_blocking_pairs
from witness.oracles_couples import (
    blocking_pairs_couples,
    candidate_assignment,
    is_individually_rational_couples,
    is_stable_couples,
)
from witness.core import resolve_priorities


def singles(order):
    """A strict order as singleton priority classes."""
    return tuple((s,) for s in order)


class CplANoLoopStableMatch(unittest.TestCase):
    """CPL-A. A single displaced by a couple's joint proposal resettles;
    the couple's joint proposal succeeds because BOTH halves are accepted
    simultaneously.

    Programs: p1(1), p2(1), p3(1)
    Single s1, ROL=[p1, p3]
    Couple (w1,w2), joint ROL = [(p1,p2), (p3,p2)]
    p1 priority: w1 > s1
    p2 priority: w2 (only w2 acceptable)
    p3 priority: s1 > w1
    Processing order: s1 first, then the couple (COUPLE_ORDER_INTERMIXED,
    since s1's declared position precedes both w1 and w2's).

    HAND TRACE
      s1 proposes p1 (vacant) -> holds p1.
      couple proposes (p1,p2): p1 prefers w1 to s1 (accept, hypothetically
        displacing s1); p2 is vacant and w2 acceptable (accept). BOTH
        halves accept -> couple matched (p1,p2), s1 displaced.
      s1 reproposes: p3 is vacant -> holds p3.
      final: p1=w1, p2=w2, p3=s1. No loop.
    """

    def setUp(self):
        self.market = Market(
            students=("s1", "w1", "w2"),
            schools=("p1", "p2", "p3"),
            capacities={"p1": 1, "p2": 1, "p3": 1},
            priority_classes={
                "p1": singles(("w1", "s1")),
                "p2": singles(("w2",)),
                "p3": singles(("s1", "w1")),
            },
        )
        self.profile = CouplesProfile(
            singles={"s1": ("p1", "p3")},
            couples=(Couple(members=("w1", "w2"), joint_rankings=(("p1", "p2"), ("p3", "p2"))),),
        )
        self.config = CouplesConfig()

    def test_final_assignment_matches_the_hand_trace(self):
        res = couples_deferred_acceptance(self.market, self.profile, self.config)
        self.assertEqual(res.status, STATUS_STABLE, msg=res.format_trace())
        self.assertEqual(
            res.assignment.student_to_school,
            {"s1": "p3", "w1": "p1", "w2": "p2"},
            msg=res.format_trace(),
        )

    def test_exact_event_trace_matches_the_hand_trace(self):
        """Pins the TRACE, not just the final answer -- mirroring why
        `witness.ttc.TTCStep` exists (see that module's docstring): a wrong
        mechanic could coincidentally reproduce the right final assignment
        on this one instance while being broken in general.
        """
        res = couples_deferred_acceptance(self.market, self.profile, self.config)
        kinds = [e.kind for e in res.events]
        self.assertEqual(
            kinds,
            [
                "agent_introduced",
                "single_accepted",
                "agent_introduced",
                "couple_proposal",
                "departure",
                "single_accepted",
            ],
            msg=res.format_trace(),
        )
        e = res.events
        self.assertEqual(e[0].data["agent_kind"], "single")
        self.assertEqual(e[0].data["applicant"], "s1")
        self.assertEqual(e[1].data, {"applicant": "s1", "program": "p1", "displaced": []})
        self.assertEqual(e[2].data["agent_kind"], "couple")
        self.assertEqual(sorted(e[2].data["couple"]), ["w1", "w2"])
        self.assertEqual(
            e[3].data, {"couple": ["w1", "w2"], "pair": ["p1", "p2"], "accepted": True}
        )
        self.assertEqual(e[4].data, {"applicant": "s1", "program": "p1"})
        self.assertEqual(e[5].data, {"applicant": "s1", "program": "p3", "displaced": []})

    def test_final_matching_is_independently_confirmed_stable(self):
        """The algorithm's own STATUS_STABLE is checked-not-proven (see
        `witness.couples`'s module docstring); this confirms it against the
        independent oracle for this specific instance."""
        priorities = resolve_priorities(self.market, self.config)
        res = couples_deferred_acceptance(self.market, self.profile, self.config)
        self.assertTrue(
            is_stable_couples(self.market, self.profile, priorities, res.assignment)
        )


class CplBNoStableMatchingExists(unittest.TestCase):
    """CPL-B. Roth (1984)'s core impossibility, minimal instance.

    Programs: p1(1), p2(1)
    Single s, ROL=[p1, p2]
    Couple (w1,w2), joint ROL = [(p1,p2), (p2,p1)]
    p1 priority (full): w1 > s > w2
    p2 priority (full): s > w2 > w1

    There are exactly 5 candidate outcomes and EVERY ONE is blocked (see
    this module's docstring and the task's own derivation, reproduced in
    `witness/oracles_couples.py`'s docstring). No stable matching exists,
    under ANY processing order, by the definition itself -- independent of
    what the algorithm's loop-detector does.
    """

    def setUp(self):
        self.market = Market(
            students=("s", "w1", "w2"),
            schools=("p1", "p2"),
            capacities={"p1": 1, "p2": 1},
            priority_classes={
                "p1": singles(("w1", "s", "w2")),
                "p2": singles(("s", "w2", "w1")),
            },
        )
        self.profile = CouplesProfile(
            singles={"s": ("p1", "p2")},
            couples=(Couple(members=("w1", "w2"), joint_rankings=(("p1", "p2"), ("p2", "p1"))),),
        )
        self.priorities = resolve_priorities(self.market, CouplesConfig())

    def test_algorithm_reports_loop_detected_not_a_silent_wrong_answer(self):
        res = couples_deferred_acceptance(self.market, self.profile, CouplesConfig())
        self.assertEqual(res.status, STATUS_LOOP_DETECTED, msg=res.format_trace())

    def test_algorithm_reports_loop_detected_under_couples_first_too(self):
        """Same instance, the other declared processing order -- the paper's
        own text ("loops due to the nonexistence of a stable matching would
        be more serious") implies this should not be an artefact of one
        particular order."""
        res = couples_deferred_acceptance(
            self.market, self.profile, CouplesConfig(couple_order_policy=COUPLE_ORDER_COUPLES_FIRST)
        )
        self.assertEqual(res.status, STATUS_LOOP_DETECTED, msg=res.format_trace())

    def test_all_five_candidate_matchings_are_independently_confirmed_unstable(self):
        """The definition-based check, entirely independent of
        `witness.couples` -- constructs each candidate directly and checks
        it against `witness.oracles_couples`, never against the algorithm's
        own output.
        """
        candidates = {
            "couple@(p1,p2),s_unmatched": {"s": None, "w1": "p1", "w2": "p2"},
            "couple@(p2,p1),s_unmatched": {"s": None, "w1": "p2", "w2": "p1"},
            "couple_unmatched,s@p1": {"s": "p1", "w1": None, "w2": None},
            "couple_unmatched,s@p2": {"s": "p2", "w1": None, "w2": None},
            "couple_unmatched,s_unmatched": {"s": None, "w1": None, "w2": None},
        }
        for name, student_to_school in candidates.items():
            with self.subTest(candidate=name):
                a = candidate_assignment(self.market, self.priorities, student_to_school)
                ok, reasons = is_individually_rational_couples(
                    self.market, self.profile, self.priorities, a
                )
                self.assertTrue(ok, msg=f"{name}: expected individually rational, got {reasons}")
                self.assertFalse(
                    is_stable_couples(self.market, self.profile, self.priorities, a),
                    msg=f"{name}: expected UNSTABLE (this is Roth 1984's impossibility)",
                )

    def test_named_blocking_parties_match_the_hand_derivation(self):
        """Pins the SPECIFIC blocking party the task's own derivation names
        for each candidate -- not merely "some blocking pair exists," which
        would also pass for a wrong-but-nonempty result."""
        priorities = self.priorities

        a = candidate_assignment(self.market, priorities, {"s": None, "w1": "p1", "w2": "p2"})
        self.assertIn(("single", "s", "p2"), blocking_pairs_couples(self.market, self.profile, priorities, a))

        a = candidate_assignment(self.market, priorities, {"s": None, "w1": "p2", "w2": "p1"})
        self.assertIn(("single", "s", "p1"), blocking_pairs_couples(self.market, self.profile, priorities, a))

        a = candidate_assignment(self.market, priorities, {"s": "p1", "w1": None, "w2": None})
        self.assertIn(
            ("couple", ("w1", "w2"), ("p1", "p2")),
            blocking_pairs_couples(self.market, self.profile, priorities, a),
        )

        a = candidate_assignment(self.market, priorities, {"s": "p2", "w1": None, "w2": None})
        blocks = blocking_pairs_couples(self.market, self.profile, priorities, a)
        self.assertIn(("single", "s", "p1"), blocks)
        # The subtle case: verify neither couple pairing blocks this one.
        self.assertNotIn(("couple", ("w1", "w2"), ("p1", "p2")), blocks)
        self.assertNotIn(("couple", ("w1", "w2"), ("p2", "p1")), blocks)

        a = candidate_assignment(self.market, priorities, {"s": None, "w1": None, "w2": None})
        blocks = blocking_pairs_couples(self.market, self.profile, priorities, a)
        self.assertIn(("single", "s", "p1"), blocks)


class FlatOracleDoesNotApplyToCouples(unittest.TestCase):
    """A DELIBERATE non-inheritance check, mirroring
    `tests/test_reserves_handworked.py`'s equivalent for `witness.reserves`.

    `witness.oracles.blocking_pairs` has no notion of a joint report at all:
    called against a couple's members using their INDIVIDUAL assigned
    school as if it were their own preference list, it can only ever be fed
    a `witness.core.Profile`, which has no slot for a couple's joint ROL of
    pairs. Concretely: if someone tried to "adapt" the flat oracle by
    inventing a fake per-member report (e.g. flattening each half of every
    joint-ranked pair into an individual ranking), it would treat w1 and w2
    as independently blockable -- exactly the mistake this fixture's own
    "couple_unmatched, s@p2" candidate warns against (CPL-B's subtle case,
    where NEITHER couple pairing blocks even though each half individually
    looks tempting). This test pins that the flat, non-couples-aware type
    signature cannot even be handed CPL-B's applicants directly, so a future
    reader cannot assume `witness.oracles.is_stable`/`blocking_pairs`
    silently works here.
    """

    def test_flat_blocking_pairs_has_no_report_for_a_couple_member(self):
        from witness.core import Profile

        market = Market(
            students=("s", "w1", "w2"),
            schools=("p1", "p2"),
            capacities={"p1": 1, "p2": 1},
            priority_classes={
                "p1": singles(("w1", "s", "w2")),
                "p2": singles(("s", "w2", "w1")),
            },
        )
        priorities = resolve_priorities(market, CouplesConfig())
        # A couple has no individual report -- only `singles` entries exist
        # in `witness.core.Profile`. Constructing one that even TRIES to
        # stand in for the couple's members must fail validation: there is
        # no well-defined individual ranking to give w1 or w2, because their
        # only real preference is over PAIRS, not over programs alone.
        with self.assertRaises(ModelError):
            Profile({"s": ("p1", "p2")}).validate_against(market)


class CplCProcessingOrderChangesTheOutcome(unittest.TestCase):
    """CPL-C. `couple_order_policy` provably CAN change who matches where
    -- unlike `DAConfig.proposal_policy` (proven inert) and exactly like
    `ReserveConfig.precedence` (RES-B), this setting has no invariance
    theorem to protect it, and the paper's own sequencing experiments found
    real (if rare) sensitivity in NRMP data.

    Programs: p1(1), p2(1), p3(1)
    Single s1, ROL = [p2, p1, p3]
    Couple A = (a1, a2), joint ROL = [(p1, p2)]
    Couple B = (b1, b2), joint ROL = [(p1, p3)]
    p1 priority: b1 > a1 > s1
    p2 priority: a2 > s1
    p3 priority: s1 > b2

    HAND TRACE, couples_last (s1 first, then A, then B -- A precedes B by
    declared position):
      s1 -> p2 (vacant, holds).
      A proposes (p1,p2): p1 vacant (accept a1); p2 -- a2 beats s1 (accept,
        displacing s1). BOTH accept -> A matched (p1,p2), s1 displaced.
      s1 reproposes: p1 -- a1 beats s1 (rejected); p3 -- vacant (holds p3).
      B proposes (p1,p3): p1 -- b1 beats a1 (would accept, displacing a1);
        p3 -- s1 beats b2 (REJECTED). Either half rejecting fails the WHOLE
        pair -> B's proposal fails entirely, no fallback -> B unmatched.
      final: s1->p3, a1->p1, a2->p2, b1/b2 unmatched.

    HAND TRACE, couples_first (A, then B, then s1):
      A proposes (p1,p2) first: both vacant -> accept unconditionally.
        A matched (p1,p2).
      B proposes (p1,p3): p1 -- b1 beats a1 (accept, displacing a1); p3 --
        vacant (accept). BOTH accept -> B matched (p1,p3), a1 displaced.
        a1's displacement is a COUPLE cascade: a2 is ALSO withdrawn from p2
        (even though not directly displaced), and p2 becomes genuinely
        vacant. A re-proposes its (only) pair (p1,p2): p1 now held by b1,
        who beats a1 -- rejected -> A's WHOLE proposal fails again -> A
        exhausted, permanently unmatched.
      Program-stack pulls A back in when p2 vacates (A's own list still
        mentions p2), but the retry fails identically (p1 still blocked by
        b1) -- no further state change.
      s1 (not yet introduced when this happened) finally proposes: her
        first choice p2 is vacant (A never got back in) -> holds p2.
      final: s1->p2, b1->p1, b2->p3, a1/a2 unmatched.

    So COUPLES_LAST gives s1 her SECOND choice (p3) and matches couple A;
    COUPLES_FIRST gives s1 her FIRST choice (p2) and leaves couple A
    entirely unmatched -- a genuine difference in who matches where, driven
    purely by `couple_order_policy`, with no loop involved on either side.
    """

    def setUp(self):
        self.market = Market(
            students=("s1", "a1", "a2", "b1", "b2"),
            schools=("p1", "p2", "p3"),
            capacities={"p1": 1, "p2": 1, "p3": 1},
            priority_classes={
                "p1": singles(("b1", "a1", "s1")),
                "p2": singles(("a2", "s1")),
                "p3": singles(("s1", "b2")),
            },
        )
        self.profile = CouplesProfile(
            singles={"s1": ("p2", "p1", "p3")},
            couples=(
                Couple(members=("a1", "a2"), joint_rankings=(("p1", "p2"),)),
                Couple(members=("b1", "b2"), joint_rankings=(("p1", "p3"),)),
            ),
        )

    def test_couples_last(self):
        res = couples_deferred_acceptance(
            self.market, self.profile, CouplesConfig(couple_order_policy=COUPLE_ORDER_COUPLES_LAST)
        )
        self.assertEqual(res.status, STATUS_STABLE, msg=res.format_trace())
        self.assertEqual(
            res.assignment.student_to_school,
            {"s1": "p3", "a1": "p1", "a2": "p2", "b1": None, "b2": None},
            msg=res.format_trace(),
        )

    def test_couples_first(self):
        res = couples_deferred_acceptance(
            self.market, self.profile, CouplesConfig(couple_order_policy=COUPLE_ORDER_COUPLES_FIRST)
        )
        self.assertEqual(res.status, STATUS_STABLE, msg=res.format_trace())
        self.assertEqual(
            res.assignment.student_to_school,
            {"s1": "p2", "a1": None, "a2": None, "b1": "p1", "b2": "p3"},
            msg=res.format_trace(),
        )

    def test_the_two_orders_actually_disagree(self):
        """The distinguishing fixture, asserted as a difference rather than
        left implicit in two separate expected values -- mirrors RES-B's
        `test_precedence_is_not_inert`."""
        last = couples_deferred_acceptance(
            self.market, self.profile, CouplesConfig(couple_order_policy=COUPLE_ORDER_COUPLES_LAST)
        ).assignment
        first = couples_deferred_acceptance(
            self.market, self.profile, CouplesConfig(couple_order_policy=COUPLE_ORDER_COUPLES_FIRST)
        ).assignment
        self.assertNotEqual(last.to_dict(), first.to_dict())
        self.assertEqual(last.of("s1"), "p3")
        self.assertEqual(first.of("s1"), "p2")
        self.assertEqual(last.of("a1"), "p1")
        self.assertIsNone(first.of("a1"))


class CouplesModelValidation(unittest.TestCase):
    def test_couple_must_have_two_distinct_members(self):
        with self.assertRaises(ModelError):
            Couple(members=("a", "a"), joint_rankings=(("p1", "p2"),))
        with self.assertRaises(ModelError):
            Couple(members=("a", "b", "c"), joint_rankings=(("p1", "p2"),))

    def test_joint_rankings_cannot_repeat_a_pair(self):
        with self.assertRaises(ModelError):
            Couple(members=("a", "b"), joint_rankings=(("p1", "p2"), ("p1", "p2")))

    def test_profile_applicant_coverage_is_checked(self):
        market = Market(
            students=("s", "w1", "w2"),
            schools=("p1",),
            capacities={"p1": 1},
            priority_classes={"p1": singles(("s", "w1", "w2"))},
        )
        profile = CouplesProfile(
            singles={"s": ("p1",)},
            couples=(Couple(members=("w1", "w2"), joint_rankings=(("p1", "p1"),)),),
        )
        with self.assertRaises(ModelError):
            profile.validate_against(
                Market(
                    students=("s", "w1"),
                    schools=("p1",),
                    capacities={"p1": 1},
                    priority_classes={"p1": singles(("s", "w1"))},
                )
            )

    def test_config_round_trips_through_dict(self):
        cfg = CouplesConfig(couple_order_policy=COUPLE_ORDER_COUPLES_FIRST, max_loop_repeats=5)
        rebuilt = CouplesConfig.from_dict(cfg.to_dict())
        self.assertEqual(cfg.to_dict(), rebuilt.to_dict())

    def test_couple_and_profile_round_trip_through_dict(self):
        c = Couple(members=("a1", "a2"), joint_rankings=(("p1", "p2"), ("p2", "p1")))
        self.assertEqual(Couple.from_dict(c.to_dict()).to_dict(), c.to_dict())
        profile = CouplesProfile(singles={"s": ("p1",)}, couples=(c,))
        self.assertEqual(
            CouplesProfile.from_dict(profile.to_dict()).to_dict(), profile.to_dict()
        )


if __name__ == "__main__":
    unittest.main()
