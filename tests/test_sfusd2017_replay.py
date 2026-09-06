"""Replay REAL, deployed administrative data through this project's mechanisms:
SFUSD's 2017-18 Kindergarten Main Round.

Data: San Francisco Unified School District kindergarten application/
assignment records, obtained by KQED journalist Lisa Pickoff-White via a
California Public Records Act request. See `witness.sfusd2017` for the full
provenance, the primary-source research establishing what the real 2017-18
mechanism and priority order actually were, and for exactly how the measured
numbers below were produced.

This is the project's second real dataset and its first that is NOT a lab
experiment. Unlike `tests/test_stephenson_replay.py` (0 mismatches out of
5,184 real recorded outcomes), this suite does NOT expect or assert a clean
reproduction -- three real priority inputs (sibling status, attendance area,
the real per-program lottery draw) are simply absent from the public file, so
an exact replay is not achievable from this data at all. The point of this
suite is to measure the actual match rate honestly, show it is not vacuous,
and show the one real signal this file DOES contain (CTIP1) is both
correctly modelled and independently corroborated against a published paper
analyzing this exact dataset.

Skipped cleanly when the data file is absent, so the suite still runs for
anyone who has not fetched the dataset.
"""

from __future__ import annotations

import collections
import csv
import functools
import itertools
import json
import os
import subprocess
import sys
import unittest

from witness import sfusd2017 as s
from witness.mechanisms import get_mechanism

DATA_DIR = os.path.join("data", "external", "sfusd_2017_kindergarten")
RAW = os.path.join(
    DATA_DIR,
    "20171103_KQED_KinderAssignmentData_201718_K_Placement_2017-2018.csv",
)

HAVE_RAW = os.path.exists(RAW)

#: What the raw file itself contains -- asserted, not assumed, below. See
#: `data/external/sfusd_2017_kindergarten/SOURCE.txt` for why this differs
#: from the CHI 2021 paper's own "4,594 applicants" by 17 rows, an
#: independently-sourced discrepancy that is reported rather than resolved.
N_APPLICANTS = 4611
N_SCHOOLS = 72
N_CTIP1 = 705
N_ASSIGNED_ROUND1 = 4470
N_UNASSIGNED_ROUND1 = 141
N_STUDENTS_WITH_DUPLICATE_SCHOOL_MENTIONS = 1647

# The instance is real, ~4,600-applicant/72-school data (unlike Stephenson's
# 24-participant periods), and several test classes below independently need
# the parsed records, the built market, and full three-mechanism replays.
# These are all pure, deterministic functions of the (fixed) raw file, so
# they are cached rather than recomputed per test -- this changes nothing
# about what is being tested, only how many times the same computation runs.


@functools.lru_cache(maxsize=None)
def load_records():
    rows = s.load_raw_rows(RAW)
    return tuple(rows), s.build_records(rows)


@functools.lru_cache(maxsize=None)
def cached_market(invert_ctip1: bool = False):
    _, records = load_records()
    return s.build_market(records, invert_ctip1=invert_ctip1)


@functools.lru_cache(maxsize=None)
def cached_run_all(seed: str, invert_ctip1: bool = False):
    """{mechanism_name: student_to_school}, cached by (seed, invert_ctip1)."""
    _, records = load_records()
    market = cached_market(invert_ctip1)
    profile = s.build_profile(records)
    tiebreak = s.stand_in_tiebreak(seed)
    out = {}
    for name in s.CANDIDATE_MECHANISMS:
        cfg = s.config_for(name, tiebreak)
        spec = get_mechanism(name)
        out[name] = spec.run(market, profile, cfg).student_to_school
    return out


