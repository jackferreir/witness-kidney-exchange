"""Tests for `witness.depth`: hand-checkable misreport-depth measurements, plus
one integration test that a real search-produced witness carries a correct
"depth" dict and still passes replay.
"""

from __future__ import annotations

import itertools
import unittest

from witness.boston import BostonConfig
from witness.core import Market, Profile
from witness.depth import (
    SPACE_LOCAL_SWAPS,
    SPACE_PREFIX_TRUNCATIONS,
    SPACE_SINGLETONS,
    SPACE_SUBLISTS,
    SPACE_SUBLISTS_PLUS_SWAPS,
    ReportDepth,
    in_restricted_space,
    report_depth,
)
from witness.errors import ModelError
from witness.replay import verify_in_subprocess, verify_witness
from witness.search import find_manipulation
from witness.tiebreak import RejectTies


class TruncationTestCase(unittest.TestCase):
    """truthful ("c1","c2","c3"), false ("c1","c2"): false is exactly the
    first two elements of truthful, so it is a prefix truncation (and, since
    every prefix is a sublist, also a sublist). Nothing about the order of
    the two remaining schools changed, so kendall_tau is 0 and the first
    choice is unchanged. A pure prefix truncation is always in both
    SPACE_PREFIX_TRUNCATIONS and SPACE_SUBLISTS."""

    def test_values(self):
        d = report_depth(("c1", "c2", "c3"), ("c1", "c2"))
        self.assertTrue(d.is_prefix_truncation)
        self.assertTrue(d.is_sublist)  # a prefix IS a sublist
        self.assertEqual(d.n_dropped, 1)
        self.assertEqual(d.n_added, 0)
        self.assertEqual(d.kendall_tau, 0)
        self.assertFalse(d.first_choice_changed)
        self.assertFalse(d.is_permutation)
        self.assertIsNone(d.adjacent_swap_distance)  # lengths differ (3 vs 2)
        self.assertTrue(in_restricted_space(d, SPACE_PREFIX_TRUNCATIONS))
        self.assertTrue(in_restricted_space(d, SPACE_SUBLISTS))

    def test_prefix_truncations_is_a_strict_subset_of_sublists(self):
        """A case that is in SPACE_SUBLISTS but NOT in SPACE_PREFIX_TRUNCATIONS:
        truthful ("c1","c2","c3","c4"), false ("c1","c3") drops the middle
        school c2, so it is not a prefix (the third truthful element is c3,
        not the false report's second element's truthful neighbor c2) -- but
        it IS an order-preserving sublist (c1 then c3, matching their
        relative order in truthful)."""
        d = report_depth(("c1", "c2", "c3", "c4"), ("c1", "c3"))
        self.assertTrue(d.is_sublist)
        self.assertFalse(d.is_prefix_truncation)
        self.assertTrue(in_restricted_space(d, SPACE_SUBLISTS))
        self.assertFalse(in_restricted_space(d, SPACE_PREFIX_TRUNCATIONS))


class AdjacentSwapTestCase(unittest.TestCase):
    """truthful ("c1","c2","c3"), false ("c2","c1","c3"): the first two
    entries are swapped, the third is untouched. Same set of schools (a
    permutation), one adjacent transposition (kendall_tau 1), reachable by
    exactly one disjoint adjacent swap, and the first choice changed (c1 ->
    c2). A single adjacent swap is within max_kendall_tau=1, so it is in
    SPACE_LOCAL_SWAPS at that setting."""

    def test_values(self):
        d = report_depth(("c1", "c2", "c3"), ("c2", "c1", "c3"))
        self.assertTrue(d.is_permutation)
        self.assertEqual(d.kendall_tau, 1)
        self.assertEqual(d.adjacent_swap_distance, 1)
        self.assertTrue(d.first_choice_changed)
        self.assertFalse(d.is_prefix_truncation)
        self.assertFalse(d.is_sublist)  # order of c1/c2 is not preserved
        self.assertEqual(d.n_dropped, 0)
        self.assertEqual(d.n_added, 0)
        self.assertTrue(in_restricted_space(d, SPACE_LOCAL_SWAPS, max_kendall_tau=1))


