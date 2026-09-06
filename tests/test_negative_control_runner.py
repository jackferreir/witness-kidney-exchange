"""Tests for scripts/negative_control.py: the deep negative-control sweep.

The CLI runs are all invoked as real subprocesses (`sys.executable
scripts/negative_control.py ...`), exactly the way a user would run it, so
these tests exercise the actual argv-parsing / exit-code contract, not just
its Python API. Every run here uses tiny --configs / --instances-per-config
values and a tempfile --out directory, keeping the whole file well under the
~30 second budget. The one exception is `TestVerificationFailureAborts`,
which calls `run_sweep` directly (with a monkeypatched verifier) rather than
through a subprocess -- see that class's docstring for why.

`TestExpectManipulationsMode.test_boston_manipulations_mode_completes_and_reports_everything`
is the regression test for the "witnesses.jsonl is unusable" defect: earlier,
this test only asserted the file was non-empty, which stayed green even while
every line was wrapped in an envelope
(`{"config_index": ..., "instance_index": ..., "mechanism": ..., "witness":
{...}}`) that `python3 -m witness.replay --jsonl` rejected outright. It now
asserts, in addition: every line passes `witness.replay.verify_witness`
in-process; the replay CLI itself accepts the whole file as a real
subprocess and exits 0 with no "REJECTED" in its output; no line carries a
"config_index" / "instance_index" / "witness" key (the envelope can never
come back); and the `witness_index.jsonl` provenance sidecar has exactly one
line per witness, joined totally by `witness_id`.

`TestExpectZeroWithBostonAborts` (formerly `TestInjectedHit`) is the most
important test in this file: it proves the runner would actually notice a
real failure, by pointing it at "boston_immediate_acceptance" (which IS
manipulable) with an explicit `--expect zero` and checking that it finds,
verifies, records, and aborts on a hit. Without this test, a runner that
silently never detected anything would make every other test in this file
(and every real run of the negative control) look like a clean pass for the
wrong reason. It now passes `--expect zero` EXPLICITLY: `--expect`'s default
for "boston_immediate_acceptance" is "manipulations" (it is manipulable by
design), so omitting the flag here would no longer abort at all -- see
`TestExpectManipulationsMode` for that (now default) behaviour instead.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from collections import Counter
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = str(PROJECT_ROOT / "scripts" / "negative_control.py")

sys.path.insert(0, str(PROJECT_ROOT))

import scripts.negative_control as nc  # noqa: E402
from scripts.negative_control import (  # noqa: E402
    DEFAULT_EXPECT_BY_MECHANISM,
    EXPECT_MANIPULATIONS,
    EXPECT_ZERO,
    draw_configuration,
    draw_configurations,
    mechanism_runs_per_instance,
    ordered_subset_count,
    resolve_expect,
    run_sweep,
)
from witness.replay import verify_witness  # noqa: E402


def run_cli(args, timeout=60):
    """Invoke the CLI as a real subprocess and return the CompletedProcess."""
    return subprocess.run(
        [sys.executable, SCRIPT] + args,
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def load_jsonl(path, strip_fields=("elapsed_seconds",)):
    """Parse a JSONL file into a list of dicts, dropping timing fields so
    two runs' outputs can be compared for content equality."""
    records = []
    with open(path, mode="r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            for field in strip_fields:
                record.pop(field, None)
            records.append(record)
    return records


class TestEndToEnd(unittest.TestCase):
    def test_tiny_sweep_completes_writes_all_outputs_and_finds_nothing(self):
        with TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "out")
            proc = run_cli(
                [
                    "--seed", "e2e-seed",
                    "--configs", "3",
                    "--instances-per-config", "6",
                    "--out", out,
                ]
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)

            for name in (
                "negative_control.jsonl",
                "negative_control_hits.jsonl",
                "checkpoint.json",
                "negative_control_summary.json",
            ):
                self.assertTrue(
                    os.path.exists(os.path.join(out, name)), msg=f"missing {name}"
                )

            records = load_jsonl(os.path.join(out, "negative_control.jsonl"))
            self.assertEqual(len(records), 3)
            for r in records:
                self.assertEqual(r["manipulations_found"], 0)
                self.assertEqual(r["n_instances"], 6)

            # Hits file must exist but be empty -- zero manipulations, as
            # DA's strategy-proofness demands.
            self.assertEqual(
                os.path.getsize(os.path.join(out, "negative_control_hits.jsonl")), 0
            )

            with open(os.path.join(out, "negative_control_summary.json")) as f:
                summary = json.load(f)
            self.assertEqual(summary["total_configurations"], 3)
            self.assertEqual(summary["total_instances"], 18)
            self.assertEqual(summary["manipulations_found"], 0)
            self.assertIn("coverage", summary)
            self.assertIn("unreached_branches", summary)

    def test_coverage_report_has_nonzero_fractions_for_hit_branches(self):
        # over-subscription (majority-weighted) plus non-trivial n_students
        # over a few configs virtually guarantees unmatched students and
        # capacity contention show up; incomplete/short lists are similarly
        # heavily weighted. Assert on the branches this shape MUST hit
        # rather than on the full set (school-unacceptable-rejection and
        # lottery-tie are not guaranteed at this tiny a sample).
        with TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "out")
            proc = run_cli(
                [
                    "--seed", "coverage-seed",
                    "--configs", "12",
                    "--instances-per-config", "10",
                    "--out", out,
                ]
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)

            with open(os.path.join(out, "negative_control_summary.json")) as f:
                summary = json.load(f)

            fractions = summary["coverage"]["fractions"]
            self.assertGreater(fractions["had_unmatched_student"], 0.0)
            self.assertGreater(fractions["had_capacity_contention"], 0.0)
            self.assertGreater(fractions["had_incomplete_list"], 0.0)

            # unreached_branches is reported, whatever it says -- not
            # necessarily empty at this sample size.
            self.assertIsInstance(summary["unreached_branches"], list)
            for name in summary["unreached_branches"]:
                self.assertEqual(fractions[name], 0.0)


