"""Sanity checks for the raw external research datasets under
data/external/. These are pure data-plumbing checks: they verify that a
downloaded file is not truncated/corrupted/wrong by cross-checking counts
derived from the raw file against numbers independently published about the
same dataset (a paper's own reported sample size, or another paper's
literature-table citation of it) — not against a number this repo invented.

Per REVIEWER.md's "Test the property, not a proxy" rule, a non-empty file is
not verification; matching an independently-published count is. See
data/external/README.md for full source citations, license findings, and a
detailed discussion of every number checked here (including the ones that do
NOT match, which are recorded as known findings, not hidden).

These tests are skipped (not failed) when the raw data files are not present
on disk, so the rest of the suite is unaffected for anyone without the data
checked out. Nothing here touches witness/da.py, witness/reserves.py, or
witness/mechanisms.py, and no mechanism logic is implied or tested.
"""

from __future__ import annotations

import csv
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
EXTERNAL_DIR = REPO_ROOT / "data" / "external"

ZENODO_DIR = EXTERNAL_DIR / "zenodo_6791431_stephenson_school_choice"
ZENODO_CSV = ZENODO_DIR / "SchoolChoiceData.csv"

UMASS_DIR = EXTERNAL_DIR / "umass_cs_course_allocation"
UMASS_SURVEY_CSV = UMASS_DIR / "survey_data.csv"
UMASS_COURSES_XLSX = UMASS_DIR / "anonymized_courses.xlsx"

KIDNEY_DIR = EXTERNAL_DIR / "pansart2022_kep"
KIDNEY_ZIP = KIDNEY_DIR / "Pansart2022.zip"

try:
    import openpyxl  # noqa: F401

    OPENPYXL_AVAILABLE = True
except ImportError:
    OPENPYXL_AVAILABLE = False