class FullReversalTestCase(unittest.TestCase):
    """truthful ("c1","c2","c3"), false ("c3","c2","c1"): a full reversal of
    3 elements. The number of inversions in a full reversal of n elements is
    n*(n-1)/2 = 3 for n=3, so kendall_tau is 3. That is well above
    max_kendall_tau=1, so this is NOT reachable via SPACE_LOCAL_SWAPS at that
    setting (and it is not a prefix truncation or a sublist either, since
    false is not order-preserving), so it is outside every space."""

    def test_values(self):
        d = report_depth(("c1", "c2", "c3"), ("c3", "c2", "c1"))
        self.assertEqual(d.kendall_tau, 3)
        self.assertFalse(d.is_sublist)
        self.assertFalse(in_restricted_space(d, SPACE_LOCAL_SWAPS, max_kendall_tau=1))
        self.assertFalse(in_restricted_space(d, SPACE_SUBLISTS_PLUS_SWAPS, max_kendall_tau=1))


class NonPrefixDropTestCase(unittest.TestCase):
    """truthful ("c1","c2","c3","c4"), false ("c2",): this is the exact shape
    the 719-Boston-case measurement found responsible for the defect this
    module used to have -- REGRESSION LOCK. false is not a prefix of
    truthful (truthful's first element is c1, not c2), so `is_prefix_truncation`
    is False even though false IS a legitimate order-preserving sublist
    (`is_sublist` True): c2 alone, taken out of the middle of truthful and
    promoted to the only entry. Before the fix, `in_restricted_space` had no
    way to express "drop everything but c2" as anything but a truncation, so
    it scored this kind of misreport as unreachable; that was the wrong
    concept, not a fact about the data."""

    def test_values(self):
        d = report_depth(("c1", "c2", "c3", "c4"), ("c2",))
        self.assertTrue(d.is_sublist)
        self.assertFalse(d.is_prefix_truncation)
        self.assertTrue(d.is_singleton)
        self.assertEqual(d.promotes_school, "c2")
        self.assertEqual(d.n_added, 0)
        self.assertEqual(d.kendall_tau, 0)
        self.assertEqual(d.n_dropped, 3)
        self.assertTrue(d.first_choice_changed)

        self.assertTrue(in_restricted_space(d, SPACE_SUBLISTS))
        self.assertTrue(in_restricted_space(d, SPACE_SINGLETONS))
        self.assertFalse(in_restricted_space(d, SPACE_PREFIX_TRUNCATIONS))


class FullReversalOfFourNotSublistTestCase(unittest.TestCase):
    """truthful ("c1","c2","c3"), false ("c3","c1"): dropping c2 and
    reversing the relative order of c1 and c3 is NOT order-preserving, so
    this is not a sublist even though no school outside {c1,c3} appears."""

    def test_values(self):
        d = report_depth(("c1", "c2", "c3"), ("c3", "c1"))
        self.assertFalse(d.is_sublist)
        self.assertEqual(d.kendall_tau, 1)


class AdditionTestCase(unittest.TestCase):
    """truthful ("c1","c2"), false ("c1","c2","c3") where c3 is truthfully
    unacceptable (absent from the truthful report): this ADDS a
    truthfully-unacceptable school at the end. No school is dropped and the
    order of the common schools (c1, c2) is unchanged (kendall_tau 0), so
    whether this lands in SPACE_LOCAL_SWAPS depends entirely on
    allow_additions."""

    def test_values(self):
        d = report_depth(("c1", "c2"), ("c1", "c2", "c3"))
        self.assertEqual(d.n_added, 1)
        self.assertEqual(d.n_dropped, 0)
        self.assertEqual(d.kendall_tau, 0)
        self.assertFalse(d.is_prefix_truncation)  # false is longer than truthful
        self.assertFalse(d.is_sublist)  # c3 is not in truthful at all
        self.assertFalse(
            in_restricted_space(d, SPACE_LOCAL_SWAPS, allow_additions=False)
        )
        self.assertTrue(
            in_restricted_space(d, SPACE_LOCAL_SWAPS, allow_additions=True)
        )