class TestResumability(unittest.TestCase):
    def test_partial_then_resume_matches_a_single_pass(self):
        with TemporaryDirectory() as tmp:
            resumed_out = os.path.join(tmp, "resumed")
            single_out = os.path.join(tmp, "single")

            # Phase 1: a small budget.
            proc1 = run_cli(
                [
                    "--seed", "resume-seed",
                    "--configs", "3",
                    "--instances-per-config", "5",
                    "--out", resumed_out,
                ]
            )
            self.assertEqual(proc1.returncode, 0, msg=proc1.stdout + proc1.stderr)
            partial_records = load_jsonl(os.path.join(resumed_out, "negative_control.jsonl"))
            self.assertEqual(len(partial_records), 3)

            # Phase 2: resume to a larger budget.
            proc2 = run_cli(
                [
                    "--seed", "resume-seed",
                    "--configs", "8",
                    "--instances-per-config", "5",
                    "--out", resumed_out,
                    "--resume",
                ]
            )
            self.assertEqual(proc2.returncode, 0, msg=proc2.stdout + proc2.stderr)

            # A single, uninterrupted pass at the final budget.
            proc3 = run_cli(
                [
                    "--seed", "resume-seed",
                    "--configs", "8",
                    "--instances-per-config", "5",
                    "--out", single_out,
                ]
            )
            self.assertEqual(proc3.returncode, 0, msg=proc3.stdout + proc3.stderr)

            resumed_records = load_jsonl(os.path.join(resumed_out, "negative_control.jsonl"))
            single_records = load_jsonl(os.path.join(single_out, "negative_control.jsonl"))
            self.assertEqual(len(resumed_records), 8)
            self.assertEqual(len(single_records), 8)
            self.assertEqual(
                sorted(resumed_records, key=lambda r: r["config_index"]),
                sorted(single_records, key=lambda r: r["config_index"]),
            )

            # And the first 3 records of the resumed run are byte-for-byte
            # (modulo timing) what phase 1 alone produced -- resuming never
            # rewrites already-completed work.
            self.assertEqual(
                sorted(partial_records, key=lambda r: r["config_index"]),
                sorted(
                    [r for r in resumed_records if r["config_index"] < 3],
                    key=lambda r: r["config_index"],
                ),
            )

    def test_rerunning_without_resume_when_checkpoint_exists_is_refused(self):
        with TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "out")
            proc1 = run_cli(
                ["--seed", "no-resume-seed", "--configs", "2", "--instances-per-config", "3", "--out", out]
            )
            self.assertEqual(proc1.returncode, 0, msg=proc1.stdout + proc1.stderr)

            proc2 = run_cli(
                ["--seed", "no-resume-seed", "--configs", "2", "--instances-per-config", "3", "--out", out]
            )
            self.assertNotEqual(proc2.returncode, 0)
            self.assertIn("--resume", proc2.stdout + proc2.stderr)


