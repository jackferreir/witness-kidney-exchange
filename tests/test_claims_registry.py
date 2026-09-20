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
