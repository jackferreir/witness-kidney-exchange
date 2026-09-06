"""Tests for witness.replay: independent re-verification of a saved witness.

Witness dicts here are built BY HAND against the schema documented in the
task contract -- this module deliberately does not import witness.search
(owned by a different, parallel effort) so that these tests exercise nothing
but the replay contract itself: rebuild market/profile/config/mechanism from
the dict alone, re-run the mechanism twice from scratch, and check every
recorded field against that fresh re-run.

The POSITIVE case below is a hand-worked instance of "first_choice_bonus_da"
whose values were verified independently on paper (see the task contract).
If it does not verify, that is a real finding about either witness.replay or
witness.mechanisms.first_choice_bonus_da -- NOT something to "fix" by
adjusting the expected values here.
"""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from witness.core import content_hash

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _replay_importable() -> bool:
    """witness.replay transitively imports witness.mechanisms, which in turn
    imports witness.controls -- both owned by a parallel effort writing
    against the same contract. Only truly usable once the whole chain
    imports cleanly, checked in a subprocess so a half-written module never
    corrupts this process's import cache."""
    proc = subprocess.run(
        [sys.executable, "-c", "import witness.replay"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=30,
    )
    return proc.returncode == 0


def _wait_for_replay(timeout_seconds: float = 180.0, poll_seconds: float = 15.0) -> bool:
    """Poll briefly for witness.replay's full import chain to become usable."""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if _replay_importable():
            return True
        time.sleep(poll_seconds)
    return _replay_importable()


MECHANISMS_AVAILABLE = _wait_for_replay()

if MECHANISMS_AVAILABLE:
    from witness.replay import verify_file, verify_in_subprocess, verify_witness
else:  # pragma: no cover - only when the parallel effort is still incomplete
    verify_file = verify_in_subprocess = verify_witness = None


def _market_dict() -> dict:
    return {
        "students": ["s1", "s2", "s3"],
        "schools": ["c1", "c2"],
        "capacities": {"c1": 1, "c2": 1},
        "priority_classes": {
            "c1": [["s1"], ["s2"], ["s3"]],
            "c2": [["s1"], ["s2"], ["s3"]],
        },
    }


def _config_dict() -> dict:
    return {
        "mechanism": "first_choice_bonus_da",
        "tiebreak": {"rule": "reject_ties"},
        "unlisted_student_policy": "unacceptable",
        "proposal_policy": "all_free_simultaneous",
    }


def _truthful_profile_dict() -> dict:
    return {
        "rankings": {
            "s1": ["c1", "c2"],
            "s2": ["c1", "c2"],
            "s3": ["c2", "c1"],
        }
    }


def _truthful_assignment_dict() -> dict:
    return {
        "student_to_school": {"s1": "c1", "s2": None, "s3": "c2"},
        "school_to_students": {"c1": ["s1"], "c2": ["s3"]},
    }


def _false_assignment_dict() -> dict:
    return {
        "student_to_school": {"s1": "c1", "s2": "c2", "s3": None},
        "school_to_students": {"c1": ["s1"], "c2": ["s2"]},
    }


def _witness_without_id() -> dict:
    """The hand-worked positive instance, exactly as specified in the task
    contract, minus the witness_id field."""
    return {
        "witness_version": 1,
        "mechanism": "first_choice_bonus_da",
        "config": _config_dict(),
        "market": _market_dict(),
        "truthful_profile": _truthful_profile_dict(),
        "target": "s2",
        "truthful_report": ["c1", "c2"],
        "false_report": ["c2", "c1"],
        "truthful_assignment": _truthful_assignment_dict(),
        "false_assignment": _false_assignment_dict(),
        "truthful_outcome": None,
        "false_outcome": "c2",
        "truthful_outcome_rank": None,
        "false_outcome_rank": 1,
        "preference_proof": (
            "s2 truthfully reports (c1, c2) and is unmatched; by misreporting "
            "(c2, c1), s2 is assigned c2, which s2 strictly prefers to being "
            "unmatched under their truthful report (c1, c2)."
        ),
    }


def make_valid_witness() -> dict:
    d = _witness_without_id()
    d["witness_id"] = content_hash(d)
    return d


@unittest.skipUnless(
    MECHANISMS_AVAILABLE, "witness/mechanisms.py was not written within the poll window"
)
class TestPositiveWitness(unittest.TestCase):
    def test_valid_hand_worked_witness_verifies(self):
        d = make_valid_witness()
        ok, reasons = verify_witness(d)
        self.assertEqual((ok, reasons), (True, ()))

    def test_valid_witness_verifies_in_a_fresh_subprocess(self):
        d = make_valid_witness()
        ok, reasons = verify_in_subprocess(d)
        self.assertEqual((ok, reasons), (True, ()))

    def test_verify_file_on_disk(self):
        d = make_valid_witness()
        with TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "witness.json")
            with open(path, mode="w", encoding="utf-8") as f:
                json.dump(d, f)
            ok, reasons = verify_file(path)
            self.assertEqual((ok, reasons), (True, ()))