class TestDeterminismAcrossWorkers(unittest.TestCase):
    def test_workers_1_and_2_produce_identical_journal_content(self):
        with TemporaryDirectory() as tmp:
            out1 = os.path.join(tmp, "w1")
            out2 = os.path.join(tmp, "w2")

            proc1 = run_cli(
                [
                    "--seed", "det-seed",
                    "--configs", "6",
                    "--instances-per-config", "4",
                    "--out", out1,
                    "--workers", "1",
                ]
            )
            self.assertEqual(proc1.returncode, 0, msg=proc1.stdout + proc1.stderr)

            proc2 = run_cli(
                [
                    "--seed", "det-seed",
                    "--configs", "6",
                    "--instances-per-config", "4",
                    "--out", out2,
                    "--workers", "2",
                ]
            )
            self.assertEqual(proc2.returncode, 0, msg=proc2.stdout + proc2.stderr)

            records1 = load_jsonl(os.path.join(out1, "negative_control.jsonl"))
            records2 = load_jsonl(os.path.join(out2, "negative_control.jsonl"))
            self.assertEqual(records1, records2)

            with open(os.path.join(out1, "negative_control_summary.json")) as f:
                summary1 = json.load(f)
            with open(os.path.join(out2, "negative_control_summary.json")) as f:
                summary2 = json.load(f)
            for key in ("total_configurations", "total_instances", "manipulations_found", "coverage"):
                self.assertEqual(summary1[key], summary2[key])


class TestConfigurationDraw(unittest.TestCase):
    def test_same_seed_gives_same_configuration_list(self):
        a = draw_configurations("draw-seed-A", 25)
        b = draw_configurations("draw-seed-A", 25)
        self.assertEqual(a, b)

    def test_different_seed_gives_different_configuration_list(self):
        a = draw_configurations("draw-seed-A", 25)
        b = draw_configurations("draw-seed-B", 25)
        self.assertNotEqual(a, b)

    def test_prefix_is_stable_regardless_of_how_many_are_drawn(self):
        full = draw_configurations("prefix-seed", 10)
        partial = draw_configurations("prefix-seed", 4)
        self.assertEqual(full[:4], partial)

    def test_single_draw_matches_the_batch_draw(self):
        batch = draw_configurations("single-vs-batch-seed", 5)
        for i, params in enumerate(batch):
            self.assertEqual(params, draw_configuration("single-vs-batch-seed", i))


class TestConfigurationWeighting(unittest.TestCase):
    def test_subscription_weighting_biases_toward_over_and_away_from_under(self):
        configs = draw_configurations("weight-check-seed", 500)
        counts = Counter(c["subscription"] for c in configs)

        self.assertGreater(counts["over"], 0)
        self.assertGreater(counts["exact"], 0)
        self.assertGreater(counts["under"], 0)

        most_common = counts.most_common()
        self.assertEqual(most_common[0][0], "over")
        self.assertEqual(most_common[-1][0], "under")

    def test_subscription_mix_matches_over_50_exact_35_under_15_within_tolerance(self):
        # The stated intent (see SUBSCRIPTION_WEIGHTS's own comment) is
        # over ~50%, exact ~35%, under ~15%. A real 40-config draw once
        # produced over 42.5% / exact 42.5% / under 15% -- "over" and
        # "exact" landing equal -- which is exactly the kind of collapse
        # this test exists to catch. At 40 draws that collapse is within
        # ordinary sampling noise (std ~ 8 points on a 50/50 split); this
        # test instead draws several hundred configurations, over several
        # independent seeds, so noise this large would be a real anomaly,
        # not a coin-flip.
        #
        # Tolerance: +/- 6 percentage points per level. Tight enough to
        # fail if the weights were, say, swapped or flattened toward
        # equal thirds (33/33/33 -- each off by >10 points), loose enough
        # to comfortably absorb hash-derived sampling noise at n=600.
        tolerance = 0.06
        expected = {"over": 0.50, "exact": 0.35, "under": 0.15}
        for seed in ("weight-tolerance-seed-1", "weight-tolerance-seed-2", "weight-tolerance-seed-3"):
            configs = draw_configurations(seed, 600)
            counts = Counter(c["subscription"] for c in configs)
            total = sum(counts.values())
            fractions = {k: counts[k] / total for k in expected}

            for level, target in expected.items():
                self.assertAlmostEqual(
                    fractions[level],
                    target,
                    delta=tolerance,
                    msg=f"seed={seed!r}: subscription={level!r} realized {fractions[level]:.3f}, "
                    f"expected close to {target:.3f} (fractions={fractions})",
                )

            most_common = counts.most_common()
            self.assertEqual(most_common[0][0], "over", msg=f"seed={seed!r}: counts={counts}")
            self.assertEqual(most_common[-1][0], "under", msg=f"seed={seed!r}: counts={counts}")

    def test_school_lists_fraction_is_below_1_in_the_majority_of_configs(self):
        configs = draw_configurations("fraction-weight-seed", 500)
        partial = sum(1 for c in configs if c["school_lists_fraction"] < 1.0)
        self.assertGreater(partial, len(configs) / 2)

    def test_list_length_mode_weights_short_and_uniform_over_complete(self):
        configs = draw_configurations("list-length-weight-seed", 500)
        counts = Counter(c["list_length_mode"] for c in configs)
        self.assertGreater(counts["short"], counts["complete"])
        self.assertGreater(counts["uniform"], counts["complete"])