@unittest.skipUnless(HAVE_RAW, "SFUSD 2017 raw CSV not present")
class DatasetShape(unittest.TestCase):
    """Pins the dataset's own shape, independent of any mechanism replay.
    If any of these failed, everything below would be measuring the wrong
    file or the wrong parsing of it."""

    def test_row_and_school_counts(self):
        rows, records = load_records()
        self.assertEqual(len(rows), N_APPLICANTS)
        self.assertEqual(len(records), N_APPLICANTS)
        self.assertEqual(len(s.all_schools(records)), N_SCHOOLS)

    def test_ctip1_and_assignment_counts(self):
        _, records = load_records()
        self.assertEqual(sum(1 for r in records if r.ctip1), N_CTIP1)
        self.assertEqual(
            sum(1 for r in records if r.round1_assignment is not None),
            N_ASSIGNED_ROUND1,
        )
        self.assertEqual(
            sum(1 for r in records if r.round1_assignment is None),
            N_UNASSIGNED_ROUND1,
        )
        self.assertEqual(N_ASSIGNED_ROUND1 + N_UNASSIGNED_ROUND1, N_APPLICANTS)

    def test_inferred_capacity_sums_to_assigned_count(self):
        """`infer_capacities` sets each school's capacity to its realized
        Round 1 fill count, so summed capacity must equal the number of
        applicants actually assigned in Round 1 -- see the module docstring's
        CAPACITY INFERENCE section."""
        _, records = load_records()
        schools = s.all_schools(records)
        caps = s.infer_capacities(records, schools)
        self.assertEqual(sum(caps.values()), N_ASSIGNED_ROUND1)

    def test_every_recorded_assignment_is_within_the_students_own_report(self):
        """A student can only be assigned a school they actually ranked --
        confirms the adapter isn't silently producing an assignment the
        student never listed, which `recorded_assignment`'s docstring
        claims."""
        _, records = load_records()
        outside = [
            r.student_id
            for r in records
            if r.round1_assignment and r.round1_assignment not in r.ranked_schools
        ]
        self.assertEqual(outside, [])

    def test_the_documented_school_code_duplication_finding(self):
        """1,647 applicants list the same school code more than once across
        their 92 rank columns -- direct evidence the file collapses distinct
        PROGRAMS at one school into a single school code. See the module
        docstring's "SCHOOL VS. PROGRAM GRANULARITY" section."""
        rows, records = load_records()
        n_dupe = sum(
            1
            for row, r in zip(rows, records)
            if r.n_duplicate_school_mentions(tuple(row[c] for c in s.RANK_COLUMNS)) > 0
        )
        self.assertEqual(n_dupe, N_STUDENTS_WITH_DUPLICATE_SCHOOL_MENTIONS)

    def test_no_sibling_household_or_address_column_exists_in_the_raw_file(self):
        """Confirms, against the RAW file's own header -- not against
        `RAW_FIELDS`, this adapter's own curated subset, which could itself
        silently omit a column that exists -- that sibling priority
        genuinely has no reconstruction path here: no sibling flag, no
        household/family identifier, and no address finer than ZIP code
        (so shared-address inference is not available either). This is
        what backs the module docstring's "SIBLING PRIORITY: CONFIRMED
        UNRECOVERABLE" section as a checked claim rather than an assumption."""
        with open(RAW, newline="") as f:
            header = next(csv.reader(f))
        self.assertEqual(len(header), 98, "raw file's own column count changed")
        lowered = [h.lower() for h in header]
        for banned_substring in (
            "sibling",
            "household",
            "family",
            "address",
            "street",
        ):
            hits = [h for h in lowered if banned_substring in h]
            self.assertEqual(
                hits,
                [],
                f"a column containing {banned_substring!r} exists in the raw "
                f"file ({hits}) -- sibling priority may be reconstructable "
                f"after all; this test and the module docstring's claim that "
                f"it is not need to be revisited",
            )
        # The only geographic field, at any granularity, is ZIP code.
        geo_like = [
            h
            for h in lowered
            if "zip" in h or "tract" in h or "geo" in h or "attendance" in h
        ]
        self.assertEqual(geo_like, ["student's residential zip code"])

    def test_the_dead_school_code_is_never_assigned_or_enrolled(self):
        """See the module docstring: school code 476 was ranked by exactly
        one applicant and is otherwise inert in this dataset."""
        _, records = load_records()
        ranked_by = sum(
            1 for r in records if s.DEAD_SCHOOL_CODE in r.ranked_schools
        )
        assigned_to = sum(
            1 for r in records if r.round1_assignment == s.DEAD_SCHOOL_CODE
        )
        enrolled_in = sum(
            1 for r in records if r.enrolled_school == s.DEAD_SCHOOL_CODE
        )
        self.assertEqual(ranked_by, 1)
        self.assertEqual(assigned_to, 0)
        self.assertEqual(enrolled_in, 0)


