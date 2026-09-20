#!/usr/bin/env python3
"""Tell me, for every result directory, whether I can trust what is in it.

This is the backward-checking tool. `witness/runlog.py` records provenance
going forward; this reports on what is already on disk, including the large
amount of it that predates the ledger and therefore has none.

For each directory under `results/` it reports:

  COMPLETE    a run finished cleanly and its outputs are intact
  PARTIAL     a run started and never recorded an ending -- it was killed.
              `results/samesolver_k3` is the worked example: it looked
              merely sparse, and its figure was quoted as if final.
  FAILED      the run recorded an exception
  CORRUPT     an output file has lines that do not parse, or its digest no
              longer matches what the run recorded. Two writers on one
              directory produced exactly this and nothing noticed.
  NO LEDGER   produced before RUN.json existed. Not necessarily wrong, but
              the command, the code version, and whether it finished are
              all unrecoverable. Quote with care.

Exit code is non-zero if anything is CORRUPT or PARTIAL, so this can gate
a release the same way the claims registry does.

    python3 scripts/audit_runs.py [--results DIR] [--quiet]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from witness.runlog import RUN_FILE, RUNS_LOG, read_run  # noqa: E402


def _check_file(path: str, recorded: "dict | None") -> "list[str]":
    problems = []
    if not os.path.exists(path):
        return [f"{os.path.basename(path)}: recorded by the run but now missing"]
    name = os.path.basename(path)
    if name.endswith(".jsonl"):
        bad = total = 0
        with open(path, "rb") as f:
            for raw in f:
                total += 1
                try:
                    json.loads(raw.decode("utf-8"))
                except Exception:  # noqa: BLE001
                    bad += 1
        if bad:
            problems.append(f"{name}: {bad} of {total} lines do not parse as JSON")
    if recorded and "sha256" in recorded:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        if h.hexdigest()[:16] != recorded["sha256"]:
            problems.append(f"{name}: content changed since the run recorded it")
    return problems


def audit_dir(d: str) -> dict:
    run = read_run(d)
    try:
        files = [f for f in sorted(os.listdir(d))
                 if os.path.isfile(os.path.join(d, f)) and f not in (RUN_FILE, RUNS_LOG)
                 and not f.startswith(".")]
    except OSError as exc:
        # An auditor that dies on one unreadable directory audits nothing.
        return {"dir": d, "state": "UNREADABLE", "files": 0,
                "problems": [f"cannot list directory: {exc.strerror}"],
                "git": None, "elapsed": None}
    problems = []
    for f in files:
        problems += _check_file(os.path.join(d, f), (run or {}).get("outputs", {}).get(f))

    if run is None:
        state = "NO LEDGER"
    elif run.get("status") == "complete":
        state = "COMPLETE"
    elif run.get("status") == "running":
        state = "PARTIAL"
        problems.append("run never recorded an ending: it was killed or is still live")
    elif run.get("status") in ("failed", "killed"):
        state = run["status"].upper()
        problems.append(run.get("error", "no reason recorded"))
    else:
        state = "UNKNOWN"
    if problems and state in ("COMPLETE", "NO LEDGER"):
        state = "CORRUPT"
    return {"dir": d, "state": state, "files": len(files), "problems": problems,
            "git": (run or {}).get("git", {}).get("commit"),
            "elapsed": (run or {}).get("elapsed_seconds")}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--results", default=os.path.join(PROJECT_ROOT, "results"))
    ap.add_argument("--quiet", action="store_true", help="only show anything not COMPLETE")
    args = ap.parse_args()

    dirs = sorted(d for d in (os.path.join(args.results, x) for x in os.listdir(args.results))
                  if os.path.isdir(d))
    rows = [audit_dir(d) for d in dirs]

    counts: dict = {}
    bad = 0
    for r in rows:
        counts[r["state"]] = counts.get(r["state"], 0) + 1
        if r["state"] in ("CORRUPT", "PARTIAL", "FAILED", "KILLED"):
            bad += 1
        if args.quiet and r["state"] == "COMPLETE":
            continue
        name = os.path.relpath(r["dir"], PROJECT_ROOT)
        sha = (r["git"] or "")[:8]
        print(f"{r['state']:<10} {name:<52} files={r['files']:<3} {('@'+sha) if sha else ''}")
        for p in r["problems"]:
            print(f"           - {p}")

    print()
    print("  ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    if bad:
        print(f"\n{bad} directory(ies) are corrupt, partial, or failed. "
              f"Nothing in them should be quoted without re-running.")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
