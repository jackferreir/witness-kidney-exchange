"""CLI: measure how many random `witness.generate` instances it takes to find
a Boston manipulation, when none is planted.

Each of `--trials` independent trials draws instances one at a time from a
trial-specific `witness.generate.GeneratorConfig` (a distinct seed per trial,
derived from `--seed` and the trial index via `witness.generate.derive_seed`),
running `witness.search.search_all_students` under
`"boston_immediate_acceptance"` on each instance until one yields at least one
manipulation. That first hit is RE-VERIFIED with
`witness.replay.verify_in_subprocess` -- a genuinely fresh process -- and is
only counted as a hit if it verifies; a hit that fails to verify is a real
defect and is reported loudly rather than silently dropped or retried.

Every trial's outcome is appended to an append-only JSONL journal
(`witness.journal.Journal`, default path `results/search_power_3a.jsonl`), and
every verified witness is separately appended to
`results/witnesses_3a.jsonl`, so the run is fully reproducible from its own
recorded seeds and generator config.

Remember the scope limitation documented in `witness.generate`: this measures
search power against Step-3A's NARROW instance distribution (complete
rankings, one tied priority class per school, uniform capacity) -- a lower
bound on that slice, not an estimate over the full modeled instance space.
"""

from __future__ import annotations

import argparse
import os
import statistics
import sys
import time
from dataclasses import dataclass
from typing import Optional

# Make `witness` importable when this file is run directly as
# `python3 scripts/search_power.py ...` (as opposed to `python3 -m
# scripts.search_power ...`, where `-m` already puts the current working
# directory on `sys.path`): insert the project root (this file's parent's
# parent) at the front of `sys.path` before importing anything from `witness`.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from witness.boston import BostonConfig
from witness.generate import GeneratorConfig, derive_seed, generate_instance, priority_tiebreak
from witness.journal import Journal
from witness.replay import verify_in_subprocess
from witness.search import search_all_students

#: Fixed, non-configurable location for every verified witness this script
#: finds -- separate from --out, which is the per-trial results journal.
WITNESSES_PATH = "results/witnesses_3a.jsonl"

#: Default per-trial results journal path.
DEFAULT_OUT = "results/search_power_3a.jsonl"


@dataclass(frozen=True)
class TrialResult:
    """Everything about one trial, in a JSON-able shape."""

    trial_index: int
    trial_seed: str
    found: bool
    instances_scanned: int
    witness_id: Optional[str]
    verified_in_fresh_process: Optional[bool]
    defect_reasons: tuple
    scan_seconds: float

    def to_dict(self) -> dict:
        return {
            "trial_index": self.trial_index,
            "trial_seed": self.trial_seed,
            "found": self.found,
            "instances_scanned": self.instances_scanned,
            "witness_id": self.witness_id,
            "verified_in_fresh_process": self.verified_in_fresh_process,
            "defect_reasons": list(self.defect_reasons),
            "scan_seconds": self.scan_seconds,
        }


