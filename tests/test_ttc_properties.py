"""Properties of Top Trading Cycles that hold across generated instances.

These are the checks that would be too weak as a single hand-worked example:
invariance under a provably-inert setting, efficiency, strategy-proofness at
volume, and survival of a serialization round-trip in a FRESH interpreter.

Every "0 manipulations" style claim here is paired with a non-vacuity
measurement, because REVIEWER.md is explicit that a control which never moved
anything is not a passing control -- it is an untested one.
"""

from __future__ import annotations

import itertools
import json
import subprocess
import sys
import unittest

from witness.core import WORST, Market, Profile, position, resolve_priorities
from witness.da import DAConfig, deferred_acceptance
from witness.generate import (
    MECHANISM_TOP_TRADING_CYCLES,
    TIEBREAK_MTB,
    TIEBREAK_STB,
    GeneratorConfig,
    generate_config,
    generate_instance,
)
from witness.search import find_all_manipulations, misreport_space
from witness.oracles import blocking_pairs
from witness.ttc import (
    CYCLES_ALL_SIMULTANEOUS,
    distinct_priority_orders,
    ttc_differs_from_da_iff_unstable,
    CYCLES_ONE_AT_A_TIME_DECLARED_ORDER,
    TTCConfig,
    top_trading_cycles,
)


def instances(n, *, n_students=5, n_schools=3, seed="ttc-props", **kw):
    """`n` generated (market, profile, config) triples for TTC.

    `tiebreak_family` defaults to MTB here, NOT to the generator's own STB
    default, and that is deliberate. Under STB with one priority class every
    school ends up with the identical priority order, and TTC then provably
    degenerates into serial dictatorship -- the same mechanism DA degenerates
    into, so every test below would pass while testing nothing about TTC.
    See `witness.ttc.distinct_priority_orders`, and the pinned degeneracy in
    `CommonPriorityOrderDegeneracy` at the bottom of this file.
    """
    kw.setdefault("tiebreak_family", TIEBREAK_MTB)
    gc = GeneratorConfig(
        n_students=n_students, n_schools=n_schools, seed=seed, **kw
    )
    for i in range(n):
        market, profile = generate_instance(gc, i)
        config = generate_config(gc, i, MECHANISM_TOP_TRADING_CYCLES)
        yield market, profile, config


class CyclePolicyCannotChangeTheOutcome(unittest.TestCase):
    """Within a step the cycles are vertex-disjoint and independent, so the
    order in which they are executed provably cannot change the assignment.

    This is the same discipline `DAConfig.proposal_policy` gets: the setting
    exists precisely so that "provably cannot" can be checked rather than
    assumed, because the proof is about the published algorithm and not about
    this code.
    """

    def test_both_policies_agree_on_every_generated_instance(self):
        checked = 0
        for market, profile, config in instances(300):
            a = top_trading_cycles(
                market, profile, TTCConfig(
                    tiebreak=config.tiebreak,
                    unlisted_student_policy=config.unlisted_student_policy,
                    cycle_policy=CYCLES_ALL_SIMULTANEOUS,
                )
            ).assignment
            b = top_trading_cycles(
                market, profile, TTCConfig(
                    tiebreak=config.tiebreak,
                    unlisted_student_policy=config.unlisted_student_policy,
                    cycle_policy=CYCLES_ONE_AT_A_TIME_DECLARED_ORDER,
                )
            ).assignment
            self.assertEqual(a, b, msg=f"cycle policy changed the outcome")
            checked += 1
        self.assertEqual(checked, 300)

    def test_the_invariance_is_not_vacuous(self):
        """If no generated instance ever produced a step with two or more
        cycles, the two policies would be executing identical code paths and
        the agreement above would mean nothing. This measures that they do
        diverge, and by how much."""
        multi_cycle_steps = 0
        instances_with_multi = 0
        step_count_differs = 0
        for market, profile, config in instances(300):
            allc = top_trading_cycles(
                market, profile, TTCConfig(
                    tiebreak=config.tiebreak,
                    unlisted_student_policy=config.unlisted_student_policy,
                    cycle_policy=CYCLES_ALL_SIMULTANEOUS,
                )
            )
            one = top_trading_cycles(
                market, profile, TTCConfig(
                    tiebreak=config.tiebreak,
                    unlisted_student_policy=config.unlisted_student_policy,
                    cycle_policy=CYCLES_ONE_AT_A_TIME_DECLARED_ORDER,
                )
            )
            n = sum(1 for st in allc.steps if len(st.cycles) >= 2)
            multi_cycle_steps += n
            if n:
                instances_with_multi += 1
            if len(one.steps) != len(allc.steps):
                step_count_differs += 1

        self.assertGreater(
            instances_with_multi,
            0,
            "no instance ever had a step with 2+ cycles: the two cycle "
            "policies never actually diverged, so their agreement is vacuous",
        )
        self.assertGreater(
            step_count_differs,
            0,
            "the two policies always took the same number of steps, so they "
            "were not really running different code paths",
        )


