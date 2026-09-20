"""The executable definition of every publicly stated number.

A claim in `claims.json` names a function here. `scripts/verify_claims.py`
imports and RUNS it, and fails if the registered figure is not what the
function returns. That is what makes a hand-typed or inherited number
impossible to ship: the only way to register a figure is to write the code
that regenerates it from raw rows, and that code returns a `Measurement`,
which enforces its own commensurability and eligibility rules.

Each function takes no arguments and returns either a `Measurement` or, for
a comparison, a `(Measurement, Measurement, varies)` triple which the
verifier feeds through `Measurement.compare_to`.
"""
from __future__ import annotations

import glob
import json
import os

from witness.measurement import Measurement, load_jsonl

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _paths(pattern: str) -> list:
    return sorted(glob.glob(os.path.join(ROOT, pattern)))


# --------------------------------------------------------------------------
# cycle_length_p250_paired
# --------------------------------------------------------------------------

def _sweep_rows(summary_path: str, p: int, cycle_length: int) -> list:
    """`kidney_real_data_sweep.py` never writes a per-check row -- only
    confirmed witnesses and an aggregate summary. n_checks and n_confirmed
    in that summary ARE the complete record of every check attempted
    (n_skipped_too_hard is tracked and excluded separately, never silently
    folded into n_checks), so synthesising one row per check from those two
    counts is not an approximation: it is the full eligible population,
    just without a per-row detail file to re-read.
    """
    d = json.load(open(summary_path))
    block = next(s for s in d["per_size"] if s["p"] == p)
    assert block["n_skipped_too_hard"] == 0, (
        "skipped checks exist and are not represented in n_checks; "
        "this derivation would then understate the eligible population")
    n, hits = block["n_checks"], block["n_confirmed"]
    return [{"hit": i < hits, "cycle_length": cycle_length, "pool_size": p,
             "ownership_seed": d["ownership_seed"], "tiebreak": d["tiebreak_policy"]}
            for i in range(n)]


def cycle_length_p250_paired():
    """The headline: same solver, same ownership seed, same partitions,
    only cycle length differs. K=3 arm was RE-RUN after the original was
    corrupted by a duplicate-launch race (see claims.json blocker, now
    cleared) -- results/samesolver_k3_p250, a clean single-writer run."""
    k2 = _sweep_rows(os.path.join(ROOT, "results/samesolver_k2/summary.json"), 250, 2)
    k3 = _sweep_rows(os.path.join(ROOT, "results/samesolver_k3_p250/summary.json"), 250, 3)
    elig = "all attempted checks; zero skipped as too-hard in either arm"
    a = Measurement.from_rows(
        k2, unit="hospital_check", eligibility=elig, eligible=lambda r: True,
        hit=lambda r: r["hit"],
        config_of=lambda r: {"cycle_length": r["cycle_length"], "pool_size": r["pool_size"],
                             "ownership_seed": r["ownership_seed"], "tiebreak": r["tiebreak"]},
        sources=["results/samesolver_k2/summary.json"])
    b = Measurement.from_rows(
        k3, unit="hospital_check", eligibility=elig, eligible=lambda r: True,
        hit=lambda r: r["hit"],
        config_of=lambda r: {"cycle_length": r["cycle_length"], "pool_size": r["pool_size"],
                             "ownership_seed": r["ownership_seed"], "tiebreak": r["tiebreak"]},
        sources=["results/samesolver_k3_p250/summary.json"])
    return a, b, ["cycle_length"]


# --------------------------------------------------------------------------
# minimal_boundary_counterexample
# --------------------------------------------------------------------------

def minimal_boundary_search():
    """Runs the actual exhaustive enumeration (not a stored number) proving
    4 pairs is the minimum market size containing a determinate hospital
    that can profit at k=3, and that k=2 has NO such market at n=3 or n=4.
    Rows here are (n, k) SCANS, not hospital-checks, so this returns a
    Measurement whose unit is the scan itself and whose 'hit' is exact
    equality with the value scripts/kidney_minimal_boundary_search.py's
    own docstring claims -- re-running the search IS the check."""
    import scripts.kidney_minimal_boundary_search as search
    expected = {(3, 2): (342, 0), (3, 3): (372, 0), (4, 2): (46976, 0), (4, 3): (49888, 204)}
    rows = []
    for (n, k), (exp_checked, exp_hits) in expected.items():
        checked, hits = search.scan(n, k)
        rows.append({"n": n, "k": k, "checked": checked, "hits": hits,
                     "matches_docstring": (checked, hits) == (exp_checked, exp_hits)})
    return Measurement.from_rows(
        rows, unit="exhaustive_scan",
        eligibility="all four (n,k) cells the module docstring makes claims about",
        eligible=lambda r: True,
        hit=lambda r: r["matches_docstring"],
        config_of=lambda r: {"n": r["n"], "k": r["k"]},
        sources=["scripts/kidney_minimal_boundary_search.py"])


