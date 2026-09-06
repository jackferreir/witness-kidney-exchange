"""Replay a REAL published experiment through this project's mechanisms.

Stephenson (2022), Experimental Economics 25(5); data from Zenodo record
6791431 under CC-BY-4.0. See `witness.stephenson` for the full provenance and
for how the priority structure was recovered.

This is the first test in the suite whose expected values were produced by
someone else: the `assignment` column is what the experiment's own software
assigned to 432 real people, and every mechanism here has to reproduce it
exactly from the reports those people actually submitted.

Skipped cleanly when the data files are absent, so the suite still runs for
anyone who has not fetched the dataset.
"""

from __future__ import annotations

import collections
import itertools
import json
import os
import subprocess
import sys
import unittest

from witness.core import Profile, position
from witness.mechanisms import get_mechanism
from witness import stephenson as st

DATA_DIR = os.path.join(
    "data", "external", "zenodo_6791431_stephenson_school_choice"
)
RAW = os.path.join(DATA_DIR, "SchoolChoiceData.csv")
CACHE = os.path.join(DATA_DIR, "final_snapshots.csv")

HAVE_CACHE = os.path.exists(CACHE)
HAVE_RAW = os.path.exists(RAW)

#: What the dataset itself contains -- asserted, not assumed, in
#: `DatasetShape` below.
N_SESSIONS = 18
N_PERIODS_TOTAL = 216
N_OBSERVATIONS = 5184


def load_periods():
    return st.periods(st.read_snapshot_cache(CACHE))


def run_period(period, *, type_priority=None, profile=None):
    market, tiebreak = st.build_market(period, type_priority=type_priority)
    prof = profile if profile is not None else st.build_profile(period)
    config = st.config_for(period, tiebreak)
    spec = get_mechanism(st.MECHANISM_BY_CODE[period.mechanism])
    return spec.run(market, prof, config)


@unittest.skipUnless(HAVE_CACHE, "Stephenson snapshot cache not present")
class DatasetShape(unittest.TestCase):
    def test_counts_match_the_published_design(self):
        ps = load_periods()
        self.assertEqual(len(ps), N_PERIODS_TOTAL)
        self.assertEqual(sum(len(p.rows) for p in ps), N_OBSERVATIONS)
        self.assertEqual(len({p.session for p in ps}), N_SESSIONS)
        for p in ps:
            self.assertEqual(len(p.rows), st.PARTICIPANTS_PER_PERIOD)

    def test_six_sessions_per_mechanism(self):
        ps = load_periods()
        by = collections.defaultdict(set)
        for p in ps:
            by[p.mechanism].add(p.session)
        self.assertEqual(
            {m: len(s) for m, s in sorted(by.items())},
            {"boston": 6, "defAccept": 6, "topTrading": 6},
        )

    def test_every_option_seats_exactly_its_capacity(self):
        """24 participants, 3 options, capacity 8 -- so the recorded outcome
        must place exactly 8 at each. If this failed, the capacity model
        would be wrong and every replay below would be meaningless."""
        for p in load_periods():
            counts = collections.Counter(st.recorded_assignment(p).values())
            self.assertEqual(
                sorted(counts.values()), [8, 8, 8], msg=f"period {p.key}"
            )


@unittest.skipUnless(HAVE_CACHE, "Stephenson snapshot cache not present")
class ReplayReproducesTheRecordedOutcomes(unittest.TestCase):
    """The headline check: this project's mechanisms, run on the reports real
    participants submitted, produce the assignments the experiment recorded."""

    def test_every_mechanism_reproduces_every_recorded_assignment(self):
        mismatches = []
        checked = collections.Counter()
        for p in load_periods():
            got = run_period(p).student_to_school
            recorded = st.recorded_assignment(p)
            for s, want in recorded.items():
                checked[p.mechanism] += 1
                if got[s] != want:
                    mismatches.append((p.key, p.mechanism, s, got[s], want))
        self.assertEqual(
            dict(checked),
            {"defAccept": 1728, "boston": 1728, "topTrading": 1728},
        )
        self.assertEqual(
            mismatches, [], msg=f"{len(mismatches)} recorded assignments not reproduced"
        )