@unittest.skipUnless(HAVE_RAW, "SFUSD 2017 raw CSV not present")
class CrossCheckAgainstThePublishedPaper(unittest.TestCase):
    """Robertson, Nguyen & Salehi (CHI 2021, arXiv:2101.10367) analyze this
    exact dataset and publish several summary statistics from it. Every
    number here is reproduced directly from the raw file by this project's
    own code, then compared to the paper's own text -- this is the same
    discipline `data/external/README.md` already applies to the UMass
    dataset (Table 2 cross-checks), and it is what justifies calling this
    the SAME dataset the paper analyzes rather than merely a similarly-named
    one."""

    def test_ctip1_and_non_ctip1_mean_ranked_schools_match_the_paper(self):
        """Paper (verbatim): "students ranked 5.5 schools in their
        application ... families in other areas of the city ranked an
        average of 11.6". Uses raw (pre-dedup) rank-column counts, since
        that is what "schools ranked" counts in the paper's own methodology
        (a repeated school code from a second program still occupied a rank
        slot on the family's real submitted list)."""
        _, records = load_records()
        ctip1_mean = s.mean_raw_rank_count(records, ctip1=True)
        non_ctip1_mean = s.mean_raw_rank_count(records, ctip1=False)
        self.assertAlmostEqual(ctip1_mean, 5.5, delta=0.15)
        self.assertAlmostEqual(non_ctip1_mean, 11.6, delta=0.15)

    def test_white_applicants_mean_ranked_schools_matches_the_paper(self):
        """Paper (verbatim): "White students submitted especially long
        preference lists (mean = 16.5...)"."""
        _, records = load_records()
        white = [
            r for r in records if r.ethnicity == "White, Not of Hispanic Origin"
        ]
        self.assertGreater(len(white), 0)
        mean_ranked = sum(r.raw_rank_count for r in white) / len(white)
        self.assertAlmostEqual(mean_ranked, 16.5, delta=0.2)

    def test_ctip1_recorded_first_choice_rate_matches_the_paper(self):
        """Paper (verbatim): "96% of families eligible for CTIP1 priority
        were assigned their first choice." This uses ONLY the recorded
        outcome column -- no replay, no mechanism, no tiebreak -- so it
        checks the raw file and this adapter's parsing of it, not anything
        this project computed."""
        _, records = load_records()
        got, total = s.recorded_first_choice_rate(records, ctip1=True)
        self.assertEqual(total, N_CTIP1)
        self.assertAlmostEqual(got / total * 100, 96.0, delta=0.5)

    def test_non_ctip1_recorded_first_choice_rate_matches_the_paper(self):
        """Paper (verbatim): "...compared to only 58% of other students.\""""
        _, records = load_records()
        got, total = s.recorded_first_choice_rate(records, ctip1=False)
        self.assertAlmostEqual(got / total * 100, 58.0, delta=0.5)