def parse_args(argv: "list[str] | None" = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python3 scripts/search_power.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--seed", default="search-power-3a", help="root seed for every derived trial seed")
    parser.add_argument("--trials", type=int, default=20, help="number of independent trials")
    parser.add_argument("--students", type=int, default=4, help="students per generated instance")
    parser.add_argument("--schools", type=int, default=3, help="schools per generated instance")
    parser.add_argument("--capacity", type=int, default=1, help="uniform per-school capacity")
    parser.add_argument(
        "--max-instances",
        type=int,
        default=500,
        help="give up on a trial after this many instances with no manipulation found",
    )
    parser.add_argument("--out", default=DEFAULT_OUT, help="path to the per-trial results JSONL journal")
    return parser.parse_args(argv)


def run_trial(
    *,
    base_seed: str,
    trial_index: int,
    n_students: int,
    n_schools: int,
    capacity: int,
    max_instances: int,
    witnesses_journal: Journal,
) -> TrialResult:
    """Scan generated instances for trial `trial_index` until the first
    verified Boston manipulation, or until `max_instances` is exhausted."""
    trial_seed = derive_seed(base_seed, trial_index, "trial")
    gc = GeneratorConfig(
        n_students=n_students, n_schools=n_schools, capacity=capacity, seed=trial_seed
    )

    t0 = time.perf_counter()
    for i in range(max_instances):
        market, profile = generate_instance(gc, i)
        config = BostonConfig(tiebreak=priority_tiebreak(gc, i))
        witnesses = search_all_students(market, profile, "boston_immediate_acceptance", config)
        if witnesses:
            scan_seconds = time.perf_counter() - t0
            w = witnesses[0]
            ok, reasons = verify_in_subprocess(w.to_dict())
            if not ok:
                print(
                    f"DEFECT: trial {trial_index} (seed {trial_seed!r}) instance {i}: "
                    f"a manipulation was found but FAILED fresh-process replay: {reasons}"
                )
                return TrialResult(
                    trial_index=trial_index,
                    trial_seed=trial_seed,
                    found=False,
                    instances_scanned=i + 1,
                    witness_id=w.witness_id,
                    verified_in_fresh_process=False,
                    defect_reasons=reasons,
                    scan_seconds=scan_seconds,
                )
            witnesses_journal.append(w.to_dict())
            return TrialResult(
                trial_index=trial_index,
                trial_seed=trial_seed,
                found=True,
                instances_scanned=i + 1,
                witness_id=w.witness_id,
                verified_in_fresh_process=True,
                defect_reasons=(),
                scan_seconds=scan_seconds,
            )

    scan_seconds = time.perf_counter() - t0
    return TrialResult(
        trial_index=trial_index,
        trial_seed=trial_seed,
        found=False,
        instances_scanned=max_instances,
        witness_id=None,
        verified_in_fresh_process=None,
        defect_reasons=(),
        scan_seconds=scan_seconds,
    )


def main(argv: "list[str] | None" = None) -> int:
    args = parse_args(argv)

    journal = Journal(args.out)
    witnesses_journal = Journal(WITNESSES_PATH)

    generator_config_record = {
        "n_students": args.students,
        "n_schools": args.schools,
        "capacity": args.capacity,
    }

    results: list[TrialResult] = []
    wall_start = time.perf_counter()
    for t in range(args.trials):
        result = run_trial(
            base_seed=args.seed,
            trial_index=t,
            n_students=args.students,
            n_schools=args.schools,
            capacity=args.capacity,
            max_instances=args.max_instances,
            witnesses_journal=witnesses_journal,
        )
        results.append(result)

        record = {
            "base_seed": args.seed,
            "generator_config": generator_config_record,
            "mechanism": "boston_immediate_acceptance",
            "max_instances": args.max_instances,
            **result.to_dict(),
        }
        journal.append(record)

        print(
            f"trial {t}: trial_seed={result.trial_seed!r} found={result.found} "
            f"instances_scanned={result.instances_scanned} "
            f"verified_in_fresh_process={result.verified_in_fresh_process} "
            f"scan_seconds={result.scan_seconds:.4f}"
        )

    total_wall = time.perf_counter() - wall_start

    hits = [r for r in results if r.found]
    defects = [r for r in results if r.witness_id is not None and not r.found]
    instances_to_hit = [r.instances_scanned for r in hits]
    total_instances_scanned = sum(r.instances_scanned for r in results)
    total_scan_seconds = sum(r.scan_seconds for r in results)

    print()
    print("=== search_power_3a summary ===")
    print(
        f"base_seed={args.seed!r} trials={args.trials} students={args.students} "
        f"schools={args.schools} capacity={args.capacity} max_instances={args.max_instances}"
    )
    print(f"trial seeds: {[r.trial_seed for r in results]}")
    print(f"trials with a verified hit: {len(hits)}/{args.trials}")
    if defects:
        print(f"DEFECTS (found but failed fresh-process replay): {len(defects)} -- see DEFECT lines above")

    if instances_to_hit:
        print(f"instances-to-first-hit per trial (hits only): {instances_to_hit}")
        print(
            "  min="
            f"{min(instances_to_hit)} median={statistics.median(instances_to_hit)} "
            f"max={max(instances_to_hit)} mean={statistics.mean(instances_to_hit):.3f}"
        )
    else:
        print("no trial produced a verified hit within max_instances")

    if total_instances_scanned:
        fraction = len(hits) / total_instances_scanned
        print(
            "fraction of scanned instances containing >=1 manipulation: "
            f"{fraction:.4f} ({len(hits)}/{total_instances_scanned})"
        )
        mean_seconds_per_instance = total_scan_seconds / total_instances_scanned
        print(f"mean seconds per instance (search time only): {mean_seconds_per_instance:.6f}")

    print(f"total wall time (this script, all trials): {total_wall:.3f}s")
    print(f"results journal: {journal.path}")
    print(f"witnesses journal: {witnesses_journal.path}")

    return 1 if defects else 0


if __name__ == "__main__":
    raise SystemExit(main())