class SecondAdditionTestCase(unittest.TestCase):
    """truthful ("c1","c2"), false ("c2","c9") where c9 is truthfully
    unacceptable: adds one school (c9), and is not order-preserving as a
    sublist either (c9 was never in truthful, so it can never form a valid
    subsequence match). This must be OUTSIDE EVERY space when
    allow_additions=False, regardless of the space asked about."""

    def test_values(self):
        d = report_depth(("c1", "c2"), ("c2", "c9"))
        self.assertEqual(d.n_added, 1)
        self.assertFalse(d.is_sublist)

        for space in (
            SPACE_PREFIX_TRUNCATIONS,
            SPACE_SUBLISTS,
            SPACE_SINGLETONS,
            SPACE_LOCAL_SWAPS,
            SPACE_SUBLISTS_PLUS_SWAPS,
        ):
            self.assertFalse(
                in_restricted_space(d, space, allow_additions=False),
                msg=f"space {space!r} incorrectly admitted a misreport with n_added>0",
            )


class SingletonAdditionTestCase(unittest.TestCase):
    """A singleton false report naming a truthfully-unacceptable school is
    `is_singleton` True but still has n_added > 0, so the global
    allow_additions gate must still exclude it from SPACE_SINGLETONS."""

    def test_values(self):
        d = report_depth(("c1", "c2"), ("c9",))
        self.assertTrue(d.is_singleton)
        self.assertEqual(d.n_added, 1)
        self.assertIsNone(d.promotes_school)  # c9 is not in truthful at all
        self.assertFalse(in_restricted_space(d, SPACE_SINGLETONS, allow_additions=False))
        self.assertTrue(in_restricted_space(d, SPACE_SINGLETONS, allow_additions=True))


class PromotesSchoolTestCase(unittest.TestCase):
    def test_promotes_a_lower_ranked_school(self):
        d = report_depth(("c1", "c2", "c3"), ("c3", "c1", "c2"))
        self.assertEqual(d.promotes_school, "c3")

    def test_first_choice_unchanged_promotes_nothing(self):
        d = report_depth(("c1", "c2", "c3"), ("c1", "c3"))
        self.assertIsNone(d.promotes_school)

    def test_empty_false_promotes_nothing(self):
        d = report_depth(("c1", "c2"), ())
        self.assertIsNone(d.promotes_school)


