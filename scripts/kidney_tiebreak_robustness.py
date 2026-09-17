"""Tiebreak-robustness checker for saved `witness.search_kidney` witnesses.

A reviewer objection this answers: "the hospital only profits against your
arbitrary tiebreak" -- `witness.kidney.KidneyConfig.tiebreak_policy` fixes ONE
maximum-cardinality central clearing (whichever `TIEBREAK_MAX_CARDINALITY_ILP`
or `TIEBREAK_LEX_SMALLEST_BY_INDEX` happens to pick), but the mechanism's own
spec only requires MAXIMUM CARDINALITY, not a specific tie-broken selection.
This script asks, for each saved witness, independent of the fixed-seed
selection: across every possible maximum-cardinality central clearing the
mechanism could equally validly have chosen, what is the RANGE of the target
hospital's utility -- both truthful and under the false report? If the
false-report range beats the truthful range under every tiebreak (`false_min
> true_max`), the manipulation is robust to the reviewer's objection.

THE MODEL THIS RELIES ON (verified against `witness/kidney.py`, see its
"THE MODEL" docstring and `clear_kidney_exchange`, lines 643-682):

  * Central clearing (`clear_kidney_exchange`, line 652-654) selects a
    MAXIMUM-CARDINALITY vertex-disjoint cycle packing over the pool of ALL
    hospitals' REPORTED pairs. A hospital `h`'s CENTRAL FOOTPRINT is exactly
    the subset of `h`'s own REPORTED pairs that end up matched in whichever
    central selection is chosen.
  * Residual local clearing (line 662-669): for EVERY hospital `h`, the
    RESIDUAL is `h`'s OWNED pairs (not just reported ones -- `market.
    pairs_of(h)`, line 664) that were not matched centrally. `h`'s local
    stage reruns the SAME maximum-cardinality rule restricted to `h`'s own
    internal graph over that residual.
  * `h`'s UTILITY (line 674) is `|central footprint| + |local match|`. Since
    the residual is fully determined by the central footprint (it is exactly
    `h`'s owned pairs minus the footprint), and the local stage is ALWAYS run
    to its own maximum cardinality (never a free choice), utility as a
    function of `h`'s footprint is well-defined and single-valued once the
    footprint is fixed -- see `_local_max_cardinality` below, which literally
    calls `witness.kidney._select_maximum_cycles_ilp`, the SAME function the
    mechanism itself uses for local clearing, so this script's residual
    computation is not a reimplementation but a direct reuse of the
    mechanism's own rule.

METHOD, per hospital `h` and a given profile (truthful, or false with only
`h`'s report swapped -- every other hospital's report is asserted unchanged,
mirroring `witness.search_kidney._assert_only_target_changed`):

  1. `C* = `the maximum central cardinality over the FULL reported pool,
     computed via `witness.kidney._select_maximum_cycles_ilp` (the same ILP
     the mechanism itself uses for central clearing) -- never re-derived by
     a separate, potentially-inconsistent formulation.
  2. Enumerate every candidate footprint `S` (subset of `h`'s OWN reported
     pairs -- `h` owns only a handful of pairs in every real witness checked,
     so `2**|report|` is always small). For each `S`, an ILP checks FEASIBILITY:
     does there exist a vertex-disjoint selection of the SAME central
     candidate cycles, covering exactly `C*` pairs total, whose matched
     subset of `h`'s reported pairs is EXACTLY `S`?
  3. For every FEASIBLE `S`, `h`'s utility is `|S| + LocalMax(residual(S))`,
     where `residual(S) = (h's report - S) | (h's owned pairs never
     reported)` and `LocalMax` is the mechanism's own local-clearing ILP
     call (see above) -- NOT a re-derivation.
  4. `u_min`/`u_max` = the min/max utility over every feasible `S`. Sanity
     check (mandatory): the witness's OWN fixed-seed `truthful_utility`/
     `false_utility` must fall inside `[u_min, u_max]` / `[u_min, u_max]`
     respectively -- if not, something is inconsistent (a bug in this
     script, or in the mechanism), and the record is flagged
     `SANITY_CHECK_FAILED` loudly rather than silently dropped.

VERDICTS: `STRONG_ROBUST` (false_min > true_max -- profitable under EVERY
tiebreak), `WEAK` (false_max > true_min, but not strong -- profitable under
SOME tiebreak), `NEVER_ROBUST` (false_max <= true_min -- should be
impossible, since the witness was found via a fixed-seed run that DID show a
profitable deviation; flagged as a likely bug if it ever occurs),
`UNDETERMINED` (an ILP solve hit `--max-ilp-seconds` without resolving).

RESUMABILITY (required -- the real sweep runs for a long time in the
background and the user's machine may sleep or the process may be killed):
`per_witness.jsonl` is opened in append mode; each witness's full result is
written as ONE line, flushed, and `fsync`'d IMMEDIATELY after that witness
finishes -- never batched. On startup, every `witness_id` already present in
`per_witness.jsonl` is read first and skipped. Killing the process between
witnesses and rerunning the identical command therefore resumes cleanly: no
witness is re-solved, none is skipped. See
`tests/test_kidney_tiebreak_resumability.py` for the actual kill/resume
demonstration (not just a claim).

CLI:
    python3 scripts/kidney_tiebreak_robustness.py WITNESS_FILE [WITNESS_FILE ...] \\
        [--max-ilp-seconds SECONDS] [--out-dir DIR]
    python3 scripts/kidney_tiebreak_robustness.py --summarize [--out-dir DIR]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Mapping, Optional, Sequence

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from witness.kidney import (  # noqa: E402
    IlpTimeLimitExceeded,
    KidneyConfig,
    KidneyMarket,
    KidneyProfile,
    candidate_cycles,
    _select_maximum_cycles_ilp,
)

DEFAULT_OUT_DIR = PROJECT_ROOT / "results" / "kidney_tiebreak_robustness"
DEFAULT_MAX_ILP_SECONDS = 60.0


# ---------------------------------------------------------------------------
# Core ILP building blocks
# ---------------------------------------------------------------------------


def _central_c_star(
    market: KidneyMarket, reported_pool: Sequence[str], max_cycle_length: int, max_seconds: Optional[float]
):
    """`C*`: the maximum central cardinality over `reported_pool`, computed by
    literally calling `witness.kidney._select_maximum_cycles_ilp` -- the SAME
    function `clear_kidney_exchange` itself uses for central clearing under
    `TIEBREAK_MAX_CARDINALITY_ILP`. Returns `(c_star, central_candidates,
    elapsed_seconds)`, or `(None, central_candidates, elapsed_seconds)` if the
    solve could not prove optimality within `max_seconds`."""
    central_candidates = candidate_cycles(market, reported_pool, max_cycle_length)
    t0 = time.monotonic()
    try:
        selection = _select_maximum_cycles_ilp(market, central_candidates, max_seconds=max_seconds)
    except IlpTimeLimitExceeded:
        return None, central_candidates, time.monotonic() - t0
    elapsed = time.monotonic() - t0
    c_star = sum(len(c) for c in selection)
    return c_star, central_candidates, elapsed


def _local_max_cardinality(
    market: KidneyMarket, residual: Sequence[str], max_cycle_length: int, max_seconds: Optional[float]
):
    """The mechanism's own local-clearing rule (line 665-666 of `witness/
    kidney.py`), reused directly rather than reimplemented: maximum
    cardinality over `residual` via the SAME ILP call. Returns
    `(count, elapsed_seconds)`, or `(None, elapsed_seconds)` on a timeout."""
    local_candidates = candidate_cycles(market, residual, max_cycle_length)
    t0 = time.monotonic()
    try:
        selection = _select_maximum_cycles_ilp(market, local_candidates, max_seconds=max_seconds)
    except IlpTimeLimitExceeded:
        return None, time.monotonic() - t0
    elapsed = time.monotonic() - t0
    return sum(len(c) for c in selection), elapsed


def _footprint_feasible(
    market: KidneyMarket,
    central_candidates: "tuple[tuple[str, ...], ...]",
    h_report: Sequence[str],
    footprint: Sequence[str],
    c_star: int,
    max_seconds: Optional[float],
):
    """Does some vertex-disjoint selection of `central_candidates`, covering
    EXACTLY `c_star` pairs total (the proven central maximum), exist whose
    matched subset of `h_report` equals EXACTLY `footprint`? A plain
    feasibility ILP (no objective): CP-SAT proves OPTIMAL as soon as it finds
    any satisfying assignment (there is nothing to optimize), or INFEASIBLE
    if none exists, or -- within `max_seconds` -- may fail to resolve either
    way, in which case the caller must treat the whole witness as
    UNDETERMINED rather than silently guessing. Returns
    `(True/False/None, elapsed_seconds)`."""
    from ortools.sat.python import cp_model

    by_pair: "dict[str, list[int]]" = {}
    for i, cyc in enumerate(central_candidates):
        for p in cyc:
            by_pair.setdefault(p, []).append(i)

    footprint_set = set(footprint)
    # Fast, solver-free rejection: a report pair with NO candidate cycle at
    # all can never be matched, so any footprint claiming it is matched is
    # immediately infeasible -- skip building a model for it.
    for p in footprint_set:
        if not by_pair.get(p):
            return False, 0.0

    t0 = time.monotonic()
    model = cp_model.CpModel()
    x = [model.NewBoolVar(f"cycle_{i}") for i in range(len(central_candidates))]
    for p in sorted(by_pair):  # deterministic constraint-creation order, matching kidney.py's own convention
        idxs = by_pair[p]
        model.Add(sum(x[i] for i in idxs) <= 1)
    model.Add(sum(len(central_candidates[i]) * x[i] for i in range(len(central_candidates))) == c_star)
    for p in h_report:
        idxs = by_pair.get(p, [])
        target = 1 if p in footprint_set else 0
        if idxs:
            model.Add(sum(x[i] for i in idxs) == target)
        # else: p has no candidate cycle at all -- target must be 0, which is
        # automatically true (p can never be matched), nothing to constrain.

    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 0
    if max_seconds is not None:
        solver.parameters.max_time_in_seconds = max_seconds
    status = solver.Solve(model)
    elapsed = time.monotonic() - t0
    if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
        return True, elapsed
    if status == cp_model.INFEASIBLE:
        return False, elapsed
    return None, elapsed  # UNKNOWN: ran out of time without resolving


# ---------------------------------------------------------------------------
# Per-profile utility range
# ---------------------------------------------------------------------------


def utility_range_for_profile(
    market: KidneyMarket,
    report_map: Mapping[str, Sequence[str]],
    hospital: str,
    max_cycle_length: int,
    max_seconds: Optional[float],
) -> dict:
    """The range of `hospital`'s utility across every maximum-cardinality
    central tiebreak, for the given `report_map` (every hospital's report
    under ONE profile -- truthful or false). See the module docstring's
    METHOD for the four steps this implements. Returns a dict with `status`
    ('ok' or 'undetermined'), and on 'ok', `u_min`/`u_max`/
    `n_feasible_footprints`; always `solve_seconds`."""
    total_seconds = 0.0
    reported_pool = tuple(p for h in market.hospitals for p in report_map[h])
    c_star, central_candidates, t = _central_c_star(market, reported_pool, max_cycle_length, max_seconds)
    total_seconds += t
    if c_star is None:
        return {"status": "undetermined", "reason": "central C* solve timed out", "solve_seconds": total_seconds}

    h_report = tuple(report_map[hospital])
    owned = market.pairs_of(hospital)
    unreported = tuple(p for p in owned if p not in set(h_report))

    k = len(h_report)
    utilities: "list[int]" = []
    n_feasible = 0
    for mask in range(2 ** k):
        footprint = tuple(p for i, p in enumerate(h_report) if mask & (1 << i))
        feasible, t = _footprint_feasible(market, central_candidates, h_report, footprint, c_star, max_seconds)
        total_seconds += t
        if feasible is None:
            return {
                "status": "undetermined",
                "reason": f"footprint feasibility solve timed out for footprint={list(footprint)}",
                "solve_seconds": total_seconds,
            }
        if not feasible:
            continue
        n_feasible += 1

        residual_set = (set(h_report) - set(footprint)) | set(unreported)
        residual = tuple(p for p in market.pairs if p in residual_set)  # canonical market order
        local_count, t = _local_max_cardinality(market, residual, max_cycle_length, max_seconds)
        total_seconds += t
        if local_count is None:
            return {
                "status": "undetermined",
                "reason": f"local max-cardinality solve timed out for footprint={list(footprint)}",
                "solve_seconds": total_seconds,
            }
        utilities.append(len(footprint) + local_count)

    if not utilities:
        return {
            "status": "undetermined",
            "reason": "no feasible footprint found at all (possible bug -- the empty/full "
            "footprint should always be checked)",
            "solve_seconds": total_seconds,
        }

    return {
        "status": "ok",
        "u_min": min(utilities),
        "u_max": max(utilities),
        "c_star": c_star,
        "n_feasible_footprints": n_feasible,
        "solve_seconds": total_seconds,
    }


# ---------------------------------------------------------------------------
# Per-witness processing
# ---------------------------------------------------------------------------


def process_witness(d: Mapping, max_seconds: Optional[float], source_file: str) -> dict:
    market = KidneyMarket.from_dict(d["market"])
    truthful_profile = KidneyProfile.from_dict(d["truthful_profile"])
    config = KidneyConfig.from_dict(d["config"])
    max_cycle_length = config.max_cycle_length
    hospital = d["target_hospital"]
    false_report = tuple(d["false_report"])
    false_profile = truthful_profile.with_report(hospital, false_report)

    truthful_report_map = {h: truthful_profile.report(h) for h in market.hospitals}
    false_report_map = {h: false_profile.report(h) for h in market.hospitals}

    t0 = time.monotonic()
    true_range = utility_range_for_profile(market, truthful_report_map, hospital, max_cycle_length, max_seconds)
    false_range = utility_range_for_profile(market, false_report_map, hospital, max_cycle_length, max_seconds)
    solve_seconds = time.monotonic() - t0

    record = {
        "witness_id": d["witness_id"],
        "source_file": source_file,
        "K": max_cycle_length,
        "P": len(market.pairs),
        "hospital": hospital,
        "fixed_seed_truthful_utility": d["truthful_utility"],
        "fixed_seed_false_utility": d["false_utility"],
        "true_status": true_range["status"],
        "false_status": false_range["status"],
        "solve_seconds": round(solve_seconds, 3),
    }

    if true_range["status"] != "ok" or false_range["status"] != "ok":
        record["verdict"] = "UNDETERMINED"
        record["reason"] = true_range.get("reason") or false_range.get("reason")
        return record

    record["true_min"] = true_range["u_min"]
    record["true_max"] = true_range["u_max"]
    record["false_min"] = false_range["u_min"]
    record["false_max"] = false_range["u_max"]

    sanity_ok = (
        record["true_min"] <= record["fixed_seed_truthful_utility"] <= record["true_max"]
        and record["false_min"] <= record["fixed_seed_false_utility"] <= record["false_max"]
    )
    record["sanity_check_passed"] = sanity_ok
    if not sanity_ok:
        record["verdict"] = "SANITY_CHECK_FAILED"
        return record

    if record["false_min"] > record["true_max"]:
        record["verdict"] = "STRONG_ROBUST"
    elif record["false_max"] > record["true_min"]:
        record["verdict"] = "WEAK"
    else:
        # Should be impossible: the witness was found via a fixed-seed run
        # that DID show false_utility > truthful_utility, so at least ONE
        # tiebreak (the fixed-seed one) must have false > true.
        record["verdict"] = "NEVER_ROBUST"
    return record


# ---------------------------------------------------------------------------
# CLI: resumable batch runner + summarizer
# ---------------------------------------------------------------------------


def _load_done_ids(per_witness_path: Path) -> set:
    done = set()
    if not per_witness_path.exists():
        return done
    with open(per_witness_path, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                # A truncated last line from a killed process -- tolerate it;
                # that witness_id is simply not marked done and gets re-run.
                continue
            wid = rec.get("witness_id")
            if wid:
                done.add(wid)
    return done


def _priority_bucket(d: Mapping) -> int:
    config = d.get("config") or {}
    K = config.get("max_cycle_length", 2)
    P = len(d["market"]["pairs"])
    if K == 3 and P >= 250:
        return 0
    if K == 2 and P >= 250:
        return 1
    return 2


def _iter_witnesses(paths: Sequence[str]):
    for wf in paths:
        with open(wf, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                yield wf, json.loads(line)


def _run(witness_files: Sequence[str], max_seconds: Optional[float], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    per_witness_path = out_dir / "per_witness.jsonl"

    done_ids = _load_done_ids(per_witness_path)
    print(f"[kidney_tiebreak_robustness] {len(done_ids)} witness(es) already done, will be skipped", file=sys.stderr)

    all_witnesses = list(_iter_witnesses(witness_files))
    all_witnesses.sort(key=lambda pair: _priority_bucket(pair[1]))
    print(f"[kidney_tiebreak_robustness] {len(all_witnesses)} witness(es) loaded from {len(witness_files)} file(s)", file=sys.stderr)

    with open(per_witness_path, "a") as out_f:
        for wf, d in all_witnesses:
            wid = d["witness_id"]
            if wid in done_ids:
                continue
            K = (d.get("config") or {}).get("max_cycle_length", 2)
            P = len(d["market"]["pairs"])
            print(
                f"[kidney_tiebreak_robustness] processing {wid[:12]} (K={K}, P={P}, "
                f"hospital={d['target_hospital']!r}) from {wf}",
                file=sys.stderr,
            )
            record = process_witness(d, max_seconds, wf)
            out_f.write(json.dumps(record) + "\n")
            out_f.flush()
            os.fsync(out_f.fileno())
            done_ids.add(wid)
            print(
                f"[kidney_tiebreak_robustness]   -> {record['verdict']} "
                f"({record['solve_seconds']}s)",
                file=sys.stderr,
            )
            if record["verdict"] in ("SANITY_CHECK_FAILED", "NEVER_ROBUST"):
                print(f"[kidney_tiebreak_robustness] *** {record['verdict']} *** {json.dumps(record)}", file=sys.stderr)


def summarize(per_witness_path: Path, summary_path: Path) -> dict:
    counts: "dict[str, dict[str, int]]" = {}
    total = 0
    flagged: "list[str]" = []
    if per_witness_path.exists():
        with open(per_witness_path, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                total += 1
                key = f"K{rec.get('K')}_P{rec.get('P')}"
                verdict = rec.get("verdict", "UNKNOWN")
                bucket = counts.setdefault(key, {})
                bucket[verdict] = bucket.get(verdict, 0) + 1
                if verdict in ("SANITY_CHECK_FAILED", "NEVER_ROBUST"):
                    flagged.append(rec.get("witness_id", "<unknown>"))
    summary = {"total_processed": total, "by_K_P_bucket": counts, "flagged_witness_ids": flagged}
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2, sort_keys=True)
        f.write("\n")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("witness_files", nargs="*", help="One or more witnesses.jsonl files (KidneyWitness format)")
    parser.add_argument("--max-ilp-seconds", type=float, default=DEFAULT_MAX_ILP_SECONDS, help="Per-ILP-solve time limit (default: 60s)")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR), help="Output directory (default: results/kidney_tiebreak_robustness)")
    parser.add_argument("--summarize", action="store_true", help="Summarize whatever is in per_witness.jsonl into summary.json and exit")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)

    if args.summarize:
        out_dir.mkdir(parents=True, exist_ok=True)
        summary = summarize(out_dir / "per_witness.jsonl", out_dir / "summary.json")
        print(json.dumps(summary, indent=2, sort_keys=True))
        return

    if not args.witness_files:
        parser.error("at least one witness file is required unless --summarize is given")

    _run(args.witness_files, args.max_ilp_seconds, out_dir)
    # Always refresh summary.json after a run so it's never stale.
    summary = summarize(out_dir / "per_witness.jsonl", out_dir / "summary.json")
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
