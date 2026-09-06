"""Hand-worked examples for Top Trading Cycles (witness.ttc).

Every expected value in this file was derived BY HAND on paper from the
published algorithm in Abdulkadiroglu & Sonmez (2003), "School Choice: A
Mechanism Design Approach", AER 93(3):729-747, section on the Top Trading
Cycles Mechanism -- and written down BEFORE witness/ttc.py existed. DO NOT
change an expected value to make a test pass: a disagreement here is a
finding about the implementation.

The algorithm, as hand-transcribed from A&S before coding:

    Each school starts with a counter equal to its capacity. Each remaining
    student points to her favourite remaining school; each remaining school
    points to the remaining student with highest priority. The graph has
    out-degree exactly 1 at every node, so at least one cycle exists. Every
    student in a cycle is assigned the school she points to and is removed;
    that school's counter drops by one, and the school is removed when its
    counter reaches zero. Repeat until no students remain.

Two extensions A&S do not need but this codebase does, because it models
acceptability on both sides (`unlisted_student_policy`):

  * a student points to her favourite remaining school THAT FINDS HER
    ACCEPTABLE. Pointing at a school that can never take her would stall her
    forever behind a school that may never fill.
  * a school with no acceptable remaining student cannot point at all, so it
    is removed and its seats stay empty.

Both prunings are iterated to a fixed point at the start of each step, which
is what restores the "out-degree exactly 1 everywhere" precondition that
makes the existence of a cycle a theorem rather than a hope.

TTC-A  the textbook separation from DA: TTC's outcome PARETO-DOMINATES DA's
       here, and TTC's outcome has a blocking pair while DA's has none. This
       is the shape that catches implementing DA twice under two names.
TTC-B  capacity > 1: a school survives a cycle with a seat left and is
       assigned again in a later step.
TTC-C  a student whose whole list is consumed goes unmatched, and a school
       that finds nobody acceptable is removed with its seat unfilled.
TTC-C2 acceptability gates the POINTER, not just the assignment: each
       student's first choice is a school that will not have her.
TTC-D  the negative control: TTC is strategy-proof, so an exhaustive search
       must return nothing -- including for a student who is unmatched when
       truthful and therefore has maximal incentive to deviate.

Priority classes are singletons throughout (RejectTies never has to fire), so
every priority order below is the exact order written down.
"""

from __future__ import annotations

import unittest

from witness.core import UNLISTED_UNACCEPTABLE, Market, Profile, resolve_priorities
from witness.da import DAConfig, deferred_acceptance
from witness.oracles import blocking_pairs, is_stable
from witness.search import find_all_manipulations, misreport_space
from witness.ttc import (
    CYCLES_ONE_AT_A_TIME_DECLARED_ORDER,
    TTCConfig,
    top_trading_cycles,
)


def singles(order):
    """A strict order as singleton priority classes."""
    return tuple((s,) for s in order)


