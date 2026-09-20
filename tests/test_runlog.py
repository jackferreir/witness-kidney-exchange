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


# --------------------------------------------------------------------------
# begin_run: the one-line entry point used by the scripts. Its signal
# handling is the part that matters here -- these jobs are routinely killed,
# and a `finally:` block does not run on SIGTERM.
# --------------------------------------------------------------------------

from witness.runlog import begin_run  # noqa: E402


def test_sigterm_is_recorded_as_killed_not_left_running():
    """A killed run must be visibly killed. Under a context manager alone
    it would sit at status 'running' forever, which is indistinguishable
    from a run still in progress -- the samesolver_k3 ambiguity."""
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "run")
        script = os.path.join(d, "s.py")
        with open(script, "w") as f:
            f.write(
                "import sys, time\n"
                f"sys.path.insert(0, {PROJECT_ROOT!r})\n"
                "from witness.runlog import begin_run\n"
                f"begin_run({out!r}, note='sigterm')\n"
                "time.sleep(60)\n")
        proc = subprocess.Popen([sys.executable, script])
        import time as _t
        _t.sleep(3)
        proc.terminate()
        proc.wait(timeout=30)
        rec = read_run(out)
    assert rec["status"] == "killed"
    assert "15" in rec["error"]
    assert not os.path.exists(os.path.join(out, LOCK_FILE)), "lock not released on kill"


def test_begin_run_releases_lock_on_clean_exit():
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "run")
        script = os.path.join(d, "s.py")
        with open(script, "w") as f:
            f.write(
                "import sys\n"
                f"sys.path.insert(0, {PROJECT_ROOT!r})\n"
                "from witness.runlog import begin_run\n"
                f"begin_run({out!r})\n")
        subprocess.run([sys.executable, script], check=True, timeout=60)
        rec = read_run(out)
    assert rec["status"] == "complete"
    assert not os.path.exists(os.path.join(out, LOCK_FILE))


def test_every_result_writing_script_is_wired_to_the_ledger():
    """Coverage gate. A new script that writes results without provenance
    fails here rather than producing another unattributable directory."""
    import glob
    unwired = []
    for p in sorted(glob.glob(os.path.join(PROJECT_ROOT, "scripts", "*.py"))):
        src = open(p).read()
        writes_results = "out_dir" in src or "out-dir" in src
        if writes_results and "begin_run" not in src and "record_run" not in src:
            unwired.append(os.path.basename(p))
    assert not unwired, f"scripts write result dirs without provenance: {unwired}"