@unittest.skipUnless(HAVE_CACHE, "Stephenson snapshot cache not present")
class TheReplayIsNotVacuous(unittest.TestCase):
    """A perfect reproduction proves nothing if the three mechanisms would
    have agreed anyway, or if every participant simply got their first choice.
    Both are measured here, and both must fail to be true."""

    def test_the_three_mechanisms_disagree_substantially_on_these_markets(self):
        disagree = collections.Counter()
        total = 0
        for p in load_periods():
            market, tiebreak = st.build_market(p)
            profile = st.build_profile(p)
            outs = {}
            for code, name in st.MECHANISM_BY_CODE.items():
                cfg = st.config_for(
                    st.Period(p.session, p.period, code, p.feedback, p.rows), tiebreak
                )
                outs[code] = get_mechanism(name).run(
                    market, profile, cfg
                ).student_to_school
            for s in market.students:
                total += 1
                for x, y in itertools.combinations(sorted(outs), 2):
                    if outs[x][s] != outs[y][s]:
                        disagree[(x, y)] += 1
        self.assertEqual(total, N_OBSERVATIONS)
        for pair, n in disagree.items():
            self.assertGreater(
                n / total, 0.20, f"{pair} disagreed on only {n}/{total}"
            )

    def test_scarcity_actually_binds(self):
        not_first = 0
        total = 0
        for p in load_periods():
            profile = st.build_profile(p)
            for s, got in st.recorded_assignment(p).items():
                total += 1
                if position(profile.report(s), got) != 0:
                    not_first += 1
        self.assertEqual(total, N_OBSERVATIONS)
        self.assertGreater(
            not_first / total,
            0.25,
            "almost everyone got their first choice, so the mechanisms were "
            "barely doing anything and reproducing them proves little",
        )


@unittest.skipUnless(HAVE_CACHE, "Stephenson snapshot cache not present")
class TheRecoveredStructureIsActuallyIdentified(unittest.TestCase):
    """The priority structure was recovered by search, so the suite has to
    show the search had a unique-ish answer -- otherwise "it reproduces the
    data" would just mean the data cannot tell structures apart."""

    def test_a_wrong_type_order_fails_loudly(self):
        """Perturbing option a's type order must BREAK the reproduction. If
        it did not, the exact match above would be insensitive to the very
        parameter it was used to determine."""
        wrong = dict(st.TYPE_PRIORITY)
        wrong["a"] = ("2", "1", "3")
        mismatches = 0
        for p in load_periods():
            got = run_period(p, type_priority=wrong).student_to_school
            for s, want in st.recorded_assignment(p).items():
                if got[s] != want:
                    mismatches += 1
        self.assertGreater(
            mismatches,
            0,
            "a deliberately wrong priority structure still reproduced every "
            "recorded assignment, so the replay does not identify it at all",
        )

    def test_the_documented_ambiguity_in_option_c_really_is_an_ambiguity(self):
        """`witness.stephenson` states that option c's ordering of types 1 and
        3 beneath type 2 is NOT determined by this data. That claim is pinned
        here, so nobody later resolves it by preference and believes it was
        measured."""
        alt = dict(st.TYPE_PRIORITY)
        alt["c"] = st.EQUIVALENT_C_ORDER
        for p in load_periods():
            got = run_period(p, type_priority=alt).student_to_school
            self.assertEqual(got, st.recorded_assignment(p), msg=f"period {p.key}")


@unittest.skipUnless(
    HAVE_CACHE and HAVE_RAW, "Stephenson raw CSV or cache not present"
)
class TheCacheIsFaithfulToTheRawFile(unittest.TestCase):
    """The compact cache is derived, so it is only trustworthy while it still
    matches what the 90MB raw event log actually says. Re-derives it."""

    def test_cache_equals_a_fresh_derivation_from_the_raw_log(self):
        fresh = st.final_snapshots(RAW)
        cached = st.read_snapshot_cache(CACHE)
        self.assertEqual(len(fresh), len(cached))
        self.assertEqual(
            [{k: r[k] for k in st.SNAPSHOT_FIELDS} for r in fresh],
            [{k: r[k] for k in st.SNAPSHOT_FIELDS} for r in cached],
        )


@unittest.skipUnless(HAVE_CACHE, "Stephenson snapshot cache not present")
class RealDataReplaysInAFreshProcess(unittest.TestCase):
    def test_one_real_period_reproduces_in_a_subprocess(self):
        period = next(p for p in load_periods() if p.mechanism == "topTrading")
        market, tiebreak = st.build_market(period)
        profile = st.build_profile(period)
        config = st.config_for(period, tiebreak)
        payload = json.dumps(
            {
                "market": market.to_dict(),
                "profile": profile.to_dict(),
                "config": config.to_dict(),
                "recorded": st.recorded_assignment(period),
            }
        )
        script = (
            "import json,sys;"
            "from witness.core import Market, Profile;"
            "from witness.mechanisms import get_mechanism;"
            "d=json.loads(sys.stdin.read());"
            "spec=get_mechanism('top_trading_cycles');"
            "got=spec.run(Market.from_dict(d['market']),Profile.from_dict(d['profile']),"
            "spec.config_from_dict(d['config'])).student_to_school;"
            "print(json.dumps(got==d['recorded']))"
        )
        proc = subprocess.run(
            [sys.executable, "-c", script], input=payload,
            capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertTrue(
            json.loads(proc.stdout),
            "a real recorded period did not reproduce in a fresh interpreter",
        )


if __name__ == "__main__":
    unittest.main()
