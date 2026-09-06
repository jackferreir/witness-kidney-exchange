"""Tests for witness.tiebreak: ExplicitTiebreak, DeclaredStudentOrderTiebreak,
lottery_key purity, and tiebreak_from_dict round-tripping of every rule."""

from __future__ import annotations

import unittest

from witness.errors import ModelError
from witness.tiebreak import (
    DeclaredStudentOrderTiebreak,
    ExplicitTiebreak,
    MultipleLotteryTiebreak,
    RejectTies,
    SingleLotteryTiebreak,
    lottery_key,
    tiebreak_from_dict,
)


class ExplicitTiebreakTests(unittest.TestCase):
    def test_uses_per_school_order_when_present(self):
        rule = ExplicitTiebreak(
            orders={"c1": ("s2", "s1", "s3"), "*": ("s1", "s2", "s3")}
        )
        result = rule.order_within("c1", ("s1", "s2", "s3"), ("s1", "s2", "s3"))
        self.assertEqual(result, ("s2", "s1", "s3"))

    def test_uses_default_scope_when_school_has_no_entry(self):
        rule = ExplicitTiebreak(orders={"*": ("s3", "s1", "s2")})
        result = rule.order_within("c1", ("s1", "s2", "s3"), ("s1", "s2", "s3"))
        self.assertEqual(result, ("s3", "s1", "s2"))

    def test_raises_when_neither_per_school_nor_default_exists(self):
        rule = ExplicitTiebreak(orders={"c2": ("s1", "s2")})
        with self.assertRaises(ModelError):
            rule.order_within("c1", ("s1", "s2"), ("s1", "s2"))

    def test_raises_when_class_member_missing_from_applicable_order(self):
        rule = ExplicitTiebreak(orders={"c1": ("s1", "s2")})
        with self.assertRaises(ModelError):
            rule.order_within("c1", ("s1", "s2", "s3"), ("s1", "s2", "s3"))

    def test_raises_on_duplicate_student_in_declared_order(self):
        with self.assertRaises(ModelError):
            ExplicitTiebreak(orders={"c1": ("s1", "s2", "s1")})


class DeclaredStudentOrderTiebreakTests(unittest.TestCase):
    def test_orders_by_market_students_order(self):
        rule = DeclaredStudentOrderTiebreak()
        canonical_students = ("s3", "s1", "s2")
        result = rule.order_within("c1", ("s1", "s2", "s3"), canonical_students)
        self.assertEqual(result, ("s3", "s1", "s2"))

    def test_orders_subset_preserving_canonical_order(self):
        rule = DeclaredStudentOrderTiebreak()
        canonical_students = ("s1", "s2", "s3", "s4")
        result = rule.order_within("c1", ("s4", "s2"), canonical_students)
        self.assertEqual(result, ("s2", "s4"))

    def test_raises_on_unknown_student(self):
        rule = DeclaredStudentOrderTiebreak()
        canonical_students = ("s1", "s2")
        with self.assertRaises(ModelError):
            rule.order_within("c1", ("s1", "nonexistent"), canonical_students)


class LotteryKeyPurityTests(unittest.TestCase):
    def test_different_seed_gives_different_key(self):
        key1 = lottery_key("seed-a", "scope-x", "s1")
        key2 = lottery_key("seed-b", "scope-x", "s1")
        self.assertNotEqual(key1, key2)

    def test_different_scope_gives_different_key(self):
        key1 = lottery_key("seed-a", "scope-x", "s1")
        key2 = lottery_key("seed-a", "scope-y", "s1")
        self.assertNotEqual(key1, key2)

    def test_different_student_gives_different_key(self):
        key1 = lottery_key("seed-a", "scope-x", "s1")
        key2 = lottery_key("seed-a", "scope-x", "s2")
        self.assertNotEqual(key1, key2)

    def test_same_triple_gives_same_key(self):
        key1 = lottery_key("seed-a", "scope-x", "s1")
        key2 = lottery_key("seed-a", "scope-x", "s1")
        self.assertEqual(key1, key2)

    def test_same_triple_gives_same_key_across_calls_and_instances(self):
        """Purity: repeated calls with an identical triple, called many
        times, always agree -- lottery_key has no hidden state."""
        keys = {lottery_key("witness-test-seed", "*GLOBAL*", "s1") for _ in range(5)}
        self.assertEqual(len(keys), 1)


class TiebreakFromDictRoundTripTests(unittest.TestCase):
    def test_reject_ties_round_trips(self):
        original = RejectTies().to_dict()
        rebuilt = tiebreak_from_dict(original).to_dict()
        self.assertEqual(original, rebuilt)

    def test_declared_student_order_round_trips(self):
        original = DeclaredStudentOrderTiebreak().to_dict()
        rebuilt = tiebreak_from_dict(original).to_dict()
        self.assertEqual(original, rebuilt)

    def test_explicit_round_trips(self):
        original = ExplicitTiebreak(
            orders={"c1": ("s2", "s1"), "*": ("s1", "s2")}
        ).to_dict()
        rebuilt = tiebreak_from_dict(original).to_dict()
        self.assertEqual(original, rebuilt)

    def test_single_lottery_round_trips(self):
        original = SingleLotteryTiebreak(seed="witness-test-seed").to_dict()
        rebuilt = tiebreak_from_dict(original).to_dict()
        self.assertEqual(original, rebuilt)

    def test_multiple_lottery_round_trips(self):
        original = MultipleLotteryTiebreak(seed="witness-test-seed").to_dict()
        rebuilt = tiebreak_from_dict(original).to_dict()
        self.assertEqual(original, rebuilt)

    def test_unknown_rule_name_raises(self):
        with self.assertRaises(ModelError):
            tiebreak_from_dict({"rule": "not_a_real_rule"})

    def test_missing_rule_key_raises(self):
        with self.assertRaises(ModelError):
            tiebreak_from_dict({})


if __name__ == "__main__":
    unittest.main()
