"""End-to-end integration tests crossing the search -> journal -> replay seam.

No other test module exercises this seam as a whole: `test_search.py` checks the
search in isolation, `test_replay.py` checks replay against hand-built witness
dicts, and `test_journal.py` checks the journal against arbitrary records. None of
them ever appends a *real, search-produced* witness to a *real* journal and then
replays it -- which is exactly the path that exposed the bug this change fixes:
`witness.da.DAConfig.to_dict()` used to hardcode `"mechanism":
"student_proposing_da"`, so a witness produced by searching `first_choice_bonus_da`
(which reuses `DAConfig`) carried a config disagreeing with its own top-level
`"mechanism"` field, and `witness.replay.verify_witness`'s check 2 rejected every
such witness. This module is the regression test for that failure mode.
"""

from __future__ import annotations

import copy
import os
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from witness.core import Market, Profile
from witness.da import DAConfig
from witness.errors import ModelError
from witness.journal import Journal
from witness.replay import verify_in_subprocess, verify_witness
from witness.search import search_all_students
from witness.tiebreak import RejectTies

PROJECT_ROOT = Path(__file__).resolve().parent.parent

#: The VERIFIED CONTROL INSTANCE from witness/controls.py: students s1,s2,s3;
#: schools c1,c2; capacities 1 each; identical priority s1>s2>s3 at both schools.


def _market() -> Market:
    return Market(
        students=("s1", "s2", "s3"),
        schools=("c1", "c2"),
        capacities={"c1": 1, "c2": 1},
        priority_classes={
            "c1": (("s1",), ("s2",), ("s3",)),
            "c2": (("s1",), ("s2",), ("s3",)),
        },
    )


def _profile() -> Profile:
    return Profile({"s1": ("c1", "c2"), "s2": ("c1", "c2"), "s3": ("c2", "c1")})


def _run_replay_cli(jsonl_path: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "witness.replay", "--jsonl", jsonl_path],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=60,
    )


class SearchJournalReplayIntegrationTestCase(unittest.TestCase):
    """search_all_students -> Journal -> replay.verify_witness /
    verify_in_subprocess / the `python3 -m witness.replay --jsonl` CLI must all
    agree, for BOTH mechanisms that share `DAConfig`."""

    def _run_and_check(self, mechanism_name: str, config: DAConfig) -> tuple:
        market, profile = _market(), _profile()
        witnesses = search_all_students(market, profile, mechanism_name, config)

        with TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "journal.jsonl")
            journal = Journal(path)
            for w in witnesses:
                journal.append(w.to_dict())

            records = journal.read_all()
            self.assertEqual(records, tuple(w.to_dict() for w in witnesses))

            for i, record in enumerate(records):
                ok, reasons = verify_witness(record)
                self.assertEqual(
                    (ok, reasons), (True, ()),
                    msg=f"{mechanism_name} record {i}: verify_witness rejected it: {reasons}",
                )

            for i, record in enumerate(records):
                ok, reasons = verify_in_subprocess(record)
                self.assertEqual(
                    (ok, reasons), (True, ()),
                    msg=f"{mechanism_name} record {i}: verify_in_subprocess rejected it: {reasons}",
                )

            proc = _run_replay_cli(path)
            self.assertEqual(
                proc.returncode, 0,
                msg=f"{mechanism_name}: CLI exited {proc.returncode}; "
                f"stdout={proc.stdout!r} stderr={proc.stderr!r}",
            )

        return witnesses

    def test_first_choice_bonus_da_end_to_end(self):
        config = DAConfig(tiebreak=RejectTies(), mechanism="first_choice_bonus_da")
        witnesses = self._run_and_check("first_choice_bonus_da", config)
        # Canary: this control instance has a hand-verified manipulation for s2.
        self.assertGreaterEqual(
            len(witnesses), 1,
            "expected at least one manipulation under first_choice_bonus_da on "
            "the control instance",
        )

    def test_student_proposing_da_end_to_end(self):
        config = DAConfig(tiebreak=RejectTies())  # default mechanism="student_proposing_da"
        witnesses = self._run_and_check("student_proposing_da", config)
        # Plain DA is strategy-proof for students, so this instance -- being
        # the same market/profile as the canary above -- must yield zero.
        self.assertEqual(
            len(witnesses), 0,
            "plain student_proposing_da must not be manipulable on this instance",
        )


class TamperedWitnessIsRejectedTestCase(unittest.TestCase):
    """A genuine witness with one student's `false_assignment` school changed
    must fail both `verify_witness` and the CLI, with a reason naming the
    tampered field."""

    def test_tampered_false_assignment_fails_replay_and_cli_exits_1(self):
        config = DAConfig(tiebreak=RejectTies(), mechanism="first_choice_bonus_da")
        market, profile = _market(), _profile()
        witnesses = search_all_students(market, profile, "first_choice_bonus_da", config)
        self.assertTrue(witnesses, "expected the canary manipulation to be found")

        genuine = witnesses[0].to_dict()
        tampered = copy.deepcopy(genuine)
        s_to_c = tampered["false_assignment"]["student_to_school"]
        target_student = sorted(s_to_c)[0]
        current = s_to_c[target_student]
        s_to_c[target_student] = "c1" if current != "c1" else "c2"

        with TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "journal.jsonl")
            journal = Journal(path)
            journal.append(tampered)

            ok, reasons = verify_witness(tampered)
            self.assertFalse(ok)
            self.assertTrue(
                any("false_assignment" in r for r in reasons),
                msg=f"expected a reason mentioning false_assignment, got {reasons!r}",
            )

            proc = _run_replay_cli(path)
            self.assertEqual(
                proc.returncode, 1,
                msg=f"CLI exited {proc.returncode} on a tampered witness; "
                f"stdout={proc.stdout!r} stderr={proc.stderr!r}",
            )


class MechanismConfigGuardTestCase(unittest.TestCase):
    """The new search-time guard: a config whose own `to_dict()["mechanism"]`
    disagrees with the mechanism actually being searched must raise
    `ModelError` before any search work happens."""

    def test_search_all_students_raises_on_mechanism_config_disagreement(self):
        market, profile = _market(), _profile()
        config = DAConfig(tiebreak=RejectTies())  # mechanism="student_proposing_da"
        with self.assertRaises(ModelError):
            search_all_students(market, profile, "first_choice_bonus_da", config)


if __name__ == "__main__":
    unittest.main()
