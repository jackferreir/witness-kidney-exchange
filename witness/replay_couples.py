"""Independent re-verification of a saved `witness.search_couples` witness --
the couples analogue of `witness.replay`, re-derived separately (not
imported/branched) for the same reason `witness.search_couples` is its own
module rather than a couples branch of `witness.search`: `couples_deferred_
acceptance` is not a `MechanismSpec.run` and is never called through
`witness.mechanisms.get_mechanism`, so `witness.replay.rebuild` cannot
reconstruct a couples witness at all (it would look up a mechanism name that
was never registered). This module rebuilds a couples witness's market,
truthful profile, and config PURELY from the witness dict's own fields, then
re-runs `couples_deferred_acceptance` from scratch -- twice, exactly as
`witness.search_couples` itself does before ever trusting a truthful run --
and checks every recorded field is reproduced exactly.

`verify_in_subprocess` gives the same "fresh process, no shared interpreter
state" guarantee `witness.replay.verify_in_subprocess` does, via the same
mechanism: write the witness to a temp file, launch this module as a CLI in
a brand-new `sys.executable` subprocess, parse its RESULT_JSON line.
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

from witness.core import Market, content_hash
from witness.couples import (
    Couple,
    CouplesConfig,
    CouplesProfile,
    STATUS_STABLE,
    couples_deferred_acceptance,
)
from witness.search_couples import (
    TARGET_COUPLE,
    TARGET_SINGLE,
    couple_strictly_prefers,
)
from witness.core import strictly_prefers

PROJECT_ROOT = Path(__file__).resolve().parent.parent

_RESULT_PREFIX = "RESULT_JSON:"


def rebuild(d: Mapping) -> "tuple[Market, CouplesProfile, CouplesConfig]":
    """Rebuild (market, truthful profile, config) from `d` alone -- never
    from any ambient default. `d["config"]["mechanism"]` is not consulted to
    look anything up (there is no couples registry entry); it is only
    checked for self-consistency below."""
    market = Market.from_dict(d["market"])
    profile = CouplesProfile.from_dict(d["truthful_profile"])
    config = CouplesConfig.from_dict(d["config"])
    return market, profile, config


def _find_couple_index(profile: CouplesProfile, target_ids: "tuple[str, ...]") -> "int | None":
    wanted = set(target_ids)
    for i, c in enumerate(profile.couples):
        if set(c.members) == wanted:
            return i
    return None


def _with_single_report(profile: CouplesProfile, student: str, new_report) -> CouplesProfile:
    singles = dict(profile.singles)
    singles[student] = tuple(new_report)
    return CouplesProfile(singles=singles, couples=profile.couples)


def _with_couple_report(profile: CouplesProfile, couple_index: int, new_joint_rankings) -> CouplesProfile:
    couples = list(profile.couples)
    old = couples[couple_index]
    couples[couple_index] = Couple(members=old.members, joint_rankings=tuple(tuple(p) for p in new_joint_rankings))
    return CouplesProfile(singles=profile.singles, couples=tuple(couples))


def verify_witness(d: Mapping) -> "tuple[bool, tuple[str, ...]]":
    """Re-derive `d` from scratch and check every claim it makes. Never
    stops at the first failure -- every check is attempted independently."""
    reasons: list[str] = []

    if d.get("witness_version") != 1:
        reasons.append(f"witness_version: expected 1, got {d.get('witness_version')!r}")

    mechanism_name = d.get("mechanism")
    config_field = d.get("config")
    config_mechanism = config_field.get("mechanism") if isinstance(config_field, Mapping) else None
    if config_mechanism != mechanism_name:
        reasons.append(
            f"config['mechanism'] is {config_mechanism!r}, disagreeing with the "
            f"top-level 'mechanism' field {mechanism_name!r}"
        )

    target_kind = d.get("target_kind")
    if target_kind not in (TARGET_SINGLE, TARGET_COUPLE):
        reasons.append(f"target_kind must be {TARGET_SINGLE!r} or {TARGET_COUPLE!r}, got {target_kind!r}")

    without_id = {k: v for k, v in d.items() if k != "witness_id"}
    expected_id = content_hash(without_id)
    actual_id = d.get("witness_id")
    if actual_id != expected_id:
        reasons.append(
            f"witness_id {actual_id!r} does not match content_hash of the witness "
            f"dict with 'witness_id' removed (expected {expected_id!r})"
        )

    market: "Market | None" = None
    profile: "CouplesProfile | None" = None
    config: "CouplesConfig | None" = None
    try:
        market, profile, config = rebuild(d)
    except Exception as exc:  # noqa: BLE001
        reasons.append(f"could not rebuild market/truthful profile/config from the witness dict alone: {exc!r}")

    target_ids = tuple(d.get("target_ids") or ())
    truthful_report_claimed = d.get("truthful_report")

    couple_index: "int | None" = None
    if profile is not None and target_kind == TARGET_COUPLE:
        couple_index = _find_couple_index(profile, target_ids)
        if couple_index is None:
            reasons.append(f"no couple with members {target_ids!r} found in the rebuilt truthful profile")
        else:
            actual = [list(p) for p in profile.couples[couple_index].joint_rankings]
            if actual != truthful_report_claimed:
                reasons.append(
                    f"truthful profile's joint ROL for couple {target_ids!r} is {actual!r}, "
                    f"which disagrees with truthful_report {truthful_report_claimed!r}"
                )
    elif profile is not None and target_kind == TARGET_SINGLE:
        if len(target_ids) != 1:
            reasons.append(f"target_kind is 'single' but target_ids is {target_ids!r} (expected exactly one id)")
        else:
            actual = list(profile.singles.get(target_ids[0], ()))
            if actual != truthful_report_claimed:
                reasons.append(
                    f"truthful profile's report for single {target_ids[0]!r} is {actual!r}, "
                    f"which disagrees with truthful_report {truthful_report_claimed!r}"
                )

    truthful_assignment_actual = None
    truthful_status_actual = None
    if market is not None and profile is not None and config is not None:
        try:
            first = couples_deferred_acceptance(market, profile, config)
            second = couples_deferred_acceptance(market, profile, config)
        except Exception as exc:  # noqa: BLE001
            reasons.append(f"re-running couples_deferred_acceptance on the truthful profile raised {exc!r}")
        else:
            if first.status != second.status or first.assignment != second.assignment:
                reasons.append(
                    "couples_deferred_acceptance is not deterministic on the truthful profile: "
                    f"{first.status!r}/{first.assignment.to_dict()!r} vs "
                    f"{second.status!r}/{second.assignment.to_dict()!r}"
                )
            truthful_status_actual = first.status
            truthful_assignment_actual = first.assignment
            if first.status != STATUS_STABLE:
                reasons.append(
                    f"re-running the truthful profile yields status {first.status!r}, not "
                    f"{STATUS_STABLE!r} -- not a comparable baseline, so this witness should "
                    f"never have been produced"
                )
            else:
                expected = d.get("truthful_assignment")
                got = first.assignment.to_dict()
                if got != expected:
                    reasons.append(
                        f"re-running on the truthful profile does not reproduce truthful_assignment "
                        f"exactly: got {got!r}, expected {expected!r}"
                    )

    false_assignment_actual = None
    false_report_claimed = d.get("false_report")
    if market is not None and profile is not None and config is not None:
        try:
            if target_kind == TARGET_SINGLE and len(target_ids) == 1:
                false_profile = _with_single_report(profile, target_ids[0], false_report_claimed or [])
            elif target_kind == TARGET_COUPLE and couple_index is not None:
                false_profile = _with_couple_report(profile, couple_index, false_report_claimed or [])
            else:
                false_profile = None
            if false_profile is not None:
                # Rule 2: only the target's own report may differ.
                for s, report in profile.singles.items():
                    if target_kind == TARGET_SINGLE and s == target_ids[0]:
                        continue
                    if false_profile.singles.get(s) != report:
                        reasons.append(f"false profile perturbed single {s!r}'s report, not just the target's")
                for i, c in enumerate(profile.couples):
                    if target_kind == TARGET_COUPLE and i == couple_index:
                        continue
                    if false_profile.couples[i].joint_rankings != c.joint_rankings:
                        reasons.append(f"false profile perturbed couple {c.members!r}'s joint ROL, not just the target's")

                false_result = couples_deferred_acceptance(market, false_profile, config)
                false_assignment_actual = false_result.assignment
                if false_result.status != STATUS_STABLE:
                    reasons.append(
                        f"re-running the false profile yields status {false_result.status!r}, not "
                        f"{STATUS_STABLE!r} -- not a comparable outcome, so this witness should "
                        f"never have been produced"
                    )
                else:
                    expected = d.get("false_assignment")
                    got = false_result.assignment.to_dict()
                    if got != expected:
                        reasons.append(
                            f"re-running with target's report replaced by false_report does not "
                            f"reproduce false_assignment exactly: got {got!r}, expected {expected!r}"
                        )
        except Exception as exc:  # noqa: BLE001
            reasons.append(f"re-running the false profile raised {exc!r}")

    truthful_outcome_claimed = d.get("truthful_outcome")
    false_outcome_claimed = d.get("false_outcome")
    if truthful_assignment_actual is not None:
        if target_kind == TARGET_SINGLE and len(target_ids) == 1:
            actual_outcome = truthful_assignment_actual.of(target_ids[0])
            if actual_outcome != truthful_outcome_claimed:
                reasons.append(
                    f"truthful_outcome {truthful_outcome_claimed!r} disagrees with re-run outcome {actual_outcome!r}"
                )
        elif target_kind == TARGET_COUPLE and len(target_ids) == 2:
            actual_pair = [truthful_assignment_actual.of(target_ids[0]), truthful_assignment_actual.of(target_ids[1])]
            if actual_pair != truthful_outcome_claimed:
                reasons.append(
                    f"truthful_outcome {truthful_outcome_claimed!r} disagrees with re-run pair {actual_pair!r}"
                )
    if false_assignment_actual is not None:
        if target_kind == TARGET_SINGLE and len(target_ids) == 1:
            actual_outcome = false_assignment_actual.of(target_ids[0])
            if actual_outcome != false_outcome_claimed:
                reasons.append(
                    f"false_outcome {false_outcome_claimed!r} disagrees with re-run outcome {actual_outcome!r}"
                )
        elif target_kind == TARGET_COUPLE and len(target_ids) == 2:
            actual_pair = [false_assignment_actual.of(target_ids[0]), false_assignment_actual.of(target_ids[1])]
            if actual_pair != false_outcome_claimed:
                reasons.append(
                    f"false_outcome {false_outcome_claimed!r} disagrees with re-run pair {actual_pair!r}"
                )

    if truthful_report_claimed is not None:
        if target_kind == TARGET_SINGLE:
            if not strictly_prefers(truthful_report_claimed, false_outcome_claimed, truthful_outcome_claimed):
                reasons.append(
                    f"single target does not strictly prefer false_outcome {false_outcome_claimed!r} "
                    f"over truthful_outcome {truthful_outcome_claimed!r} under their own truthful_report "
                    f"-- not a genuine manipulation"
                )
        elif target_kind == TARGET_COUPLE:
            joint = [tuple(p) for p in truthful_report_claimed]
            t_pair = tuple(truthful_outcome_claimed) if truthful_outcome_claimed is not None else None
            f_pair = tuple(false_outcome_claimed) if false_outcome_claimed is not None else None
            if not couple_strictly_prefers(joint, f_pair, t_pair):
                reasons.append(
                    f"couple target does not strictly prefer false pair {f_pair!r} over truthful "
                    f"pair {t_pair!r} under their own truthful joint ROL -- not a genuine manipulation"
                )
    else:
        reasons.append("truthful_report is missing, so the preference claim could not be checked")

    return (len(reasons) == 0, tuple(reasons))


def verify_file(path: "os.PathLike[str] | str") -> "tuple[bool, tuple[str, ...]]":
    with open(path, mode="r", encoding="utf-8") as f:
        d = json.load(f)
    return verify_witness(d)


def verify_in_subprocess(d: Mapping) -> "tuple[bool, tuple[str, ...]]":
    fd, temp_path = tempfile.mkstemp(suffix=".json", prefix="witness-replay-couples-")
    try:
        with os.fdopen(fd, mode="w", encoding="utf-8") as f:
            json.dump(dict(d), f)
        proc = subprocess.run(
            [sys.executable, "-m", "witness.replay_couples", temp_path],
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
    parser = argparse.ArgumentParser(prog="python3 -m witness.replay_couples")
    parser.add_argument("witness_file", help="path to a single witness JSON file")
    args = parser.parse_args(argv)
    ok, reasons = verify_file(args.witness_file)
    _print_verdict(args.witness_file, ok, reasons)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
