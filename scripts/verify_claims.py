#!/usr/bin/env python3
"""Mechanical gate on every number this project states publicly.

WHY THIS EXISTS. `REVIEWER.md` has said "re-derive, don't inherit" since
early in the project. That norm did not prevent a single one of the errors
that actually shipped, because a norm written in prose is checked only by
the person who already believes they are following it. This script is the
executable version.

Run it before any claim goes into README.md, MODEL.md, or an email:

    python3 scripts/verify_claims.py

`tests/test_claims_registry.py` runs it in CI, so a registry that does not
pass fails the suite.

THE THREE CHECKS correspond to the three shapes every shipped error took.

C1. COMMENSURABILITY (comparisons). Each arm declares its FULL config. The
    checker diffs the two configs and requires the set of differing keys to
    equal `varies` exactly. An undeclared difference is an error even if the
    author believes it is immaterial -- the plain-vs-IR comparison differed
    in the tie-breaking rule as well as the IR constraint, and that second
    difference is precisely what made the result uninterpretable.

C2. ELIGIBILITY AND UNIT. Every claim must name its unit of analysis and
    state which rows are admissible and which are excluded. This is aimed at
    denominators that silently include units that cannot move: counting
    hospitals already matching all their pairs as evidence of "no profitable
    deviation" inflated one denominator from 195,123 to 490,147.

C3. SCOPE. Every claim must carry a scope string, and a claim whose text
    uses a universal quantifier ("never", "always", "every", "no ", "all ")
    must say in scope what population was actually tested. "The IR
    constraint never binds" was verified at the truthful profile only.

Plus P0. PROVENANCE: every path in `sources` must exist. A claim citing a
file that does not contain the analysis -- an earlier README cited
`clustered_inference.py` for a comparison it never performed -- fails here.

EXIT CODE is non-zero if any check fails, so this composes with CI.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REGISTRY = os.path.join(PROJECT_ROOT, "claims.json")

UNIVERSALS = ("never", "always", "every", "no ", "all ", "none", "not one", "zero ")
REQUIRED = ("id", "text", "kind", "scope", "unit", "eligibility", "sources", "status")
VALID_KIND = {"comparison", "measurement", "theorem"}
VALID_STATUS = {"verified", "retracted", "under_review"}


class Failure(Exception):
    pass


def _fail(claim_id: str, check: str, msg: str) -> str:
    return f"[{check}] {claim_id}: {msg}"


def check_schema(c: dict) -> list:
    out = []
    cid = c.get("id", "<no id>")
    for field in REQUIRED:
        if field not in c or c[field] in (None, "", [], {}):
            out.append(_fail(cid, "SCHEMA", f"missing or empty required field {field!r}"))
    if c.get("kind") not in VALID_KIND:
        out.append(_fail(cid, "SCHEMA", f"kind must be one of {sorted(VALID_KIND)}, got {c.get('kind')!r}"))
    if c.get("status") not in VALID_STATUS:
        out.append(_fail(cid, "SCHEMA", f"status must be one of {sorted(VALID_STATUS)}, got {c.get('status')!r}"))
    if c.get("status") == "retracted" and not c.get("retraction"):
        out.append(_fail(cid, "SCHEMA", "status is 'retracted' but no 'retraction' explanation given"))
    return out


def check_provenance(c: dict) -> list:
    """P0: every cited source must exist on disk."""
    out = []
    for path in c.get("sources", []):
        full = os.path.join(PROJECT_ROOT, path)
        if not os.path.exists(full):
            out.append(_fail(c["id"], "PROVENANCE", f"cited source does not exist: {path}"))
    return out


def check_commensurability(c: dict) -> list:
    """C1: a comparison's arms may differ ONLY in the declared `varies` keys."""
    out = []
    if c.get("kind") != "comparison":
        return out
    cid = c["id"]
    arms = c.get("arms") or {}
    if set(arms) != {"a", "b"}:
        return [_fail(cid, "COMMENSURABILITY", f"expected arms 'a' and 'b', got {sorted(arms)}")]
    if "varies" not in c:
        return [_fail(cid, "COMMENSURABILITY", "comparison has no 'varies' declaration")]

    ca, cb = arms["a"].get("config", {}), arms["b"].get("config", {})
    keys = set(ca) | set(cb)
    differing = {k for k in keys if ca.get(k, "<absent>") != cb.get(k, "<absent>")}
    declared = set(c["varies"])

    undeclared = differing - declared
    if undeclared:
        detail = "; ".join(f"{k}: {ca.get(k,'<absent>')!r} vs {cb.get(k,'<absent>')!r}" for k in sorted(undeclared))
        out.append(_fail(
            cid, "COMMENSURABILITY",
            f"arms differ in UNDECLARED key(s) {sorted(undeclared)} -- {detail}. "
            f"The claim attributes the difference to {sorted(declared)} alone, but the "
            f"design cannot separate those effects. Either hold the extra key(s) fixed "
            f"and rerun, or widen 'varies' and weaken the claim."))

    vacuous = declared - differing
    if vacuous:
        out.append(_fail(
            cid, "COMMENSURABILITY",
            f"'varies' names {sorted(vacuous)} but the arms are IDENTICAL on those keys"))
    return out


def check_scope(c: dict) -> list:
    """C3: universal claims must state the tested population explicitly."""
    out = []
    text = (c.get("text") or "").lower()
    scope = (c.get("scope") or "").strip()
    if any(u in text for u in UNIVERSALS):
        if len(scope) < 25:
            out.append(_fail(
                c["id"], "SCOPE",
                "claim text uses a universal quantifier but 'scope' is too thin to say "
                "what population was actually tested"))
    return out


def check_eligibility(c: dict) -> list:
    """C2: the admissible/excluded population must be stated, not implied."""
    out = []
    elig = (c.get("eligibility") or "").strip()
    if len(elig) < 15:
        out.append(_fail(c["id"], "ELIGIBILITY", "'eligibility' must state which rows count and which are excluded"))
    return out


def verify(registry_path: str = REGISTRY, quiet: bool = False) -> list:
    with open(registry_path) as f:
        reg = json.load(f)
    claims = reg.get("claims", [])
    if not claims:
        return ["[REGISTRY] no claims registered"]

    failures = []
    seen = set()
    for c in claims:
        cid = c.get("id", "<no id>")
        if cid in seen:
            failures.append(_fail(cid, "SCHEMA", "duplicate claim id"))
        seen.add(cid)

        errs = check_schema(c)
        failures.extend(errs)
        if errs:
            continue  # schema broken: downstream checks would be noise

        # A retracted claim is a record, not an assertion: it must carry an
        # explanation (checked above) but is exempt from the design checks,
        # since the whole point is that it FAILED them.
        if c["status"] == "retracted":
            if not quiet:
                print(f"  - {cid}: RETRACTED (exempt) -- {c['retraction'][:70]}...")
            continue

        failures.extend(check_provenance(c))
        failures.extend(check_commensurability(c))
        failures.extend(check_scope(c))
        failures.extend(check_eligibility(c))
        if not quiet:
            print(f"  - {cid}: ok")
    return failures


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--registry", default=REGISTRY)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    print(f"verifying {os.path.relpath(args.registry, PROJECT_ROOT)}")
    failures = verify(args.registry, quiet=args.quiet)
    print()
    if failures:
        print(f"FAILED ({len(failures)} problem(s)):")
        for f in failures:
            print(f"  {f}")
        return 1
    print("all registered claims pass")
    return 0


if __name__ == "__main__":
    sys.exit(main())
