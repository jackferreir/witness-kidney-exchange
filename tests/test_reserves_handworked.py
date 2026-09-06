"""Hand-worked examples for DA with reserved seats (witness.reserves).

Every expected value in this file was derived BY HAND on paper from the
published choice rule in Dur, Kominers, Pathak & Sonmez (2018), before the
implementation was run. DO NOT change an expected value to make a test pass:
a disagreement here is a finding about the implementation.

RES-A  separates a RESERVE seat from a QUOTA seat. Every instance with enough
       eligible applicants gives the same answer under both, so this is the
       only shape that can catch implementing one and citing the other.
RES-B  precedence changes one school's admitted set, in the direction DKPS
       Proposition 3(ii) requires.
RES-C  that change CASCADES through DA to a school with no reserves at all,
       and the flat stability oracle does not apply to this mechanism.
RES-D  the negative control: DA under reserves is strategy-proof, so an
       exhaustive search must return nothing.
RES-E  DKPS's own stylised 50/50 walk-zone example, at its published numbers.

Priority classes are singletons throughout (RejectTies never has to fire), so
every priority order below is the exact order written down.
"""

from __future__ import annotations

import itertools
import unittest

from witness.core import Market, Profile
from witness.da import DAConfig, deferred_acceptance
from witness.errors import ModelError
from witness.oracles import blocking_pairs, is_individually_rational, is_stable
from witness.reserves import (
    PRECEDENCE_OPEN_FIRST,
    PRECEDENCE_RESERVE_FIRST,
    RESERVE_HARD,
    RESERVE_SOFT,
    SLOT_OPEN,
    SLOT_RESERVE,
    ReserveConfig,
    SchoolReserve,
    fill_slots,
    reserve_da,
    reserve_seats_used,
    slot_sequence,
)
from witness.search import find_all_manipulations


def singles(order):
    """A strict order as singleton priority classes."""
    return tuple((s,) for s in order)


class ResANameTheSemantics(unittest.TestCase):
    """RES-A. c1 has capacity 2, split 1 reserve + 1 open, reserve first.

    Priority at c1:      m1 > m2 > r1        (the reserve-eligible student is LAST)
    Reserve-eligible:    {r1}

    A1  all three apply. The reserve slot reaches past m1 and m2 to seat r1;
        the open slot then seats m1. Chosen {r1, m1}; m2 rejected.

    A2  r1 does not apply, reserve_type = soft_reserve. The reserve seat is a
        FLOOR, so with no eligible applicant it goes to the best remaining
        student. Chosen {m1, m2} -- both seats filled.

    A3  identical to A2 except reserve_type = hard_quota. The seat is
        EXCLUSIVE, so it stays EMPTY and m2 is rejected while a seat sits
        unused. Chosen {m1}.

    A2 and A3 are the same market, same slots, same precedence, same reports.
    Only the semantics differ, and they give different answers. That is the
    whole point of keeping the two names apart.
    """

    def setUp(self):
        self.market = Market(
            students=("m1", "m2", "r1"),
            schools=("c1",),
            capacities={"c1": 2},
            priority_classes={"c1": singles(("m1", "m2", "r1"))},
        )
        self.reserves = {"c1": SchoolReserve(reserved_seats=1, eligible=("r1",))}

    def config(self, reserve_type):
        return ReserveConfig(
            reserves=self.reserves,
            reserve_type=reserve_type,
            precedence=PRECEDENCE_RESERVE_FIRST,
        )

    def test_a1_reserve_reaches_past_higher_priority_students(self):
        profile = Profile({"m1": ("c1",), "m2": ("c1",), "r1": ("c1",)})
        for rtype in (RESERVE_SOFT, RESERVE_HARD):
            with self.subTest(reserve_type=rtype):
                cfg = self.config(rtype)
                res = reserve_da(self.market, profile, cfg)
                self.assertEqual(
                    fill_slots(self.market, res.priorities, cfg, "c1", ("m1", "m2", "r1")),
                    ((SLOT_RESERVE, "r1"), (SLOT_OPEN, "m1")),
                )
                self.assertEqual(res.assignment.of("r1"), "c1")
                self.assertEqual(res.assignment.of("m1"), "c1")
                self.assertIsNone(res.assignment.of("m2"))
                # Roster is in the school's priority order, not slot order.
                self.assertEqual(res.assignment.roster("c1"), ("m1", "r1"))

    def test_a2_soft_reserve_spills_over_to_an_ineligible_student(self):
        profile = Profile({"m1": ("c1",), "m2": ("c1",), "r1": ()})
        cfg = self.config(RESERVE_SOFT)
        res = reserve_da(self.market, profile, cfg)
        self.assertEqual(
            fill_slots(self.market, res.priorities, cfg, "c1", ("m1", "m2")),
            ((SLOT_RESERVE, "m1"), (SLOT_OPEN, "m2")),
        )
        self.assertEqual(res.assignment.of("m1"), "c1")
        self.assertEqual(res.assignment.of("m2"), "c1")
        self.assertEqual(res.assignment.roster("c1"), ("m1", "m2"))

    def test_a3_hard_quota_leaves_the_seat_empty(self):
        profile = Profile({"m1": ("c1",), "m2": ("c1",), "r1": ()})
        cfg = self.config(RESERVE_HARD)
        res = reserve_da(self.market, profile, cfg)
        self.assertEqual(
            fill_slots(self.market, res.priorities, cfg, "c1", ("m1", "m2")),
            ((SLOT_RESERVE, None), (SLOT_OPEN, "m1")),
        )
        self.assertEqual(res.assignment.of("m1"), "c1")
        self.assertIsNone(res.assignment.of("m2"))
        self.assertEqual(res.assignment.roster("c1"), ("m1",))

    def test_a2_and_a3_actually_disagree(self):
        """The distinguishing fixture, asserted as a difference rather than
        left implicit in two separate expected values."""
        profile = Profile({"m1": ("c1",), "m2": ("c1",), "r1": ()})
        soft = reserve_da(self.market, profile, self.config(RESERVE_SOFT)).assignment
        hard = reserve_da(self.market, profile, self.config(RESERVE_HARD)).assignment
        self.assertNotEqual(soft.to_dict(), hard.to_dict())
        self.assertEqual(soft.of("m2"), "c1")
        self.assertIsNone(hard.of("m2"))