class TtcIsNotAccidentallyDa(unittest.TestCase):
    """A TTC that silently reduced to DA would pass every strategy-proofness
    test in this file, since DA is strategy-proof too. So the suite has to
    prove the two mechanisms actually differ at volume.

    NOTE ON DOUBLE COUNTING. The rate measured here is the SAME NUMBER as the
    rate at which TTC's outcome is unstable -- they are provably identical
    (see `DifferingFromDaIsExactlyInstability` below). Do not report them as
    two independent pieces of evidence.
    """

    def test_ttc_and_da_disagree_on_a_real_fraction_of_instances(self):
        differ = 0
        total = 0
        for market, profile, config in instances(300):
            ttc = top_trading_cycles(market, profile, config).assignment
            da = deferred_acceptance(
                market,
                profile,
                DAConfig(
                    tiebreak=config.tiebreak,
                    unlisted_student_policy=config.unlisted_student_policy,
                ),
            ).assignment
            total += 1
            if ttc != da:
                differ += 1
        self.assertEqual(total, 300)
        self.assertGreater(
            differ,
            30,
            f"TTC differed from DA on only {differ}/300 instances; a TTC that "
            f"had collapsed into DA would look like this",
        )

    def test_the_disagreement_rate_is_a_function_of_size_not_a_constant(self):
        """Pins that this rate must never be quoted without a shape attached.

        An earlier version of this project's own documentation described the
        TTC/DA disagreement rate as "roughly 26%" with no qualifier. It is
        nothing of the sort -- it climbs monotonically with instance size,
        and 26% is simply what 5x3 happens to give. An independent
        reproduction flagged this as exactly the failure mode REVIEWER.md
        names under "a surprising rate is a distributional question."
        """
        rates = {}
        for ns, nc in ((3, 3), (10, 5)):
            differ = 0
            for market, profile, config in instances(
                200, n_students=ns, n_schools=nc, seed=f"rate{ns}x{nc}"
            ):
                ttc = top_trading_cycles(market, profile, config).assignment
                da = deferred_acceptance(
                    market,
                    profile,
                    DAConfig(
                        tiebreak=config.tiebreak,
                        unlisted_student_policy=config.unlisted_student_policy,
                    ),
                ).assignment
                differ += ttc != da
            rates[(ns, nc)] = differ / 200
        self.assertLess(rates[(3, 3)], 0.20)
        self.assertGreater(rates[(10, 5)], 0.60)
        self.assertGreater(
            rates[(10, 5)] - rates[(3, 3)],
            0.45,
            f"the rate barely moved with size ({rates}), which would mean the "
            f"size-dependence documented in witness.ttc is wrong",
        )


class DifferingFromDaIsExactlyInstability(unittest.TestCase):
    """A proved invariant, asserted rather than measured.

    TTC's outcome differs from DA's if and only if it has a blocking pair --
    see `witness.ttc.ttc_differs_from_da_iff_unstable` for the proof. This
    was surfaced by an independent reproduction of this mechanism, which
    noticed the two rates coinciding to the digit in all 18 cells of its own
    grid and worked out why. REVIEWER.md: convert a measurement into an
    invariant wherever a proof exists.
    """

    def test_identity_holds_across_shapes(self):
        checked = 0
        both_sides_seen = [0, 0]
        for ns, nc in ((3, 3), (6, 4), (10, 5)):
            for market, profile, config in instances(
                150, n_students=ns, n_schools=nc, seed=f"ident{ns}x{nc}"
            ):
                priorities = resolve_priorities(market, config)
                ttc = top_trading_cycles(
                    market, profile, config, priorities=priorities
                ).assignment
                da = deferred_acceptance(
                    market,
                    profile,
                    DAConfig(
                        tiebreak=config.tiebreak,
                        unlisted_student_policy=config.unlisted_student_policy,
                    ),
                    priorities=priorities,
                ).assignment
                self.assertTrue(
                    ttc_differs_from_da_iff_unstable(
                        ttc, da, market, profile, priorities
                    ),
                    msg=f"identity failed on a {ns}x{nc} instance",
                )
                both_sides_seen[bool(ttc != da)] += 1
                checked += 1
        self.assertEqual(checked, 450)
        # A vacuous pass would be one where every instance sat on the same
        # side of the iff. Both sides must actually occur.
        self.assertGreater(both_sides_seen[0], 0, "TTC never equalled DA")
        self.assertGreater(both_sides_seen[1], 0, "TTC always equalled DA")