# --------------------------------------------------------------------------
# ir_creates_manipulations
# --------------------------------------------------------------------------

def ir_paired_rates():
    """Plain vs IR on identical markets. Returns both arms and the keys that
    genuinely differ -- which is BOTH mechanism and tiebreak, not mechanism
    alone. Registering this forced the claim to be stated at the strength
    the design actually supports."""
    rows = load_jsonl(_paths("results/kidney_ir_paired_p250_w*/paired_rows.jsonl"))
    elig = "paired checks where both arms resolved"
    resolved = lambda r: bool(r.get("both_resolved"))  # noqa: E731
    plain = Measurement.from_rows(
        rows, unit="hospital_check", eligibility=elig, eligible=resolved,
        hit=lambda r: bool(r["plain_hit"]),
        config_of=lambda r: {
            "mechanism": "plain", "tiebreak": "max_cardinality_ilp",
            "cycle_length": r["k"], "pool_size": r["p"],
        },
        sources=["results/kidney_ir_paired_p250_w*/paired_rows.jsonl"])
    ir = Measurement.from_rows(
        rows, unit="hospital_check", eligibility=elig, eligible=resolved,
        hit=lambda r: bool(r["ir_hit"]),
        config_of=lambda r: {
            "mechanism": "ir_constrained", "tiebreak": "lexicographic_min_rank",
            "cycle_length": r["k"], "pool_size": r["p"],
        },
        sources=["results/kidney_ir_paired_p250_w*/paired_rows.jsonl"])
    return plain, ir, ["mechanism", "tiebreak"]


# --------------------------------------------------------------------------
# determinacy_k2
# --------------------------------------------------------------------------

def determinacy_k2_synth():
    """Determinate k=2 hospitals WITH room to gain. The eligibility rule is
    the load-bearing part: without the room-to-gain exclusion this
    denominator silently absorbs hospitals that cannot move, which is how an
    earlier version reached 490,147."""
    rows = [r for r in load_jsonl(_paths("results/determinacy_synth_k2_n100/rows.jsonl"))
            if r.get("status") == "ok"]
    return Measurement.from_rows(
        rows, unit="hospital_check",
        eligibility=("determinate (tiebreak_spread == 0) AND not already matching all own "
                     "pairs; the latter cannot gain by construction and is excluded"),
        eligible=lambda r: r["tiebreak_spread"] == 0 and r["seed_truthful_utility"] < r["hospital_size"],
        hit=lambda r: r["strategic_gain"] > 0,
        config_of=lambda r: {"cycle_length": 2, "generator": "synthetic_er", "n_pairs": r["n_pairs"]},
        sources=["results/determinacy_synth_k2_n100/rows.jsonl"])


# --------------------------------------------------------------------------
# claim_a_k2
# --------------------------------------------------------------------------

def claim_a_k2_corroboration():
    """Deviations at k=2 whose payoff exceeds U_true_max. The theorem says
    this is 0; this is the corroborating measurement, not its basis."""
    rows = []
    for d in _paths("results/kidney_tiebreak_census_k2_p*"):
        p = os.path.join(d, "hospital_rows.jsonl")
        if os.path.exists(p):
            rows.extend(load_jsonl([p]))
    return Measurement.from_rows(
        rows, unit="verified_deviation",
        eligibility=("confirmed deviations (strategic_gain > 0) whose u_true_min and "
                     "u_true_max were both proven optimal and whose realized truthful "
                     "utility lies inside that range"),
        eligible=lambda r: (
            r.get("status") == "ok" and r.get("strategic_gain", 0) > 0
            and r.get("u_min_status") in (None, "ok") and r.get("u_max_status") in (None, "ok")
            and r["u_true_min"] <= r["seed_truthful_utility"] <= r["u_true_max"]
            and r.get("manipulation_verified") is not False
        ),
        hit=lambda r: r["seed_truthful_utility"] + r["strategic_gain"] > r["u_true_max"],
        config_of=lambda r: {"cycle_length": 2, "mechanism": "plain",
                             "tiebreak": "max_cardinality_ilp"},
        sources=["results/kidney_tiebreak_census_k2_p*/hospital_rows.jsonl"])


REGISTRY = {
    "minimal_boundary_search": minimal_boundary_search,
    "cycle_length_p250_paired": cycle_length_p250_paired,
    "ir_paired_rates": ir_paired_rates,
    "determinacy_k2_synth": determinacy_k2_synth,
    "claim_a_k2_corroboration": claim_a_k2_corroboration,
}
