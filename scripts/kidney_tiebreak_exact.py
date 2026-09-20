"""Exact joint-ILP tiebreak-robustness checker for saved `witness.search_kidney`
witnesses -- an independent re-derivation of, and cross-check against,
`scripts/kidney_tiebreak_robustness.py` (see that script's own module
docstring for the question it answers and its two-stage
enumerate-footprints-then-add-local method).

THE EXACT QUESTION (restated from the task spec this script implements):
for a witness (market, truthful profile, target hospital `h`, false_report,
false_utility), let `C*` be the maximum total matched pairs achievable
centrally over the reported pool (cycles length <= K). `U_true_max` is the
MAXIMUM, over every central packing of cardinality EXACTLY `C*`, of `h`'s
FINAL utility -- final utility = (h's own pairs matched centrally) + (h's
best local packing over h's own TRUE pairs left unmatched centrally). The
manipulation is `STRONG_ROBUST` iff `U_false_min > U_true_max`, where
`U_false_min` is the symmetric joint MINIMUM under the false report.

WHY A SEPARATE SCRIPT, NOT A REUSE OF `kidney_tiebreak_robustness.py`: that
script computes, per candidate footprint `S` of `h`'s report, an INDEPENDENT
local-clearing ILP call on `residual(S)`, then takes the max/min of
`|S| + LocalMax(residual(S))` over every feasible `S`. This is ALGEBRAICALLY
equivalent to a joint optimum only if the enumeration over footprints is
complete and each per-footprint local solve is genuinely independent of how
that footprint was reached centrally -- both true here, but the equivalence
is exactly the thing worth checking independently rather than assuming (see
REVIEWER.md: "never inherit a theorem across mechanisms," and more directly,
never inherit an equivalence you haven't independently verified).

IMPORTANT COURSE CORRECTION, FOUND BY THIS SCRIPT'S OWN VALIDATION SUITE: the
task this script was written against calls for "ONE JOINT CP-SAT
optimization over central cycle variables AND h's local cycle variables
simultaneously... Do the symmetric joint MINIMIZATION for the false report."
A literal reading -- one CP-SAT model per sense, with BOTH `x` (central) and
`y` (local) left free and `Minimize`d together for the false-report side --
is WRONG, and `tests/test_kidney_tiebreak_exact.py`'s randomized cross-check
against an independent brute force caught it directly (disagreed with the
true minimum on 17/240 random instances, e.g. joint-minimize found 0 where
the true minimum was 3). The reason: `witness.kidney`'s local stage is NEVER
adversarial -- `clear_kidney_exchange` always runs `h`'s local clearing to
ITS OWN maximum cardinality on whatever residual central clearing leaves,
unconditionally (lines 662-669). So the true quantity is a nested min-max,
`min_x [f(x) + max_y g(x,y)]` (the central tiebreak varies adversarially,
but local ALWAYS maximizes) -- NOT `min_{x,y} [f(x)+g(x,y)]` (both jointly
minimized), which is what a naive single free-`y` `Minimize` call computes,
and which lets the solver starve `y` below its true local maximum purely to
shrink the objective. For MAX this distinction does not matter -- a joint
max over `(x,y)` together IS `max_x [f(x) + max_y g(x,y)]`, since the two
orderings of a joint maximum always agree -- so `sense="max"` genuinely does
use one free-`y` joint CP-SAT model (`_joint_single_model_max`), fulfilling
the task's literal instruction there. For `sense="min"`,
`_min_via_footprint_enumeration` instead enumerates `h`'s report's candidate
footprints (small in every real witness -- see below) and, for each
FEASIBLE one, calls the mechanism's own local-max ILP directly (never a free
variable), then takes the true min over footprints -- see that function's
own docstring for the full argument. This is DELIBERATELY structurally
similar to `kidney_tiebreak_robustness.py`'s own method (independently
re-implemented here, not imported) because that decomposition is, per the
argument above, the mathematically correct one for a min over an
always-maximizing inner stage.

MODEL, for hospital `h` under one report_map (truthful, or false with only
`h`'s report swapped):

  1. `C*`: the maximum central cardinality over the FULL reported pool,
     via `witness.kidney._select_maximum_cycles_ilp` on
     `candidate_cycles(market, reported_pool, K)` -- the SAME function the
     mechanism itself uses for central clearing.
  2. `central_candidates`: every candidate cycle over the reported pool.
     `local_candidates`: every candidate cycle over `h`'s OWN TRUE pairs
     (`market.pairs_of(h)` -- includes pairs `h` withheld from its report;
     central clearing can never touch those, but local clearing can).
  3. MAX (`_joint_single_model_max`): one CP-SAT model, `x_i` per central
     candidate, `y_j` per local candidate. For every pair `p` touched by any
     central or local candidate: `sum(x_i : p in central_i) + sum(y_j : p in
     local_j) <= 1` (the SAME "at most one cycle" constraint central
     clearing uses on its own, extended to also forbid a pair being claimed
     by both a central AND a local cycle -- exactly the mechanism's own
     "every pair is used in at most one cycle, central or local, never
     both," `witness/kidney.py` line 69). Central total cardinality is
     pinned: `sum(len(central_i) * x_i) == C*`. Objective:
     `Maximize(sum(x_i * |central_i ∩ h's pairs|) + sum(y_j * len(local_j)))`
     -- exactly `h`'s final utility, since the disjointness constraint above
     guarantees every one of `h`'s own pairs is counted at most once.
     MIN (`_min_via_footprint_enumeration`): enumerate every subset `S` of
     `h`'s REPORT; for each, a feasibility-only ILP (`_footprint_feasible`)
     checks whether some central selection hits `C*` with `h`'s matched
     report-pairs exactly `S`; for every feasible `S`, `LocalMax(residual(S))`
     is computed by the mechanism's own ILP (`_select_maximum_cycles_ilp`);
     `U_false_min = min_S (|S| + LocalMax(residual(S)))`.
  4. Every solve uses `num_search_workers=1`, `random_seed=0`, matching
     `witness.kidney`'s own determinism discipline. A time-limited solve
     that fails to prove optimality (or feasibility, for the per-footprint
     checks) is recorded UNDETERMINED, never guessed.

RESUMABILITY: `per_witness.jsonl` under `results/kidney_tiebreak_exact/` is
opened in append mode; each witness's result is written as ONE line,
flushed and `fsync`'d immediately. On startup every `witness_id` already
present is skipped -- identical discipline to `kidney_tiebreak_robustness.py`
(see that script's own docstring), independently re-implemented here rather
than imported, since this script owns its own output directory.

RECONCILIATION: after (or during, via `--reconcile-only`) a run, this script
also diffs its own verdicts against
`results/kidney_tiebreak_robustness/per_witness.jsonl` by `witness_id` and
writes `results/kidney_tiebreak_exact/reconciliation.json` -- every
witness_id present in both files, whether the verdicts agree, and (for
disagreements) both scripts' raw numbers side by side so a human can judge
which is right without re-running anything.

CLI:
    python3 scripts/kidney_tiebreak_exact.py WITNESS_FILE [WITNESS_FILE ...] \\
        [--max-ilp-seconds SECONDS] [--out-dir DIR] [--k KIDNEY_K_FILTER] [--min-p P]
    python3 scripts/kidney_tiebreak_exact.py --summarize [--out-dir DIR]
    python3 scripts/kidney_tiebreak_exact.py --reconcile-only [--out-dir DIR]
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

DEFAULT_OUT_DIR = PROJECT_ROOT / "results" / "kidney_tiebreak_exact"
DEFAULT_MAX_ILP_SECONDS = 600.0
OLD_PER_WITNESS_PATH = PROJECT_ROOT / "results" / "kidney_tiebreak_robustness" / "per_witness.jsonl"


# ---------------------------------------------------------------------------
# Core: central-only C*, then the joint model
# ---------------------------------------------------------------------------


from witness.runlog import begin_run


def central_c_star(
    market: KidneyMarket, reported_pool: Sequence[str], max_cycle_length: int, max_seconds: Optional[float]
):
    """`C*`: the maximum central cardinality over `reported_pool`, via the
    SAME `_select_maximum_cycles_ilp` the mechanism itself uses centrally.
    Returns `(c_star, central_candidates, elapsed_seconds)`, or
    `(None, central_candidates, elapsed_seconds)` on a proven-optimality
    timeout."""
    central_candidates = candidate_cycles(market, reported_pool, max_cycle_length)
    t0 = time.monotonic()
    try:
        selection = _select_maximum_cycles_ilp(market, central_candidates, max_seconds=max_seconds)
    except IlpTimeLimitExceeded:
        return None, central_candidates, time.monotonic() - t0
    elapsed = time.monotonic() - t0
    c_star = sum(len(c) for c in selection)
    return c_star, central_candidates, elapsed


#: Guard on `2**len(h_report)` for the footprint-enumeration MIN path (see
#: `_min_via_footprint_enumeration`'s own docstring for why MIN cannot use a
#: single free-`y` joint model). Every real witness checked has
#: `len(h_report) <= 7` (see the reconciliation notes in this module's
#: docstring / the final report), so this is a generous, rarely-hit ceiling,
#: not a tight operating point.
MAX_FOOTPRINT_ENUM = 2 ** 22


def _joint_single_model_max(
    market: KidneyMarket,
    report_map: Mapping[str, Sequence[str]],
    hospital: str,
    max_cycle_length: int,
    max_seconds: Optional[float],
) -> dict:
    """The genuine one-shot joint CP-SAT MAXIMIZATION: central cycle
    variables `x` and `hospital`'s local cycle variables `y` in the SAME
    model, `Maximize(central-own + local-own)` subject to (a) global
    disjointness across every pair either stage's variables touch and (b)
    central total cardinality == `C*`. This is exactly right for MAX
    because maximizing `x` and `y` TOGETHER is mathematically identical to
    `max_x [f(x) + max_y g(x,y)]` -- the two orderings of a joint max always
    agree. (The mirror is NOT true for MIN -- see
    `_min_via_footprint_enumeration`'s docstring.) Returns a dict with
    `status` ("ok" or "undetermined") and, on "ok", `value`/`c_star`/
    `n_central_candidates`/`n_local_candidates`; always `solve_seconds`."""
    from ortools.sat.python import cp_model

    total_seconds = 0.0
    reported_pool = tuple(p for h in market.hospitals for p in report_map[h])
    c_star, central_candidates, t = central_c_star(market, reported_pool, max_cycle_length, max_seconds)
    total_seconds += t
    if c_star is None:
        return {"status": "undetermined", "reason": "central C* solve timed out", "solve_seconds": total_seconds}

    owned = market.pairs_of(hospital)
    owned_set = set(owned)
    local_candidates = candidate_cycles(market, owned, max_cycle_length)

    t0 = time.monotonic()
    model = cp_model.CpModel()
    x = [model.NewBoolVar(f"central_{i}") for i in range(len(central_candidates))]
    y = [model.NewBoolVar(f"local_{j}") for j in range(len(local_candidates))]

    central_by_pair: "dict[str, list[int]]" = {}
    for i, cyc in enumerate(central_candidates):
        for p in cyc:
            central_by_pair.setdefault(p, []).append(i)
    local_by_pair: "dict[str, list[int]]" = {}
    for j, cyc in enumerate(local_candidates):
        for p in cyc:
            local_by_pair.setdefault(p, []).append(j)

    all_pairs = sorted(set(central_by_pair) | set(local_by_pair))
    for p in all_pairs:  # deterministic constraint-creation order
        c_idxs = central_by_pair.get(p, [])
        l_idxs = local_by_pair.get(p, [])
        # Every pair touched by local candidates is, by construction, one of
        # `hospital`'s own pairs -- local clearing never sees another
        # hospital's pairs (witness/kidney.py's own residual rule). A pair
        # not owned by `hospital` therefore never has an `l_idxs` term here;
        # this loop still enforces plain central at-most-one for it.
        terms = [x[i] for i in c_idxs] + [y[j] for j in l_idxs]
        if terms:
            model.Add(sum(terms) <= 1)

    model.Add(sum(len(central_candidates[i]) * x[i] for i in range(len(central_candidates))) == c_star)

    own_central_weight = [sum(1 for p in cyc if p in owned_set) for cyc in central_candidates]
    objective_terms = [own_central_weight[i] * x[i] for i in range(len(central_candidates)) if own_central_weight[i]]
    objective_terms += [len(local_candidates[j]) * y[j] for j in range(len(local_candidates))]
    objective = sum(objective_terms) if objective_terms else 0
    model.Maximize(objective)

    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 0
    if max_seconds is not None:
        solver.parameters.max_time_in_seconds = max_seconds
    status = solver.Solve(model)
    elapsed = time.monotonic() - t0
    total_seconds += elapsed

    if status != cp_model.OPTIMAL:
        if max_seconds is not None and status in (cp_model.FEASIBLE, cp_model.UNKNOWN):
            return {
                "status": "undetermined",
                "reason": f"joint max solve did not prove optimality within max_seconds={max_seconds} "
                f"(status={solver.StatusName(status)!r})",
                "solve_seconds": total_seconds,
            }
        raise RuntimeError(
            f"_joint_single_model_max: solver did not prove optimality (status={solver.StatusName(status)!r}), "
            f"and no max_seconds was given, so this is a genuine failure, not a timeout"
        )

    value = int(round(solver.ObjectiveValue()))
    return {
        "status": "ok",
        "value": value,
        "c_star": c_star,
        "n_central_candidates": len(central_candidates),
        "n_local_candidates": len(local_candidates),
        "solve_seconds": total_seconds,
    }


def _footprint_feasible(
    market: KidneyMarket,
    central_candidates: "tuple[tuple[str, ...], ...]",
    h_report: Sequence[str],
    footprint: Sequence[str],
    c_star: int,
    max_seconds: Optional[float],
):
    """Plain feasibility ILP: does some vertex-disjoint selection of
    `central_candidates`, covering EXACTLY `c_star` pairs total, exist whose
    matched subset of `h_report` equals EXACTLY `footprint`? Returns
    `(True/False/None, elapsed_seconds)` -- `None` means the solver could not
    resolve feasibility either way within `max_seconds`."""
    from ortools.sat.python import cp_model

    by_pair: "dict[str, list[int]]" = {}
    for i, cyc in enumerate(central_candidates):
        for p in cyc:
            by_pair.setdefault(p, []).append(i)

    footprint_set = set(footprint)
    for p in footprint_set:
        if not by_pair.get(p):
            return False, 0.0  # a pair with no candidate cycle at all can never be matched

    t0 = time.monotonic()
    model = cp_model.CpModel()
    x = [model.NewBoolVar(f"cycle_{i}") for i in range(len(central_candidates))]
    for p in sorted(by_pair):
        idxs = by_pair[p]
        model.Add(sum(x[i] for i in idxs) <= 1)
    model.Add(sum(len(central_candidates[i]) * x[i] for i in range(len(central_candidates))) == c_star)
    for p in h_report:
        idxs = by_pair.get(p, [])
        target = 1 if p in footprint_set else 0
        if idxs:
            model.Add(sum(x[i] for i in idxs) == target)

    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 0
    if max_seconds is not None:
        solver.parameters.max_time_in_seconds = max_seconds
    status = solver.Solve(model)
    elapsed = time.monotonic() - t0
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return True, elapsed
    if status == cp_model.INFEASIBLE:
        return False, elapsed
    return None, elapsed


def _min_via_footprint_enumeration(
    market: KidneyMarket,
    report_map: Mapping[str, Sequence[str]],
    hospital: str,
    max_cycle_length: int,
    max_seconds: Optional[float],
) -> dict:
    """The correct joint computation of `hospital`'s MINIMUM final utility
    over every central packing of cardinality `C*`.

    WHY THIS IS NOT A SINGLE FREE-`y` CP-SAT MINIMIZATION: the mechanism's
    local stage is NEVER adversarial -- `clear_kidney_exchange` (witness/
    kidney.py lines 662-669) always runs local clearing to ITS OWN maximum
    cardinality on whatever residual central clearing leaves, unconditionally.
    So the true question is `min_x [f(x) + max_y g(x,y)]` (central tiebreak
    varies adversarially; local ALWAYS maximizes) -- a nested min-max, NOT
    `min_{x,y} [f(x) + g(x,y)]` (both jointly minimized), which is what a
    naive single `model.Minimize(central-own + local-own)` call computes. A
    single free-`y` minimize lets the solver starve `y` below its true
    maximum purely to make the objective look smaller -- caught directly by
    `tests/test_kidney_tiebreak_exact.py`'s randomized cross-check against an
    independent brute force (a single joint `Minimize` call disagreed with
    the brute-force minimum on 17/240 random instances before this function
    replaced it; see that test file's git history / the accompanying report
    for the concrete counterexamples, e.g. joint-min 0 vs true 3).

    METHOD (mirrors `scripts/kidney_tiebreak_robustness.py`'s own approach,
    independently re-implemented here rather than imported, since MIN
    genuinely requires decomposing by footprint -- there is no shortcut):
    enumerate every subset `S` of `hospital`'s OWN REPORT (bounded by
    `MAX_FOOTPRINT_ENUM`; every real witness has `len(h_report) <= 7`, so
    this is always a small enumeration in practice), check central
    feasibility of `S` at cardinality exactly `C*` via `_footprint_feasible`,
    and for every FEASIBLE `S` compute `|S| + LocalMax(residual(S))` via the
    mechanism's own ILP call (`_select_maximum_cycles_ilp` on
    `candidate_cycles` over the residual) -- this LocalMax computation is a
    PLAIN maximization, never adversarially constrained, because it IS the
    mechanism's own deterministic behavior, not a free variable. The minimum
    over every feasible `S` is `U_false_min`. Because `residual(S)` is fully
    determined by `S` alone (never by which specific central cycles achieved
    it -- local clearing only ever looks at which of `hospital`'s own pairs
    remain, per witness/kidney.py's own residual rule), this per-footprint
    decomposition is exact, not an approximation of the joint optimum."""
    total_seconds = 0.0
    reported_pool = tuple(p for h in market.hospitals for p in report_map[h])
    c_star, central_candidates, t = central_c_star(market, reported_pool, max_cycle_length, max_seconds)
    total_seconds += t
    if c_star is None:
        return {"status": "undetermined", "reason": "central C* solve timed out", "solve_seconds": total_seconds}

    h_report = tuple(report_map[hospital])
    owned = market.pairs_of(hospital)
    unreported = tuple(p for p in owned if p not in set(h_report))

    k = len(h_report)
    if 2 ** k > MAX_FOOTPRINT_ENUM:
        return {
            "status": "undetermined",
            "reason": f"hospital {hospital!r}'s report has {k} pairs (2**{k} footprints) exceeding "
            f"MAX_FOOTPRINT_ENUM={MAX_FOOTPRINT_ENUM}",
            "solve_seconds": total_seconds,
        }

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
        local_candidates = candidate_cycles(market, residual, max_cycle_length)
        t0 = time.monotonic()
        try:
            local_selection = _select_maximum_cycles_ilp(market, local_candidates, max_seconds=max_seconds)
        except IlpTimeLimitExceeded:
            total_seconds += time.monotonic() - t0
            return {
                "status": "undetermined",
                "reason": f"local max-cardinality solve timed out for footprint={list(footprint)}",
                "solve_seconds": total_seconds,
            }
        total_seconds += time.monotonic() - t0
        local_count = sum(len(c) for c in local_selection)
        utilities.append(len(footprint) + local_count)

    if not utilities:
        return {
            "status": "undetermined",
            "reason": "no feasible footprint found at all (possible bug -- the empty footprint should always be checked)",
            "solve_seconds": total_seconds,
        }

    return {
        "status": "ok",
        "value": min(utilities),
        "c_star": c_star,
        "n_central_candidates": len(central_candidates),
        "n_feasible_footprints": n_feasible,
        "solve_seconds": total_seconds,
    }


def joint_extreme(
    market: KidneyMarket,
    report_map: Mapping[str, Sequence[str]],
    hospital: str,
    max_cycle_length: int,
    max_seconds: Optional[float],
    sense: str,
) -> dict:
    """Dispatch: `sense="max"` uses the genuine one-shot joint CP-SAT
    (`_joint_single_model_max`, valid because a joint max IS `max_x max_y`);
    `sense="min"` uses `_min_via_footprint_enumeration` (a literal single
    free-`y` joint minimize is WRONG -- see that function's own docstring
    for the proof and the concrete counterexamples that caught it). Both
    return the same dict shape: `status`, and on "ok", `value`/`c_star`/
    `solve_seconds`."""
    assert sense in ("max", "min")
    if sense == "max":
        return _joint_single_model_max(market, report_map, hospital, max_cycle_length, max_seconds)
    return _min_via_footprint_enumeration(market, report_map, hospital, max_cycle_length, max_seconds)


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
    true_max = joint_extreme(market, truthful_report_map, hospital, max_cycle_length, max_seconds, "max")
    false_min = joint_extreme(market, false_report_map, hospital, max_cycle_length, max_seconds, "min")
    solve_seconds = time.monotonic() - t0

    record = {
        "witness_id": d["witness_id"],
        "source_file": source_file,
        "K": max_cycle_length,
        "P": len(market.pairs),
        "hospital": hospital,
        "fixed_seed_truthful_utility": d["truthful_utility"],
        "fixed_seed_false_utility": d["false_utility"],
        "true_max_status": true_max["status"],
        "false_min_status": false_min["status"],
        "solve_seconds": round(solve_seconds, 3),
    }

    if true_max["status"] != "ok" or false_min["status"] != "ok":
        record["verdict"] = "UNDETERMINED"
        record["reason"] = true_max.get("reason") or false_min.get("reason")
        return record

    record["c_star_true"] = true_max["c_star"]
    record["c_star_false"] = false_min["c_star"]
    record["U_true_max"] = true_max["value"]
    record["U_false_min"] = false_min["value"]

    sanity_ok = (
        record["fixed_seed_truthful_utility"] <= record["U_true_max"]
        and record["fixed_seed_false_utility"] >= record["U_false_min"]
    )
    record["sanity_check_passed"] = sanity_ok
    if not sanity_ok:
        record["verdict"] = "SANITY_CHECK_FAILED"
        return record

    if record["U_false_min"] > record["U_true_max"]:
        record["verdict"] = "STRONG_ROBUST"
    elif record["fixed_seed_false_utility"] > record["fixed_seed_truthful_utility"]:
        # The fixed-seed run DID show a profitable deviation (that's why this
        # is a saved witness at all) but it is not robust to every tiebreak.
        record["verdict"] = "WEAK"
    else:
        record["verdict"] = "NEVER_ROBUST"  # should be impossible; flagged below
    return record


# ---------------------------------------------------------------------------
# CLI: resumable batch runner + summarizer + reconciliation
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


def _run(
    witness_files: Sequence[str],
    max_seconds: Optional[float],
    out_dir: Path,
    k_filter: Optional[int],
    min_p: Optional[int],
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    # Provenance + exclusive lock (witness/runlog.py). These runs are
    # routinely killed mid-flight; begin_run records that as "killed"
    # rather than leaving the directory looking merely sparse.
    begin_run(str(out_dir), note="exact joint-ILP tiebreak check")
    per_witness_path = out_dir / "per_witness.jsonl"

    done_ids = _load_done_ids(per_witness_path)
    print(f"[kidney_tiebreak_exact] {len(done_ids)} witness(es) already done, will be skipped", file=sys.stderr)

    all_witnesses = list(_iter_witnesses(witness_files))
    if k_filter is not None:
        all_witnesses = [(wf, d) for wf, d in all_witnesses if (d.get("config") or {}).get("max_cycle_length", 2) == k_filter]
    if min_p is not None:
        all_witnesses = [(wf, d) for wf, d in all_witnesses if len(d["market"]["pairs"]) >= min_p]
    all_witnesses.sort(key=lambda pair: _priority_bucket(pair[1]))
    print(f"[kidney_tiebreak_exact] {len(all_witnesses)} witness(es) selected from {len(witness_files)} file(s)", file=sys.stderr)

    with open(per_witness_path, "a") as out_f:
        for wf, d in all_witnesses:
            wid = d["witness_id"]
            if wid in done_ids:
                continue
            K = (d.get("config") or {}).get("max_cycle_length", 2)
            P = len(d["market"]["pairs"])
            print(
                f"[kidney_tiebreak_exact] processing {wid[:12]} (K={K}, P={P}, "
                f"hospital={d['target_hospital']!r}) from {wf}",
                file=sys.stderr,
            )
            t0 = time.monotonic()
            record = process_witness(d, max_seconds, wf)
            wall = time.monotonic() - t0
            out_f.write(json.dumps(record) + "\n")
            out_f.flush()
            os.fsync(out_f.fileno())
            done_ids.add(wid)
            print(
                f"[kidney_tiebreak_exact]   -> {record['verdict']} (solve={record['solve_seconds']}s, wall={wall:.1f}s)",
                file=sys.stderr,
            )
            if record["verdict"] in ("SANITY_CHECK_FAILED", "NEVER_ROBUST"):
                print(f"[kidney_tiebreak_exact] *** {record['verdict']} *** {json.dumps(record)}", file=sys.stderr)


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


def _load_records(path: Path) -> "dict[str, dict]":
    out = {}
    if not path.exists():
        return out
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            wid = rec.get("witness_id")
            if wid:
                out[wid] = rec
    return out


def reconcile(exact_path: Path, old_path: Path, out_path: Path) -> dict:
    """Diff this script's verdicts against `kidney_tiebreak_robustness.py`'s
    saved `per_witness.jsonl`, by `witness_id`. Written for a human to judge
    each disagreement -- both scripts' raw numbers are included side by
    side, never just a verdict label."""
    exact = _load_records(exact_path)
    old = _load_records(old_path)
    common = sorted(set(exact) & set(old))
    agreements = []
    disagreements = []
    for wid in common:
        e, o = exact[wid], old[wid]
        if e.get("verdict") == o.get("verdict"):
            agreements.append(wid)
        else:
            disagreements.append(
                {
                    "witness_id": wid,
                    "K": e.get("K"),
                    "P": e.get("P"),
                    "hospital": e.get("hospital"),
                    "exact_verdict": e.get("verdict"),
                    "old_verdict": o.get("verdict"),
                    "exact": {
                        "U_true_max": e.get("U_true_max"),
                        "U_false_min": e.get("U_false_min"),
                    },
                    "old": {
                        "true_min": o.get("true_min"),
                        "true_max": o.get("true_max"),
                        "false_min": o.get("false_min"),
                        "false_max": o.get("false_max"),
                    },
                }
            )
    result = {
        "n_common": len(common),
        "n_only_in_exact": len(set(exact) - set(old)),
        "n_only_in_old": len(set(old) - set(exact)),
        "n_agreements": len(agreements),
        "n_disagreements": len(disagreements),
        "disagreements": disagreements,
    }
    with open(out_path, "w") as f:
        json.dump(result, f, indent=2, sort_keys=True)
        f.write("\n")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("witness_files", nargs="*", help="One or more witnesses.jsonl files (KidneyWitness format)")
    parser.add_argument("--max-ilp-seconds", type=float, default=DEFAULT_MAX_ILP_SECONDS, help="Per-ILP-solve time limit (default: 600s)")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR), help="Output directory (default: results/kidney_tiebreak_exact)")
    parser.add_argument("--k", type=int, default=None, help="Only process witnesses with this max_cycle_length")
    parser.add_argument("--min-p", type=int, default=None, help="Only process witnesses with P >= this")
    parser.add_argument("--summarize", action="store_true", help="Summarize per_witness.jsonl into summary.json and exit")
    parser.add_argument("--reconcile-only", action="store_true", help="Only (re)write reconciliation.json against the old script's results and exit")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)

    if args.reconcile_only:
        out_dir.mkdir(parents=True, exist_ok=True)
        result = reconcile(out_dir / "per_witness.jsonl", OLD_PER_WITNESS_PATH, out_dir / "reconciliation.json")
        print(json.dumps(result, indent=2, sort_keys=True))
        return

    if args.summarize:
        out_dir.mkdir(parents=True, exist_ok=True)
        summary = summarize(out_dir / "per_witness.jsonl", out_dir / "summary.json")
        print(json.dumps(summary, indent=2, sort_keys=True))
        return

    if not args.witness_files:
        parser.error("at least one witness file is required unless --summarize/--reconcile-only is given")

    _run(args.witness_files, args.max_ilp_seconds, out_dir, args.k, args.min_p)
    summary = summarize(out_dir / "per_witness.jsonl", out_dir / "summary.json")
    print(json.dumps(summary, indent=2, sort_keys=True))
    reconciliation = reconcile(out_dir / "per_witness.jsonl", OLD_PER_WITNESS_PATH, out_dir / "reconciliation.json")
    print(json.dumps(reconciliation, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