class TtcASeparatesTtcFromDa(unittest.TestCase):
    """TTC-A. Three students, three unit-capacity schools.

    reports      s1: b a c      s2: a b c      s3: a b c
    priorities   a: s1 s3 s2    b: s2 s1 s3    c: s2 s1 s3

    HAND TRACE (TTC)
      step 1  points: s1->b  s2->a  s3->a ; a->s1  b->s2  c->s2
              walk from s1: s1 -> b -> s2 -> a -> s1  CYCLE
              s3 and c both lead into that cycle without lying on it.
              assign s1=b, s2=a. a and b both hit 0 seats, removed.
      step 2  points: s3->c ; c->s3     CYCLE (2-cycle)
              assign s3=c. c hits 0 seats.
      result  s1->b  s2->a  s3->c

    HAND TRACE (DA, student-proposing, for the comparison below)
      r1  s1->b s2->a s3->a ; a holds s3 (a: s1 s3 s2) rejects s2 ; b holds s1
      r2  s2->b ; b holds s2 (b: s2 s1 s3) rejects s1
      r3  s1->a ; a holds s1 rejects s3
      r4  s3->b ; b keeps s2, rejects s3
      r5  s3->c ; c holds s3
      result  s1->a  s2->b  s3->c        (7 proposals)

    So on this instance TTC gives s1 and s2 their FIRST choices where DA gives
    each of them their second, and leaves s3 identical. That is a strict
    Pareto improvement, which is the published reason TTC exists.
    """

    def setUp(self):
        self.market = Market(
            students=("s1", "s2", "s3"),
            schools=("a", "b", "c"),
            capacities={"a": 1, "b": 1, "c": 1},
            priority_classes={
                "a": singles(("s1", "s3", "s2")),
                "b": singles(("s2", "s1", "s3")),
                "c": singles(("s2", "s1", "s3")),
            },
        )
        self.profile = Profile(
            {"s1": ("b", "a", "c"), "s2": ("a", "b", "c"), "s3": ("a", "b", "c")}
        )
        self.config = TTCConfig(unlisted_student_policy=UNLISTED_UNACCEPTABLE)

    def test_assignment_matches_the_hand_trace(self):
        result = top_trading_cycles(self.market, self.profile, self.config)
        self.assertEqual(
            result.assignment.student_to_school,
            {"s1": "b", "s2": "a", "s3": "c"},
            msg="\n" + result.format_trace(),
        )
        self.assertEqual(result.assignment.school_to_students["a"], ("s2",))
        self.assertEqual(result.assignment.school_to_students["b"], ("s1",))
        self.assertEqual(result.assignment.school_to_students["c"], ("s3",))

    def test_step_structure_matches_the_hand_trace(self):
        result = top_trading_cycles(self.market, self.profile, self.config)
        self.assertEqual(len(result.steps), 2, msg="\n" + result.format_trace())

        step1 = result.steps[0]
        self.assertEqual(
            step1.student_points_to, (("s1", "b"), ("s2", "a"), ("s3", "a"))
        )
        self.assertEqual(
            step1.school_points_to, (("a", "s1"), ("b", "s2"), ("c", "s2"))
        )
        # one cycle, written from the earliest student in declared order:
        # s1 -> b -> s2 -> a -> s1
        self.assertEqual(step1.cycles, ((("s1", "b"), ("s2", "a")),))
        self.assertEqual(step1.assigned, (("s1", "b"), ("s2", "a")))
        self.assertEqual(step1.filled_schools, ("a", "b"))
        self.assertEqual(step1.exhausted_students, ())
        self.assertEqual(step1.closed_schools, ())
        self.assertEqual(step1.seats_left_after, (("c", 1),))

        step2 = result.steps[1]
        self.assertEqual(step2.student_points_to, (("s3", "c"),))
        self.assertEqual(step2.school_points_to, (("c", "s3"),))
        self.assertEqual(step2.cycles, ((("s3", "c"),),))
        self.assertEqual(step2.filled_schools, ("c",))
        self.assertEqual(step2.seats_left_after, ())

    def test_ttc_pareto_dominates_da_here(self):
        """The whole point of the mechanism, pinned as an assertion.

        Not 'TTC differs from DA' -- that would also pass if TTC were merely
        wrong. Two named students must be STRICTLY better off and nobody
        worse, evaluated against the truthful reports.
        """
        ttc = top_trading_cycles(self.market, self.profile, self.config).assignment
        da = deferred_acceptance(
            self.market,
            self.profile,
            DAConfig(unlisted_student_policy=UNLISTED_UNACCEPTABLE),
        ).assignment

        self.assertEqual(da.student_to_school, {"s1": "a", "s2": "b", "s3": "c"})

        def rank(student, assignment):
            return self.profile.report(student).index(assignment.of(student))

        self.assertEqual((rank("s1", ttc), rank("s1", da)), (0, 1))
        self.assertEqual((rank("s2", ttc), rank("s2", da)), (0, 1))
        self.assertEqual((rank("s3", ttc), rank("s3", da)), (2, 2))

    def test_ttc_outcome_is_unstable_and_the_blocking_pair_is_named(self):
        """TTC is Pareto efficient but NOT stable. The flat stability oracle
        therefore does NOT apply to this mechanism, and this test pins the
        exact justified-envy pair rather than merely asserting 'not stable' --
        an implementation that produced some *other* unstable matching would
        pass the weaker check.

        s3 holds c but ranks a higher, and a ranks s3 (2nd) above the s2 it
        actually holds (3rd). That is the only such pair here.
        """
        priorities = resolve_priorities(self.market, self.config)
        ttc = top_trading_cycles(self.market, self.profile, self.config).assignment
        da = deferred_acceptance(
            self.market,
            self.profile,
            DAConfig(unlisted_student_policy=UNLISTED_UNACCEPTABLE),
        ).assignment

        self.assertEqual(
            blocking_pairs(self.market, self.profile, priorities, ttc), (("s3", "a"),)
        )
        self.assertFalse(is_stable(self.market, self.profile, priorities, ttc))
        # ... and DA's outcome on the SAME instance is stable, so the oracle
        # itself is not simply broken.
        self.assertTrue(is_stable(self.market, self.profile, priorities, da))


