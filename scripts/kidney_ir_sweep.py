#!/usr/bin/env python3
"""Two measurements for the IR-constrained kidney-exchange mechanism
(`witness.kidney_ir`), against the SAME real compatibility-graph benchmark
(`witness.kidney_real_data`, Pansart et al. 2022) and the SAME loading
convention `scripts/kidney_real_data_sweep.py` uses -- see that script's own
docstring for what is real (the compatibility graph) and what is a declared
synthetic choice (the hospital-ownership partition).

(A) EFFICIENCY COST: at each (P, K), the TOTAL matched pairs under plain
    max-cardinality clearing (`witness.kidney.clear_kidney_exchange`, ILP
    tiebreak) vs under `witness.kidney_ir.ir_clear_kidney_exchange`, both on
    the SAME truthful profile -- absolute and relative loss per instance,
    aggregated to a mean per (P, K) in the summary.

(B) DOES IR REMOVE THE MANIPULATIONS: `witness.kidney_ir.find_hospital_
    manipulation_ir` (this project's own exhaustive re-derivation of the
    withholding search against the IR mechanism -- see that module's
    docstring for why it is NOT `witness.search_kidney.find_hospital_
    manipulation`, which is hardwired to plain clearing) run over the same
    real instances, at the SAME `pairs_per_hospital` convention as
    `results/kidney_real_data_sweep_v2/summary.json` (K=2) and
    `results/kidney_k3_real_sweep_v2/summary.json` (K=3) so the deviation
    RATE is directly comparable. Every found manipulation is independently
    re-verified in a fresh subprocess (`witness.kidney_ir.verify_in_
    subprocess`) before being counted; a verification failure is recorded
    separately, never silently dropped.

RESUMABLE, INCREMENTAL: every per-instance record is written (flush+fsync)
to a JSONL file the moment it's computed, tagged with a stable `id`. On
startup this script reads the `id`s already present in each output file and
skips them -- safe to Ctrl-C or let the laptop sleep and resume later with
the identical command. `summary.json` is always REBUILT from the on-disk
JSONL files (never accumulated in memory across a resume), so it is correct
even after an interrupted run; pass `--summary-only` to just rebuild it
without doing any more work.

PRIORITY: per the task that spawned this module, K=3 P=250 is the headline
regime (that is where the plain mechanism's own withholding-manipulation
rate is highest, per `results/kidney_k3_real_sweep_v2/summary.json`), then
K=3 P=100/50, then K=2. The default `--jobs` order reflects that; each job
is independent and fully resumable on its own.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from witness.kidney import (
    TIEBREAK_MAX_CARDINALITY_ILP,
    IlpTimeLimitExceeded,
    KidneyConfig,
    clear_kidney_exchange,
)
from witness.kidney_ir import (
    find_hospital_manipulation_ir,
    ir_clear_kidney_exchange,
    standalone_all,
    verify_in_subprocess,
)
from witness.kidney_real_data import load_real_kidney_market, real_instances_for_p

#: Default job priority: (max_cycle_length, p, draws_per_member). K=3 P=250
#: first (the headline regime), then K=3 P=100/50, then K=2 -- see module
#: docstring. Draws-per-member kept modest relative to the plain sweeps
#: (`results/kidney_k3_real_sweep_v2` used 20/20/10) because the IR joint
#: CP-SAT model (central + every hospital's local variables + n_hospitals
#: extra constraints) is strictly heavier per solve than plain clearing, and
#: `find_hospital_manipulation_ir` needs up to `2**k - 1` such solves per
#: hospital-check -- these are STARTING defaults, adjustable via --draws.
DEFAULT_JOBS = (
    (3, 250, 8),
    (3, 100, 15),
    (3, 50, 20),
    (2, 50, 20),
    (2, 100, 15),
    (2, 250, 8),
)


def _read_existing_ids(path: str) -> set:
    ids = set()
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if "id" in d:
                    ids.add(d["id"])
    return ids


def _write_record(f, record: dict) -> None:
    f.write(json.dumps(record) + "\n")
    f.flush()
    os.fsync(f.fileno())


def run_job(
    p: int,
    k: int,
    draws_per_member: int,
    pairs_per_hospital: int,
    ownership_seed: str,
    max_ilp_seconds,
    eff_f, eff_ids,
    dev_f, dev_ids,
    wit_f,
    fail_f,
) -> dict:
    members = real_instances_for_p(p)
    n_hospitals = max(1, round(p / pairs_per_hospital))

    n_eff_done = n_eff_skipped = 0
    n_dev_checks = n_dev_confirmed = n_dev_verification_failures = n_dev_skipped = 0
    t0 = time.perf_counter()

    for member in members:
        for draw in range(draws_per_member):
            base_id = f"p{p}_k{k}_{member}_d{draw}"
            market, profile, meta = load_real_kidney_market(
                member, n_hospitals=n_hospitals, ownership_seed=ownership_seed, ownership_draw_index=draw,
            )

            standalone_values = None
            eff_id = base_id + "_eff"
            if eff_id not in eff_ids:
                try:
                    if standalone_values is None:
                        standalone_values = standalone_all(market, k, max_seconds=max_ilp_seconds)
                    plain_cfg = KidneyConfig(
                        tiebreak_policy=TIEBREAK_MAX_CARDINALITY_ILP, max_cycle_length=k,
                        max_ilp_seconds=max_ilp_seconds,
                    )
                    plain = clear_kidney_exchange(market, profile, plain_cfg)
                    ir_res = ir_clear_kidney_exchange(market, profile, k, max_ilp_seconds, standalone_values)
                    plain_total = len(plain.matched_pairs)
                    record = {
                        "id": eff_id, "p": p, "k": k, "member": member, "draw": draw,
                        "n_hospitals": n_hospitals, "plain_total": plain_total,
                        "ir_feasible": ir_res.ir_feasible,
                        "ir_total": len(ir_res.matched_pairs) if ir_res.ir_feasible else None,
                        "abs_loss": (plain_total - len(ir_res.matched_pairs)) if ir_res.ir_feasible else None,
                        "rel_loss": (
                            (plain_total - len(ir_res.matched_pairs)) / plain_total
                            if ir_res.ir_feasible and plain_total else None
                        ),
                    }
                    _write_record(eff_f, record)
                    eff_ids.add(eff_id)
                    n_eff_done += 1
                except IlpTimeLimitExceeded as exc:
                    n_eff_skipped += 1
                    print(f"  [efficiency skip: too hard] {eff_id}: {exc}", file=sys.stderr)

            dev_id = base_id + "_dev"
            if dev_id not in dev_ids:
                hospital = market.hospitals[draw % n_hospitals]
                try:
                    if standalone_values is None:
                        standalone_values = standalone_all(market, k, max_seconds=max_ilp_seconds)
                    witness, stats = find_hospital_manipulation_ir(
                        market, profile, hospital, k, max_ilp_seconds, standalone_values=standalone_values,
                    )
                    confirmed = False
                    verified_ok = None
                    if witness is not None:
                        wd = witness.to_dict()
                        wd["_real_data_provenance"] = meta.to_dict()
                        ok, reasons = verify_in_subprocess(witness.to_dict())
                        verified_ok = ok
                        if ok:
                            confirmed = True
                            _write_record(wit_f, wd)
                            n_dev_confirmed += 1
                        else:
                            n_dev_verification_failures += 1
                            _write_record(fail_f, {"witness": wd, "reasons": list(reasons)})
                    record = {
                        "id": dev_id, "p": p, "k": k, "member": member, "draw": draw,
                        "n_hospitals": n_hospitals, "hospital": hospital,
                        "found": witness is not None, "confirmed": confirmed, "verified_ok": verified_ok,
                        "n_reports_tried": stats.n_reports_tried, "n_infeasible": stats.n_infeasible,
                        "truthful_ir_feasible": stats.truthful_ir_feasible,
                    }
                    _write_record(dev_f, record)
                    dev_ids.add(dev_id)
                    n_dev_checks += 1
                except IlpTimeLimitExceeded as exc:
                    n_dev_skipped += 1
                    print(f"  [deviation skip: too hard] {dev_id}: {exc}", file=sys.stderr)

    wall = time.perf_counter() - t0
    return {
        "p": p, "k": k, "n_hospitals": n_hospitals, "n_real_members": len(members),
        "draws_per_member": draws_per_member, "wall_seconds_this_invocation": wall,
        "n_efficiency_done_this_invocation": n_eff_done, "n_efficiency_skipped_this_invocation": n_eff_skipped,
        "n_deviation_checks_this_invocation": n_dev_checks,
        "n_deviation_skipped_this_invocation": n_dev_skipped,
    }


def build_summary(out_dir: str, jobs, pairs_per_hospital: int, ownership_seed: str) -> dict:
    """Rebuilds the full summary purely from the on-disk JSONL files -- safe
    to call after a partial/interrupted/resumed run, never from in-memory
    state accumulated across a single invocation."""
    eff_path = os.path.join(out_dir, "efficiency.jsonl")
    dev_path = os.path.join(out_dir, "deviation_checks.jsonl")
    fail_path = os.path.join(out_dir, "verification_failures.jsonl")

    eff_records = []
    if os.path.exists(eff_path):
        with open(eff_path, "r", encoding="utf-8") as f:
            eff_records = [json.loads(line) for line in f if line.strip()]
    dev_records = []
    if os.path.exists(dev_path):
        with open(dev_path, "r", encoding="utf-8") as f:
            dev_records = [json.loads(line) for line in f if line.strip()]
    n_verification_failures_total = 0
    if os.path.exists(fail_path):
        with open(fail_path, "r", encoding="utf-8") as f:
            n_verification_failures_total = sum(1 for line in f if line.strip())

    per_job = []
    for k, p, _draws in jobs:
        eff_here = [r for r in eff_records if r["p"] == p and r["k"] == k]
        dev_here = [r for r in dev_records if r["p"] == p and r["k"] == k]
        feasible_here = [r for r in eff_here if r["ir_feasible"]]
        infeasible_here = [r for r in eff_here if not r["ir_feasible"]]
        rel_losses_here = [r["rel_loss"] for r in feasible_here if r["rel_loss"] is not None]
        entry = {
            "p": p, "k": k,
            "n_efficiency_instances": len(eff_here),
            "n_efficiency_ir_infeasible": len(infeasible_here),
            "mean_plain_total": (sum(r["plain_total"] for r in eff_here) / len(eff_here)) if eff_here else None,
            "mean_ir_total_when_feasible": (
                sum(r["ir_total"] for r in feasible_here) / len(feasible_here) if feasible_here else None
            ),
            "mean_abs_loss_when_feasible": (
                sum(r["abs_loss"] for r in feasible_here) / len(feasible_here) if feasible_here else None
            ),
            "mean_rel_loss_when_feasible": (
                sum(rel_losses_here) / len(rel_losses_here) if rel_losses_here else None
            ),
            "n_deviation_checks": len(dev_here),
            "n_deviation_confirmed": sum(1 for r in dev_here if r["confirmed"]),
            "n_deviation_found_unverified": sum(1 for r in dev_here if r["found"] and not r["confirmed"]),
            "deviation_rate": (
                sum(1 for r in dev_here if r["confirmed"]) / len(dev_here) if dev_here else None
            ),
            "n_deviation_truthful_ir_infeasible": sum(1 for r in dev_here if not r["truthful_ir_feasible"]),
            "n_deviation_reports_infeasible_total": sum(r["n_infeasible"] for r in dev_here),
        }
        per_job.append(entry)

    return {
        "ownership_seed": ownership_seed,
        "pairs_per_hospital_target": pairs_per_hospital,
        "jobs": [{"k": k, "p": p, "draws_per_member_configured": d} for k, p, d in jobs],
        "per_job": per_job,
        "n_total_efficiency_instances": len(eff_records),
        "n_total_deviation_checks": len(dev_records),
        "n_total_deviation_confirmed": sum(1 for r in dev_records if r["confirmed"]),
        "n_total_verification_failures": n_verification_failures_total,
        "comparison_targets": {
            "plain_k2": "results/kidney_real_data_sweep_v2/summary.json",
            "plain_k3": "results/kidney_k3_real_sweep_v2/summary.json",
        },
        "honesty_note": (
            "Compatibility graph is REAL (Pansart et al. 2022 published KEP benchmark, "
            "see witness.kidney_real_data). Hospital ownership is SYNTHETIC (declared seeded "
            "partition), never real hospital behavior. The IR-constrained mechanism is defined in "
            "witness.kidney_ir: the IR constraint's local-recourse term counts only REPORTED "
            "residual pairs (what the mechanism can see); a hospital's REALIZED utility (used for "
            "the deviation search) also counts privately clearing withheld pairs afterward, "
            "exactly like witness.kidney's own local residual stage -- see that module's own "
            "docstring, 'REALIZED OUTCOME VS. THE IR BOOKKEEPING TERM', for why these differ."
        ),
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--jobs", type=str, nargs="+", default=None,
        help="override job list as 'K,P,DRAWS' triples, e.g. 3,250,3 3,100,6 (default: DEFAULT_JOBS, "
             "K=3 P=250 first per the task's stated priority)",
    )
    p.add_argument("--pairs-per-hospital", type=int, default=6)
    p.add_argument("--ownership-seed", type=str, default="kidney-ir-sweep-v1")
    p.add_argument(
        "--max-ilp-seconds", type=float, default=90.0,
        help="per-CP-SAT-solve time cap (the IR joint model is heavier than plain clearing's own ILP "
             "tiebreak -- an instance that can't be proven optimal/infeasible in time is SKIPPED, "
             "never counted as a false negative or a fabricated hit -- see IlpTimeLimitExceeded",
    )
    p.add_argument("--out-dir", type=str, default="results/kidney_ir_sweep")
    p.add_argument(
        "--summary-only", action="store_true",
        help="just rebuild summary.json from the existing JSONL files, run nothing",
    )
    args = p.parse_args()

    if args.jobs is None:
        jobs = list(DEFAULT_JOBS)
    else:
        jobs = []
        for spec in args.jobs:
            k_s, p_s, d_s = spec.split(",")
            jobs.append((int(k_s), int(p_s), int(d_s)))

    os.makedirs(args.out_dir, exist_ok=True)
    eff_path = os.path.join(args.out_dir, "efficiency.jsonl")
    dev_path = os.path.join(args.out_dir, "deviation_checks.jsonl")
    wit_path = os.path.join(args.out_dir, "deviation_witnesses.jsonl")
    fail_path = os.path.join(args.out_dir, "verification_failures.jsonl")
    summary_path = os.path.join(args.out_dir, "summary.json")

    if args.summary_only:
        summary = build_summary(args.out_dir, jobs, args.pairs_per_hospital, args.ownership_seed)
        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2, sort_keys=True)
        print(json.dumps(summary, indent=2, sort_keys=True))
        return

    eff_ids = _read_existing_ids(eff_path)
    dev_ids = _read_existing_ids(dev_path)
    print(
        f"resuming: {len(eff_ids)} efficiency record(s), {len(dev_ids)} deviation-check record(s) "
        f"already on disk in {args.out_dir}", file=sys.stderr,
    )

    max_ilp_seconds = args.max_ilp_seconds if args.max_ilp_seconds > 0 else None

    with open(eff_path, "a", encoding="utf-8") as eff_f, \
         open(dev_path, "a", encoding="utf-8") as dev_f, \
         open(wit_path, "a", encoding="utf-8") as wit_f, \
         open(fail_path, "a", encoding="utf-8") as fail_f:
        for k, p_val, draws in jobs:
            print(f"=== job K={k} P={p_val} draws_per_member={draws} ===", file=sys.stderr)
            result = run_job(
                p_val, k, draws, args.pairs_per_hospital, args.ownership_seed, max_ilp_seconds,
                eff_f, eff_ids, dev_f, dev_ids, wit_f, fail_f,
            )
            print(json.dumps(result, indent=2), file=sys.stderr)

            summary = build_summary(args.out_dir, jobs, args.pairs_per_hospital, args.ownership_seed)
            with open(summary_path, "w", encoding="utf-8") as f:
                json.dump(summary, f, indent=2, sort_keys=True)

    print(f"\nwrote {summary_path}, {eff_path}, {dev_path}, {wit_path}, {fail_path}")


if __name__ == "__main__":
    main()
