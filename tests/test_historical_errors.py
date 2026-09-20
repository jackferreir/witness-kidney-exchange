"""Every incorrect claim this project actually published, as a test.

This is the evidence that `witness/measurement.py` and
`scripts/verify_claims.py` do what they were built for. Each test below
reconstructs a specific error that WENT OUT -- into the README, into
MODEL.md, or into an email to an outside reader -- and asserts the
infrastructure now refuses it.

A test here failing means a real historical error would ship again.

The errors are listed in the order they were made. Where the original
number is known it is used, so these are not stylised analogues but the
actual shapes.
"""
from __future__ import annotations

import json
import os
import tempfile

import pytest

from scripts.verify_claims import verify
from witness.measurement import (
    HeterogeneousRowsError,
    IncommensurableError,
    Measurement,
)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _registry(claims):
    d = tempfile.mkdtemp()
    p = os.path.join(d, "claims.json")
    with open(p, "w") as f:
        json.dump({"claims": claims}, f)
    return p


def _rows(n, hits, **cfg):
    """n rows, `hits` of them positive, all sharing one config."""
    return [{"hit": i < hits, **cfg} for i in range(n)]


def _measure(rows, *, unit="hospital_check", eligibility="all rows, none excluded",
             eligible=None, config_keys=None, sources=("fixture",)):
    keys = config_keys or [k for k in rows[0] if k != "hit"]
    return Measurement.from_rows(
        rows, unit=unit, eligibility=eligibility,
        eligible=eligible or (lambda r: True),
        hit=lambda r: bool(r["hit"]),
        config_of=lambda r: {k: r[k] for k in keys},
        sources=list(sources))


# =========================================================================
# ERROR 1 -- "manipulation gain is always exactly 1"
# Published in MODEL.md as the basis of a conjecture. It was true of a
# FIRST-HIT search and false of the MAX-GAIN census that replaced it: the
# census records 11 gains of 2 and one of 3. The claim survived a method
# change because it was a sentence, not a computation.
# =========================================================================

def test_error1_inherited_number_across_a_method_change():
    """C4: a registered figure must be reproduced by running code. A number
    that outlives the method that produced it cannot."""
    claim = {
        "id": "gain_always_one", "text": "Every confirmed deviation gains exactly 1.",
        "kind": "measurement", "scope": "All confirmed deviations in the census, all pool sizes.",
        "unit": "verified_deviation",
        "eligibility": "confirmed deviations with strategic_gain > 0",
        "sources": ["README.md"], "status": "verified",
        "derivation": "claim_a_k2_corroboration",      # real derivation
        "expect": {"numerator": 0, "denominator": 999999},  # stale inherited figure
    }
    failures = verify(_registry([claim]), quiet=True)
    assert any("REDERIVATION" in f and "denominator" in f for f in failures), failures


# =========================================================================
# ERROR 2 -- the plain-vs-IR comparison
# Sent to two outside readers. The arms differed in the IR constraint AND
# the tie-breaking rule, but the 10.8%->3.8% drop was attributed to the
# constraint alone. Manipulability is provably tie-break contingent, so the
# two effects were not separable.
# =========================================================================

def test_error2_incommensurable_arms_at_comparison_time():
    plain = _measure(_rows(564, 52, mechanism="plain", tiebreak="max_cardinality_ilp", k=3))
    ir = _measure(_rows(564, 17, mechanism="ir_constrained", tiebreak="lexicographic", k=3))
    with pytest.raises(IncommensurableError, match="tiebreak"):
        plain.compare_to(ir, varies=["mechanism"])


def test_error2_same_error_caught_again_at_publication_time():
    """Belt and braces: even if a bare number reaches the registry, the
    declared arm configs are diffed there too."""
    claim = {
        "id": "ir_reduces", "text": "IR reduces the withholding rate from 10.8% to 3.8%.",
        "kind": "comparison", "scope": "P=250, k=3, paired on identical market and hospital.",
        "unit": "hospital_check", "eligibility": "pairs where both arms resolved",
        "sources": ["README.md"], "status": "verified",
        "arms": {
            "a": {"config": {"mechanism": "plain", "tiebreak": "max_cardinality_ilp", "k": 3}},
            "b": {"config": {"mechanism": "ir_constrained", "tiebreak": "lexicographic", "k": 3}},
        },
        "varies": ["mechanism"],
    }
    failures = verify(_registry([claim]), quiet=True)
    assert any("COMMENSURABILITY" in f and "tiebreak" in f for f in failures), failures