class TtcBCapacityGreaterThanOne(unittest.TestCase):
    """TTC-B. a has capacity 2 and must SURVIVE its first cycle.

    reports      s1: a b c   s2: b a c   s3: a b c   s4: a c b
    priorities   a: s2 s1 s3 s4   b: s1 s3 s2 s4   c: s4 s1 s2 s3
    capacities   a=2  b=1  c=1

    HAND TRACE
      step 1  points: s1->a s2->b s3->a s4->a ; a->s2 b->s1 c->s4
              walk from s1: s1 -> a -> s2 -> b -> s1   CYCLE
              assign s1=a, s2=b.
              a: 2 seats -> 1, SURVIVES.  b: 1 -> 0, removed.
      step 2  remaining students s3 s4 ; schools a(1) c(1)
              points: s3->a s4->a ; a->s3 c->s4
              walk from s3: s3 -> a -> s3   CYCLE (2-cycle)
              assign s3=a. a: 1 -> 0, removed. s4 leads in but does not lie on it.
      step 3  points: s4->c ; c->s4   CYCLE
              assign s4=c.
      result  s1->a  s2->b  s3->a  s4->c    with a's roster = (s1, s3)

    a's roster order is a's own priority order (s2 s1 s3 s4), so s1 precedes
    s3 -- not insertion order, which would also be (s1, s3) here, and not
    sorted order, which would too. The distinguishing check is that the
    roster is built by `build_assignment`'s declared convention at all.
    """

    def setUp(self):
        self.market = Market(
            students=("s1", "s2", "s3", "s4"),
            schools=("a", "b", "c"),
            capacities={"a": 2, "b": 1, "c": 1},
            priority_classes={
                "a": singles(("s2", "s1", "s3", "s4")),
                "b": singles(("s1", "s3", "s2", "s4")),
                "c": singles(("s4", "s1", "s2", "s3")),
            },
        )
        self.profile = Profile(
            {
                "s1": ("a", "b", "c"),
                "s2": ("b", "a", "c"),
                "s3": ("a", "b", "c"),
                "s4": ("a", "c", "b"),
            }
        )
        self.config = TTCConfig(unlisted_student_policy=UNLISTED_UNACCEPTABLE)

    def test_assignment_matches_the_hand_trace(self):
        result = top_trading_cycles(self.market, self.profile, self.config)
        self.assertEqual(
            result.assignment.student_to_school,
            {"s1": "a", "s2": "b", "s3": "a", "s4": "c"},
            msg="\n" + result.format_trace(),
        )
        self.assertEqual(result.assignment.school_to_students["a"], ("s1", "s3"))

    def test_school_a_survives_its_first_cycle_with_one_seat_left(self):
        result = top_trading_cycles(self.market, self.profile, self.config)
        self.assertEqual(len(result.steps), 3, msg="\n" + result.format_trace())

        step1 = result.steps[0]
        self.assertEqual(step1.cycles, ((("s1", "a"), ("s2", "b")),))
        self.assertEqual(step1.filled_schools, ("b",))
        self.assertEqual(step1.seats_left_after, (("a", 1), ("c", 1)))

        step2 = result.steps[1]
        self.assertEqual(step2.cycles, ((("s3", "a"),),))
        self.assertEqual(step2.filled_schools, ("a",))
        self.assertEqual(step2.seats_left_after, (("c", 1),))

        step3 = result.steps[2]
        self.assertEqual(step3.cycles, ((("s4", "c"),),))
        self.assertEqual(step3.filled_schools, ("c",))


