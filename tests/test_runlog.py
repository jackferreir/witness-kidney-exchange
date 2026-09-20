"""Pins the run ledger, and specifically the lock that prevents the
corruption which destroyed `results/samesolver_k3`.

That directory was lost because two processes were launched against it and
the sweep script opens its outputs with mode "w": the second truncated the
file while the first still held it open at a stale offset, producing a
9.6 MB file that parses as nothing. The headline figure it had already
produced survived only in a terminal log.

These tests assert that this is now impossible by accident, that a killed
run is visible as killed rather than merely sparse, and that corruption is
detectable after the fact.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

import pytest

from witness.runlog import (
    LOCK_FILE,
    RUN_FILE,
    OutputDirectoryBusy,
    read_run,
    record_run,
)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_completed_run_is_recorded_as_complete():
    with tempfile.TemporaryDirectory() as d:
        with record_run(d, note="unit test") as run:
            with open(os.path.join(d, "out.jsonl"), "w") as f:
                f.write(json.dumps({"x": 1}) + "\n")
            run["custom"] = "kept"
        rec = read_run(d)
    assert rec["status"] == "complete"
    assert rec["custom"] == "kept"
    assert rec["outputs"]["out.jsonl"]["lines"] == 1
    assert rec["outputs"]["out.jsonl"]["unparseable_lines"] == 0
    assert rec["git"]["commit"]
    assert rec["elapsed_seconds"] is not None


def test_a_crashed_run_is_recorded_as_failed_not_left_looking_finished():
    """The samesolver_k3 failure mode: a directory that is merely sparse is
    indistinguishable from one that finished. It must not be."""
    with tempfile.TemporaryDirectory() as d:
        with pytest.raises(RuntimeError):
            with record_run(d):
                raise RuntimeError("solver died")
        rec = read_run(d)
    assert rec["status"] == "failed"
    assert "solver died" in rec["error"]


def test_second_writer_on_the_same_directory_is_refused():
    """THE regression test for the corruption. Two live writers on one
    output directory is now an error rather than a silent truncation."""
    with tempfile.TemporaryDirectory() as d:
        with record_run(d):
            with pytest.raises(OutputDirectoryBusy, match="samesolver_k3"):
                with record_run(d):
                    pass


def test_a_stale_lock_from_a_killed_run_does_not_wedge_the_directory():
    """A killed run leaves its lock behind. If the holder is gone the lock
    is reclaimed, so recovery does not need manual cleanup."""
    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, LOCK_FILE), "w") as f:
            json.dump({"pid": 999999, "started": "old", "argv": ["dead"]}, f)  # not alive
        with record_run(d):
            pass
        assert read_run(d)["status"] == "complete"


def test_concurrent_writers_allowed_only_when_stated():
    with tempfile.TemporaryDirectory() as d:
        with record_run(d, allow_concurrent=True):
            with record_run(d, allow_concurrent=True):
                pass  # permitted, because both said so


def test_corruption_is_detectable_after_the_fact():
    """The audit re-reads outputs and compares against what the run
    recorded, so a file mangled later cannot pass as intact."""
    with tempfile.TemporaryDirectory() as parent:
        d = os.path.join(parent, "a_run")   # dedicated parent: audit scans siblings
        os.makedirs(d)
        with record_run(d):
            with open(os.path.join(d, "out.jsonl"), "w") as f:
                f.write(json.dumps({"x": 1}) + "\n")
        # mangle it the way the duplicate launch did
        with open(os.path.join(d, "out.jsonl"), "w") as f:
            f.write("\x00\x00 not json at all")
        proc = subprocess.run(
            [sys.executable, os.path.join(PROJECT_ROOT, "scripts", "audit_runs.py"),
             "--results", parent],
            capture_output=True, text=True, timeout=120)
    assert "CORRUPT" in proc.stdout
    assert proc.returncode == 1


def test_audit_flags_the_real_corrupted_directory():
    """The actual casualty, still on disk, is reported as corrupt."""
    proc = subprocess.run(
        [sys.executable, os.path.join(PROJECT_ROOT, "scripts", "audit_runs.py")],
        capture_output=True, text=True, timeout=300)
    assert "samesolver_k3 " in proc.stdout or "samesolver_k3\n" in proc.stdout
    assert "CORRUPT" in proc.stdout


def test_run_record_captures_enough_to_repeat_the_run():
    with tempfile.TemporaryDirectory() as d:
        with record_run(d):
            pass
        rec = read_run(d)
    for field in ("argv", "cwd", "git", "versions", "started", "host"):
        assert rec.get(field) is not None, f"{field} missing: run is not repeatable"
    assert "ortools" in rec["versions"]