def _load_parser_module(module_name: str, source_dir: Path):
    """Load a dataset's parsed.py as a uniquely-named module.

    Both datasets ship a script named parsed.py (by design — the task asks
    for a standalone parser per dataset, and "parsed.py" is the obvious
    name for both). A plain `import parsed` after inserting each directory
    onto sys.path would collide in sys.modules's global module cache and
    silently return the first one loaded for both datasets, so this loads
    each by explicit file path under its own unique name instead.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(module_name, source_dir / "parsed.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _import_zenodo_parser():
    return _load_parser_module("witness_test_external_zenodo_parsed", ZENODO_DIR)


def _import_umass_parser():
    return _load_parser_module("witness_test_external_umass_parsed", UMASS_DIR)


def _import_kidney_parser():
    return _load_parser_module("witness_test_external_kidney_parsed", KIDNEY_DIR)


@unittest.skipUnless(
    ZENODO_CSV.exists(),
    f"{ZENODO_CSV} not present — run the download described in "
    f"{ZENODO_DIR / 'SOURCE.txt'} to enable this dataset's checks",
)
class TestZenodoSchoolChoice(unittest.TestCase):
    """Cross-checks for the Stephenson (2022) school-choice lab-experiment
    data (Zenodo 6791431), against the "DA, TTC, BOS — 432 students" figure
    reported for this exact paper in an independent citing paper's
    literature table (arXiv 2603.24615) — see data/external/README.md."""

    @classmethod
    def setUpClass(cls):
        cls.parsed = _import_zenodo_parser()
        cls.summary = cls.parsed.compute_summary(ZENODO_CSV)

    def test_file_is_not_truncated_or_empty(self):
        # A necessary but explicitly NOT sufficient check on its own — see
        # the other tests in this class for the property that actually
        # matters (matching the paper's own reported sample size).
        self.assertGreater(self.summary["n_rows"], 0)

    def test_mechanisms_match_paper_abstract(self):
        # The paper's abstract (openly available) names exactly these three
        # mechanisms.
        self.assertEqual(
            self.summary["mechanisms"], ["boston", "defAccept", "topTrading"]
        )

    def test_feedback_conditions_match_paper_design(self):
        self.assertEqual(self.summary["feedback_types"], ["discrete", "realTime"])

    def test_participant_count_matches_independently_published_figure(self):
        # This is the real property under test: an independent secondary
        # source (arXiv 2603.24615's literature table) reports this exact
        # paper's sample as "432 students." We count unique
        # (session, subject) pairs directly from the raw file — not lines,
        # not a proxy — and it must equal 432 for the download to be
        # considered verified rather than merely present.
        self.assertEqual(self.summary["n_participants"], 432)

    def test_design_is_balanced_3x2_in_triplicate(self):
        # 3 mechanisms x 2 feedback conditions = 6 treatment cells;
        # 18 sessions / 6 cells = 3 sessions per cell exactly.
        self.assertEqual(self.summary["n_sessions"], 18)
        self.assertEqual(self.summary["n_distinct_session_treatments"], 6)
        self.assertEqual(self.summary["sessions_per_treatment_cell"], 3.0)


@unittest.skipUnless(
    UMASS_SURVEY_CSV.exists(),
    f"{UMASS_SURVEY_CSV} not present — run the download described in "
    f"{UMASS_DIR / 'SOURCE.txt'} to enable this dataset's checks",
)
class TestUmassCourseAllocationSurvey(unittest.TestCase):
    """Cross-checks for the UMass Amherst CS course-allocation survey data
    against numbers quoted verbatim from the paper's own (open-access)
    text, arXiv:2502.10592 — see data/external/README.md for the exact
    quotes and a discussion of the discrepancies these tests do NOT paper
    over.

    Reminder embedded here deliberately: UMass's actual deployed mechanism
    is a seniority-ordered Serial Dictatorship (PhD, then MS, then
    undergrads by decreasing seniority), which is provably strategy-proof.
    This dataset is a validation dataset for that deployed mechanism, not a
    manipulation-hunting target, unless a different, non-deployed mechanism
    is tested against these same preferences — which is out of scope here.
    """

    @classmethod
    def setUpClass(cls):
        cls.parsed = _import_umass_parser()
        cls.survey_summary = cls.parsed.parse_survey_data(UMASS_SURVEY_CSV)

    def test_file_is_not_truncated_or_empty(self):
        self.assertGreater(self.survey_summary["n_total_responses"], 0)

    def test_total_response_count_matches_the_actual_downloaded_file(self):
        # KNOWN, INVESTIGATED DISCREPANCY (see README.md): the published
        # paper's Table 2 reports 1,065 total responses, and this
        # dataset's own GitHub README prose reports 1,063 — but the file we
        # actually downloaded (sha256 pinned in SOURCE.txt) contains 1,061
        # data rows, confirmed at the byte level. This test pins that
        # verified fact so a future re-download that silently changes row
        # count is caught, rather than asserting the paper's number, which
        # would fail against the real file today.
        self.assertEqual(self.survey_summary["n_total_responses"], 1061)

    def test_status_specified_count_matches_paper_table_exactly(self):
        # Paper's Table 2, summed across all six academic-status rows
        # (156 + 134 + 143 + 135 + 190 + 51 = 809), matches this exactly —
        # unlike the total-response count above, this one is a clean match.
        self.assertEqual(self.survey_summary["n_has_status"], 809)


@unittest.skipUnless(
    UMASS_COURSES_XLSX.exists() and OPENPYXL_AVAILABLE,
    f"{UMASS_COURSES_XLSX} not present, or the optional 'openpyxl' package "
    "is not installed — run the download described in "
    f"{UMASS_DIR / 'SOURCE.txt'} and `pip install openpyxl` to enable this "
    "dataset's checks",
)
class TestUmassCourseAllocationCourses(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.parsed = _import_umass_parser()
        cls.courses_summary = cls.parsed.parse_courses(UMASS_COURSES_XLSX)

    def test_course_section_count_matches_paper_exactly(self):
        # Paper's own text, verbatim: "The Fall 2024 course schedule for
        # the Computer Science department includes 96 distinct course
        # sections."
        self.assertEqual(self.courses_summary["n_course_sections"], 96)
        self.assertEqual(self.courses_summary["n_distinct_catalog_section_pairs"], 96)


@unittest.skipUnless(
    ZENODO_CSV.exists(),
    f"{ZENODO_CSV} not present — see {ZENODO_DIR / 'SOURCE.txt'}",
)
class TestZenodoRawCsvShape(unittest.TestCase):
    """A second, independent read of the raw CSV using the stdlib csv
    module directly (not going through parsed.py), so this test does not
    merely re-check parsed.py's own arithmetic against itself."""

    def test_header_matches_documented_schema(self):
        with open(ZENODO_CSV, newline="") as f:
            header = next(csv.reader(f))
        self.assertEqual(
            header,
            [
                "session",
                "feedback",
                "mechanism",
                "period",
                "subject",
                "type",
                "truth",
                "lotto",
                "second",
                "assignment",
                "report",
                "pay1",
                "pay2",
                "pay3",
                "pay4",
                "pay5",
                "pay6",
            ],
        )


