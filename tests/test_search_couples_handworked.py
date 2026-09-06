"""Hand-worked pin for `witness.search_couples`'s headline finding: a SINGLE
applicant (not part of any couple) can profitably misreport in a market that
also contains couples -- confirming REVIEWER.md's flagged open question
("Expect singleton sufficiency to FAIL under couples ... round-1
independence dissolves").

The instance is `tests/test_couples_handworked.py`'s own CPL-C fixture,
re-used verbatim (not re-derived from scratch) because CPL-C's hand trace is
already vetted there under BOTH processing orders -- this test adds exactly
one new hand-traced fact on top of it: under COUPLE_ORDER_COUPLES_LAST, s1
can do BETTER than her hand-traced truthful outcome (p3, her second choice)
by truncating her list down to ONLY her first choice (p2).

HAND TRACE (extends CPL-C's own couples_last trace):
  s1 truncates to ['p2']. s1 proposes p2 (vacant) -> holds.
  Couple A proposes (p1,p2): p1 vacant (accept a1); p2 -- a2 beats s1
    (accept, displacing s1). BOTH accept -> A matched (p1,p2), s1 displaced.
  s1's list is exhausted (only had one entry, already used) -> s1 becomes
    (temporarily) unmatched via `single_exhausted`.
  Couple B proposes (p1,p3): p1 -- b1 beats a1 (accept, displacing a1); p3
    vacant (accept b2). BOTH accept -> B matched (p1,p3), a1 displaced.
    a1's displacement cascades: a2 is ALSO withdrawn (even though not
    directly displaced) -- p2 becomes genuinely vacant, pushed onto the
    program stack.
  A re-proposes its only pair (p1,p2): p1 now held by b1, who beats a1 ->
    rejected -> A's whole proposal fails again -> A exhausted, unmatched.
  Program-stack reactivation fires for p2 (now truly vacant): s1 is
    introduced, p2 is in her (truncated) report, and p2 would accept her
    (nobody holds it) -> she is reactivated and re-proposes p2 -> holds it.
  final: s1 -> p2 (her FIRST choice -- better than p3, her truthful
    couples_last outcome), a1/a2 unmatched, b1 -> p1, b2 -> p3.

Both the truthful and the false outcome are independently confirmed stable
by `witness.oracles_couples.is_stable_couples` (checked directly here, not
merely inferred from `STATUS_STABLE`), and the witness is independently
re-verified via `witness.replay_couples.verify_in_subprocess` -- a FRESH
interpreter, per REVIEWER.md's "every finding replays from its saved witness
alone, in a fresh subprocess."
"""

from __future__ import annotations

import unittest

from witness.core import Market, resolve_priorities
from witness.couples import (
    COUPLE_ORDER_COUPLES_FIRST,
    COUPLE_ORDER_COUPLES_LAST,
    Couple,
    CouplesConfig,
    CouplesProfile,
)
from witness.oracles_couples import is_stable_couples
from witness.replay_couples import verify_in_subprocess
from witness.search_couples import find_single_manipulation


def singles(order):
    return tuple((s,) for s in order)


class CplC1SingleManipulationUnderCouplesLast(unittest.TestCase):
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

    def test_truncating_to_first_choice_strictly_improves_s1(self):
        config = CouplesConfig(couple_order_policy=COUPLE_ORDER_COUPLES_LAST)
        w = find_single_manipulation(self.market, self.profile, "s1", config, max_space=10_000)
        self.assertIsNotNone(w, "expected a manipulation for s1 under couples_last")
        self.assertEqual(w.false_report, ["p2"])
        self.assertEqual(w.truthful_outcome, "p3")
        self.assertEqual(w.false_outcome, "p2")
        self.assertEqual(w.truthful_outcome_rank, 2)
        self.assertEqual(w.false_outcome_rank, 0)
        # Full false-run assignment, pinned exactly (not just s1's own cell):
        self.assertEqual(
            w.false_assignment["student_to_school"],
            {"s1": "p2", "a1": None, "a2": None, "b1": "p1", "b2": "p3"},
        )

    def test_both_truthful_and_false_outcomes_are_independently_stable(self):
        """Not merely STATUS_STABLE (the algorithm's own, checked-not-proven
        claim) -- confirmed against the Appendix-C oracle directly, which
        shares no code with `witness.couples`."""
        config = CouplesConfig(couple_order_policy=COUPLE_ORDER_COUPLES_LAST)
        priorities = resolve_priorities(self.market, config)
        w = find_single_manipulation(self.market, self.profile, "s1", config, max_space=10_000)

        from witness.couples import couples_deferred_acceptance

        false_profile = CouplesProfile(singles={"s1": ("p2",)}, couples=self.profile.couples)
        truthful_res = couples_deferred_acceptance(self.market, self.profile, config)
        false_res = couples_deferred_acceptance(self.market, false_profile, config)
        self.assertTrue(is_stable_couples(self.market, self.profile, priorities, truthful_res.assignment))
        self.assertTrue(is_stable_couples(self.market, false_profile, priorities, false_res.assignment))

    def test_witness_replays_in_a_fresh_subprocess(self):
        config = CouplesConfig(couple_order_policy=COUPLE_ORDER_COUPLES_LAST)
        w = find_single_manipulation(self.market, self.profile, "s1", config, max_space=10_000)
        ok, reasons = verify_in_subprocess(w.to_dict())
        self.assertTrue(ok, msg=f"witness failed replay: {reasons}")

    def test_no_manipulation_for_s1_under_couples_first(self):
        """Confirms the finding is genuinely order-dependent, not a
        blanket property of this instance -- mirrors CPL-C's own point that
        `couple_order_policy` is not inert."""
        config = CouplesConfig(couple_order_policy=COUPLE_ORDER_COUPLES_FIRST)
        w = find_single_manipulation(self.market, self.profile, "s1", config, max_space=10_000)
        self.assertIsNone(w)


if __name__ == "__main__":
    unittest.main()