class TestSummaryTimingFields(unittest.TestCase):
    def test_summary_has_wall_seconds_instances_per_second_and_mean_seconds_per_instance(self):
        with TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "out")
            proc = run_cli(
                [
                    "--seed", "timing-seed",
                    "--configs", "4",
                    "--instances-per-config", "6",
                    "--out", out,
                ]
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)

            with open(os.path.join(out, "negative_control_summary.json")) as f:
                summary = json.load(f)

            for field in ("wall_seconds", "instances_per_second", "mean_seconds_per_instance"):
                self.assertIn(field, summary, msg=f"missing {field!r} in summary")
                self.assertIsNotNone(summary[field], msg=f"{field!r} must not be null on a real run")
                self.assertGreater(summary[field], 0.0, msg=f"{field!r} must be > 0, got {summary[field]}")

            # instances_per_second must be consistent with
            # total_instances_processed_this_invocation / wall_seconds,
            # within a generous tolerance (process/subprocess overhead
            # means this is not exact to many digits, but it must not be
            # off by an order of magnitude or inverted).
            expected_rate = summary["instances_processed_this_invocation"] / summary["wall_seconds"]
            self.assertAlmostEqual(
                summary["instances_per_second"], expected_rate, delta=max(1.0, expected_rate * 0.05)
            )

            # mean_seconds_per_instance is the reciprocal relationship --
            # also checked directly rather than trusting it agrees with
            # instances_per_second only by construction.
            expected_mean = summary["wall_seconds"] / summary["instances_processed_this_invocation"]
            self.assertAlmostEqual(
                summary["mean_seconds_per_instance"],
                expected_mean,
                delta=max(1e-6, expected_mean * 0.05),
            )

            self.assertIn("total_mechanism_runs", summary)
            self.assertGreater(summary["total_mechanism_runs"], 0)


class TestInstancesRunField(unittest.TestCase):
    def test_every_journal_record_has_a_non_null_instances_run_matching_the_request(self):
        instances_per_config = 7
        with TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "out")
            proc = run_cli(
                [
                    "--seed", "instances-run-seed",
                    "--configs", "5",
                    "--instances-per-config", str(instances_per_config),
                    "--out", out,
                ]
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)

            records = load_jsonl(os.path.join(out, "negative_control.jsonl"))
            self.assertEqual(len(records), 5)
            for r in records:
                self.assertIn("instances_run", r)
                self.assertIsNotNone(r["instances_run"], msg=f"record {r['config_index']} has null instances_run")
                self.assertIsInstance(r["instances_run"], int)
                # student_proposing_da is strategy-proof, so this run
                # cannot hit -- every configuration must run the full
                # requested instance count.
                self.assertEqual(r["instances_run"], instances_per_config)
                self.assertEqual(r["instances_run"], r["n_instances"])