@unittest.skipUnless(
    MECHANISMS_AVAILABLE, "witness/mechanisms.py was not written within the poll window"
)
class TestNegativeWitnesses(unittest.TestCase):
    def test_tampered_truthful_assignment_is_rejected(self):
        d = make_valid_witness()
        d["truthful_assignment"] = copy.deepcopy(d["truthful_assignment"])
        d["truthful_assignment"]["student_to_school"]["s1"] = "c2"
        ok, reasons = verify_witness(d)
        self.assertFalse(ok)
        self.assertTrue(reasons)
        self.assertTrue(
            any("truthful_assignment" in r for r in reasons),
            msg=f"expected a reason mentioning truthful_assignment, got {reasons!r}",
        )

    def test_tampered_false_assignment_is_rejected(self):
        d = make_valid_witness()
        d["false_assignment"] = copy.deepcopy(d["false_assignment"])
        d["false_assignment"]["student_to_school"]["s3"] = "c1"
        ok, reasons = verify_witness(d)
        self.assertFalse(ok)
        self.assertTrue(reasons)
        self.assertTrue(
            any("false_assignment" in r for r in reasons),
            msg=f"expected a reason mentioning false_assignment, got {reasons!r}",
        )

    def test_wrong_witness_id_is_rejected(self):
        d = make_valid_witness()
        d["witness_id"] = "0" * 64
        ok, reasons = verify_witness(d)
        self.assertFalse(ok)
        self.assertTrue(reasons)
        self.assertTrue(
            any("witness_id" in r for r in reasons),
            msg=f"expected a reason mentioning witness_id, got {reasons!r}",
        )

    def test_truthful_report_disagreeing_with_profile_is_rejected(self):
        d = make_valid_witness()
        # The profile's report for s2 is ["c1", "c2"]; claim something else.
        d["truthful_report"] = ["c2", "c1"]
        ok, reasons = verify_witness(d)
        self.assertFalse(ok)
        self.assertTrue(reasons)
        self.assertTrue(
            any("truthful_report" in r for r in reasons),
            msg=f"expected a reason mentioning truthful_report, got {reasons!r}",
        )

    def test_gain_running_the_wrong_way_is_rejected(self):
        """Swap truthful_outcome and false_outcome so the target would have
        to strictly prefer their TRUTHFUL outcome over the misreport outcome
        -- i.e. this is not a manipulation at all."""
        d = make_valid_witness()
        d["truthful_outcome"], d["false_outcome"] = d["false_outcome"], d["truthful_outcome"]
        d["truthful_outcome_rank"], d["false_outcome_rank"] = (
            d["false_outcome_rank"],
            d["truthful_outcome_rank"],
        )
        ok, reasons = verify_witness(d)
        self.assertFalse(ok)
        self.assertTrue(reasons)
        self.assertTrue(
            any("prefer" in r.lower() for r in reasons),
            msg=f"expected a reason about the preference direction, got {reasons!r}",
        )

    def test_config_mechanism_disagreeing_with_top_level_is_rejected(self):
        d = make_valid_witness()
        d["config"] = copy.deepcopy(d["config"])
        d["config"]["mechanism"] = "student_proposing_da"
        ok, reasons = verify_witness(d)
        self.assertFalse(ok)
        self.assertTrue(reasons)
        self.assertTrue(
            any("mechanism" in r and "config" in r for r in reasons),
            msg=f"expected a reason about config/mechanism disagreement, got {reasons!r}",
        )

    def test_wrong_witness_version_is_rejected(self):
        d = make_valid_witness()
        d["witness_version"] = 2
        ok, reasons = verify_witness(d)
        self.assertFalse(ok)
        self.assertTrue(reasons)
        self.assertTrue(
            any("witness_version" in r for r in reasons),
            msg=f"expected a reason mentioning witness_version, got {reasons!r}",
        )

    def test_two_independent_defects_both_get_reported(self):
        """verify_witness must not stop at the first failure: a witness with
        TWO unrelated defects must come back with at least two reasons."""
        d = make_valid_witness()
        d["witness_version"] = 2  # defect 1
        d["witness_id"] = "f" * 64  # defect 2, independent of defect 1
        ok, reasons = verify_witness(d)
        self.assertFalse(ok)
        self.assertGreaterEqual(len(reasons), 2)
        self.assertTrue(any("witness_version" in r for r in reasons))
        self.assertTrue(any("witness_id" in r for r in reasons))


