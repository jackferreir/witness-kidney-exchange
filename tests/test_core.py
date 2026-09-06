"""Tests for witness.core: Market/Profile validation, position/strictly_prefers,
MechanismConfig validation, and canonical_json key/list ordering behavior."""

from __future__ import annotations

import unittest

from witness.core import (
    Market,
    MechanismConfig,
    Profile,
    UNLISTED_UNACCEPTABLE,
    canonical_json,
    position,
    strictly_prefers,
)
from witness.errors import ModelError
from witness.tiebreak import RejectTies


def _simple_market(**overrides) -> Market:
    kwargs = dict(
        students=("s1", "s2"),
        schools=("c1", "c2"),
        capacities={"c1": 1, "c2": 1},
        priority_classes={"c1": (("s1",), ("s2",)), "c2": (("s2",), ("s1",))},
    )
    kwargs.update(overrides)
    return Market(**kwargs)


class MarketValidationTests(unittest.TestCase):
    def test_rejects_duplicate_student_ids(self):
        with self.assertRaises(ModelError):
            _simple_market(students=("s1", "s1"))

    def test_rejects_duplicate_school_ids(self):
        with self.assertRaises(ModelError):
            _simple_market(
                schools=("c1", "c1"),
                capacities={"c1": 1},
                priority_classes={"c1": (("s1",), ("s2",))},
            )

    def test_rejects_empty_students(self):
        with self.assertRaises(ModelError):
            _simple_market(students=())

    def test_rejects_empty_schools(self):
        with self.assertRaises(ModelError):
            _simple_market(schools=(), capacities={}, priority_classes={})

    def test_rejects_capacities_key_set_mismatch_missing(self):
        with self.assertRaises(ModelError):
            _simple_market(capacities={"c1": 1})

    def test_rejects_capacities_key_set_mismatch_extra(self):
        with self.assertRaises(ModelError):
            _simple_market(capacities={"c1": 1, "c2": 1, "c3": 1})

    def test_rejects_negative_capacity(self):
        with self.assertRaises(ModelError):
            _simple_market(capacities={"c1": -1, "c2": 1})

    def test_rejects_bool_capacity(self):
        """A bool is an int subclass in Python; capacity=True must still be
        rejected rather than silently accepted as capacity=1."""
        with self.assertRaises(ModelError):
            _simple_market(capacities={"c1": True, "c2": 1})

    def test_rejects_priority_classes_key_set_mismatch(self):
        with self.assertRaises(ModelError):
            _simple_market(priority_classes={"c1": (("s1",), ("s2",))})

    def test_rejects_priority_class_naming_unknown_student(self):
        with self.assertRaises(ModelError):
            _simple_market(
                priority_classes={
                    "c1": (("s1",), ("s2",)),
                    "c2": (("s2",), ("nonexistent",)),
                }
            )

    def test_rejects_student_in_two_priority_classes_of_same_school(self):
        with self.assertRaises(ModelError):
            _simple_market(
                priority_classes={
                    "c1": (("s1",), ("s1",)),
                    "c2": (("s2",), ("s1",)),
                }
            )


class ProfileValidateAgainstTests(unittest.TestCase):
    def setUp(self):
        self.market = _simple_market()

    def test_rejects_missing_report(self):
        profile = Profile({"s1": ("c1",)})
        with self.assertRaises(ModelError):
            profile.validate_against(self.market)

    def test_rejects_report_for_unknown_student(self):
        profile = Profile({"s1": ("c1",), "s2": ("c1",), "s3": ("c1",)})
        with self.assertRaises(ModelError):
            profile.validate_against(self.market)

    def test_rejects_report_listing_unknown_school(self):
        profile = Profile({"s1": ("c1", "nonexistent"), "s2": ("c1",)})
        with self.assertRaises(ModelError):
            profile.validate_against(self.market)

    def test_accepts_valid_profile(self):
        profile = Profile({"s1": ("c1", "c2"), "s2": ("c2",)})
        # Should not raise.
        profile.validate_against(self.market)