class TestMechanismRunsPerInstance(unittest.TestCase):
    def test_ordered_subset_count_matches_hand_computed_values(self):
        # sum_{r=0}^{m} m!/(m-r)!
        self.assertEqual(ordered_subset_count(0), 1)  # just the empty subset
        self.assertEqual(ordered_subset_count(1), 2)  # 1 + 1
        self.assertEqual(ordered_subset_count(3), 16)  # 1 + 3 + 6 + 6
        self.assertEqual(ordered_subset_count(5), 326)  # 1+5+20+60+120+120

    def test_mechanism_runs_per_instance_matches_hand_computed_value(self):
        # 6 students x 5 schools -> 6 * 326 = 1956, the task's own worked
        # example.
        self.assertEqual(mechanism_runs_per_instance(6, 5), 1956)

    def test_journal_records_carry_the_correct_mechanism_runs_per_instance(self):
        with TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "out")
            proc = run_cli(
                [
                    "--seed", "runs-per-instance-seed",
                    "--configs", "6",
                    "--instances-per-config", "3",
                    "--out", out,
                ]
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)

            records = load_jsonl(os.path.join(out, "negative_control.jsonl"))
            self.assertEqual(len(records), 6)
            for r in records:
                self.assertIn("mechanism_runs_per_instance", r)
                expected = mechanism_runs_per_instance(
                    r["params"]["n_students"], r["params"]["n_schools"]
                )
                self.assertEqual(r["mechanism_runs_per_instance"], expected)

            with open(os.path.join(out, "negative_control_summary.json")) as f:
                summary = json.load(f)
            expected_total = sum(r["mechanism_runs_per_instance"] * r["instances_run"] for r in records)
            self.assertEqual(summary["total_mechanism_runs"], expected_total)


class TestExpectZeroWithBostonAborts(unittest.TestCase):
    def test_boston_manipulability_is_caught_verified_and_aborts(self):
        # Boston / immediate acceptance is NOT strategy-proof, so a wide
        # enough sweep must find a manipulation quickly. This is the test
        # that proves the runner actually works as a detector -- without
        # it, a runner that never finds anything would pass every other
        # test in this file vacuously. `--expect zero` is EXPLICIT here:
        # Boston's own default is now "manipulations" (see
        # `TestExpectManipulationsMode`), so this is the "legitimate thing
        # to test" case the task calls out -- asking the runner to treat a
        # manipulable mechanism as a negative control anyway.
        with TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "out")
            proc = run_cli(
                [
                    "--seed", "boston-hit-seed",
                    "--configs", "25",
                    "--instances-per-config", "60",
                    "--out", out,
                    "--mechanism", "boston_immediate_acceptance",
                    "--expect", "zero",
                ],
                timeout=90,
            )
            self.assertNotEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
            self.assertIn("ABORTING", proc.stdout)
            # Explicitly requesting --expect zero against a mechanism whose
            # own default is "manipulations" prints a one-line notice that
            # the run is expected to abort.
            self.assertIn("NOTE", proc.stdout)

            hits_path = os.path.join(out, "negative_control_hits.jsonl")
            self.assertTrue(os.path.exists(hits_path))
            hits = load_jsonl(hits_path, strip_fields=())
            self.assertEqual(len(hits), 1)

            hit = hits[0]
            self.assertEqual(hit["mechanism"], "boston_immediate_acceptance")
            self.assertEqual(hit["expect"], "zero")
            self.assertTrue(hit["verified_in_fresh_subprocess"])
            self.assertEqual(hit["verify_reasons"], [])
            self.assertIn("witness", hit)
            self.assertIn("market", hit)
            self.assertIn("profile", hit)
            self.assertIn("mechanism_config", hit)