@unittest.skipUnless(
    MECHANISMS_AVAILABLE, "witness/mechanisms.py was not written within the poll window"
)
class TestReplayCLI(unittest.TestCase):
    def _run_cli(self, path: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-m", "witness.replay", path],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=60,
        )

    def test_cli_exit_code_0_for_good_witness(self):
        d = make_valid_witness()
        with TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "good.json")
            with open(path, mode="w", encoding="utf-8") as f:
                json.dump(d, f)
            proc = self._run_cli(path)
            self.assertEqual(proc.returncode, 0, msg=f"stdout={proc.stdout!r} stderr={proc.stderr!r}")
            self.assertIn("VERIFIED", proc.stdout)

    def test_cli_exit_code_1_for_bad_witness(self):
        d = make_valid_witness()
        d["witness_id"] = "0" * 64
        with TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "bad.json")
            with open(path, mode="w", encoding="utf-8") as f:
                json.dump(d, f)
            proc = self._run_cli(path)
            self.assertEqual(proc.returncode, 1, msg=f"stdout={proc.stdout!r} stderr={proc.stderr!r}")
            self.assertIn("REJECTED", proc.stdout)

    def test_cli_jsonl_mode_exits_nonzero_if_any_record_fails(self):
        good = make_valid_witness()
        bad = make_valid_witness()
        bad["witness_id"] = "0" * 64
        with TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "journal.jsonl")
            with open(path, mode="w", encoding="utf-8") as f:
                f.write(json.dumps(good) + "\n")
                f.write(json.dumps(bad) + "\n")
            proc = subprocess.run(
                [sys.executable, "-m", "witness.replay", "--jsonl", path],
                cwd=str(PROJECT_ROOT),
                capture_output=True,
                text=True,
                timeout=60,
            )
            self.assertNotEqual(proc.returncode, 0)

    def test_cli_jsonl_mode_exits_zero_if_all_records_pass(self):
        good_a = make_valid_witness()
        good_b = make_valid_witness()
        with TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "journal.jsonl")
            with open(path, mode="w", encoding="utf-8") as f:
                f.write(json.dumps(good_a) + "\n")
                f.write(json.dumps(good_b) + "\n")
            proc = subprocess.run(
                [sys.executable, "-m", "witness.replay", "--jsonl", path],
                cwd=str(PROJECT_ROOT),
                capture_output=True,
                text=True,
                timeout=60,
            )
            self.assertEqual(proc.returncode, 0, msg=f"stdout={proc.stdout!r} stderr={proc.stderr!r}")


if __name__ == "__main__":
    unittest.main()