@unittest.skipUnless(
    KIDNEY_ZIP.exists(),
    f"{KIDNEY_ZIP} not present — run the download described in "
    f"{KIDNEY_DIR / 'SOURCE.txt'} to enable this dataset's checks",
)
class TestPansart2022KidneyExchange(unittest.TestCase):
    """Exercises `parsed.py` on the smallest instance (P=50, N=3) — checks
    the header-vs-actual-matrix-shape agreement and the diagonal structural
    invariant (a pair's own donor can never transplant to that pair's own
    recipient, since that pair only exists BECAUSE they are incompatible
    with each other) that `witness/kidney_real_data.py` later depends on."""

    @classmethod
    def setUpClass(cls):
        cls.parsed_module = _import_kidney_parser()
        cls.instances = cls.parsed_module.list_instances(KIDNEY_ZIP)

    def test_270_instance_files_present(self):
        # 6 P-values (50/100/250/500/750/1000) x 3 N-values each x 3
        # L-values (3/6/12) x 5 replicates = 270, independently confirmed
        # by directly enumerating the zip -- pinned so a future silently-
        # truncated re-download is caught.
        self.assertEqual(len(self.instances), 270)

    def test_smallest_instance_header_matches_actual_matrix_shape(self):
        member = "Pansart2022/KEP_p50_n3_k3_l3_0.txt"
        self.assertIn(member, self.instances)
        parsed = self.parsed_module.parse_instance(KIDNEY_ZIP, member)
        self.assertEqual(parsed["declared_p"], 50)
        self.assertEqual(parsed["declared_n"], 3)
        self.assertTrue(parsed["shape_matches_header"])
        self.assertEqual(parsed["actual_matrix_rows"], 53)
        self.assertEqual(parsed["actual_matrix_cols"], [50])

    def test_diagonal_is_always_infeasible(self):
        # Structural invariant, not merely observed on one file: a
        # patient-donor pair exists specifically because ITS OWN donor and
        # recipient are incompatible.
        parsed = self.parsed_module.parse_instance(KIDNEY_ZIP, "Pansart2022/KEP_p50_n3_k3_l3_0.txt")
        self.assertTrue(parsed["diagonal_all_infeasible"])

    def test_feasible_density_is_real_and_sparse_not_uniform_synthetic(self):
        # The real graph's density (~5-7%) is reported here as a pinned
        # fact about THIS file, not a claim about all KEP data everywhere
        # -- it exists so a future re-download that silently changes the
        # file is caught, and so `witness/kidney_real_data.py`'s own
        # docstring can cite a checked number rather than an assumed one.
        parsed = self.parsed_module.parse_instance(KIDNEY_ZIP, "Pansart2022/KEP_p50_n3_k3_l3_0.txt")
        self.assertEqual(parsed["n_feasible_entries"], 152)
        self.assertEqual(parsed["n_matrix_entries"], 2650)  # (3 + 50) rows x 50 cols
        self.assertAlmostEqual(parsed["feasible_density"], 152 / 2650, places=6)


@unittest.skipUnless(
    KIDNEY_ZIP.exists(),
    f"{KIDNEY_ZIP} not present — see {KIDNEY_DIR / 'SOURCE.txt'}",
)
class TestKidneyRawZipShape(unittest.TestCase):
    """A second, independent read of the raw zip member using Python's
    zipfile module directly (not going through parsed.py's own header/
    matrix-parsing logic), so this test does not merely re-check parsed.py's
    own arithmetic against itself."""

    def test_header_and_first_matrix_row_read_independently(self):
        import zipfile

        with zipfile.ZipFile(KIDNEY_ZIP) as zf:
            text = zf.read("Pansart2022/KEP_p50_n3_k3_l3_0.txt").decode("utf-8")
        lines = [ln for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("//")]
        # First 4 non-comment, non-blank lines are P, N, K, L in that order.
        self.assertEqual([int(x) for x in lines[:4]], [50, 3, 3, 3])
        # Every subsequent line is a tab-separated row of exactly 50 ints.
        matrix_lines = lines[4:]
        self.assertEqual(len(matrix_lines), 3 + 50)  # N + P rows
        for ln in matrix_lines:
            # Each raw line has a TRAILING tab before the newline (confirmed
            # directly in the raw bytes) -- stripped first, matching what
            # parsed.py itself does, or a naive split("\t") reports 51
            # fields (50 real values + 1 spurious empty trailing field).
            cells = ln.strip().split("\t")
            self.assertEqual(len(cells), 50)
            for c in cells:
                int(c)  # raises ValueError if not a clean integer -- not asserted separately


if __name__ == "__main__":
    unittest.main()
