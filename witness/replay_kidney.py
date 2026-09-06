"""Independent re-verification of a saved `witness.search_kidney` witness --
the kidney-exchange analogue of `witness.replay` / `witness.replay_couples`,
re-derived separately for the same reason those two are separate from each
other: `clear_kidney_exchange` is never called through
`witness.mechanisms.get_mechanism` (see `witness.kidney`'s own "WHAT IS NOT
REGISTERED" note), so the flat replay module cannot rebuild a kidney
witness at all. Rebuilds market/truthful profile/config PURELY from the
witness dict's own fields, re-runs `clear_kidney_exchange` from scratch --
twice, to also re-check determinism -- and checks every recorded field is
reproduced exactly, plus the strict-utility-improvement claim itself.

`verify_in_subprocess` gives the same fresh-process guarantee the other two
replay modules do, via the same mechanism.
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

from witness.core import content_hash
from witness.kidney import KidneyConfig, KidneyMarket, KidneyProfile, clear_kidney_exchange

PROJECT_ROOT = Path(__file__).resolve().parent.parent

_RESULT_PREFIX = "RESULT_JSON:"


def rebuild(d: Mapping) -> "tuple[KidneyMarket, KidneyProfile, KidneyConfig]":
    market = KidneyMarket.from_dict(d["market"])
    profile = KidneyProfile.from_dict(d["truthful_profile"])
    config = KidneyConfig.from_dict(d["config"])
    return market, profile, config


def verify_witness(d: Mapping) -> "tuple[bool, tuple[str, ...]]":
    reasons: list[str] = []

    if d.get("witness_version") != 1:
        reasons.append(f"witness_version: expected 1, got {d.get('witness_version')!r}")

    mechanism_name = d.get("mechanism")
    config_field = d.get("config")
    config_mechanism = config_field.get("mechanism") if isinstance(config_field, Mapping) else None
    if config_mechanism != mechanism_name:
        reasons.append(
            f"config['mechanism'] is {config_mechanism!r}, disagreeing with the top-level "
            f"'mechanism' field {mechanism_name!r}"
        )

    without_id = {k: v for k, v in d.items() if k != "witness_id"}
    expected_id = content_hash(without_id)
    actual_id = d.get("witness_id")
    if actual_id != expected_id:
        reasons.append(
            f"witness_id {actual_id!r} does not match content_hash of the witness dict with "
            f"'witness_id' removed (expected {expected_id!r})"
        )

    market = profile = config = None
    try:
        market, profile, config = rebuild(d)
    except Exception as exc:  # noqa: BLE001
        reasons.append(f"could not rebuild market/truthful profile/config from the witness dict alone: {exc!r}")

    hospital = d.get("target_hospital")
    truthful_report_claimed = d.get("truthful_report")
    if profile is not None and hospital is not None:
        actual = list(profile.report(hospital))
        if actual != truthful_report_claimed:
            reasons.append(
                f"truthful profile's report for hospital {hospital!r} is {actual!r}, which "
                f"disagrees with truthful_report {truthful_report_claimed!r}"
            )

    truthful_result_actual = None
    if market is not None and profile is not None and config is not None:
        try:
            first = clear_kidney_exchange(market, profile, config)
            second = clear_kidney_exchange(market, profile, config)
        except Exception as exc:  # noqa: BLE001
            reasons.append(f"re-running clear_kidney_exchange on the truthful profile raised {exc!r}")
        else:
            if first != second:
                reasons.append(
                    "clear_kidney_exchange is not deterministic on the truthful profile: "
                    f"{first.to_dict()!r} vs {second.to_dict()!r}"
                )
            truthful_result_actual = first
            expected = d.get("truthful_result")
            got = first.to_dict()
            if got != expected:
                reasons.append(
                    f"re-running on the truthful profile does not reproduce truthful_result exactly: "
                    f"got {got!r}, expected {expected!r}"
                )

    false_result_actual = None
    false_report_claimed = d.get("false_report")
    if market is not None and profile is not None and config is not None and hospital is not None:
        try:
            false_profile = profile.with_report(hospital, false_report_claimed or [])
            for h, report in profile.reports.items():
                if h == hospital:
                    continue
                if false_profile.reports.get(h) != report:
                    reasons.append(f"false profile perturbed hospital {h!r}'s report, not just the target's")
            false_result_actual = clear_kidney_exchange(market, false_profile, config)
            expected = d.get("false_result")
            got = false_result_actual.to_dict()
            if got != expected:
                reasons.append(
                    f"re-running with target's report replaced by false_report does not reproduce "
                    f"false_result exactly: got {got!r}, expected {expected!r}"
                )
        except Exception as exc:  # noqa: BLE001
            reasons.append(f"re-running the false profile raised {exc!r}")

    truthful_utility_claimed = d.get("truthful_utility")
    false_utility_claimed = d.get("false_utility")
    if truthful_result_actual is not None and hospital is not None:
        actual_u = truthful_result_actual.utility.get(hospital)
        if actual_u != truthful_utility_claimed:
            reasons.append(
                f"truthful_utility {truthful_utility_claimed!r} disagrees with re-run utility {actual_u!r}"
            )
    if false_result_actual is not None and hospital is not None:
        actual_u = false_result_actual.utility.get(hospital)
        if actual_u != false_utility_claimed:
            reasons.append(
                f"false_utility {false_utility_claimed!r} disagrees with re-run utility {actual_u!r}"
            )

    if truthful_utility_claimed is not None and false_utility_claimed is not None:
        if not (false_utility_claimed > truthful_utility_claimed):
            reasons.append(
                f"false_utility {false_utility_claimed!r} is not strictly greater than "
                f"truthful_utility {truthful_utility_claimed!r} -- not a genuine manipulation"
            )
    else:
        reasons.append("truthful_utility/false_utility missing, so the improvement claim could not be checked")

    return (len(reasons) == 0, tuple(reasons))


def verify_file(path: "os.PathLike[str] | str") -> "tuple[bool, tuple[str, ...]]":
    with open(path, mode="r", encoding="utf-8") as f:
        d = json.load(f)
    return verify_witness(d)


def verify_in_subprocess(d: Mapping) -> "tuple[bool, tuple[str, ...]]":
    fd, temp_path = tempfile.mkstemp(suffix=".json", prefix="witness-replay-kidney-")
    try:
        with os.fdopen(fd, mode="w", encoding="utf-8") as f:
            json.dump(dict(d), f)
        proc = subprocess.run(
            [sys.executable, "-m", "witness.replay_kidney", temp_path],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=60,
        )
    finally:
        os.unlink(temp_path)

    for line in reversed(proc.stdout.splitlines()):
        if line.startswith(_RESULT_PREFIX):
            payload = json.loads(line[len(_RESULT_PREFIX):])
            return (bool(payload["ok"]), tuple(payload["reasons"]))

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
    parser = argparse.ArgumentParser(prog="python3 -m witness.replay_kidney")
    parser.add_argument("witness_file", help="path to a single witness JSON file")
    args = parser.parse_args(argv)
    ok, reasons = verify_file(args.witness_file)
    _print_verdict(args.witness_file, ok, reasons)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
