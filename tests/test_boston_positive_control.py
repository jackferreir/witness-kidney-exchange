"""Positive control for the manipulation search against Boston (`witness.search`
finding a real Boston manipulation), plus an unplanted scan and a same-instances
DA negative control.

Three parts:

  A. THE PLANTED POSITIVE CONTROL -- BOS-B rediscovered by the search. BOS-B is
     the hand-worked textbook manipulation in
     `tests/test_boston_handworked.py::test_bos_b_textbook_manipulation`: s1
     misreporting (c2,c1) instead of truthful (c1,c2) turns s1's truthful
     outcome (None) into c2, a strict gain by s1's own truthful ranking. This
     module does not re-derive that by hand again -- it asks `witness.search`
     to FIND it, cross-checks that plain `student_proposing_da` on the
     identical instance finds nothing (DA is strategy-proof, Boston is not),
     and round-trips the found witness through the journal and a fresh-process
     replay.

  B. UNPLANTED: scan `witness.generate`-produced instances (Step 3A's narrow
     generator -- see that module's docstring for the scope limitation) until
     the search finds its first Boston manipulation, bounded comfortably above
     what was actually measured while writing this test (see the comment on
     `MAX_INSTANCES_TO_SCAN` below).

  C. NEGATIVE CONTROL ON THE SAME GENERATED INSTANCES: over the first
     `N_INSTANCES` instances from the identical generator, `student_proposing_da`
     must find ZERO manipulations. Same instances as part B, different
     mechanism -- so any difference is attributable to the mechanism, not to
     the instance distribution. A manipulation found here would be a genuine
     finding about `witness.da` or `witness.search`, not something to adjust
     away.
"""

from __future__ import annotations

import os
import unittest
from tempfile import TemporaryDirectory

from witness.boston import BostonConfig
from witness.core import Market, Profile
from witness.da import DAConfig, deferred_acceptance
from witness.generate import GeneratorConfig, generate_instance, priority_tiebreak
from witness.journal import Journal
from witness.replay import verify_in_subprocess, verify_witness
from witness.search import find_all_manipulations, find_manipulation, search_all_students
from witness.tiebreak import RejectTies


def _bos_b_market() -> Market:
    return Market(
        students=("s1", "s2", "s3"),
        schools=("c1", "c2"),
        capacities={"c1": 1, "c2": 1},
        priority_classes={
            "c1": (("s3",), ("s1",), ("s2",)),
            "c2": (("s1",), ("s2",), ("s3",)),
        },
    )


def _bos_b_profile() -> Profile:
    return Profile({"s1": ("c1", "c2"), "s2": ("c2", "c1"), "s3": ("c1", "c2")})


class PlantedBostonPositiveControlTestCase(unittest.TestCase):
    """The hand-verified BOS-B instance, rediscovered by the search."""

    def _config(self) -> BostonConfig:
        return BostonConfig(tiebreak=RejectTies())

    def test_find_manipulation_finds_a_profitable_s1_misreport(self):
        market, profile, config = _bos_b_market(), _bos_b_profile(), self._config()
        w = find_manipulation(market, profile, "s1", "boston_immediate_acceptance", config)
        self.assertIsNotNone(w)
        self.assertIsNone(w.truthful_outcome)
        self.assertEqual(w.false_outcome, "c2")

    def test_hand_verified_c2_c1_misreport_is_among_all_manipulations(self):
        """`find_manipulation` returns the CANONICALLY FIRST profitable
        misreport in `ordered_subsets`' length-ascending order, which may be a
        shorter truncation than the hand-verified `("c2","c1")` -- so this
        does not assert `find_manipulation`'s result equals `("c2","c1")`.
        It only asserts the hand-verified full permutation is genuinely among
        ALL of s1's profitable misreports, with the stated outcomes."""
        market, profile, config = _bos_b_market(), _bos_b_profile(), self._config()
        all_witnesses = find_all_manipulations(
            market, profile, "s1", "boston_immediate_acceptance", config
        )
        matches = [w for w in all_witnesses if w.false_report == ("c2", "c1")]
        self.assertEqual(len(matches), 1, all_witnesses)
        w = matches[0]
        self.assertIsNone(w.truthful_outcome)
        self.assertEqual(w.false_outcome, "c2")

    def test_shorter_manipulation_reported_if_any(self):
        """Report, informationally, which misreport `find_manipulation`
        actually returns first (it may or may not be `("c2","c1")` itself --
        both are fine; this just documents the observed canonical winner)."""
        market, profile, config = _bos_b_market(), _bos_b_profile(), self._config()
        w = find_manipulation(market, profile, "s1", "boston_immediate_acceptance", config)
        self.assertIsNotNone(w)
        print(
            f"find_manipulation's canonically-first profitable misreport for s1 "
            f"is {w.false_report!r} (hand-verified BOS-B misreport is "
            f"('c2', 'c1'))"
        )

    def test_same_instance_under_plain_da_has_no_manipulation_for_s1(self):
        """DA is strategy-proof, Boston is not -- the whole point of this
        control. Same market and profile, only the mechanism differs. (Under
        DA, s1's truthful outcome need not be None -- and in fact isn't, here;
        the "truthfully s1 -> None" fact is specific to the Boston run. What
        matters is that DA offers s1 no profitable misreport at all.)"""
        market, profile = _bos_b_market(), _bos_b_profile()
        da_config = DAConfig(tiebreak=RejectTies())  # mechanism="student_proposing_da"

        # Sanity: DA runs cleanly on this instance (it disagrees with Boston's
        # truthful outcome for s1, which is exactly the point -- Boston and DA
        # are different mechanisms on the same inputs).
        deferred_acceptance(market, profile, da_config)

        w = find_manipulation(market, profile, "s1", "student_proposing_da", da_config)
        self.assertIsNone(w)

    def test_found_witness_round_trips_through_journal_and_fresh_process_replay(self):
        market, profile, config = _bos_b_market(), _bos_b_profile(), self._config()
        w = find_manipulation(market, profile, "s1", "boston_immediate_acceptance", config)
        self.assertIsNotNone(w)

        with TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "journal.jsonl")
            journal = Journal(path)
            journal.append(w.to_dict())

            records = journal.read_all()
            self.assertEqual(records, (w.to_dict(),))

            ok_same_process, reasons_same_process = verify_witness(records[0])
            self.assertEqual((ok_same_process, reasons_same_process), (True, ()))

            ok, reasons = verify_in_subprocess(records[0])
            self.assertEqual(
                (ok, reasons), (True, ()),
                msg=f"witness failed fresh-process replay: {reasons}",
            )


