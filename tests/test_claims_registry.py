"""Makes the claims registry a hard gate rather than a good intention.

`scripts/verify_claims.py` is only useful if it is impossible to ship a
claim without it passing. This test is what makes that true: the suite
fails if `claims.json` contains a claim that is incommensurable, out of
scope, missing its eligibility rule, or citing a file that does not exist.

It also pins the checks themselves with synthetic fixtures, so that a
future edit that quietly neuters a check -- the most likely way this
infrastructure would rot -- fails here rather than silently letting the
next bad claim through.
"""
from __future__ import annotations

import json
import os
import tempfile

import pytest

from scripts.verify_claims import verify  # noqa: E402

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _write(tmpdir, claims):
    path = os.path.join(tmpdir, "claims.json")
    with open(path, "w") as f:
        json.dump({"claims": claims}, f)
    return path


BASE = {
    "id": "fixture",
    "text": "A rate rises from 1% to 2%.",
    "kind": "comparison",
    "scope": "A fully stated scope, long enough to be meaningful.",
    "unit": "source_graph",
    "eligibility": "All rows that resolved in both arms.",
    "sources": ["README.md"],
    "status": "verified",
    "arms": {
        "a": {"config": {"mechanism": "plain", "cycle_length": 2, "tiebreak": "ilp"}},
        "b": {"config": {"mechanism": "plain", "cycle_length": 3, "tiebreak": "ilp"}},
    },
    "varies": ["cycle_length"],
}


def test_the_projects_own_registry_passes():
    """The real gate. If this fails, a public claim is unsound."""
    failures = verify(os.path.join(PROJECT_ROOT, "claims.json"), quiet=True)
    assert failures == [], "claims.json has unsound claims:\n" + "\n".join(failures)


def test_catches_undeclared_second_difference():
    """C1. The exact shape of the plain-vs-IR error: the arms differed in
    the tie-breaking rule as well as the mechanism, but only the mechanism
    was claimed to vary."""
    with tempfile.TemporaryDirectory() as d:
        c = json.loads(json.dumps(BASE))
        c["arms"]["b"]["config"]["tiebreak"] = "lexicographic"  # undeclared
        failures = verify(_write(d, [c]), quiet=True)
    assert any("COMMENSURABILITY" in f and "tiebreak" in f for f in failures), failures


def test_catches_vacuous_varies():
    """C1, other direction: claiming a key varies when the arms agree on it."""
    with tempfile.TemporaryDirectory() as d:
        c = json.loads(json.dumps(BASE))
        c["arms"]["b"]["config"]["cycle_length"] = 2  # now identical
        failures = verify(_write(d, [c]), quiet=True)
    assert any("COMMENSURABILITY" in f and "IDENTICAL" in f for f in failures), failures


def test_catches_universal_claim_with_thin_scope():
    """C3. 'The constraint never binds' was verified at the truthful profile
    only. A universal quantifier obliges an explicit population."""
    with tempfile.TemporaryDirectory() as d:
        c = json.loads(json.dumps(BASE))
        c["text"] = "No hospital ever benefits."
        c["scope"] = "k=2"  # too thin to say what was tested
        failures = verify(_write(d, [c]), quiet=True)
    assert any("SCOPE" in f for f in failures), failures


def test_catches_missing_eligibility():
    """C2. Denominators that silently include units which cannot move."""
    with tempfile.TemporaryDirectory() as d:
        c = json.loads(json.dumps(BASE))
        c["eligibility"] = "all"  # too thin
        failures = verify(_write(d, [c]), quiet=True)
    assert any("ELIGIBILITY" in f for f in failures), failures


def test_catches_nonexistent_source():
    """P0. An earlier README cited a script for an analysis it did not
    contain."""
    with tempfile.TemporaryDirectory() as d:
        c = json.loads(json.dumps(BASE))
        c["sources"] = ["results/does_not_exist/summary.json"]
        failures = verify(_write(d, [c]), quiet=True)
    assert any("PROVENANCE" in f for f in failures), failures


def test_retracted_claim_requires_explanation():
    with tempfile.TemporaryDirectory() as d:
        c = json.loads(json.dumps(BASE))
        c["status"] = "retracted"
        failures = verify(_write(d, [c]), quiet=True)
    assert any("retraction" in f for f in failures), failures


@pytest.mark.parametrize("field", ["scope", "unit", "eligibility", "sources", "text"])
def test_required_fields_cannot_be_omitted(field):
    with tempfile.TemporaryDirectory() as d:
        c = json.loads(json.dumps(BASE))
        c.pop(field)
        failures = verify(_write(d, [c]), quiet=True)
    assert any("SCHEMA" in f and field in f for f in failures), failures