class TestExpectDefaults(unittest.TestCase):
    """Pure Python-API checks of `resolve_expect` / `DEFAULT_EXPECT_BY_MECHANISM`
    -- no subprocess needed, so these stay essentially instantaneous."""

    def test_da_defaults_to_zero(self):
        self.assertEqual(DEFAULT_EXPECT_BY_MECHANISM["student_proposing_da"], EXPECT_ZERO)
        self.assertEqual(resolve_expect("student_proposing_da", None), EXPECT_ZERO)

    def test_boston_defaults_to_manipulations(self):
        self.assertEqual(
            DEFAULT_EXPECT_BY_MECHANISM["boston_immediate_acceptance"], EXPECT_MANIPULATIONS
        )
        self.assertEqual(resolve_expect("boston_immediate_acceptance", None), EXPECT_MANIPULATIONS)

    def test_explicit_expect_always_overrides_the_default(self):
        self.assertEqual(resolve_expect("student_proposing_da", EXPECT_MANIPULATIONS), EXPECT_MANIPULATIONS)
        self.assertEqual(resolve_expect("boston_immediate_acceptance", EXPECT_ZERO), EXPECT_ZERO)

    def test_da_default_run_records_expect_zero_in_the_summary_and_records(self):
        with TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "out")
            proc = run_cli(
                ["--seed", "expect-default-da", "--configs", "2", "--instances-per-config", "3", "--out", out]
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)

            with open(os.path.join(out, "negative_control_summary.json")) as f:
                summary = json.load(f)
            self.assertEqual(summary["expect"], "zero")

            for r in load_jsonl(os.path.join(out, "negative_control.jsonl")):
                self.assertEqual(r["expect"], "zero")

    def test_boston_default_run_records_expect_manipulations_in_the_summary_and_records(self):
        with TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "out")
            proc = run_cli(
                [
                    "--seed", "expect-default-boston",
                    "--configs", "2",
                    "--instances-per-config", "5",
                    "--out", out,
                    "--mechanism", "boston_immediate_acceptance",
                ]
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)

            with open(os.path.join(out, "negative_control_summary.json")) as f:
                summary = json.load(f)
            self.assertEqual(summary["expect"], "manipulations")

            for r in load_jsonl(os.path.join(out, "negative_control.jsonl")):
                self.assertEqual(r["expect"], "manipulations")

    def test_explicit_expect_manipulations_overrides_da_default(self):
        # DA is strategy-proof, so this must still find zero manipulations
        # -- but the OVERRIDE itself (the recorded "expect" value) must take
        # effect regardless of what the mechanism actually does.
        with TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "out")
            proc = run_cli(
                [
                    "--seed", "expect-override-da",
                    "--configs", "2",
                    "--instances-per-config", "3",
                    "--out", out,
                    "--mechanism", "student_proposing_da",
                    "--expect", "manipulations",
                ]
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
            with open(os.path.join(out, "negative_control_summary.json")) as f:
                summary = json.load(f)
            self.assertEqual(summary["expect"], "manipulations")
            self.assertEqual(summary["manipulable_cases"], 0)
            # An explicit --expect that matches the mechanism's own default
            # (zero for DA, or here a non-default override that still can't
            # abort) never prints the "explicit --expect zero against a
            # manipulable mechanism" notice -- that notice is specific to
            # --expect zero against a mechanism defaulting to manipulations.
            self.assertNotIn("NOTE", proc.stdout)


class TestExpectManipulationsMode(unittest.TestCase):
    """The core new behaviour: `--expect manipulations` against Boston must
    run the FULL sweep (never abort on a manipulation), count and record
    every one, sample-verify some of them, and actually exercise the
    singleton-sufficiency invariant (`witness.invariants`) -- this is the
    figure that used to require a hand-run script outside this file
    entirely (see the module docstring's "--expect: ZERO vs MANIPULATIONS"
    section)."""

    def test_boston_manipulations_mode_completes_and_reports_everything(self):
        with TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "out")
            proc = run_cli(
                [
                    "--seed", "boston-hit-seed",
                    "--configs", "2",
                    "--instances-per-config", "10",
                    "--out", out,
                    "--mechanism", "boston_immediate_acceptance",
                    "--expect", "manipulations",
                ],
                timeout=30,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
            self.assertNotIn("ABORTING", proc.stdout)

            with open(os.path.join(out, "negative_control_summary.json")) as f:
                summary = json.load(f)

            self.assertEqual(summary["expect"], "manipulations")
            self.assertGreater(summary["manipulable_cases"], 0)
            self.assertGreater(summary["instances_with_manipulation"], 0)
            self.assertEqual(
                summary["hits_verified"] + summary["hits_unverified"], summary["manipulable_cases"]
            )

            # The whole point: the singleton-sufficiency invariant must
            # actually be exercised through this runner now, not silently
            # inert (which is exactly what --expect zero's early-abort made
            # it, for a manipulable mechanism like this one).
            self.assertGreater(summary["singleton_cases"], 0)
            self.assertGreater(summary["singleton_holds"], 0)

            witnesses_path = os.path.join(out, "witnesses.jsonl")
            self.assertTrue(os.path.exists(witnesses_path))
            self.assertGreater(os.path.getsize(witnesses_path), 0)
            witnesses = load_jsonl(witnesses_path, strip_fields=())
            self.assertEqual(len(witnesses), summary["witnesses_recorded"])

            # witnesses.jsonl is the artifact of record: each line must be a
            # BARE witness dict, exactly the schema witness.replay consumes
            # -- never wrapped in an envelope carrying this script's own
            # bookkeeping. This is the regression guard for the defect where
            # every line was wrapped as {"config_index": ..., "instance_index":
            # ..., "mechanism": ..., "witness": {...}}, which the replay CLI
            # could not consume at all.
            for i, w in enumerate(witnesses):
                self.assertEqual(w["mechanism"], "boston_immediate_acceptance")
                for forbidden_key in ("config_index", "instance_index", "witness"):
                    self.assertNotIn(
                        forbidden_key, w,
                        msg=f"witnesses.jsonl line {i} still carries {forbidden_key!r} -- "
                        "the envelope must never come back",
                    )

            # In-process: every single recorded witness must independently
            # re-verify from its own saved fields alone.
            for i, w in enumerate(witnesses):
                ok, reasons = verify_witness(w)
                self.assertEqual(
                    (ok, reasons), (True, ()),
                    msg=f"witnesses.jsonl line {i}: verify_witness rejected it: {reasons}",
                )

            # Out-of-process, exactly the way a user would actually check
            # this file: the replay CLI must accept it wholesale, with zero
            # rejections, and exit 0.
            replay_proc = subprocess.run(
                [sys.executable, "-m", "witness.replay", "--jsonl", witnesses_path],
                cwd=str(PROJECT_ROOT),
                capture_output=True,
                text=True,
                timeout=60,
            )
            self.assertEqual(
                replay_proc.returncode, 0,
                msg=f"replay CLI rejected witnesses.jsonl: stdout="
                f"{replay_proc.stdout!r} stderr={replay_proc.stderr!r}",
            )
            self.assertNotIn("REJECTED", replay_proc.stdout)

            # The provenance sidecar: exactly one line per recorded witness,
            # positionally matching witnesses.jsonl by witness_id, with the
            # join total in both directions (no orphans on either side).
            index_path = os.path.join(out, "witness_index.jsonl")
            self.assertTrue(os.path.exists(index_path))
            index_records = load_jsonl(index_path, strip_fields=())
            self.assertEqual(
                len(index_records), len(witnesses),
                msg="witness_index.jsonl must have exactly one line per witness line",
            )
            for i, (index_rec, witness) in enumerate(zip(index_records, witnesses)):
                self.assertIn("config_index", index_rec)
                self.assertIn("instance_index", index_rec)
                self.assertEqual(
                    index_rec["witness_id"], witness["witness_id"],
                    msg=f"line {i}: witness_index.jsonl witness_id "
                    f"{index_rec['witness_id']!r} does not match witnesses.jsonl's "
                    f"own witness_id {witness['witness_id']!r}",
                )
            self.assertEqual(
                {w["witness_id"] for w in witnesses},
                {r["witness_id"] for r in index_records},
                msg="witnesses.jsonl and witness_index.jsonl must join totally by "
                "witness_id, with no orphans in either direction",
            )

            # negative_control_hits.jsonl is the --expect zero artifact --
            # never populated in this mode, but still touched into existence.
            self.assertTrue(os.path.exists(os.path.join(out, "negative_control_hits.jsonl")))
            self.assertEqual(
                os.path.getsize(os.path.join(out, "negative_control_hits.jsonl")), 0
            )

            # A no-op, always-empty verification_failures.jsonl on a clean run.
            failures_path = os.path.join(out, "verification_failures.jsonl")
            self.assertTrue(os.path.exists(failures_path))
            self.assertEqual(os.path.getsize(failures_path), 0)


class TestVerifyHitsHonoured(unittest.TestCase):
    def test_verify_hits_caps_verification_per_configuration(self):
        with TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "out")
            proc = run_cli(
                [
                    "--seed", "boston-hit-seed",
                    "--configs", "2",
                    "--instances-per-config", "10",
                    "--out", out,
                    "--mechanism", "boston_immediate_acceptance",
                    "--expect", "manipulations",
                    "--verify-hits", "1",
                ],
                timeout=30,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)

            records = load_jsonl(os.path.join(out, "negative_control.jsonl"))
            self.assertEqual(len(records), 2)
            saw_any_manipulation = False
            for r in records:
                self.assertLessEqual(r["hits_verified"], 1)
                self.assertEqual(
                    r["hits_verified"] + r["hits_unverified"], r["manipulable_cases"]
                )
                if r["manipulable_cases"] > 0:
                    saw_any_manipulation = True
            self.assertTrue(saw_any_manipulation, "expected at least one manipulable config")

            with open(os.path.join(out, "negative_control_summary.json")) as f:
                summary = json.load(f)
            self.assertEqual(summary["verify_hits"], 1)
            self.assertEqual(
                summary["hits_verified"] + summary["hits_unverified"], summary["manipulable_cases"]
            )