class TtcOutputIsWellFormed(unittest.TestCase):
    def test_never_assigns_a_student_to_an_unranked_school(self):
        """Student-side individual rationality. `build_assignment` already
        enforces the SCHOOL side (a school never holds a student it finds
        unacceptable); nothing enforces the student side, so it is asserted
        here rather than assumed."""
        for market, profile, config in instances(300):
            result = top_trading_cycles(market, profile, config)
            for s in market.students:
                got = result.assignment.of(s)
                if got is not None:
                    self.assertIn(
                        got,
                        profile.report(s),
                        msg=f"{s} was assigned {got}, which is not on their list",
                    )

    def test_capacities_are_never_exceeded(self):
        for market, profile, config in instances(300):
            result = top_trading_cycles(market, profile, config)
            for c in market.schools:
                self.assertLessEqual(
                    len(result.assignment.roster(c)), market.capacity(c)
                )


class TtcIsParetoEfficient(unittest.TestCase):
    """No individually-rational assignment makes a student better off without
    making another worse off.

    SCOPE OF THE CLAIM. Abdulkadiroglu & Sonmez prove Pareto efficiency for
    the case where every student is acceptable to every school. This codebase
    also models school-side acceptability, which their statement does not
    cover, so this test MEASURES the property on the restricted-acceptability
    instances the generator actually produces rather than inheriting it. It
    is exhaustive over feasible assignments, which is only affordable at this
    size -- hence the deliberately tiny market.
    """

    def _feasible(self, market, profile, priorities):
        options = []
        for s in market.students:
            allowed = [None] + [
                c for c in profile.report(s) if priorities.acceptable(c, s)
            ]
            options.append(allowed)
        for combo in itertools.product(*options):
            counts = {}
            for c in combo:
                if c is not None:
                    counts[c] = counts.get(c, 0) + 1
            if all(n <= market.capacity(c) for c, n in counts.items()):
                yield dict(zip(market.students, combo))

    def test_no_feasible_assignment_pareto_dominates_ttc(self):
        checked = 0
        for market, profile, config in instances(
            40, n_students=4, n_schools=3, seed="ttc-pareto"
        ):
            priorities = resolve_priorities(market, config)
            ttc = top_trading_cycles(
                market, profile, config, priorities=priorities
            ).assignment
            mine = {
                s: position(profile.report(s), ttc.of(s)) for s in market.students
            }
            for alt in self._feasible(market, profile, priorities):
                theirs = {
                    s: position(profile.report(s), alt[s]) for s in market.students
                }
                better = any(theirs[s] < mine[s] for s in market.students)
                worse = any(theirs[s] > mine[s] for s in market.students)
                self.assertFalse(
                    better and not worse,
                    msg=(
                        f"TTC outcome {ttc.student_to_school} is Pareto-"
                        f"dominated by {alt}"
                    ),
                )
            checked += 1
        self.assertEqual(checked, 40)


