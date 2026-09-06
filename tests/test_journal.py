"""Tests for witness.journal: the append-only JSONL candidate-witness log.

Every test here is aimed at the module's one job -- APPEND ONLY -- and at the
crash-safety and round-tripping properties that make an appended line real
evidence rather than something that might silently vanish or get rewritten.
"""

from __future__ import annotations

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from witness.core import canonical_json, content_hash
from witness.errors import ModelError
from witness.journal import Journal


class TestJournalRoundTrip(unittest.TestCase):
    def test_append_then_read_all_round_trips_in_order(self):
        with TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "journal.jsonl")
            journal = Journal(path)
            records = [
                {"kind": "a", "value": 1},
                {"kind": "b", "value": 2},
                {"kind": "c", "value": 3},
            ]
            for r in records:
                journal.append(r)

            got = journal.read_all()
            self.assertEqual(got, tuple(records))

    def test_len_matches_number_of_appended_records(self):
        with TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "journal.jsonl")
            journal = Journal(path)
            self.assertEqual(len(journal), 0)
            journal.append({"n": 1})
            journal.append({"n": 2})
            self.assertEqual(len(journal), 2)

    def test_append_returns_content_hash_of_record(self):
        with TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "journal.jsonl")
            journal = Journal(path)
            record = {"witness": "candidate", "n": 42}
            returned_hash = journal.append(record)
            self.assertEqual(returned_hash, content_hash(record))

    def test_path_property(self):
        with TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "journal.jsonl")
            journal = Journal(path)
            self.assertEqual(journal.path, path)

    def test_creates_file_and_parent_directories_if_absent(self):
        with TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "nested", "dirs", "journal.jsonl")
            self.assertFalse(os.path.exists(path))
            Journal(path)
            self.assertTrue(os.path.exists(path))


class TestJournalAppendOnly(unittest.TestCase):
    def test_reopening_existing_journal_preserves_earlier_lines(self):
        """A second Journal instance opened on the same path must see every
        record the first instance wrote, in order, and appending through the
        second instance must not disturb what the first wrote."""
        with TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "journal.jsonl")
            first = Journal(path)
            first.append({"who": "first", "n": 1})
            first.append({"who": "first", "n": 2})

            second = Journal(path)
            self.assertEqual(
                second.read_all(),
                ({"who": "first", "n": 1}, {"who": "first", "n": 2}),
            )
            second.append({"who": "second", "n": 3})

            expected = (
                {"who": "first", "n": 1},
                {"who": "first", "n": 2},
                {"who": "second", "n": 3},
            )
            self.assertEqual(first.read_all(), expected)
            self.assertEqual(second.read_all(), expected)

    def test_file_length_strictly_increases_with_each_append_never_truncated(self):
        with TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "journal.jsonl")
            journal = Journal(path)
            sizes = []
            for i in range(5):
                journal.append({"i": i, "payload": "x" * i})
                sizes.append(os.path.getsize(path))

            for earlier, later in zip(sizes, sizes[1:]):
                self.assertLess(earlier, later)

    def test_record_with_newlines_and_non_ascii_round_trips_on_one_line(self):
        with TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "journal.jsonl")
            journal = Journal(path)
            record = {
                "note": "line one\nline two\nline three",
                "school": "Université café — 学校",
                "quote": 'contains "quotes" and \t tabs',
            }
            journal.append(record)

            with open(path, mode="r", encoding="utf-8") as f:
                lines = f.readlines()
            # Exactly one physical line was written for this one record.
            self.assertEqual(len(lines), 1)

            got = journal.read_all()
            self.assertEqual(got, (record,))

    def test_canonical_json_never_emits_a_raw_newline(self):
        record = {"note": "line one\nline two", "other": "tab\there"}
        line = canonical_json(record)
        self.assertNotIn("\n", line)
        self.assertNotIn("\r", line)


class TestJournalMalformedLine(unittest.TestCase):
    def test_read_all_raises_model_error_naming_line_number(self):
        with TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "journal.jsonl")
            journal = Journal(path)
            journal.append({"ok": 1})
            journal.append({"ok": 2})
            # Hand-write a malformed third line, exactly as a crash mid-write
            # or external corruption might produce.
            with open(path, mode="a", encoding="utf-8") as f:
                f.write("{not valid json,,,\n")

            with self.assertRaises(ModelError) as ctx:
                journal.read_all()
            message = str(ctx.exception)
            self.assertIn("3", message)

    def test_read_all_raises_on_non_object_json_line(self):
        with TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "journal.jsonl")
            journal = Journal(path)
            journal.append({"ok": 1})
            with open(path, mode="a", encoding="utf-8") as f:
                f.write("[1, 2, 3]\n")

            with self.assertRaises(ModelError) as ctx:
                journal.read_all()
            message = str(ctx.exception)
            self.assertIn("2", message)


if __name__ == "__main__":
    unittest.main()
