"""Shape control and reserve-structure exercise rate in the sweep runner.

The sweep's market shapes used to be constants. That was harmless for plain
DA and Boston, whose choice rules are fully exercised at one seat per school,
and quietly disastrous for reserve_da, whose precedence order has nothing to
order when a school has a single slot: the first reserve_da sweep reported a
truthful zero manipulations over 160 instances while flipping `precedence`
changed the matching in only 2 of them.

So two things are tested here. That shape is now a caller-chosen parameter
AND that the old defaults are byte-for-byte unchanged (existing artifacts
must stay reproducible); and that the runner itself measures how often the
reserve structure actually mattered, so nobody has to think to ask.
"""

from __future__ import annotations

import json
import os
import unittest

from scripts.negative_control import (
    MIN_PRECEDENCE_SENSITIVITY,
    N_SCHOOLS_CHOICES,
    N_STUDENTS_CHOICES,
    SUPPORTED_MECHANISMS,
    _parse_choices,
    draw_configurations,
    process_configuration,
    resolve_expect,
)
from witness.core import UNLISTED_UNACCEPTABLE

RESULTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "results")

#: Judgement floor for `UnacceptableRejectionBranchIsWidenable` below, the
#: same shape as `MIN_PRECEDENCE_SENSITIVITY`: not a theorem, just a value
#: comfortably below every rate actually measured once the branch is forced
#: eligible on every configuration (10-42% for top_trading_cycles, whose
#: `skipped_unacceptable` reading has fewer opportunities per instance than
#: DA/Boston/reserve_da's rejection-based reading; 70-80% for the other
#: three) across many seeds, so a real regression (the widening knobs
#: silently stopped doing anything) fails loudly instead of flaking.
MIN_FORCED_UNACCEPTABLE_REJECTION_COVERAGE = 0.05


class DefaultDrawIsUnchanged(unittest.TestCase):
    """A regression lock with real stakes: every recorded artifact in
    results/ was produced by the pre-parameterisation draw, so if adding the
    shape parameter perturbed the default sequence by even one field, those
    artifacts would silently stop reproducing."""

    def test_recorded_artifacts_still_reproduce(self):
        checked = 0
        for name in sorted(os.listdir(RESULTS)):
            path = os.path.join(RESULTS, name, "negative_control.jsonl")
            summary = os.path.join(RESULTS, name, "negative_control_summary.json")
            if not (os.path.exists(path) and os.path.exists(summary)):
                continue
            records = [json.loads(l) for l in open(path)]
            if not records:
                continue
            meta = json.load(open(summary))
            seed = meta["seed"]
            # Artifacts written before shape became a parameter record no
            # choices and were swept under the defaults; ones written after
            # record exactly what they drew from. Either way the draw is
            # reproduced with the SAME choices the sweep used, so this
            # detects a changed draw rather than a changed configuration.
            drawn = draw_configurations(
                seed,
                len(records),
                n_students_choices=tuple(meta["n_students_choices"])
                if "n_students_choices" in meta else None,
                n_schools_choices=tuple(meta["n_schools_choices"])
                if "n_schools_choices" in meta else None,
            )
            for rec, params in zip(records, drawn):
                recorded = rec["params"]
                shared = set(recorded) & set(params)
                self.assertTrue(shared, f"{name}: no comparable params")
                for key in sorted(shared):
                    self.assertEqual(
                        recorded[key], params[key],
                        f"{name} config {rec['config_index']}: param {key!r} no "
                        f"longer reproduces -- the default shape draw changed",
                    )
                checked += 1
        self.assertGreater(checked, 0, "no recorded artifacts found to check against")


class ShapeIsAParameter(unittest.TestCase):
    def test_defaults_are_used_when_unset(self):
        drawn = draw_configurations("shape-test", 30)
        self.assertTrue(all(p["n_students"] in N_STUDENTS_CHOICES for p in drawn))
        self.assertTrue(all(p["n_schools"] in N_SCHOOLS_CHOICES for p in drawn))

    def test_explicit_choices_are_honoured(self):
        drawn = draw_configurations(
            "shape-test", 30, n_students_choices=(10, 12), n_schools_choices=(3,)
        )
        self.assertEqual({p["n_students"] for p in drawn}, {10, 12})
        self.assertEqual({p["n_schools"] for p in drawn}, {3})

    def test_parse_choices_rejects_rather_than_falling_back(self):
        """A malformed shape flag that silently used the default would make
        the sweep claim a width it never swept -- the exact failure the flag
        exists to prevent."""
        self.assertIsNone(_parse_choices(None, "--x"))
        self.assertEqual(_parse_choices("8,10,12", "--x"), (8, 10, 12))
        for bad in ("", "abc", "8,x", "0", "-3", ","):
            with self.subTest(bad=bad):
                with self.assertRaises(SystemExit):
                    _parse_choices(bad, "--x")