# =========================================================================
# ERROR 3 -- "0 of 490,147 determinate hospitals could gain"
# The denominator silently absorbed hospitals already matching all their own
# pairs, which cannot gain by construction. In the densest arm that was 98%
# of the rows. The honest denominator is 195,123.
# =========================================================================

def test_error3_denominator_full_of_units_that_cannot_move():
    """The eligibility rule is part of the object, and a filter that removes
    most of the rows is surfaced rather than hidden."""
    # 1000 determinate hospitals, 900 of them already fully matched
    rows = [{"hit": False, "fully_matched": i < 900, "k": 2} for i in range(1000)]
    honest = Measurement.from_rows(
        rows, unit="hospital_check",
        eligibility="determinate AND not already fully matched (excluded: cannot gain by construction)",
        eligible=lambda r: not r["fully_matched"],
        hit=lambda r: bool(r["hit"]),
        config_of=lambda r: {"k": r["k"]}, sources=["fixture"])
    assert honest.denominator == 100
    assert honest.excluded == 900
    # the filter is doing most of the work, and the object says so
    assert "eligibility rule is doing most of the work" in (honest.is_extreme() or "")


def test_error3_extreme_figure_cannot_be_asserted_without_a_challenge():
    """C5: a rate of exactly 0 must arrive with the adversarial test that
    tried to break it. 'Perfect numbers are artifact-shaped' was already in
    REVIEWER.md as prose and did not prevent this."""
    claim = {
        "id": "determinacy", "text": "No determinate k=2 hospital has a profitable deviation.",
        "kind": "measurement",
        "scope": "Real benchmark plus one synthetic generator at four parameter settings.",
        "unit": "hospital_check",
        "eligibility": "determinate AND with room to gain; fully-matched hospitals excluded",
        "sources": ["README.md"], "status": "verified",
        "derivation": "determinacy_k2_synth",
        "expect": {"numerator": 0, "denominator": 94655},
        # no 'challenge' field
    }
    failures = verify(_registry([claim]), quiet=True)
    assert any("EXTREME" in f for f in failures), failures


# =========================================================================
# ERROR 4 -- "the IR constraint never binds"
# Verified at the TRUTHFUL profile only, then stated universally. The
# matched-tie-break control later showed the constraint does bite under
# misreports, and this overreach nearly caused a CORRECT finding to be
# withdrawn.
# =========================================================================

def test_error4_universal_claim_from_a_narrow_test():
    claim = {
        "id": "never_binds", "text": "The IR constraint never binds.",
        "kind": "measurement", "scope": "truthful profile",   # too thin for 'never'
        "unit": "instance", "eligibility": "all instances sampled at the truthful profile",
        "sources": ["README.md"], "status": "verified",
        "derivation": "determinacy_k2_synth", "expect": {"numerator": 0, "denominator": 94655},
        "challenge": "adversarial dense regimes",
    }
    failures = verify(_registry([claim]), quiet=True)
    assert any("SCOPE" in f for f in failures), failures


# =========================================================================
# ERROR 5 -- "10 strong cases survive adversarial tie-breaking"
# There were 6. Ten was a count of ROWS; four of the underlying markets had
# been independently rediscovered by a second collection pipeline and
# counted twice.
# =========================================================================

def test_error5_counting_rows_when_the_unit_is_markets():
    """Two pipelines, same underlying markets. Pooling them without naming
    the pipeline key raises, which is what forces 'ten what?' to be asked."""
    rows = ([{"hit": True, "market": f"m{i}", "pipeline": "census"} for i in range(6)]
            + [{"hit": True, "market": f"m{i}", "pipeline": "sweep"} for i in range(4)])
    with pytest.raises(HeterogeneousRowsError, match="pipeline"):
        Measurement.from_rows(
            rows, unit="distinct_market", eligibility="strong cases",
            eligible=lambda r: True, hit=lambda r: bool(r["hit"]),
            config_of=lambda r: {"pipeline": r["pipeline"]}, sources=["fixture"])