# --------------------------------------------------------------------------
# The deeper layer: errors are born at aggregation, not at publication.
# These pin witness/measurement.py, which is what makes the incommensurable
# comparison unrepresentable rather than merely discouraged.
# --------------------------------------------------------------------------

from witness.measurement import (  # noqa: E402
    HeterogeneousRowsError,
    IncommensurableError,
    Measurement,
)


def _m(hit_key, cfg, rows=None, elig="all rows", unit="hospital_check"):
    rows = rows or [{"h": i % 3 == 0, "k": cfg.get("cycle_length", 2)} for i in range(60)]
    return Measurement.from_rows(
        rows, unit=unit, eligibility=elig, eligible=lambda r: True,
        hit=lambda r: bool(r[hit_key]), config_of=lambda r: cfg, sources=["fixture"])


def test_measurement_blocks_the_real_plain_vs_ir_error():
    """The exact error, at the moment it was born rather than published."""
    plain = _m("h", {"mechanism": "plain", "tiebreak": "ilp", "cycle_length": 3})
    ir = _m("h", {"mechanism": "ir", "tiebreak": "lexicographic", "cycle_length": 3})
    with pytest.raises(IncommensurableError, match="tiebreak"):
        plain.compare_to(ir, varies=["mechanism"])


def test_measurement_allows_the_honest_weaker_attribution():
    plain = _m("h", {"mechanism": "plain", "tiebreak": "ilp", "cycle_length": 3})
    ir = _m("h", {"mechanism": "ir", "tiebreak": "lexicographic", "cycle_length": 3})
    out = plain.compare_to(ir, varies=["mechanism", "tiebreak"])
    assert out["varies"] == ["mechanism", "tiebreak"]


def test_measurement_refuses_comparison_across_different_populations():
    """A rate difference measured on different admissible sets is not an effect."""
    a = _m("h", {"cycle_length": 2}, elig="determinate only")
    b = _m("h", {"cycle_length": 3}, elig="determinate AND room to gain")
    with pytest.raises(IncommensurableError, match="eligibility"):
        a.compare_to(b, varies=["cycle_length"])


def test_measurement_refuses_silent_pooling():
    """Collapsing two cycle lengths into one denominator must be deliberate."""
    rows = [{"h": False, "k": 2} for _ in range(30)] + [{"h": True, "k": 3} for _ in range(30)]
    with pytest.raises(HeterogeneousRowsError, match="cycle_length"):
        Measurement.from_rows(
            rows, unit="hospital_check", eligibility="all", eligible=lambda r: True,
            hit=lambda r: bool(r["h"]),
            config_of=lambda r: {"cycle_length": r["k"]}, sources=["fixture"])


def test_measurement_allows_declared_pooling():
    rows = [{"h": False, "k": 2} for _ in range(30)] + [{"h": True, "k": 3} for _ in range(30)]
    m = Measurement.from_rows(
        rows, unit="hospital_check", eligibility="all", eligible=lambda r: True,
        hit=lambda r: bool(r["h"]), config_of=lambda r: {"cycle_length": r["k"]},
        sources=["fixture"], pool_over=["cycle_length"])
    assert m.pooled_over == ("cycle_length",)


def test_perfect_rates_are_flagged_extreme():
    """'Perfect numbers are artifact-shaped' as a property of the object."""
    zero = Measurement.from_rows(
        [{"h": False} for _ in range(500)], unit="hospital_check", eligibility="all",
        eligible=lambda r: True, hit=lambda r: r["h"], config_of=lambda r: {"k": 2},
        sources=["fixture"])
    assert "exactly 0" in (zero.is_extreme() or "")


def test_thin_denominators_are_flagged_extreme():
    thin = Measurement.from_rows(
        [{"h": i == 0} for i in range(9)], unit="market", eligibility="all",
        eligible=lambda r: True, hit=lambda r: r["h"], config_of=lambda r: {"k": 2},
        sources=["fixture"])
    assert "only 9" in (thin.is_extreme() or "")


def test_empty_denominator_is_an_error_not_a_zero():
    with pytest.raises(ValueError, match="empty denominator"):
        Measurement.from_rows(
            [{"h": True}], unit="x", eligibility="none qualify",
            eligible=lambda r: False, hit=lambda r: r["h"],
            config_of=lambda r: {}, sources=["fixture"])


def test_unit_and_eligibility_cannot_be_blank():
    with pytest.raises(ValueError):
        Measurement.from_rows(
            [{"h": True}], unit="", eligibility="stated", eligible=lambda r: True,
            hit=lambda r: r["h"], config_of=lambda r: {}, sources=["fixture"])