class TtcCUnmatchedAndUnreachable(unittest.TestCase):
    """TTC-C. Two removals that A&S's own statement does not cover.

    students  s1 s2 s3       schools  a(1) b(1) d(1)
    reports   s1: a          s2: b... no -- s2: b is NOT its first choice; see below
              s1: (a,)   s2: (a, b)   s3: (a,)
    priorities  a: s1 s2 s3    b: s2 s1 s3    d: (nobody -- empty priority classes)

    d is offered but finds NO student acceptable, and nobody ranks it.

    HAND TRACE
      step 1  prune: d has no acceptable remaining student -> CLOSED, seat unfilled.
              points: s1->a s2->a s3->a ; a->s1  b->s2
              walk from s1: s1 -> a -> s1  CYCLE
              assign s1=a. a: 1 -> 0, removed.
      step 2  prune: s3's list is (a,) and a is gone -> EXHAUSTED, unmatched.
              points: s2->b ; b->s2   CYCLE
              assign s2=b. b: 1 -> 0.
      result  s1->a  s2->b  s3->unmatched, d empty

    Without the student-side prune, s3 would point at nothing and the
    'a cycle always exists' guarantee would be false. Without the school-side
    prune, d would point at nothing and the same guarantee would fail. Both
    failures are silent-hang shaped, not wrong-answer shaped, which is why
    they get a named test.
    """

    def setUp(self):
        self.market = Market(
            students=("s1", "s2", "s3"),
            schools=("a", "b", "d"),
            capacities={"a": 1, "b": 1, "d": 1},
            priority_classes={
                "a": singles(("s1", "s2", "s3")),
                "b": singles(("s2", "s1", "s3")),
                "d": (),
            },
        )
        self.profile = Profile({"s1": ("a",), "s2": ("a", "b"), "s3": ("a",)})
        self.config = TTCConfig(unlisted_student_policy=UNLISTED_UNACCEPTABLE)

    def test_assignment_matches_the_hand_trace(self):
        result = top_trading_cycles(self.market, self.profile, self.config)
        self.assertEqual(
            result.assignment.student_to_school,
            {"s1": "a", "s2": "b", "s3": None},
            msg="\n" + result.format_trace(),
        )
        self.assertEqual(result.assignment.school_to_students["d"], ())
        self.assertEqual(result.assignment.unmatched(self.market), ("s3",))

    def test_both_prunes_are_recorded_in_the_right_steps(self):
        result = top_trading_cycles(self.market, self.profile, self.config)
        self.assertEqual(len(result.steps), 2, msg="\n" + result.format_trace())

        step1 = result.steps[0]
        self.assertEqual(step1.closed_schools, ("d",))
        self.assertEqual(step1.exhausted_students, ())
        self.assertEqual(step1.cycles, ((("s1", "a"),),))

        step2 = result.steps[1]
        self.assertEqual(step2.exhausted_students, ("s3",))
        self.assertEqual(step2.closed_schools, ())
        self.assertEqual(step2.cycles, ((("s2", "b"),),))