# =========================================================================
# ERROR 6 -- the '25x tie-break' magnitude claim
# Compared a range taken over ALL tied optima against a gain measured under
# ONE fixed rule: two different reference classes, presented as a ratio.
# =========================================================================

def test_error6_comparing_across_different_admissible_populations():
    spread = _measure(_rows(100, 51, k=2), eligibility="range over ALL tied optimal clearings")
    gain = _measure(_rows(100, 2, k=3), eligibility="best gain under ONE fixed tie-break rule")
    with pytest.raises(IncommensurableError, match="eligibility"):
        spread.compare_to(gain, varies=["k"])


# =========================================================================
# ERROR 7 -- README cited scripts/clustered_inference.py for a K2-vs-K3
# comparison that script never performed.
# =========================================================================

def test_error7_citing_a_source_that_does_not_exist():
    claim = {
        "id": "miscited", "text": "K=3 raises the rate by 6.6 points.",
        "kind": "measurement", "scope": "P=250 on real benchmark graphs, clustered on source graph.",
        "unit": "source_graph", "eligibility": "all resolved hospital checks",
        "sources": ["scripts/clustered_inference.py"], "status": "verified",
        "derivation": "determinacy_k2_synth", "expect": {"numerator": 0, "denominator": 94655},
        "challenge": "x",
    }
    failures = verify(_registry([claim]), quiet=True)
    assert any("PROVENANCE" in f for f in failures), failures


# =========================================================================
# ERROR 8 -- "zero overlap" between tie-break policies (0/135 vs 4/135)
# Technically true and vacuous: one of the two sets was empty. It read as
# though two disjoint non-empty sets had been found.
# =========================================================================

def test_error8_vacuous_difference_is_still_flagged_as_extreme():
    """An arm that is all-zero is flagged, so 'no overlap' cannot be stated
    without the zero being visible."""
    ilp = _measure(_rows(135, 0, tiebreak="ilp"))
    assert "exactly 0" in (ilp.is_extreme() or "")


# =========================================================================
# ERROR 9 -- "four different generators agree"
# One Erdos-Renyi generator at four parameter settings, plus the real
# benchmark. Two families, not five.
# =========================================================================

def test_error9_parameter_settings_are_not_independent_generators():
    rows = ([{"hit": False, "generator": "synthetic_er", "density": d}
             for d in (0.06, 0.15, 0.30, 0.45) for _ in range(25)])
    with pytest.raises(HeterogeneousRowsError, match="density"):
        Measurement.from_rows(
            rows, unit="hospital_check", eligibility="determinate with room to gain",
            eligible=lambda r: True, hit=lambda r: bool(r["hit"]),
            config_of=lambda r: {"generator": r["generator"], "density": r["density"]},
            sources=["fixture"])


# =========================================================================
# ERROR 10 -- retracting a correct result
# Twice a true finding was nearly withdrawn on the strength of a test that
# did not test the claim. A retraction is an assertion and needs the same
# evidence.
# =========================================================================

def test_error10_retraction_without_stated_grounds_is_refused():
    claim = {
        "id": "withdrawn", "text": "IR creates new withholding opportunities.",
        "kind": "measurement", "scope": "P=250 k=3 discordant pairs from the paired run.",
        "unit": "hospital_check", "eligibility": "the IR-only discordant pairs",
        "sources": ["README.md"], "status": "retracted",
        # no 'retraction' field saying what specifically failed
    }
    failures = verify(_registry([claim]), quiet=True)
    assert any("retraction" in f for f in failures), failures


# =========================================================================
# The live registry must itself be clean.
# =========================================================================

def test_the_real_registry_still_passes():
    failures = verify(os.path.join(PROJECT_ROOT, "claims.json"), quiet=True)
    assert failures == [], "\n".join(failures)