class ResBPrecedence(unittest.TestCase):
    """RES-B. c1 has capacity 2, split 1 reserve + 1 open. All four apply.

    Priority at c1:      r1 > m1 > r2 > m2
    Reserve-eligible:    {r1, r2}

    reserve_first: the reserve slot seats r1 (the best eligible), and the open
                   slot then seats m1. Eligible admitted = 1.
    open_first:    the open slot seats r1 (best overall), and the reserve slot
                   then seats r2 (best eligible remaining). Eligible = 2.

    DKPS Proposition 3(ii): swapping a reserve slot with a SUBSEQUENT open
    slot weakly increases reserve-eligible assignment. Going reserve_first ->
    open_first is exactly that swap, and 1 -> 2 is the increase. Note the
    direction: putting the reserve seats FIRST is what costs the reserve group
    a seat. That counterintuitive fact is the paper's headline.
    """

    def setUp(self):
        self.market = Market(
            students=("r1", "m1", "r2", "m2"),
            schools=("c1",),
            capacities={"c1": 2},
            priority_classes={"c1": singles(("r1", "m1", "r2", "m2"))},
        )
        self.profile = Profile({s: ("c1",) for s in ("r1", "m1", "r2", "m2")})
        self.reserves = {"c1": SchoolReserve(reserved_seats=1, eligible=("r1", "r2"))}

    def config(self, precedence):
        return ReserveConfig(
            reserves=self.reserves, reserve_type=RESERVE_SOFT, precedence=precedence
        )

    def test_reserve_first_admits_one_eligible(self):
        cfg = self.config(PRECEDENCE_RESERVE_FIRST)
        res = reserve_da(self.market, self.profile, cfg)
        self.assertEqual(
            fill_slots(self.market, res.priorities, cfg, "c1", ("r1", "m1", "r2", "m2")),
            ((SLOT_RESERVE, "r1"), (SLOT_OPEN, "m1")),
        )
        self.assertEqual(res.assignment.roster("c1"), ("r1", "m1"))
        self.assertEqual(
            reserve_seats_used(self.market, res.priorities, cfg, "c1", ("r1", "m1")),
            (1, 1),
        )

    def test_open_first_admits_two_eligible(self):
        cfg = self.config(PRECEDENCE_OPEN_FIRST)
        res = reserve_da(self.market, self.profile, cfg)
        self.assertEqual(
            fill_slots(self.market, res.priorities, cfg, "c1", ("r1", "m1", "r2", "m2")),
            ((SLOT_OPEN, "r1"), (SLOT_RESERVE, "r2")),
        )
        self.assertEqual(res.assignment.roster("c1"), ("r1", "r2"))
        self.assertEqual(
            reserve_seats_used(self.market, res.priorities, cfg, "c1", ("r1", "r2")),
            (2, 0),
        )

    def test_precedence_is_not_inert(self):
        """`proposal_policy`'s two settings must NEVER change the matching;
        `precedence`'s two settings MUST be able to. This asserts the
        difference rather than trusting that it exists."""
        a = reserve_da(self.market, self.profile, self.config(PRECEDENCE_RESERVE_FIRST))
        b = reserve_da(self.market, self.profile, self.config(PRECEDENCE_OPEN_FIRST))
        self.assertNotEqual(a.assignment.to_dict(), b.assignment.to_dict())