@unittest.skipUnless(HAVE_RAW, "SFUSD 2017 raw CSV not present")
class ReplayReproducesTheRecordedOutcomesAsFarAsItCan(unittest.TestCase):
    """The headline check -- and the headline honest result. Unlike
    Stephenson, this is NOT a 100% reproduction: three real priority inputs
    (sibling, attendance area, the real per-program lottery) are not present
    in the public file at all, so this project's candidate mechanisms cannot
    be expected to reproduce SFUSD's real 2017 outcome exactly. What is
    checked here is the ACTUAL measured match rate against the recorded
    `Round 1 Assignment` column, exactly as computed and not tuned to hit a
    target -- see REVIEWER.md's "test the property, not a proxy"."""

    #: Measured under `STAND_IN_SEED`; see `witness.sfusd2017`'s module
    #: docstring "EMPIRICAL RESULT" section for the full breakdown and the
    #: mechanical explanation for the CTIP1 figures. These are EXACT counts
    #: (not "approximately"), and a regression in any of them means either
    #: the adapter or one of `witness.ttc`/`witness.da`/`witness.boston`
    #: changed -- not something to "fix" by adjusting the number here.
    EXPECTED = {
        "top_trading_cycles": 2586,
        "student_proposing_da": 2108,
        "boston_immediate_acceptance": 2800,
    }
    EXPECTED_CTIP1 = 677  # identical across all three mechanisms

    def test_overall_match_counts_are_exactly_what_is_measured(self):
        _, records = load_records()
        results = cached_run_all(s.STAND_IN_SEED)
        actual = {}
        for name, got in results.items():
            matched, total = s.match_rate(got, records)
            self.assertEqual(total, N_APPLICANTS)
            actual[name] = matched
        self.assertEqual(actual, self.EXPECTED)

    def test_no_mechanism_reproduces_close_to_everything(self):
        """The honest headline: none of the three candidates comes close to
        Stephenson's 100%. If one ever did, that would be a strong signal
        this project had accidentally reconstructed the real mechanism (or,
        far more likely, a bug that made the check vacuous) -- either way,
        worth immediate scrutiny rather than celebration."""
        for name, matched in self.EXPECTED.items():
            rate = matched / N_APPLICANTS
            self.assertLess(rate, 0.75, f"{name} matched suspiciously well: {rate:.1%}")
            self.assertGreater(rate, 0.30, f"{name} matched suspiciously badly: {rate:.1%}")

    def test_ctip1_matches_identically_across_all_three_mechanisms(self):
        """Mechanical consequence of CTIP1 being the shared top (and only
        modelled) priority tier at every school -- see
        `witness.ttc.distinct_priority_orders` and the module docstring."""
        _, records = load_records()
        results = cached_run_all(s.STAND_IN_SEED)
        ctip1_matches = {}
        for name, got in results.items():
            matched, total = s.match_rate(got, records, ctip1=True)
            self.assertEqual(total, N_CTIP1)
            ctip1_matches[name] = matched
        self.assertEqual(
            ctip1_matches,
            {name: self.EXPECTED_CTIP1 for name in s.CANDIDATE_MECHANISMS},
        )

    def test_every_ctip1_student_gets_their_own_first_choice_in_the_replay(self):
        """The mechanical claim underlying the identity above: under this
        adapter's model, ALL 705 CTIP1 students receive their own reported
        first-ranked school in the replay, regardless of which of the three
        mechanisms is used. Combined with `recorded_first_choice_rate`
        (96.0% in the real recorded outcome), this is what pins the 677/705
        match figure -- a CTIP1 student's replay matches the recording iff
        the recording already WAS their first choice."""
        _, records = load_records()
        profile = s.build_profile(records)
        results = cached_run_all(s.STAND_IN_SEED)
        ctip1_ids = {r.student_id for r in records if r.ctip1}
        for name, got in results.items():
            n_first = sum(
                1
                for sid in ctip1_ids
                if profile.report(sid) and got.get(sid) == profile.report(sid)[0]
            )
            self.assertEqual(n_first, N_CTIP1, msg=f"{name} broke the CTIP1 first-choice identity")


