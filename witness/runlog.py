"""A durable record of how every result directory was produced.

WHAT WENT WRONG WITHOUT THIS. Three distinct failures in a single night,
all of them invisible after the fact:

  * `results/samesolver_k3/` was killed part-way through its second stage.
    No `summary.json` was ever written, so the directory looked merely
    sparse rather than incomplete, and the headline figure it had already
    produced survived only in a terminal log that is not repo data.

  * Two processes were launched against that same directory. The sweep
    script opens its output with mode "w", so the second launch truncated
    the file while the first still held it open at a stale offset. The
    result was a 9.6 MB single-line file that parses as nothing. Nothing
    recorded that a second writer had ever existed.

  * A figure quoted in the README (0/135 vs 4/135 under two tie-break
    policies) had no surviving run behind it at all. It could not be
    checked, only believed.

WHAT THIS RECORDS. `record_run` wraps a script's main body and writes
`RUN.json` into the output directory:

  status        running | complete | failed | killed   -- set on exit, so a
                directory left at "running" is a run that died
  argv          the exact command, so the run can be repeated
  git           commit sha and whether the tree was dirty, because results
                in this repo were produced by code that has since changed
  started/ended ISO timestamps and elapsed seconds
  versions      python, ortools, networkx -- solver behaviour is version
                dependent
  outputs       per file: size, line count, sha256, and whether every line
                parses as JSON, so silent corruption is detectable later

AND WHAT IT PREVENTS. `record_run` takes an exclusive lock on the output
directory and refuses to start if another live process holds it. That is
the specific defect that destroyed `samesolver_k3`: it is now impossible
to run two writers against one directory by accident.

The lock stores the holder's pid and is broken automatically if that
process is gone, so a killed run does not wedge the directory forever.
"""
from __future__ import annotations

import contextlib
import datetime
import hashlib
import json
import os
import socket
import subprocess
import sys
import time

RUN_FILE = "RUN.json"
RUNS_LOG = "RUNS.jsonl"
LOCK_FILE = ".run.lock"


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def _git_state() -> dict:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    def _run(args):
        try:
            return subprocess.run(args, cwd=root, capture_output=True, text=True,
                                  timeout=10).stdout.strip()
        except Exception:  # noqa: BLE001
            return None
    sha = _run(["git", "rev-parse", "HEAD"])
    dirty = _run(["git", "status", "--porcelain"])
    return {"commit": sha, "dirty": bool(dirty), "dirty_files": len(dirty.splitlines()) if dirty else 0}


def _versions() -> dict:
    out = {"python": sys.version.split()[0]}
    for mod in ("ortools", "networkx", "numpy"):
        try:
            out[mod] = __import__(mod).__version__
        except Exception:  # noqa: BLE001
            out[mod] = None
    return out


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def _fingerprint(path: str) -> dict:
    """Size, line count, digest, and JSON-parseability of every line.

    The parseability flag is what makes the `samesolver_k3` corruption
    detectable without opening the file by hand: a 9.6 MB output whose
    lines do not parse is obviously broken, and silently ignoring that is
    how a dead figure stayed in the README.
    """
    h = hashlib.sha256()
    lines = 0
    bad = 0
    with open(path, "rb") as f:
        for raw in f:
            h.update(raw)
            lines += 1
            if path.endswith(".jsonl"):
                try:
                    json.loads(raw.decode("utf-8"))
                except Exception:  # noqa: BLE001
                    bad += 1
    d = {"bytes": os.path.getsize(path), "lines": lines, "sha256": h.hexdigest()[:16]}
    if path.endswith(".jsonl"):
        d["unparseable_lines"] = bad
    return d


def _scan_outputs(out_dir: str) -> dict:
    out = {}
    for name in sorted(os.listdir(out_dir)):
        if name in (RUN_FILE, LOCK_FILE):
            continue
        p = os.path.join(out_dir, name)
        if os.path.isfile(p):
            try:
                out[name] = _fingerprint(p)
            except Exception as exc:  # noqa: BLE001
                out[name] = {"error": repr(exc)[:100]}
    return out


class OutputDirectoryBusy(Exception):
    """Another live process is already writing this directory."""


@contextlib.contextmanager
def record_run(out_dir: str, *, note: str = "", allow_concurrent: bool = False):
    """Wrap a script's main body. Writes RUN.json and holds a lock.

    `allow_concurrent=True` is for designs that genuinely shard one logical
    run across processes, and even then each shard should use its own
    directory; it exists so that intent has to be stated rather than
    happening by accident.
    """
    os.makedirs(out_dir, exist_ok=True)
    lock_path = os.path.join(out_dir, LOCK_FILE)

    if not allow_concurrent:
        if os.path.exists(lock_path):
            try:
                holder = json.load(open(lock_path))
                pid = int(holder.get("pid", -1))
            except Exception:  # noqa: BLE001
                pid = -1
            if pid > 0 and _pid_alive(pid):
                raise OutputDirectoryBusy(
                    f"{out_dir} is being written by live pid {pid} "
                    f"(started {holder.get('started')!r}, cmd {holder.get('argv')!r}). "
                    f"Two writers on one directory is what corrupted results/samesolver_k3. "
                    f"Use a different --out-dir, or wait for that run to finish."
                )
            # stale lock from a killed run: reclaim it, but say so
            with contextlib.suppress(OSError):
                os.unlink(lock_path)
        with open(lock_path, "w") as f:
            json.dump({"pid": os.getpid(), "started": _now(), "argv": sys.argv}, f)

    record = {
        "status": "running",
        "argv": sys.argv,
        "cwd": os.getcwd(),
        "out_dir": out_dir,
        "note": note,
        "host": socket.gethostname(),
        "pid": os.getpid(),
        "git": _git_state(),
        "versions": _versions(),
        "started": _now(),
        "ended": None,
        "elapsed_seconds": None,
        "outputs": {},
    }
    path = os.path.join(out_dir, RUN_FILE)
    with open(path, "w") as f:
        json.dump(record, f, indent=2, sort_keys=True)

    t0 = time.time()
    try:
        yield record
    except KeyboardInterrupt:
        record["status"] = "killed"
        record["error"] = "KeyboardInterrupt"
        raise
    except BaseException as exc:  # noqa: BLE001
        record["status"] = "failed"
        record["error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
        raise
    else:
        record["status"] = "complete"
    finally:
        record["ended"] = _now()
        record["elapsed_seconds"] = round(time.time() - t0, 1)
        with contextlib.suppress(Exception):
            record["outputs"] = _scan_outputs(out_dir)
        with contextlib.suppress(Exception):
            with open(path, "w") as f:
                json.dump(record, f, indent=2, sort_keys=True)
        # Resumable scripts are relaunched repeatedly, and RUN.json only
        # holds the latest attempt. RUNS.jsonl is append-only, so the fact
        # that a directory took four killed attempts to fill is recoverable
        # rather than overwritten -- that history is exactly what was
        # missing when samesolver_k3 was quoted as if it were one clean run.
        with contextlib.suppress(Exception):
            with open(os.path.join(out_dir, RUNS_LOG), "a") as f:
                f.write(json.dumps({k: v for k, v in record.items() if k != "outputs"},
                                   sort_keys=True) + "\n")
        if not allow_concurrent:
            with contextlib.suppress(OSError):
                os.unlink(lock_path)


def read_run(out_dir: str) -> "dict | None":
    p = os.path.join(out_dir, RUN_FILE)
    if not os.path.exists(p):
        return None
    try:
        return json.load(open(p))
    except Exception:  # noqa: BLE001
        return {"status": "unreadable"}