class ResCCascade(unittest.TestCase):
    """RES-C. Two schools; only c1 has reserves.

    students   r1, m1, r2, m2
    c1         capacity 2, 1 reserve + 1 open, eligible {r1, r2}
    c2         capacity 1, no reserves
    priority   r1 > m1 > r2 > m2 at BOTH schools
    reports    r1, m1, r2: (c1, c2);  m2: (c1,)

    reserve_first
      step 1  all four -> c1;  reserve seats r1, open seats m1;  r2, m2 out
      step 2  r2 -> c2 (m2's list is exhausted);  c2 holds r2
      final   r1->c1  m1->c1  r2->c2  m2->unmatched

    open_first
      step 1  all four -> c1;  open seats r1, reserve seats r2;  m1, m2 out
      step 2  m1 -> c2;  c2 holds m1
      final   r1->c1  r2->c1  m1->c2  m2->unmatched

    The precedence order at c1 decides who gets the seat at c2 -- a school
    with no reserve structure at all. That cascade is why DKPS's Proposition 3
    needed a separate proof for the centralised mechanism.
    """

    def setUp(self):
        order = ("r1", "m1", "r2", "m2")
        self.market = Market(
            students=order,
            schools=("c1", "c2"),
            capacities={"c1": 2, "c2": 1},
            priority_classes={"c1": singles(order), "c2": singles(order)},
        )
        self.profile = Profile(
            {
                "r1": ("c1", "c2"),
                "m1": ("c1", "c2"),
                "r2": ("c1", "c2"),
                "m2": ("c1",),
            }
        )
        self.reserves = {"c1": SchoolReserve(reserved_seats=1, eligible=("r1", "r2"))}

    def config(self, precedence):
        return ReserveConfig(
            reserves=self.reserves, reserve_type=RESERVE_SOFT, precedence=precedence
        )

    def test_reserve_first_final_assignment(self):
        res = reserve_da(self.market, self.profile, self.config(PRECEDENCE_RESERVE_FIRST))
        self.assertEqual(
            res.assignment.student_to_school,
            {"r1": "c1", "m1": "c1", "r2": "c2", "m2": None},
        )

    def test_open_first_final_assignment(self):
        res = reserve_da(self.market, self.profile, self.config(PRECEDENCE_OPEN_FIRST))
        self.assertEqual(
            res.assignment.student_to_school,
            {"r1": "c1", "r2": "c1", "m1": "c2", "m2": None},
        )

    def test_cascade_reaches_a_school_with_no_reserves(self):
        a = reserve_da(self.market, self.profile, self.config(PRECEDENCE_RESERVE_FIRST))
        b = reserve_da(self.market, self.profile, self.config(PRECEDENCE_OPEN_FIRST))
        self.assertEqual(a.assignment.roster("c2"), ("r2",))
        self.assertEqual(b.assignment.roster("c2"), ("m1",))

    def test_individual_rationality_still_holds(self):
        """IR is a property of the reports alone, so it DOES carry over from
        plain DA -- unlike stability below. Asserted, not assumed."""
        for prec in (PRECEDENCE_RESERVE_FIRST, PRECEDENCE_OPEN_FIRST):
            res = reserve_da(self.market, self.profile, self.config(prec))
            ok, reasons = is_individually_rational(
                self.market, self.profile, res.priorities, res.assignment
            )
            self.assertTrue(ok, reasons)

    def test_flat_stability_oracle_does_not_apply_to_this_mechanism(self):
        """A DELIBERATE non-inheritance check.

        `witness.oracles.is_stable` defines a blocking pair against a school's
        single flat priority order. Under a slot structure that definition is
        the wrong one: m1 outranks r2 at c1 and prefers c1 to c2, so (m1, c1)
        blocks in the flat sense -- yet the outcome is exactly what the
        published choice rule produces, because m1 has no claim on a RESERVE
        seat over an eligible student.

        So the flat oracle reports this mechanism as unstable, correctly by
        its own definition and uselessly as a correctness check. This test
        pins that fact so nobody later wires the flat oracle in as a
        validation of reserve_da and reads the failures as bugs. A slot-aware
        fairness oracle is required before stability can be checked here at
        all, and it does not exist yet.
        """
        res = reserve_da(self.market, self.profile, self.config(PRECEDENCE_OPEN_FIRST))
        pairs = blocking_pairs(
            self.market, self.profile, res.priorities, res.assignment
        )
        self.assertIn(("m1", "c1"), pairs)
        self.assertFalse(
            is_stable(self.market, self.profile, res.priorities, res.assignment)
        )