class TtcDNegativeControl(unittest.TestCase):
    """TTC-D. TTC is strategy-proof (A&S 2003, Theorem 1), so an exhaustive
    search over every ordered subset of the schools must find NOTHING.

    reports     s1: a b c   s2: b a c   s3: a c b   s4: c b a
    priorities  a: s3 s1 s4 s2   b: s1 s2 s3 s4   c: s2 s4 s1 s3
    capacities  a=b=c=1, so with four students exactly one goes unmatched.

    HAND TRACE (truthful)
      step 1  points s1->a s2->b s3->a s4->c ; a->s3 b->s1 c->s2
              a -> s3 -> a  CYCLE.  assign s3=a, a removed.
      step 2  points s1->b s2->b s4->c ; b->s1 c->s2
              b -> s1 -> b  CYCLE.  assign s1=b, b removed.
      step 3  points s2->c s4->c ; c->s2
              c -> s2 -> c  CYCLE.  assign s2=c, c removed.
      step 4  s4's list is consumed -> unmatched.
      result  s1->b  s2->c  s3->a  s4->unmatched

    s4 is the interesting target: unmatched when truthful, so ANY seat is an
    improvement and the incentive to deviate is maximal. Strategy-proofness
    still has to hold for s4, and by hand it does -- s4 never lies on a cycle,
    so s4's report cannot change anyone else's pointer, and every school fills
    from students s4 cannot outrank at it.
    """

    def setUp(self):
        self.market = Market(
            students=("s1", "s2", "s3", "s4"),
            schools=("a", "b", "c"),
            capacities={"a": 1, "b": 1, "c": 1},
            priority_classes={
                "a": singles(("s3", "s1", "s4", "s2")),
                "b": singles(("s1", "s2", "s3", "s4")),
                "c": singles(("s2", "s4", "s1", "s3")),
            },
        )
        self.profile = Profile(
            {
                "s1": ("a", "b", "c"),
                "s2": ("b", "a", "c"),
                "s3": ("a", "c", "b"),
                "s4": ("c", "b", "a"),
            }
        )
        self.config = TTCConfig(unlisted_student_policy=UNLISTED_UNACCEPTABLE)

    def test_truthful_outcome_matches_the_hand_trace(self):
        result = top_trading_cycles(self.market, self.profile, self.config)
        self.assertEqual(
            result.assignment.student_to_school,
            {"s1": "b", "s2": "c", "s3": "a", "s4": None},
            msg="\n" + result.format_trace(),
        )

    def test_no_student_can_manipulate(self):
        for target in self.market.students:
            with self.subTest(target=target):
                found = find_all_manipulations(
                    self.market, self.profile, target, "top_trading_cycles", self.config
                )
                self.assertEqual(
                    found,
                    (),
                    msg=f"{target} manipulated a strategy-proof mechanism: {found}",
                )

    def test_the_unmatched_student_specifically_cannot_manipulate(self):
        """Called out separately from the loop above because 'nobody gained'
        is a much weaker claim when the only students tested already held
        their first choice. s4 holds nothing."""
        self.assertIsNone(
            top_trading_cycles(
                self.market, self.profile, self.config
            ).assignment.of("s4")
        )
        self.assertEqual(
            find_all_manipulations(
                self.market, self.profile, "s4", "top_trading_cycles", self.config
            ),
            (),
        )

    def test_the_search_is_not_vacuous(self):
        """REVIEWER.md: a clean negative control is worthless if the search
        space never moved anything. Misreports MUST be able to change a
        student's own outcome here -- they just can never improve it. This
        measures both, and asserts the mechanism is genuinely responsive.
        """
        truthful = top_trading_cycles(
            self.market, self.profile, self.config
        ).assignment

        changed = 0
        strictly_worse = 0
        for target in self.market.students:
            true_report = self.profile.report(target)
            for false_report in misreport_space(self.market, target, true_report):
                outcome = top_trading_cycles(
                    self.market,
                    self.profile.with_report(target, false_report),
                    self.config,
                ).assignment.of(target)
                if outcome != truthful.of(target):
                    changed += 1
                    honest = truthful.of(target)
                    # WORST-style comparison against the TRUTHFUL report.
                    def rank(school):
                        if school is None:
                            return len(true_report)
                        try:
                            return true_report.index(school)
                        except ValueError:
                            return len(true_report)

                    if rank(outcome) > rank(honest):
                        strictly_worse += 1

        self.assertGreater(
            changed, 0, "no misreport changed any outcome: the control is vacuous"
        )
        self.assertGreater(
            strictly_worse,
            0,
            "no misreport made anyone worse off: the search has no teeth",
        )


