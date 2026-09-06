"""Append-only JSONL journal of candidate witnesses.

APPEND-ONLY IS THE WHOLE POINT. A journal is the durable record of what the
search process found; if a line could be silently rewritten or dropped, the
record would no longer be evidence of anything. This module therefore never
opens its file in "w" or "r+" mode, never seeks, never truncates, and never
rewrites a previously-written line -- the only write operation it performs is
opening in append ("a") mode and writing new lines at the end. Every write is
followed by an explicit flush() and os.fsync() so that a crash immediately
after `append` returns cannot lose the record: once the caller has the
returned hash, the line is durably on disk.
"""

from __future__ import annotations

import os
from typing import Mapping

from witness.core import canonical_json, content_hash
from witness.errors import ModelError

try:
    import json as _json
except ImportError:  # pragma: no cover - json is stdlib, always present
    raise


class Journal:
    """An append-only JSONL log of candidate witness records.

    Each call to `append` writes exactly one physical line (canonical JSON,
    no embedded newline) to the end of the file at `path`, creating the file
    and any missing parent directories on first use. `read_all` parses every
    line back, in the order they were written.
    """

    def __init__(self, path: "os.PathLike[str] | str") -> None:
        self._path = os.fspath(path)
        parent = os.path.dirname(self._path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        # Touch the file into existence (append mode; never truncates an
        # existing file, and creates an empty one if absent).
        with open(self._path, mode="a", encoding="utf-8"):
            pass

    @property
    def path(self) -> str:
        return self._path

    def append(self, record: Mapping) -> str:
        """Append `record` as one JSON line and return its content_hash.

        Opens the file in "a" mode ONLY -- append mode guarantees the write
        lands after every byte already on disk, even if some other process
        also appended in the meantime. flush() + os.fsync() before returning
        so the line is durable, not just buffered.
        """
        line = canonical_json(record)
        if "\n" in line or "\r" in line:
            # canonical_json must never emit a raw newline; this would
            # silently corrupt the one-record-per-line invariant.
            raise ModelError(
                "journal record serialized to a line containing a raw newline; "
                "refusing to append it, since that would break the "
                "one-record-per-physical-line invariant"
            )
        with open(self._path, mode="a", encoding="utf-8") as f:
            f.write(line)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        return content_hash(record)

    def read_all(self) -> "tuple[dict, ...]":
        """Parse every line in the journal, in the order they were written.

        A malformed line is never silently skipped: it raises `ModelError`
        naming the 1-based line number, since a journal whose lines can't
        all be trusted is not append-only evidence any more.
        """
        records: list[dict] = []
        with open(self._path, mode="r", encoding="utf-8") as f:
            for line_number, raw_line in enumerate(f, start=1):
                line = raw_line.rstrip("\n")
                if line == "":
                    continue
                try:
                    record = _json.loads(line)
                except _json.JSONDecodeError as exc:
                    raise ModelError(
                        f"journal {self._path!r}: malformed JSON on line "
                        f"{line_number}: {exc}"
                    ) from exc
                if not isinstance(record, dict):
                    raise ModelError(
                        f"journal {self._path!r}: line {line_number} is valid JSON "
                        f"but not a JSON object (got {type(record).__name__})"
                    )
                records.append(record)
        return tuple(records)

    def __len__(self) -> int:
        return len(self.read_all())
