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
import os

from witness.measurement import Measurement, load_jsonl

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _paths(pattern: str) -> list:
    return sorted(glob.glob(os.path.join(ROOT, pattern)))


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
    "ir_paired_rates": ir_paired_rates,
    "determinacy_k2_synth": determinacy_k2_synth,
    "claim_a_k2_corroboration": claim_a_k2_corroboration,
}