class TtcC2AcceptabilityGatesThePointer(unittest.TestCase):
    """TTC-C2. Each student's FIRST choice is a school that will not have her.

    students  s1 s2        schools  a(1) b(1)
    reports   s1: (a, b)   s2: (b, a)
    priorities  a: (s2,)   b: (s1,)      <- singleton lists, so under
    UNLISTED_UNACCEPTABLE s1 is unacceptable to a and s2 is unacceptable to b.

    HAND TRACE
      step 1  s1 skips a (a will not have her) and points to b.
              s2 skips b (b will not have him) and points to a.
              a -> s2 (its only acceptable student), b -> s1.
              TWO disjoint cycles now exist in the same step:
                  s1 -> b -> s1     and     s2 -> a -> s2
              assign s1=b, s2=a. Both schools fill.
      result  s1->b  s2->a -- each takes her second choice, because the first
              was never available to her in the first place.

    This case exists because a mutation survived without it. Dropping the
    acceptability test from the student pointer leaves s1 pointing at a and s2
    pointing at b, which closes the four-node cycle s1 -> a -> s2 -> b -> s1
    and hands s1 a seat at a school that finds her unacceptable. Every other
    hand-worked case here masks that: whenever a stalled student's target has
    no acceptable students left, the SCHOOL-side prune removes it and the
    student moves on with the right answer anyway. Only a mutual stall, where
    each school still holds an acceptable student who is himself stalled,
    turns the missing check into a wrong assignment rather than a slower path
    to the right one.

    It is also the first case with two cycles in a single step, which is what
    makes the cycle-policy invariance check (test_ttc_properties) non-vacuous.
    """

    def setUp(self):
        self.market = Market(
            students=("s1", "s2"),
            schools=("a", "b"),
            capacities={"a": 1, "b": 1},
            priority_classes={"a": (("s2",),), "b": (("s1",),)},
        )
        self.profile = Profile({"s1": ("a", "b"), "s2": ("b", "a")})
        self.config = TTCConfig(unlisted_student_policy=UNLISTED_UNACCEPTABLE)

    def test_assignment_matches_the_hand_trace(self):
        result = top_trading_cycles(self.market, self.profile, self.config)
        self.assertEqual(
            result.assignment.student_to_school,
            {"s1": "b", "s2": "a"},
            msg="\n" + result.format_trace(),
        )

    def test_two_disjoint_cycles_are_found_in_one_step(self):
        result = top_trading_cycles(self.market, self.profile, self.config)
        self.assertEqual(len(result.steps), 1, msg="\n" + result.format_trace())
        self.assertEqual(
            result.steps[0].cycles, ((("s1", "b"),), (("s2", "a"),))
        )
        self.assertEqual(result.steps[0].student_points_to, (("s1", "b"), ("s2", "a")))
        self.assertEqual(result.steps[0].school_points_to, (("a", "s2"), ("b", "s1")))

    def test_one_cycle_at_a_time_takes_two_steps_for_the_same_answer(self):
        one = top_trading_cycles(
            self.market,
            self.profile,
            TTCConfig(
                unlisted_student_policy=UNLISTED_UNACCEPTABLE,
                cycle_policy=CYCLES_ONE_AT_A_TIME_DECLARED_ORDER,
            ),
        )
        allc = top_trading_cycles(self.market, self.profile, self.config)
        self.assertEqual(len(one.steps), 2, msg="\n" + one.format_trace())
        self.assertEqual(one.assignment, allc.assignment)


if __name__ == "__main__":
    unittest.main()