class EmptyAndDisjointTestCase(unittest.TestCase):
    """Documented conventions at the boundary: both empty, one empty, and two
    reports that share no school at all."""

    def test_both_empty(self):
        d = report_depth((), ())
        self.assertEqual(d.length_truthful, 0)
        self.assertEqual(d.length_false, 0)
        # () is a prefix of (): trivially a truncation, and trivially a sublist.
        self.assertTrue(d.is_prefix_truncation)
        self.assertTrue(d.is_sublist)
        self.assertFalse(d.is_singleton)
        self.assertIsNone(d.promotes_school)
        # same (empty) set of schools: trivially a permutation.
        self.assertTrue(d.is_permutation)
        self.assertEqual(d.n_dropped, 0)
        self.assertEqual(d.n_added, 0)
        # neither report names a first choice, so nothing "changed".
        self.assertFalse(d.first_choice_changed)
        self.assertEqual(d.kendall_tau, 0)
        # zero-length reports: zero disjoint adjacent swaps needed.
        self.assertEqual(d.adjacent_swap_distance, 0)
        self.assertTrue(in_restricted_space(d, SPACE_PREFIX_TRUNCATIONS))
        self.assertTrue(in_restricted_space(d, SPACE_SUBLISTS))

    def test_empty_truthful_nonempty_false(self):
        d = report_depth((), ("c1",))
        # a non-empty list can never be a prefix of an empty one.
        self.assertFalse(d.is_prefix_truncation)
        self.assertFalse(d.is_sublist)  # c1 is not in the (empty) truthful report
        self.assertTrue(d.is_singleton)
        self.assertIsNone(d.promotes_school)  # c1 is not in truthful at all
        self.assertEqual(d.n_added, 1)
        self.assertEqual(d.n_dropped, 0)
        # false now has a first choice where truthful had none: changed.
        self.assertTrue(d.first_choice_changed)
        self.assertEqual(d.kendall_tau, 0)
        self.assertIsNone(d.adjacent_swap_distance)  # lengths differ (0 vs 1)

    def test_nonempty_truthful_empty_false(self):
        d = report_depth(("c1", "c2"), ())
        # the empty list is a prefix of every list: submitting nothing is the
        # most extreme truncation, and trivially a sublist too.
        self.assertTrue(d.is_prefix_truncation)
        self.assertTrue(d.is_sublist)
        self.assertFalse(d.is_singleton)
        self.assertIsNone(d.promotes_school)
        self.assertEqual(d.n_dropped, 2)
        self.assertEqual(d.n_added, 0)
        self.assertTrue(d.first_choice_changed)
        self.assertEqual(d.kendall_tau, 0)
        self.assertIsNone(d.adjacent_swap_distance)  # lengths differ (2 vs 0)
        self.assertTrue(in_restricted_space(d, SPACE_PREFIX_TRUNCATIONS))

    def test_disjoint_reports(self):
        d = report_depth(("c1", "c2"), ("c3", "c4"))
        self.assertFalse(d.is_prefix_truncation)
        self.assertFalse(d.is_sublist)
        self.assertFalse(d.is_permutation)
        self.assertEqual(d.n_dropped, 2)
        self.assertEqual(d.n_added, 2)
        self.assertTrue(d.first_choice_changed)
        # no common schools at all -> no relative order to disagree on -> 0,
        # NOT a claim that the two reports resemble each other.
        self.assertEqual(d.kendall_tau, 0)
        self.assertIsNone(d.adjacent_swap_distance)


class KendallTauSanityTestCase(unittest.TestCase):
    """Reversing a 4-element list is the maximum possible number of
    inversions for n=4: n*(n-1)/2 = 6."""

    def test_full_reversal_of_four_is_six_inversions(self):
        d = report_depth(("c1", "c2", "c3", "c4"), ("c4", "c3", "c2", "c1"))
        self.assertEqual(d.kendall_tau, 6)
        self.assertFalse(d.is_sublist)


class UnknownSpaceTestCase(unittest.TestCase):
    def test_raises_model_error_on_unknown_space_name(self):
        d = report_depth(("c1", "c2"), ("c1",))
        with self.assertRaises(ModelError):
            in_restricted_space(d, "not_a_real_space")


class RoundTripTestCase(unittest.TestCase):
    def test_to_dict_from_dict_round_trip(self):
        d = report_depth(("c1", "c2", "c3"), ("c2", "c1", "c3"))
        d2 = ReportDepth.from_dict(d.to_dict())
        self.assertEqual(d, d2)
        self.assertEqual(d.to_dict(), d2.to_dict())

    def test_round_trip_preserves_new_fields(self):
        d = report_depth(("c1", "c2", "c3", "c4"), ("c2",))
        d2 = ReportDepth.from_dict(d.to_dict())
        self.assertEqual(d.is_sublist, d2.is_sublist)
        self.assertEqual(d.is_singleton, d2.is_singleton)
        self.assertEqual(d.promotes_school, d2.promotes_school)
        self.assertIn("is_sublist", d.to_dict())
        self.assertIn("is_singleton", d.to_dict())
        self.assertIn("promotes_school", d.to_dict())
        self.assertNotIn("is_truncation", d.to_dict())  # renamed, no alias kept


