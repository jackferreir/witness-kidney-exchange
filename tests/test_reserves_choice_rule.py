"""The choice rule's own axioms, checked exhaustively over small pools.

Substituting a new C_a into the Gale-Shapley loop is only legitimate if C_a
has the properties the loop's guarantees rest on. Dur, Kominers, Pathak &
Sonmez (2018) assert (their footnote 19) that the choice functions in their
setting satisfy Hatfield-Milgrom (2005) SUBSTITUTABILITY and Aygun-Sonmez
(2013) IRRELEVANCE OF REJECTED CONTRACTS; substitutability together with the
LAW OF AGGREGATE DEMAND is what delivers strategy-proofness for the proposing
side.

That is a claim about the published rule. This file checks it about THIS
CODE, exhaustively over every subset of a small student set, for every
combination of capacity, reserve size, precedence and reserve semantics. It
is the mechanism-independent reason to believe reserve_da, and it does not
route through the manipulation search at all -- so it fails for different
reasons than RES-D does, and a bug that fooled one would have to fool a
different thing to fool the other.

Stated in the rejection form, with R(J) = J \\ C(J):

  substitutability   J subset of J'  =>  R(J) subset of R(J')
                     (a student rejected from a smaller pool is still
                     rejected from a larger one -- schools never "un-reject")
  law of aggregate   J subset of J'  =>  |C(J)| <= |C(J')|
    demand           (a bigger applicant pool never seats fewer students)
  IRC                s not in C(J)   =>  C(J \\ {s}) = C(J)
                     (removing a rejected student changes nothing)
"""

from __future__ import annotations

import itertools
import unittest

from witness.core import Market, MechanismConfig, ResolvedPriorities, resolve_priorities
from witness.reserves import (
    PRECEDENCE_OPEN_FIRST,
    PRECEDENCE_RESERVE_FIRST,
    RESERVE_HARD,
    RESERVE_SOFT,
    ReserveConfig,
    SchoolReserve,
    reserve_choice_rule,
)

STUDENTS = ("s1", "s2", "s3", "s4", "s5")


def market_with(capacity: int) -> Market:
    return Market(
        students=STUDENTS,
        schools=("c",),
        capacities={"c": capacity},
        priority_classes={"c": tuple((s,) for s in STUDENTS)},
    )


def settings():
    """Every combination worth checking, with the eligible set varied too --
    including the empty and full ones, which are where soft and hard reserves
    differ."""
    for capacity in (1, 2, 3):
        for reserved in range(capacity + 1):
            for precedence in (PRECEDENCE_RESERVE_FIRST, PRECEDENCE_OPEN_FIRST):
                for rtype in (RESERVE_SOFT, RESERVE_HARD):
                    for k in range(len(STUDENTS) + 1):
                        for eligible in itertools.combinations(STUDENTS, k):
                            yield capacity, reserved, precedence, rtype, eligible


class ChoiceRuleAxioms(unittest.TestCase):
    def all_cases(self):
        for capacity, reserved, precedence, rtype, eligible in settings():
            market = market_with(capacity)
            config = ReserveConfig(
                reserves={"c": SchoolReserve(reserved, eligible)},
                reserve_type=rtype,
                precedence=precedence,
            )
            priorities = resolve_priorities(market, config)
            def C(pool, _m=market, _p=priorities, _c=config):
                return frozenset(reserve_choice_rule(_c, _m, _p, "c", tuple(pool)))
            yield (capacity, reserved, precedence, rtype, eligible), C

    def subsets(self):
        for k in range(len(STUDENTS) + 1):
            for combo in itertools.combinations(STUDENTS, k):
                yield frozenset(combo)

    def test_substitutability(self):
        checked = 0
        for label, C in self.all_cases():
            for J in self.subsets():
                RJ = J - C(J)
                for t in STUDENTS:
                    if t in J:
                        continue
                    Jp = J | {t}
                    RJp = Jp - C(Jp)
                    self.assertTrue(
                        RJ <= RJp,
                        f"substitutability violated at {label}: adding {t!r} to "
                        f"{sorted(J)} un-rejected {sorted(RJ - RJp)}",
                    )
                    checked += 1
        # Exact, derived from the enumeration rather than observed from a run:
        #   (capacity, reserved) pairs with reserved in 0..capacity, capacity in
        #   1..3                                              = 2 + 3 + 4 = 9
        #   x 2 precedence orders x 2 reserve semantics        = 36
        #   x 2**5 eligible subsets                            = 1152 settings
        #   x sum over J of |S \ J| = sum_k C(5,k)(5-k)        = 80 per setting
        # so a complete sweep is 1152 * 80. Asserting the exact figure means a
        # silently truncated enumeration fails here instead of reporting a
        # vacuous pass.
        self.assertEqual(checked, 1152 * 80)

    def test_law_of_aggregate_demand(self):
        for label, C in self.all_cases():
            for J in self.subsets():
                for t in STUDENTS:
                    if t in J:
                        continue
                    self.assertLessEqual(
                        len(C(J)), len(C(J | {t})),
                        f"law of aggregate demand violated at {label}: adding "
                        f"{t!r} to {sorted(J)} seated fewer students",
                    )

    def test_irrelevance_of_rejected_contracts(self):
        for label, C in self.all_cases():
            for J in self.subsets():
                chosen = C(J)
                for s in J - chosen:
                    self.assertEqual(
                        C(J - {s}), chosen,
                        f"IRC violated at {label}: dropping rejected {s!r} from "
                        f"{sorted(J)} changed the choice",
                    )

    def test_choice_never_exceeds_capacity_and_is_drawn_from_the_pool(self):
        for label, C in self.all_cases():
            capacity = label[0]
            for J in self.subsets():
                chosen = C(J)
                self.assertLessEqual(len(chosen), capacity, label)
                self.assertTrue(chosen <= J, label)

    def test_soft_reserve_is_never_wasteful_but_hard_quota_can_be(self):
        """The two semantics differ in exactly one way, and it is this one.
        Asserted as a difference so neither can drift into the other."""
        soft_waste = hard_waste = 0
        for label, C in self.all_cases():
            capacity, _reserved, _prec, rtype, _elig = label
            for J in self.subsets():
                wasteful = len(C(J)) < min(capacity, len(J))
                if rtype == RESERVE_SOFT:
                    self.assertFalse(
                        wasteful,
                        f"soft reserve left a seat empty with an applicant "
                        f"waiting at {label}, pool {sorted(J)}",
                    )
                elif wasteful:
                    hard_waste += 1
            soft_waste += 0
        self.assertGreater(
            hard_waste, 0,
            "hard_quota never wasted a seat in any case, so this test cannot "
            "tell the two semantics apart and the soft-reserve assertion above "
            "is passing vacuously",
        )


if __name__ == "__main__":
    unittest.main()
