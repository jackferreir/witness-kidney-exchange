"""Independent re-verification of a saved witness.

A finding is only real if it can be re-derived from the SAVED WITNESS ALONE,
in a FRESH PROCESS, and produces the identical result. This module is that
re-derivation: `rebuild` reconstructs the market, truthful profile, mechanism
config, and mechanism purely from a witness dict's own fields (never from any
ambient default), and `verify_witness` re-runs the mechanism twice from
scratch -- once on the truthful profile, once with the target's report
swapped for the alleged manipulation -- and checks that every recorded field
of the witness is reproduced exactly.

`verify_in_subprocess` is what makes "fresh process" a real guarantee rather
than a claim: it writes the witness to a temp file and launches this module
as a CLI in a brand-new Python interpreter via `subprocess`, so nothing about
the result can depend on interpreter or import-cache state left over from
whatever process searched for the witness in the first place.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Mapping

from witness.core import Market, Profile, content_hash, strictly_prefers
from witness.da import Assignment
from witness.errors import ModelError
from witness.journal import Journal
from witness.mechanisms import MechanismSpec, get_mechanism

PROJECT_ROOT = Path(__file__).resolve().parent.parent

#: Prefix of the single machine-parseable line the CLI prints, so
#: `verify_in_subprocess` never has to scrape the human-readable verdict text.
_RESULT_PREFIX = "RESULT_JSON:"


def rebuild(d: Mapping) -> "tuple[Market, Profile, object, MechanismSpec]":
    """Rebuild (market, truthful profile, config, mechanism) from `d` alone.

    Uses `d["config"]` via the mechanism's own `config_from_dict`, never any
    ambient default -- that is what makes the rebuilt config exactly the one
    that produced the witness, rather than merely "a" config for that
    mechanism.
    """
    mechanism_name = d["mechanism"]
    spec = get_mechanism(mechanism_name)
    market = Market.from_dict(d["market"])
    profile = Profile.from_dict(d["truthful_profile"])
    config = spec.config_from_dict(d["config"])
    return market, profile, config, spec


def _assignment_dict(assignment: Assignment) -> dict:
    return assignment.to_dict()


def verify_witness(d: Mapping) -> "tuple[bool, tuple[str, ...]]":
    """Re-derive `d` from scratch and check every claim it makes.

    Never stops at the first failure: every one of the eight checks below is
    attempted independently and every failure is recorded as a specific,
    human-readable reason. Returns (True, ()) iff nothing was found wrong.
    """
    reasons: list[str] = []

    # 1. witness_version
    version = d.get("witness_version")
    if version != 1:
        reasons.append(f"witness_version: expected 1, got {version!r}")

    # 2. config's own "mechanism" key must agree with the top-level one
    mechanism_name = d.get("mechanism")
    config_field = d.get("config")
    config_mechanism = (
        config_field.get("mechanism") if isinstance(config_field, Mapping) else None
    )
    if config_mechanism != mechanism_name:
        reasons.append(
            f"config[\"mechanism\"] is {config_mechanism!r}, disagreeing with the "
            f"top-level \"mechanism\" field {mechanism_name!r}"
        )

    # 8. witness_id: content_hash of the dict with "witness_id" removed
    without_id = {k: v for k, v in d.items() if k != "witness_id"}
    expected_id = content_hash(without_id)
    actual_id = d.get("witness_id")
    if actual_id != expected_id:
        reasons.append(
            f"witness_id {actual_id!r} does not match content_hash of the witness "
            f"dict with \"witness_id\" removed (expected {expected_id!r})"
        )

    # Everything below needs the market/profile/config/mechanism to rebuild.
    market: "Market | None" = None
    profile: "Profile | None" = None
    config: object = None
    spec: "MechanismSpec | None" = None
    try:
        market, profile, config, spec = rebuild(d)
    except Exception as exc:  # noqa: BLE001 - report any rebuild failure as a finding
        reasons.append(
            f"could not rebuild market/truthful profile/config/mechanism from the "
            f"witness dict alone: {exc!r}"
        )

    target = d.get("target")

    # 3. truthful profile's report for the target must equal truthful_report
    truthful_report_claimed = d.get("truthful_report")
    if profile is not None and target is not None:
        try:
            actual_report = list(profile.report(target))
        except Exception as exc:  # noqa: BLE001
            reasons.append(
                f"the truthful profile has no report for target {target!r}: {exc!r}"
            )
        else:
            if actual_report != list(truthful_report_claimed or []):
                reasons.append(
                    f"truthful profile's report for target {target!r} is "
                    f"{actual_report!r}, which disagrees with truthful_report "
                    f"{truthful_report_claimed!r}"
                )

    # 4. re-running on the truthful profile must reproduce truthful_assignment
    truthful_assignment_actual: "Assignment | None" = None
    if market is not None and profile is not None and spec is not None:
        try:
            truthful_assignment_actual = spec.run(market, profile, config)
        except Exception as exc:  # noqa: BLE001
            reasons.append(
                f"re-running mechanism {mechanism_name!r} on the truthful profile "
                f"raised {exc!r}"
            )
        else:
            expected = d.get("truthful_assignment")
            got = _assignment_dict(truthful_assignment_actual)
            if got != expected:
                reasons.append(
                    "re-running on the truthful profile does not reproduce "
                    f"truthful_assignment exactly: got {got!r}, expected {expected!r}"
                )

    # 5. re-running with target's report replaced by false_report must
    #    reproduce false_assignment
    false_assignment_actual: "Assignment | None" = None
    false_report_claimed = d.get("false_report")
    if market is not None and profile is not None and spec is not None and target is not None:
        try:
            false_profile = profile.with_report(target, false_report_claimed or [])
            false_assignment_actual = spec.run(market, false_profile, config)
        except Exception as exc:  # noqa: BLE001
            reasons.append(
                f"re-running mechanism {mechanism_name!r} with target {target!r}'s "
                f"report replaced by false_report {false_report_claimed!r} raised "
                f"{exc!r}"
            )
        else:
            expected = d.get("false_assignment")
            got = _assignment_dict(false_assignment_actual)
            if got != expected:
                reasons.append(
                    "re-running with target's report replaced by false_report does "
                    f"not reproduce false_assignment exactly: got {got!r}, expected "
                    f"{expected!r}"
                )

    # 6. truthful_outcome / false_outcome must match the re-run assignments
    if truthful_assignment_actual is not None and target is not None:
        actual_outcome = truthful_assignment_actual.of(target)
        claimed_outcome = d.get("truthful_outcome")
        if actual_outcome != claimed_outcome:
            reasons.append(
                f"truthful_outcome {claimed_outcome!r} disagrees with target "
                f"{target!r}'s school {actual_outcome!r} in the re-run truthful "
                f"assignment"
            )
    if false_assignment_actual is not None and target is not None:
        actual_outcome = false_assignment_actual.of(target)
        claimed_outcome = d.get("false_outcome")
        if actual_outcome != claimed_outcome:
            reasons.append(
                f"false_outcome {claimed_outcome!r} disagrees with target "
                f"{target!r}'s school {actual_outcome!r} in the re-run false "
                f"assignment"
            )

    # 7. the target must STRICTLY PREFER the false outcome, evaluated with the
    #    TRUTHFUL report (d["truthful_report"]), never the false one
    truthful_outcome_claimed = d.get("truthful_outcome")
    false_outcome_claimed = d.get("false_outcome")
    if truthful_report_claimed is not None:
        if not strictly_prefers(
            truthful_report_claimed, false_outcome_claimed, truthful_outcome_claimed
        ):
            reasons.append(
                f"target {target!r} does not strictly prefer false_outcome "
                f"{false_outcome_claimed!r} over truthful_outcome "
                f"{truthful_outcome_claimed!r} under their own truthful_report "
                f"{truthful_report_claimed!r} -- this is not a genuine manipulation"
            )
    else:
        reasons.append(
            "truthful_report is missing, so preference of false_outcome over "
            "truthful_outcome could not be checked"
        )

    return (len(reasons) == 0, tuple(reasons))


def verify_file(path: "os.PathLike[str] | str") -> "tuple[bool, tuple[str, ...]]":
    """Load one witness JSON file from disk and verify it."""
    with open(path, mode="r", encoding="utf-8") as f:
        d = json.load(f)
    if not isinstance(d, dict):
        raise ModelError(f"witness file {os.fspath(path)!r} does not contain a JSON object")
    return verify_witness(d)


def verify_in_subprocess(d: Mapping) -> "tuple[bool, tuple[str, ...]]":
    """Verify `d` by launching this module as a CLI in a FRESH process.

    Writes `d` to a temp file, runs `python3 -m witness.replay <file>` via
    `subprocess.run` with `sys.executable` and `cwd=PROJECT_ROOT`, and parses
    the RESULT_JSON line the CLI prints -- no shared interpreter state with
    whatever process constructed `d`.
    """
    fd, temp_path = tempfile.mkstemp(suffix=".json", prefix="witness-replay-")
    try:
        with os.fdopen(fd, mode="w", encoding="utf-8") as f:
            json.dump(dict(d), f)
        proc = subprocess.run(
            [sys.executable, "-m", "witness.replay", temp_path],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=60,
        )
    finally:
        os.unlink(temp_path)

    for line in reversed(proc.stdout.splitlines()):
        if line.startswith(_RESULT_PREFIX):
            payload = json.loads(line[len(_RESULT_PREFIX) :])
            return (bool(payload["ok"]), tuple(payload["reasons"]))

    # The CLI is expected to always print a RESULT_JSON line. If it didn't,
    # that is itself a verification failure worth reporting in full.
    return (
        False,
        (
            f"subprocess produced no {_RESULT_PREFIX!r} line (returncode="
            f"{proc.returncode}); stdout={proc.stdout!r} stderr={proc.stderr!r}",
        ),
    )


def _print_verdict(label: str, ok: bool, reasons: "tuple[str, ...]") -> None:
    if ok:
        print(f"VERIFIED: {label}")
    else:
        print(f"REJECTED: {label}")
        for reason in reasons:
            print(f"  - {reason}")
    print(_RESULT_PREFIX + json.dumps({"ok": ok, "reasons": list(reasons)}))


def main(argv: "list[str] | None" = None) -> int:
    parser = argparse.ArgumentParser(prog="python3 -m witness.replay")
    parser.add_argument("witness_file", nargs="?", help="path to a single witness JSON file")
    parser.add_argument(
        "--jsonl", dest="jsonl_file", default=None, help="path to a journal (JSONL) to verify in full"
    )
    args = parser.parse_args(argv)

    if args.jsonl_file is not None:
        journal = Journal(args.jsonl_file)
        records = journal.read_all()
        all_ok = True
        for i, record in enumerate(records, start=1):
            ok, reasons = verify_witness(record)
            _print_verdict(f"{args.jsonl_file} line {i}", ok, reasons)
            all_ok = all_ok and ok
        if not records:
            print(f"journal {args.jsonl_file!r} contains no records")
        return 0 if all_ok else 1

    if args.witness_file is None:
        parser.error("either a witness_file or --jsonl must be given")
        return 2  # pragma: no cover - argparse.error exits already

    ok, reasons = verify_file(args.witness_file)
    _print_verdict(args.witness_file, ok, reasons)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