class ProfileWithReportTests(unittest.TestCase):
    def test_with_report_returns_new_profile_and_leaves_original_unmutated(self):
        original = Profile({"s1": ("c1", "c2"), "s2": ("c2",)})
        updated = original.with_report("s1", ("c2", "c1"))

        self.assertIsNot(updated, original)
        self.assertEqual(updated.rankings["s1"], ("c2", "c1"))
        # Original must be unchanged.
        self.assertEqual(original.rankings["s1"], ("c1", "c2"))
        self.assertEqual(original.rankings["s2"], ("c2",))

    def test_with_report_can_add_a_new_student(self):
        original = Profile({"s1": ("c1",)})
        updated = original.with_report("s2", ("c2",))

        self.assertNotIn("s2", original.rankings)
        self.assertEqual(updated.rankings["s2"], ("c2",))
        self.assertEqual(updated.rankings["s1"], ("c1",))


class PositionAndStrictlyPrefersTests(unittest.TestCase):
    def setUp(self):
        self.ranking = ("c1", "c2", "c3")

    def test_position_of_ranked_school(self):
        self.assertEqual(position(self.ranking, "c1"), 0.0)
        self.assertEqual(position(self.ranking, "c2"), 1.0)
        self.assertEqual(position(self.ranking, "c3"), 2.0)

    def test_position_of_unmatched_is_worst(self):
        self.assertEqual(position(self.ranking, None), float("inf"))

    def test_position_of_unranked_school_is_worst(self):
        self.assertEqual(position(self.ranking, "unranked"), float("inf"))

    def test_unmatched_and_unranked_are_both_worst_neither_strictly_preferred(self):
        """Both None and an unranked school map to WORST, so a student is
        indifferent between them -- neither is strictly preferred over the
        other, in EITHER direction."""
        self.assertFalse(strictly_prefers(self.ranking, None, "unranked"))
        self.assertFalse(strictly_prefers(self.ranking, "unranked", None))

    def test_ranked_school_strictly_preferred_to_unmatched(self):
        self.assertTrue(strictly_prefers(self.ranking, "c1", None))
        self.assertFalse(strictly_prefers(self.ranking, None, "c1"))

    def test_ranked_school_strictly_preferred_to_unranked(self):
        self.assertTrue(strictly_prefers(self.ranking, "c1", "unranked"))
        self.assertFalse(strictly_prefers(self.ranking, "unranked", "c1"))

    def test_better_ranked_school_strictly_preferred_to_worse(self):
        self.assertTrue(strictly_prefers(self.ranking, "c1", "c2"))
        self.assertFalse(strictly_prefers(self.ranking, "c2", "c1"))


class MechanismConfigValidationTests(unittest.TestCase):
    def test_rejects_unknown_unlisted_student_policy(self):
        with self.assertRaises(ModelError):
            MechanismConfig(tiebreak=RejectTies(), unlisted_student_policy="bogus_policy")

    def test_rejects_tiebreak_with_no_order_within(self):
        class NotATiebreak:
            pass

        with self.assertRaises(ModelError):
            MechanismConfig(tiebreak=NotATiebreak())

    def test_accepts_valid_config(self):
        # Should not raise.
        MechanismConfig(tiebreak=RejectTies(), unlisted_student_policy=UNLISTED_UNACCEPTABLE)


class CanonicalJsonTests(unittest.TestCase):
    def test_mapping_key_insertion_order_does_not_change_output(self):
        dict_a = {}
        dict_a["z"] = 1
        dict_a["a"] = 2
        dict_a["m"] = 3

        dict_b = {}
        dict_b["a"] = 2
        dict_b["m"] = 3
        dict_b["z"] = 1

        self.assertEqual(canonical_json(dict_a), canonical_json(dict_b))

    def test_nested_mapping_key_insertion_order_does_not_change_output(self):
        nested_a = {"outer": {}}
        nested_a["outer"]["z"] = 1
        nested_a["outer"]["a"] = 2

        nested_b = {"outer": {}}
        nested_b["outer"]["a"] = 2
        nested_b["outer"]["z"] = 1

        self.assertEqual(canonical_json(nested_a), canonical_json(nested_b))

    def test_list_order_does_change_output(self):
        list_a = {"items": ["c1", "c2", "c3"]}
        list_b = {"items": ["c3", "c2", "c1"]}

        self.assertNotEqual(canonical_json(list_a), canonical_json(list_b))

    def test_canonical_json_has_no_incidental_whitespace(self):
        self.assertEqual(canonical_json({"a": 1, "b": [1, 2]}), '{"a":1,"b":[1,2]}')


if __name__ == "__main__":
    unittest.main()