#: Config for the generator used by parts B and C -- 4 students, 3 schools,
#: uniform capacity 1. Deliberately small so both scans stay fast.
_GC = GeneratorConfig(n_students=4, n_schools=3, capacity=1, seed="positive-control")

#: Measured while writing this test: scanning instances 0.. of `_GC`, the
#: first Boston manipulation under `boston_immediate_acceptance` appears at
#: index 0. The bound below is comfortably above that.
MAX_INSTANCES_TO_SCAN = 50

#: How many of the same generated instances the DA negative control (part C)
#: sweeps. Kept the run under a few seconds; each instance's full
#: `search_all_students` call over 4 students is cheap (well under 100ms).
N_INSTANCES_FOR_DA_CONTROL = 50


class UnplantedBostonScanTestCase(unittest.TestCase):
    """Part B: the search finds a Boston manipulation in a GENERATED (not
    hand-planted) instance, within a small bounded number of instances."""

    def test_search_finds_a_boston_manipulation_within_bound(self):
        found_at = None
        found_witness = None
        for i in range(MAX_INSTANCES_TO_SCAN):
            market, profile = generate_instance(_GC, i)
            config = BostonConfig(tiebreak=priority_tiebreak(_GC, i))
            witnesses = search_all_students(
                market, profile, "boston_immediate_acceptance", config
            )
            if witnesses:
                found_at = i
                found_witness = witnesses[0]
                break

        self.assertIsNotNone(
            found_at,
            f"no Boston manipulation found in the first {MAX_INSTANCES_TO_SCAN} "
            f"generated instances of {_GC!r}",
        )
        self.assertIsNotNone(found_witness)

        ok, reasons = verify_in_subprocess(found_witness.to_dict())
        self.assertEqual(
            (ok, reasons), (True, ()),
            msg=f"generated-instance witness failed fresh-process replay: {reasons}",
        )
        print(
            f"unplanted scan: first Boston manipulation found at generated "
            f"instance index {found_at} (bound was {MAX_INSTANCES_TO_SCAN})"
        )


class SameInstancesDANegativeControlTestCase(unittest.TestCase):
    """Part C: on the SAME generated instances as part B, plain
    `student_proposing_da` must find zero manipulations. Any manipulation
    found here is a genuine finding, not something to paper over."""

    def test_zero_manipulations_under_plain_da_on_generated_instances(self):
        all_found: list[tuple] = []
        for i in range(N_INSTANCES_FOR_DA_CONTROL):
            market, profile = generate_instance(_GC, i)
            config = DAConfig(tiebreak=priority_tiebreak(_GC, i))
            witnesses = search_all_students(market, profile, "student_proposing_da", config)
            if witnesses:
                all_found.append((i, market, profile, witnesses))

        if all_found:
            lines = [
                "NEGATIVE CONTROL FAILURE: plain student_proposing_da is "
                "manipulable on a witness.generate instance:"
            ]
            for i, market, profile, witnesses in all_found:
                lines.append(f"instance index={i}")
                lines.append(f"market={market.to_dict()!r}")
                lines.append(f"profile={profile.to_dict()!r}")
                for w in witnesses:
                    lines.append(
                        f"  target={w.target!r} truthful_report={w.truthful_report!r} "
                        f"false_report={w.false_report!r} "
                        f"truthful_assignment={w.truthful_assignment!r} "
                        f"false_assignment={w.false_assignment!r}"
                    )
            self.fail("\n".join(lines))


if __name__ == "__main__":
    unittest.main()