class RunnerMeasuresReserveExercise(unittest.TestCase):
    def _run(self, n_configs, **shape):
        """Aggregate over SEVERAL drawn configurations, not one.

        A single configuration is not representative: `draw_configurations`
        also draws list-length mode and subscription, and a config that
        happens to draw very short lists produces almost no contention, so
        precedence has nothing to reorder even at 12 students. Judging the
        sweep's power from one config is the same error as quoting a cost
        from the smallest configuration."""
        flipped = moved = 0
        for params in draw_configurations("sens", n_configs, reserve_overrides={
            "reserve_mode": "half", "eligible_fraction": 0.5,
            "reserve_type": "soft_reserve", "precedence": "reserve_first",
        }, **shape):
            out = process_configuration(params, 40, "reserve_da", "zero")
            flipped += out["precedence_flipped_runs"]
            moved += out["precedence_changed_matching"]
        return flipped, moved

    def test_wide_shapes_exercise_the_structure_narrow_ones_do_not(self):
        wf, wm = self._run(6, n_students_choices=(10, 12), n_schools_choices=(3,))
        nf, nm = self._run(6, n_students_choices=(3,), n_schools_choices=(5,))
        self.assertEqual(wf, 240)
        self.assertEqual(nf, 240)
        self.assertEqual(
            nm, 0,
            "a school with one seat has one slot, so precedence cannot matter",
        )
        self.assertGreaterEqual(
            wm / wf, MIN_PRECEDENCE_SENSITIVITY,
            f"only {wm}/{wf} instances moved when precedence was flipped, below "
            f"the {MIN_PRECEDENCE_SENSITIVITY:.0%} floor -- at these shapes the "
            f"sweep is still mostly re-testing plain DA",
        )

    def test_metric_is_zero_for_a_mechanism_without_precedence(self):
        params = draw_configurations("sens", 1)[0]
        out = process_configuration(params, 10, "student_proposing_da", "zero")
        self.assertEqual(out["precedence_flipped_runs"], 0)
        self.assertEqual(out["precedence_changed_matching"], 0)