class IsSublistCrossCheckTestCase(unittest.TestCase):
    """`is_sublist` is computed DIRECTLY from the two report sequences (see
    `witness.depth._is_sublist`), independently of `n_added`/`kendall_tau`.
    It is claimed to be equivalent to `n_added == 0 and kendall_tau == 0`
    for every possible pair of reports. This test builds a few hundred
    (truthful, false) pairs from permutations/subsets of 4 schools and checks
    that the independent computation and the derived condition always agree.
    If they ever disagree, that is a real finding, not a test to relax.
    """

    def test_is_sublist_matches_derived_condition_over_many_pairs(self):
        schools = ("c1", "c2", "c3", "c4")

        def all_ordered_subsets(items):
            out = []
            for r in range(len(items) + 1):
                out.extend(itertools.permutations(items, r))
            return out

        reports = all_ordered_subsets(schools)
        self.assertEqual(len(reports), 65)

        checked = 0
        disagreements = []
        for truthful in reports:
            for false in reports:
                d = report_depth(truthful, false)
                derived = d.n_added == 0 and d.kendall_tau == 0
                checked += 1
                if d.is_sublist != derived:
                    disagreements.append((truthful, false, d.is_sublist, derived))

        self.assertGreaterEqual(checked, 200)
        self.assertEqual(
            disagreements,
            [],
            msg=(
                "is_sublist disagrees with (n_added == 0 and kendall_tau == 0) "
                f"for {len(disagreements)} of {checked} pairs: "
                f"{disagreements[:10]!r}"
            ),
        )


class SearchIntegrationTestCase(unittest.TestCase):
    """The hand-verified BOS-B instance from `tests/test_boston_positive_control.py`:
    students s1,s2,s3; schools c1,c2; caps 1,1; priorities c1: s3>s1>s2, c2:
    s1>s2>s3; profile s1:(c1,c2) s2:(c2,c1) s3:(c1,c2);
    boston_immediate_acceptance; target s1.

    `find_manipulation` returns the canonically FIRST profitable misreport
    (shortest first), which for this instance is s1 truncating to ("c2",) --
    confirmed independently in `test_boston_positive_control.py`. This test
    checks that the witness's "depth" dict matches whatever misreport is
    actually returned (it does not hardcode which misreport that is, beyond
    what the search already guarantees), and that the new "depth" schema does
    not break replay.
    """

    def _market(self) -> Market:
        return Market(
            students=("s1", "s2", "s3"),
            schools=("c1", "c2"),
            capacities={"c1": 1, "c2": 1},
            priority_classes={
                "c1": (("s3",), ("s1",), ("s2",)),
                "c2": (("s1",), ("s2",), ("s3",)),
            },
        )

    def _profile(self) -> Profile:
        return Profile({"s1": ("c1", "c2"), "s2": ("c2", "c1"), "s3": ("c1", "c2")})

    def _config(self) -> BostonConfig:
        return BostonConfig(tiebreak=RejectTies())

    def test_witness_carries_correct_depth_and_still_replays(self):
        market, profile, config = self._market(), self._profile(), self._config()
        w = find_manipulation(market, profile, "s1", "boston_immediate_acceptance", config)
        self.assertIsNotNone(w)

        d = w.to_dict()
        self.assertIn("depth", d)

        expected = report_depth(w.truthful_report, w.false_report)
        self.assertEqual(d["depth"], expected.to_dict())

        # Report exactly what was found, for the final message.
        print(
            f"BOS-B witness: truthful_report={w.truthful_report!r} "
            f"false_report={w.false_report!r} depth={d['depth']!r}"
        )

        ok, reasons = verify_witness(d)
        self.assertEqual((ok, reasons), (True, ()), msg=f"verify_witness rejected it: {reasons}")

        ok, reasons = verify_in_subprocess(d)
        self.assertEqual(
            (ok, reasons), (True, ()), msg=f"verify_in_subprocess rejected it: {reasons}"
        )


if __name__ == "__main__":
    unittest.main()
