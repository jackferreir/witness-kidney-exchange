"""Standalone sanity-check parser for the Stephenson (2022) school-choice
lab-experiment dataset (Zenodo record 6791431).

This is pure data plumbing: it reads the raw CSV as downloaded from Zenodo
and reports summary counts. It does NOT touch anything under witness/ and
does NOT interpret this data as a Witness Market/PreferenceProfile — that
mapping is explicitly out of scope (see data/external/README.md).

The numbers this prints are cross-checked in
tests/test_external_data.py::TestZenodoSchoolChoice against the paper's own
reported sample size, which we obtained not from the (paywalled) full text
but from an independent secondary source that quotes it directly — see the
README for exactly what was and was not verifiable and why.

Usage:
    python3 parsed.py [path/to/SchoolChoiceData.csv]
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path
from typing import Any

DEFAULT_PATH = Path(__file__).parent / "SchoolChoiceData.csv"


def compute_summary(path: Path) -> dict[str, Any]:
    """Read the raw CSV once and return summary statistics.

    Every field below is a directly-observed count from the file, not a
    derived/estimated figure.
    """
    mechanisms: set[str] = set()
    feedback_types: set[str] = set()
    sessions: set[str] = set()
    session_subject_pairs: set[tuple[str, str]] = set()
    subject_types: set[str] = set()
    periods: set[str] = set()
    session_treatment: dict[str, tuple[str, str]] = {}
    n_rows = 0

    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            n_rows += 1
            mechanisms.add(row["mechanism"])
            feedback_types.add(row["feedback"])
            sessions.add(row["session"])
            subject_types.add(row["type"])
            periods.add(row["period"])
            session_subject_pairs.add((row["session"], row["subject"]))
            session_treatment[row["session"]] = (row["mechanism"], row["feedback"])

    return {
        "n_rows": n_rows,
        "n_mechanisms": len(mechanisms),
        "mechanisms": sorted(mechanisms),
        "n_feedback_types": len(feedback_types),
        "feedback_types": sorted(feedback_types),
        "n_sessions": len(sessions),
        "n_subject_types": len(subject_types),
        "subject_types": sorted(subject_types, key=int),
        "n_periods": len(periods),
        "periods": sorted(periods, key=int),
        # This is the headline sample-size figure: one (session, subject)
        # pair is one participant's entire play of one session. Zenodo does
        # not reuse subject IDs across sessions, so this count is the total
        # number of student-participants in the experiment.
        "n_participants": len(session_subject_pairs),
        # design balance check: each session should run exactly one
        # (mechanism, feedback) treatment throughout.
        "n_distinct_session_treatments": len(set(session_treatment.values())),
        "sessions_per_treatment_cell": len(sessions) / max(len(set(session_treatment.values())), 1),
    }


def main(argv: list[str]) -> int:
    path = Path(argv[1]) if len(argv) > 1 else DEFAULT_PATH
    if not path.exists():
        print(f"error: {path} not found. See SOURCE.txt for the download URL.", file=sys.stderr)
        return 1

    summary = compute_summary(path)
    print(f"file: {path}")
    print(f"rows (excluding header): {summary['n_rows']}")
    print(f"mechanisms ({summary['n_mechanisms']}): {summary['mechanisms']}")
    print(f"feedback types ({summary['n_feedback_types']}): {summary['feedback_types']}")
    print(f"sessions: {summary['n_sessions']}")
    print(f"subject types: {summary['subject_types']}")
    print(f"periods per session: {summary['n_periods']}")
    print(f"total participants (unique session,subject pairs): {summary['n_participants']}")
    print(
        f"distinct (mechanism,feedback) treatment cells: "
        f"{summary['n_distinct_session_treatments']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