class TtcIsStrategyProofAtVolume(unittest.TestCase):
    """The negative control, run wide rather than on one hand-worked market."""

    def test_exhaustive_search_finds_nothing(self):
        instances_checked = 0
        searches = 0
        for market, profile, config in instances(
            60, n_students=5, n_schools=3, seed="ttc-sp"
        ):
            for target in market.students:
                found = find_all_manipulations(
                    market, profile, target, MECHANISM_TOP_TRADING_CYCLES, config
                )
                self.assertEqual(
                    found,
                    (),
                    msg=f"manipulation found in a strategy-proof mechanism: {found}",
                )
                searches += 1
            instances_checked += 1
        self.assertEqual(instances_checked, 60)
        self.assertEqual(searches, 300)

    def test_that_search_was_not_vacuous(self):
        """Same sweep, measuring whether misreports could move anything at
        all. A control over a space where no report ever changed an outcome
        would report a clean 0 and mean nothing."""
        changed = 0
        strictly_worse = 0
        total_reports = 0
        for market, profile, config in instances(
            60, n_students=5, n_schools=3, seed="ttc-sp"
        ):
            truthful = top_trading_cycles(market, profile, config).assignment
            for target in market.students:
                true_report = profile.report(target)
                honest_rank = position(true_report, truthful.of(target))
                for false_report in misreport_space(market, target, true_report):
                    total_reports += 1
                    got = top_trading_cycles(
                        market, profile.with_report(target, false_report), config
                    ).assignment.of(target)
                    if got != truthful.of(target):
                        changed += 1
                        if position(true_report, got) > honest_rank:
                            strictly_worse += 1
        self.assertGreater(total_reports, 3000)
        self.assertGreater(
            changed,
            0,
            "no misreport anywhere changed an outcome: the control is vacuous",
        )
        self.assertGreater(
            strictly_worse,
            0,
            "no misreport anywhere made a student worse off: the search space "
            "cannot distinguish a strategy-proof mechanism from an inert one",
        )


class TtcSurvivesAFreshProcess(unittest.TestCase):
    """REVIEWER.md: a result that only holds inside the interpreter that
    produced it is not a result. The config must round-trip through JSON and
    reproduce the identical assignment in a subprocess that shares no state
    with this one."""

    def test_config_round_trip_reproduces_the_assignment_in_a_subprocess(self):
        market, profile, config = next(
            iter(instances(1, n_students=6, n_schools=4, seed="ttc-replay"))
        )
        here = top_trading_cycles(market, profile, config).assignment.to_dict()

        payload = json.dumps(
            {
                "market": market.to_dict(),
                "profile": profile.to_dict(),
                "config": config.to_dict(),
            }
        )
        script = (
            "import json,sys;"
            "from witness.core import Market, Profile;"
            "from witness.mechanisms import get_mechanism;"
            "d=json.loads(sys.stdin.read());"
            "spec=get_mechanism('top_trading_cycles');"
            "cfg=spec.config_from_dict(d['config']);"
            "m=Market.from_dict(d['market']);"
            "p=Profile.from_dict(d['profile']);"
            "print(json.dumps(spec.run(m,p,cfg).to_dict()))"
        )
        proc = subprocess.run(
            [sys.executable, "-c", script],
            input=payload,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertEqual(json.loads(proc.stdout), here)


class CommonPriorityOrderDegeneracy(unittest.TestCase):
    """Pin the regime in which this mechanism is NOT worth running.

    Written as a test rather than a comment because it is the reason every
    other test in this file overrides the generator's default tiebreak
    family. If a future generator change made STB produce per-school orders,
    this test would fail and the override could be dropped -- which is
    exactly the signal that should not be left to a stale comment.
    """

    def test_stb_with_one_class_gives_every_school_the_same_order(self):
        for market, profile, config in instances(
            50, seed="ttc-degen", tiebreak_family=TIEBREAK_STB, n_priority_classes=1
        ):
            priorities = resolve_priorities(market, config)
            self.assertEqual(distinct_priority_orders(market, priorities), 1)

    def test_and_in_that_regime_ttc_is_exactly_da(self):
        """Not 'usually agrees' -- identical on every instance, because both
        are serial dictatorship over the one common order."""
        for market, profile, config in instances(
            200, seed="ttc-degen", tiebreak_family=TIEBREAK_STB, n_priority_classes=1
        ):
            ttc = top_trading_cycles(market, profile, config)
            da = deferred_acceptance(
                market,
                profile,
                DAConfig(
                    tiebreak=config.tiebreak,
                    unlisted_student_policy=config.unlisted_student_policy,
                ),
            ).assignment
            self.assertEqual(ttc.assignment, da)
            self.assertTrue(all(len(st.cycles) == 1 for st in ttc.steps))

    def test_the_settings_the_other_tests_use_are_not_degenerate(self):
        many = 0
        for market, profile, config in instances(50, seed="ttc-props"):
            priorities = resolve_priorities(market, config)
            if distinct_priority_orders(market, priorities) > 1:
                many += 1
        self.assertEqual(
            many, 50, "the default test settings produced a common priority order"
        )


if __name__ == "__main__":
    unittest.main()