class ResDNegativeControl(unittest.TestCase):
    """RES-D. DKPS state that the choice functions in this setting satisfy
    Hatfield-Milgrom substitutability and Aygun-Sonmez irrelevance of rejected
    contracts (their footnote 19), and that the resulting student-proposing DA
    mechanism is strategy-proof (their section 5, on the BPS match).

    So an exhaustive search over every student's full report space must find
    NOTHING -- under both precedence orders and both reserve semantics. This
    is the negative control extended to a new mechanism, and it is the test
    that would catch a slot rule that quietly depends on the reports.
    """

    def markets(self):
        order = ("r1", "m1", "r2", "m2")
        market = Market(
            students=order,
            schools=("c1", "c2"),
            capacities={"c1": 2, "c2": 1},
            priority_classes={"c1": singles(order), "c2": singles(order)},
        )
        profile = Profile(
            {
                "r1": ("c1", "c2"),
                "m1": ("c1", "c2"),
                "r2": ("c1", "c2"),
                "m2": ("c1", "c2"),
            }
        )
        return market, profile

    def test_no_manipulation_under_any_setting(self):
        market, profile = self.markets()
        reserves = {"c1": SchoolReserve(reserved_seats=1, eligible=("r1", "r2"))}
        checked = 0
        for prec in (PRECEDENCE_RESERVE_FIRST, PRECEDENCE_OPEN_FIRST):
            for rtype in (RESERVE_SOFT, RESERVE_HARD):
                cfg = ReserveConfig(
                    reserves=reserves, reserve_type=rtype, precedence=prec
                )
                for student in market.students:
                    found = find_all_manipulations(
                        market, profile, student, "reserve_da", cfg
                    )
                    self.assertEqual(
                        found,
                        (),
                        f"reserve_da is strategy-proof, but the search found a "
                        f"manipulation for {student!r} under precedence={prec!r}, "
                        f"reserve_type={rtype!r}",
                    )
                    checked += 1
        self.assertEqual(checked, 16)

    def test_no_manipulation_when_eligible_students_are_scarce(self):
        """RES-D's first market can never exercise an unfillable reserve: c1
        reserves one seat and always has an eligible applicant for it, so an
        entire branch of the choice rule goes untested there.

        This closes that gap -- c1 reserves BOTH its seats while only one or
        two students qualify -- and it is not a decorative addition. A
        deliberately non-substitutable variant of the choice rule (one that
        rejects the whole pool when it cannot fill its reserve with eligible
        students, a real and bad reserve design) is INERT on the market above,
        but produces 72 profitable manipulations across the configurations
        below. So this is the shape in which this negative control has teeth.
        """
        order = ("r1", "r2", "m1", "m2")
        schools = ("c1", "c2")
        profile = Profile(
            {
                "r1": ("c1", "c2"),
                "r2": ("c2", "c1"),
                "m1": ("c1", "c2"),
                "m2": ("c1", "c2"),
            }
        )
        checked = 0
        for eligible in (("r1",), ("r1", "r2")):
            for prio in itertools.permutations(order):
                market = Market(
                    students=order,
                    schools=schools,
                    capacities={"c1": 2, "c2": 1},
                    priority_classes={c: singles(prio) for c in schools},
                )
                for prec in (PRECEDENCE_RESERVE_FIRST, PRECEDENCE_OPEN_FIRST):
                    cfg = ReserveConfig(
                        reserves={"c1": SchoolReserve(2, eligible)},
                        reserve_type=RESERVE_SOFT,
                        precedence=prec,
                    )
                    for student in order:
                        self.assertEqual(
                            find_all_manipulations(
                                market, profile, student, "reserve_da", cfg
                            ),
                            (),
                            f"manipulation for {student!r} with eligible="
                            f"{eligible!r}, priority={prio!r}, precedence={prec!r}",
                        )
                        checked += 1
        self.assertEqual(checked, 2 * 24 * 2 * 4)


