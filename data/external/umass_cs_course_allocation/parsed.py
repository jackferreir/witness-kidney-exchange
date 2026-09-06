"""Standalone sanity-check parser for the UMass Amherst CS course-allocation
survey dataset (Fall 2024), from
https://github.com/Fair-and-Explainable-Decision-Making/course-allocation-data

This is pure data plumbing: it reads the raw CSV/XLSX files as downloaded
from GitHub and reports summary counts. It does NOT touch anything under
witness/ and does NOT interpret this data as a Witness Market/
PreferenceProfile — that mapping requires hand-traced, mechanism-specific
judgment calls that are explicitly out of scope here (see
data/external/README.md).

IMPORTANT CONTEXT (see data/external/README.md for full discussion): UMass
Amherst's actual deployed course-registration mechanism is a variant of
Serial Dictatorship (PhD, then MS, then undergrads by decreasing seniority),
which is provably strategy-proof. This dataset is therefore a validation /
clean-result dataset for that deployed mechanism, not a manipulation-hunting
target — unless a *different*, non-deployed mechanism is later tested
against these same real preferences. Nothing in this file changes that.

Usage:
    python3 parsed.py [path/to/resources/dir]
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path
from typing import Any

DEFAULT_DIR = Path(__file__).parent

# Header names for the course-ranking questions in survey_data.csv. Qualtrics
# re-numbered this question across survey revisions, so responses can carry
# their ranking under any of these three header spellings for a given course
# slot. See survey_column_mapping.csv for the question text ("7") and
# REPO_README.md's survey question list.
RANK_COLUMN_PREFIXES = ("7_", "7 _")
RANK_COLUMN_EXACT = ("7",)


def _is_rank_column(header: str) -> bool:
    return header in RANK_COLUMN_EXACT or header.startswith(RANK_COLUMN_PREFIXES)


def parse_survey_data(path: Path) -> dict[str, Any]:
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        header = next(reader)
        rows = list(reader)

    status_idx = header.index("1")  # question 1 = academic status
    rank_cols = [i for i, h in enumerate(header) if _is_rank_column(h)]
    finished_idx = header.index("Finished")

    n_total = len(rows)
    n_finished = sum(1 for r in rows if r[finished_idx].strip() == "1")
    n_has_status = sum(1 for r in rows if r[status_idx].strip() != "")
    n_has_status_and_prefs = sum(
        1
        for r in rows
        if r[status_idx].strip() != "" and any(r[i].strip() != "" for i in rank_cols)
    )

    return {
        "n_total_responses": n_total,
        "n_columns": len(header),
        "n_rank_columns": len(rank_cols),
        "n_finished": n_finished,
        "n_has_status": n_has_status,
        "n_has_status_and_nonempty_prefs": n_has_status_and_prefs,
    }


def parse_courses(path: Path) -> dict[str, Any]:
    import openpyxl

    wb = openpyxl.load_workbook(path, read_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    header = rows[0]
    idx = {name: i for i, name in enumerate(header)}
    data_rows = rows[1:]

    catalogs = {r[idx["Catalog"]] for r in data_rows}
    sections = {(r[idx["Catalog"]], r[idx["Section"]]) for r in data_rows}

    return {
        "n_course_sections": len(data_rows),
        "n_distinct_courses": len(catalogs),
        "n_distinct_catalog_section_pairs": len(sections),
    }


def main(argv: list[str]) -> int:
    directory = Path(argv[1]) if len(argv) > 1 else DEFAULT_DIR
    survey_path = directory / "survey_data.csv"
    courses_path = directory / "anonymized_courses.xlsx"

    if not survey_path.exists() or not courses_path.exists():
        print(
            f"error: expected files not found under {directory}. "
            "See SOURCE.txt for the download URLs.",
            file=sys.stderr,
        )
        return 1

    survey = parse_survey_data(survey_path)
    courses = parse_courses(courses_path)

    print(f"directory: {directory}")
    print(f"survey_data.csv total responses (rows): {survey['n_total_responses']}")
    print(f"  columns: {survey['n_columns']} ({survey['n_rank_columns']} are course-rank columns)")
    print(f"  Finished == 1: {survey['n_finished']}")
    print(f"  responses with academic status specified: {survey['n_has_status']}")
    print(
        "  responses with status AND >=1 non-empty course rank "
        f"(paper's 'effective response' concept): {survey['n_has_status_and_nonempty_prefs']}"
    )
    print(f"anonymized_courses.xlsx course sections (rows): {courses['n_course_sections']}")
    print(f"  distinct course catalog numbers: {courses['n_distinct_courses']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