class UnacceptableRejectionBranchIsWidenable(unittest.TestCase):
    """`witness.coverage`'s `had_school_unacceptable_rejection` requires BOTH
    `school_lists_fraction < 1.0` (some school leaves a student unlisted) AND
    `unlisted_student_policy == UNLISTED_UNACCEPTABLE` (being unlisted
    actually makes that student unacceptable there) on the SAME
    configuration. At the module defaults (`SCHOOL_LISTS_FULL_PROBABILITY`,
    `UNLISTED_POLICY_WEIGHTS`) that combination is drawn for only about 35%
    of configurations -- a real, nonzero baseline, but not one a sweep with
    only a handful of configurations can rely on (see
    `tests.test_negative_control_runner`'s own
    `test_coverage_report_has_nonzero_fractions_for_hit_branches`, which
    already documents this branch as "not guaranteed at this tiny a
    sample"). `--school-lists-full-probability` /
    `--unacceptable-policy-fraction` (`draw_configuration`'s
    `school_lists_full_probability` / `unacceptable_policy_fraction`) exist
    so a caller who specifically wants this branch reliably exercised can
    widen it, the same caller-overridable-but-default-preserving shape as
    `n_students_choices` / `n_schools_choices` for the reserve structure."""

    def test_defaults_are_unchanged_when_the_new_knobs_are_omitted(self):
        """The exact regression `DefaultDrawIsUnchanged` guards against, for
        these two new parameters specifically: omitting them (or passing
        `None` explicitly) must reproduce the pre-existing draw byte-for-byte,
        since every recorded artifact under results/ was drawn without them."""
        without_the_new_params = draw_configurations("widen-default-check", 40)
        explicit_none = draw_configurations(
            "widen-default-check",
            40,
            school_lists_full_probability=None,
            unacceptable_policy_fraction=None,
        )
        self.assertEqual(without_the_new_params, explicit_none)

    def test_forcing_the_combination_makes_every_configuration_eligible(self):
        configs = draw_configurations(
            "widen-eligible-check",
            40,
            school_lists_full_probability=0.0,
            unacceptable_policy_fraction=1.0,
        )
        self.assertTrue(
            all(c["school_lists_fraction"] < 1.0 for c in configs),
            "school_lists_full_probability=0.0 must never draw a full listing",
        )
        self.assertTrue(
            all(c["unlisted_student_policy"] == UNLISTED_UNACCEPTABLE for c in configs),
            "unacceptable_policy_fraction=1.0 must never draw the other policy",
        )

    def test_intermediate_fractions_are_honoured_not_just_the_extremes(self):
        """A caller might reasonably ask for e.g. 80% rather than forcing
        100% -- check the knob is a real probability, not a boolean in
        disguise, by drawing enough configurations for both outcomes to
        appear at a fraction away from either extreme."""
        configs = draw_configurations(
            "widen-intermediate-check",
            200,
            school_lists_full_probability=0.5,
            unacceptable_policy_fraction=0.5,
        )
        full = sum(1 for c in configs if c["school_lists_fraction"] >= 1.0)
        unacceptable = sum(
            1 for c in configs if c["unlisted_student_policy"] == UNLISTED_UNACCEPTABLE
        )
        self.assertTrue(0 < full < len(configs))
        self.assertTrue(0 < unacceptable < len(configs))

    def test_branch_is_genuinely_exercised_for_every_supported_mechanism(self):
        """Not just "eligible" (the configuration COULD produce an
        unacceptable rejection) -- this runs a small but real sweep (5
        configurations x 10 instances) per `SUPPORTED_MECHANISMS`, with the
        branch forced eligible on every configuration, and checks the actual
        mechanism trace (`branch_hit_counts`, read from `DAResult` /
        `BostonResult` / `TTCResult` -- see `witness.coverage`) reports it
        well above the floor, for every mechanism `draw_configuration` can
        build a `GeneratorConfig` for -- exactly the four this sweep runs in
        practice, never a proxy for them."""
        for mechanism in SUPPORTED_MECHANISMS:
            with self.subTest(mechanism=mechanism):
                configs = draw_configurations(
                    f"widen-exercise-check/{mechanism}",
                    5,
                    school_lists_full_probability=0.0,
                    unacceptable_policy_fraction=1.0,
                )
                expect = resolve_expect(mechanism, None)
                hits = 0
                total = 0
                for params in configs:
                    out = process_configuration(params, 10, mechanism, expect)
                    hits += out["branch_hit_counts"]["had_school_unacceptable_rejection"]
                    total += out["n_instances"]
                self.assertGreater(total, 0, f"{mechanism}: no instances ran")
                fraction = hits / total
                self.assertGreaterEqual(
                    fraction,
                    MIN_FORCED_UNACCEPTABLE_REJECTION_COVERAGE,
                    f"{mechanism}: only {hits}/{total} instances hit "
                    "had_school_unacceptable_rejection even with the branch forced "
                    f"eligible on every configuration (floor "
                    f"{MIN_FORCED_UNACCEPTABLE_REJECTION_COVERAGE:.0%}) -- the "
                    "widening knobs stopped doing anything",
                )

    def test_cli_flags_reject_out_of_range_values(self):
        """Mirrors `_parse_choices`'s own "reject rather than silently fall
        back" contract for the shape flags: an out-of-range probability must
        abort `main()`, never be clamped or ignored, since either of those
        would make the sweep report a widening it did not actually apply."""
        import scripts.negative_control as nc

        for flag, bad in (
            ("--school-lists-full-probability", "1.5"),
            ("--school-lists-full-probability", "-0.1"),
            ("--unacceptable-policy-fraction", "1.5"),
            ("--unacceptable-policy-fraction", "-0.1"),
        ):
            with self.subTest(flag=flag, bad=bad):
                with self.assertRaises(ValueError):
                    nc.main(
                        [
                            "--configs", "1",
                            "--instances-per-config", "1",
                            "--out", "/dev/null/unreachable",
                            flag, bad,
                        ]
                    )


if __name__ == "__main__":
    unittest.main()