@unittest.skipUnless(HAVE_RAW, "SFUSD 2017 raw CSV not present")
class TheReplayIsNotVacuous(unittest.TestCase):
    """A partial match rate proves nothing if the three mechanisms would
    have agreed anyway, or if the recorded outcome were trivial (everyone
    assigned their only-ranked school, capacity never binding, etc). Both
    are measured here."""

    def test_the_three_mechanisms_disagree_substantially_on_this_market(self):
        market = cached_market()
        results = cached_run_all(s.STAND_IN_SEED)
        disagree = collections.Counter()
        for x, y in itertools.combinations(sorted(results), 2):
            n = sum(
                1
                for sid in market.students
                if results[x][sid] != results[y][sid]
            )
            disagree[(x, y)] = n
        for pair, n in disagree.items():
            self.assertGreater(
                n / N_APPLICANTS, 0.10, f"{pair} disagreed on only {n}/{N_APPLICANTS}"
            )

    def test_scarcity_binds_most_applicants_ranked_more_than_one_school(self):
        _, records = load_records()
        multi = sum(1 for r in records if len(r.ranked_schools) > 1)
        self.assertGreater(multi / N_APPLICANTS, 0.5)

    def test_capacity_is_actually_scarce_somewhere(self):
        """If every school's capacity happened to exceed the number of
        applicants who ranked it, DA/TTC/Boston would degenerate to
        "everyone gets their first choice" and the replay would prove
        nothing. Confirms real oversubscription exists in this instance."""
        _, records = load_records()
        market = cached_market()
        demand = collections.Counter()
        for r in records:
            if r.ranked_schools:
                demand[r.ranked_schools[0]] += 1
        oversubscribed = [
            sch for sch, d in demand.items() if d > market.capacity(sch)
        ]
        self.assertGreater(len(oversubscribed), 0)


@unittest.skipUnless(HAVE_RAW, "SFUSD 2017 raw CSV not present")
class TheModelIsActuallySensitiveToWhatItClaimsToModel(unittest.TestCase):
    """The priority structure here is NOT recovered by search (see the
    module docstring's "WHY THIS COULD NOT BE RECOVERED" section) -- most of
    it is an admitted, clearly-named stand-in. But the one real signal this
    dataset supplies, CTIP1, must actually matter to the replay, or modelling
    it would be theater. This class proves it does."""

    def test_inverting_ctip1_priority_measurably_degrades_every_mechanism(self):
        """Swapping CTIP1 to the BOTTOM priority tier is a deliberately wrong
        structure. It must produce a different, and specifically a worse or
        at least different, match rate -- otherwise the replay above would
        be insensitive to the very input it claims to use."""
        _, records = load_records()
        correct = cached_run_all(s.STAND_IN_SEED, invert_ctip1=False)
        inverted = cached_run_all(s.STAND_IN_SEED, invert_ctip1=True)
        for name in s.CANDIDATE_MECHANISMS:
            m_correct, _ = s.match_rate(correct[name], records)
            m_inverted, _ = s.match_rate(inverted[name], records)
            self.assertNotEqual(
                m_correct,
                m_inverted,
                f"{name}: inverting CTIP1 priority did not change the match "
                f"count at all, so the replay does not identify CTIP1's "
                f"position",
            )
            # Specifically: CTIP1 students' own match rate should collapse,
            # since they no longer hold top priority anywhere.
            mc_correct, _ = s.match_rate(correct[name], records, ctip1=True)
            mc_inverted, _ = s.match_rate(inverted[name], records, ctip1=True)
            self.assertLess(
                mc_inverted,
                mc_correct,
                f"{name}: inverting CTIP1 priority did not hurt CTIP1 "
                f"students' own match rate",
            )

    def test_match_rate_is_not_an_artifact_of_the_one_stand_in_draw(self):
        """Re-running under a completely unrelated stand-in lottery seed
        should move the match rate somewhat (it is a real, seed-dependent
        tiebreak) but not wildly -- if the two seeds produced near-identical
        results that would suggest the lottery never actually bound
        anything; if they produced wildly different results that would
        suggest the headline numbers above are noise rather than signal."""
        _, records = load_records()
        results_a = cached_run_all(s.STAND_IN_SEED)
        results_b = cached_run_all(s.STAND_IN_SEED_ALTERNATE)
        for name in s.CANDIDATE_MECHANISMS:
            ma, _ = s.match_rate(results_a[name], records)
            mb, _ = s.match_rate(results_b[name], records)
            rate_a, rate_b = ma / N_APPLICANTS, mb / N_APPLICANTS
            self.assertNotEqual(ma, mb, f"{name}: two unrelated seeds gave the identical count")
            self.assertLess(
                abs(rate_a - rate_b),
                0.05,
                f"{name}: match rate swung by more than 5 points between "
                f"two stand-in seeds ({rate_a:.1%} vs {rate_b:.1%})",
            )

    def test_ctip1_as_a_full_reserve_is_identical_to_ctip1_as_a_plain_priority(self):
        """Answers the task's "does CTIP1 behave like a reserve or a plain
        priority" question for this dataset: giving CTIP1 a soft reserve on
        every seat, on top of the same base order, changes NOTHING, because
        CTIP1 is already the base order's top tier everywhere. See
        `witness.sfusd2017.full_ctip1_reserve_config`'s docstring."""
        _, records = load_records()
        market = cached_market()
        profile = s.build_profile(records)
        tiebreak = s.stand_in_tiebreak()
        da_cfg = s.config_for("student_proposing_da", tiebreak)
        got_da = get_mechanism("student_proposing_da").run(
            market, profile, da_cfg
        ).student_to_school
        reserve_cfg = s.full_ctip1_reserve_config(records, market, tiebreak)
        got_reserve = get_mechanism("reserve_da").run(
            market, profile, reserve_cfg
        ).student_to_school
        self.assertEqual(got_da, got_reserve)