class TestMaxWitnessesCap(unittest.TestCase):
    def test_max_witnesses_caps_the_file_and_records_the_omitted_count(self):
        with TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "out")
            proc = run_cli(
                [
                    "--seed", "boston-hit-seed",
                    "--configs", "2",
                    "--instances-per-config", "10",
                    "--out", out,
                    "--mechanism", "boston_immediate_acceptance",
                    "--expect", "manipulations",
                    "--max-witnesses", "5",
                ],
                timeout=30,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)

            with open(os.path.join(out, "negative_control_summary.json")) as f:
                summary = json.load(f)
            self.assertEqual(summary["max_witnesses"], 5)
            self.assertEqual(summary["witnesses_recorded"], 5)
            # This seed/config/instance combination produces well more than
            # 5 manipulations (see TestExpectManipulationsMode), so the cap
            # must actually have bitten.
            self.assertGreater(summary["manipulable_cases"], 5)
            self.assertEqual(
                summary["witnesses_omitted"], summary["manipulable_cases"] - 5
            )

            witnesses = load_jsonl(os.path.join(out, "witnesses.jsonl"), strip_fields=())
            self.assertEqual(len(witnesses), 5)


class TestVerificationFailureAborts(unittest.TestCase):
    """A FAILED sampled verification is a real defect and must abort the
    run regardless of --expect -- exercised here by directly monkeypatching
    `scripts.negative_control.verify_in_subprocess` to force a failure and
    calling `run_sweep` in-process (not through a subprocess), since a
    forced-failure verifier can't be injected across the subprocess/argv
    boundary the other tests in this file use. `workers=1` keeps
    `process_configuration` running in THIS process (no `multiprocessing`
    child that wouldn't see the patch)."""

    def test_failed_sampled_verification_aborts_and_is_recorded(self):
        with TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "out")

            def _always_fails(_witness_dict):
                return (False, ("forced failure for test",))

            with mock.patch.object(nc, "verify_in_subprocess", side_effect=_always_fails):
                exit_code = run_sweep(
                    seed="boston-hit-seed",
                    configs=2,
                    instances_per_config=10,
                    mechanism="boston_immediate_acceptance",
                    out_dir=out,
                    resume=False,
                    workers=1,
                    expect="manipulations",
                    verify_hits=1,
                    max_witnesses=1000,
                )

            self.assertEqual(exit_code, 1)

            failures_path = os.path.join(out, "verification_failures.jsonl")
            self.assertTrue(os.path.exists(failures_path))
            failures = load_jsonl(failures_path, strip_fields=())
            self.assertEqual(len(failures), 1)

            failure = failures[0]
            self.assertEqual(failure["mechanism"], "boston_immediate_acceptance")
            self.assertEqual(failure["expect"], "manipulations")
            self.assertEqual(list(failure["verify_reasons"]), ["forced failure for test"])
            self.assertIn("witness", failure)
            self.assertIn("market", failure)
            self.assertIn("profile", failure)
            self.assertIn("mechanism_config", failure)

            # negative_control_summary.json is never written on an abort.
            self.assertFalse(
                os.path.exists(os.path.join(out, "negative_control_summary.json"))
            )


if __name__ == "__main__":
    unittest.main()