class ResEPaperExample(unittest.TestCase):
    """RES-E. DKPS Figure 1 / section 2, at the paper's own numbers.

    The paper's stylised school: 100 seats split 50 walk-zone / 50 open, 100
    walk-zone applicants and 100 non-walk applicants, and a lottery in which
    the two groups alternate (so the top 100 contains 50 of each). The paper
    states two outcomes:

      walk-zone seats first  ->  50 walk-zone and 50 non-walk admitted
                                 (the 50/50 split reproduces the outcome of
                                 having NO walk-zone priority at all -- the
                                 "unintended consequence" of the title)
      open seats first       ->  75 walk-zone and 25 non-walk admitted

    Both numbers are quoted from the paper, not computed here. The alternating
    master order is the paper's stated stylisation, written out explicitly.
    """

    def build(self, precedence):
        walk = [f"w{i}" for i in range(1, 101)]
        non = [f"n{i}" for i in range(1, 101)]
        # The lottery: strictly alternating, w1, n1, w2, n2, ...
        order = tuple(x for pair in zip(walk, non) for x in pair)
        market = Market(
            students=order,
            schools=("a",),
            capacities={"a": 100},
            priority_classes={"a": singles(order)},
        )
        profile = Profile({s: ("a",) for s in order})
        cfg = ReserveConfig(
            reserves={"a": SchoolReserve(reserved_seats=50, eligible=tuple(walk))},
            reserve_type=RESERVE_SOFT,
            precedence=precedence,
        )
        return market, profile, cfg

    def test_reserve_first_gives_fifty_fifty(self):
        market, profile, cfg = self.build(PRECEDENCE_RESERVE_FIRST)
        res = reserve_da(market, profile, cfg)
        roster = res.assignment.roster("a")
        self.assertEqual(len(roster), 100)
        self.assertEqual(
            reserve_seats_used(market, res.priorities, cfg, "a", roster), (50, 50)
        )

    def test_open_first_gives_seventy_five_twenty_five(self):
        market, profile, cfg = self.build(PRECEDENCE_OPEN_FIRST)
        res = reserve_da(market, profile, cfg)
        roster = res.assignment.roster("a")
        self.assertEqual(len(roster), 100)
        self.assertEqual(
            reserve_seats_used(market, res.priorities, cfg, "a", roster), (75, 25)
        )


class ReserveStructureValidation(unittest.TestCase):
    def test_reserved_seats_cannot_exceed_capacity(self):
        market = Market(
            students=("a", "b"),
            schools=("c1",),
            capacities={"c1": 1},
            priority_classes={"c1": singles(("a", "b"))},
        )
        cfg = ReserveConfig(reserves={"c1": SchoolReserve(reserved_seats=2, eligible=("a",))})
        with self.assertRaises(ModelError):
            reserve_da(market, Profile({"a": ("c1",), "b": ("c1",)}), cfg)

    def test_unknown_school_and_student_are_rejected(self):
        market = Market(
            students=("a",),
            schools=("c1",),
            capacities={"c1": 1},
            priority_classes={"c1": singles(("a",))},
        )
        profile = Profile({"a": ("c1",)})
        with self.assertRaises(ModelError):
            reserve_da(
                market, profile,
                ReserveConfig(reserves={"nope": SchoolReserve(1, ("a",))}),
            )
        with self.assertRaises(ModelError):
            reserve_da(
                market, profile,
                ReserveConfig(reserves={"c1": SchoolReserve(1, ("ghost",))}),
            )

    def test_slot_sequence_lengths(self):
        self.assertEqual(slot_sequence(3, 0, PRECEDENCE_RESERVE_FIRST), (SLOT_OPEN,) * 3)
        self.assertEqual(slot_sequence(3, 3, PRECEDENCE_OPEN_FIRST), (SLOT_RESERVE,) * 3)
        self.assertEqual(
            slot_sequence(3, 1, PRECEDENCE_OPEN_FIRST),
            (SLOT_OPEN, SLOT_OPEN, SLOT_RESERVE),
        )


if __name__ == "__main__":
    unittest.main()