@unittest.skipUnless(HAVE_RAW, "SFUSD 2017 raw CSV not present")
class RealDataReplaysInAFreshProcess(unittest.TestCase):
    """Per REVIEWER.md's 'every finding replays from its saved witness alone,
    in a fresh subprocess' rule. Not a manipulation finding here (see the
    module docstring's REPORTED VS TRUE PREFERENCES section and this task's
    explicit scope limits), but the same replay discipline applies to any
    saved market/profile/config -- if it can't reproduce outside this
    interpreter, it isn't infrastructure."""

    def test_one_mechanism_reproduces_its_own_measured_match_count_in_a_subprocess(self):
        _, records = load_records()
        market = cached_market()
        profile = s.build_profile(records)
        tiebreak = s.stand_in_tiebreak()
        config = s.config_for("boston_immediate_acceptance", tiebreak)
        recorded = s.recorded_assignment(records)
        payload = json.dumps(
            {
                "market": market.to_dict(),
                "profile": profile.to_dict(),
                "config": config.to_dict(),
                "recorded": recorded,
            }
        )
        script = (
            "import json,sys;"
            "from witness.core import Market, Profile;"
            "from witness.mechanisms import get_mechanism;"
            "d=json.loads(sys.stdin.read());"
            "spec=get_mechanism('boston_immediate_acceptance');"
            "got=spec.run(Market.from_dict(d['market']),Profile.from_dict(d['profile']),"
            "spec.config_from_dict(d['config'])).student_to_school;"
            "matched=sum(1 for k,v in d['recorded'].items() if got.get(k)==v);"
            "print(json.dumps(matched))"
        )
        proc = subprocess.run(
            [sys.executable, "-c", script], input=payload,
            capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertEqual(
            json.loads(proc.stdout),
            ReplayReproducesTheRecordedOutcomesAsFarAsItCan.EXPECTED[
                "boston_immediate_acceptance"
            ],
            "the measured match count did not reproduce in a fresh interpreter",
        )


if __name__ == "__main__":
    unittest.main()
