"""Aggregation that cannot silently discard the facts needed to check it.

THE DIAGNOSIS THIS IMPLEMENTS. Every incorrect number this project has
published was born at the same instant: the moment an ad-hoc script turned
many result rows into one scalar. A row knows what it is -- which market,
which mechanism, which tie-break, which cycle length, whether the hospital
could even have moved. `sum()` over a `glob()` knows none of that. After
that line runs there is a number, the number looks like a fact, and every
subsequent step reasons about the number rather than about what produced
it. `claims.json` catches this at publication; by then the wrong number has
been load-bearing for hours.

So the fix has to bind at aggregation, not at publication:

  * A `Measurement` cannot be built from a bare scalar. It is built from
    rows, and it keeps what the rows knew -- the unit of analysis, the
    eligibility rule actually applied, the set of distinct configurations
    present, and the files the rows came from.

  * Comparing two `Measurement`s is not subtraction. `compare_to` requires
    the caller to declare which configuration keys are allowed to differ,
    and REFUSES if the arms differ in any other key. The plain-vs-IR error
    is unrepresentable: those two arms differed in `tiebreak` as well as
    `mechanism`, so the subtraction raises instead of returning 7.0.

  * Pooling heterogeneous rows requires saying so. Summing a K=2 arm and a
    K=3 arm into one denominator raises unless `pool_over` names the key
    being collapsed, which forces the question "should these be one
    number?" to be answered in code rather than assumed.

  * A rate of exactly 0 or exactly 1, or one resting on very few units, is
    flagged `extreme`. REVIEWER.md has said "perfect numbers are artifact-
    shaped" in prose for a long time and it did not stop 0-of-26,584 or
    0-of-490,147 from being reported before they were audited. An extreme
    measurement carries the flag with it, and `verify_claims.py` refuses to
    register an extreme claim that has no recorded adversarial challenge.

WHAT THIS DOES NOT DO. It cannot tell you a claim is *interesting*, or that
an eligibility rule is the *right* one. It makes the rule explicit and
carried, so that a wrong one is visible in the object rather than implicit
in a filter expression that was typed once into a heredoc and thrown away.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping, Sequence


class IncommensurableError(Exception):
    """Raised when two measurements are compared across an undeclared
    difference in configuration -- the shape of the plain-vs-IR error."""


class HeterogeneousRowsError(Exception):
    """Raised when rows spanning several configurations are collapsed into
    one measurement without declaring which key is being pooled over."""


def _freeze(cfg: Mapping[str, Any]) -> "tuple[tuple[str, Any], ...]":
    return tuple(sorted((str(k), v) for k, v in cfg.items()))


@dataclass(frozen=True)
class Measurement:
    """A number that still knows where it came from.

    Never construct directly; use `from_rows`, which forces the unit,
    eligibility rule, and configuration to be stated.
    """

    value: float
    numerator: int
    denominator: int
    unit: str
    eligibility: str
    configs: "tuple[tuple[tuple[str, Any], ...], ...]"
    sources: "tuple[str, ...]"
    excluded: int = 0
    pooled_over: "tuple[str, ...]" = field(default_factory=tuple)

    # ---- construction -----------------------------------------------

    @staticmethod
    def from_rows(
        rows: Iterable[Mapping[str, Any]],
        *,
        unit: str,
        eligibility: str,
        eligible: Callable[[Mapping[str, Any]], bool],
        hit: Callable[[Mapping[str, Any]], bool],
        config_of: Callable[[Mapping[str, Any]], Mapping[str, Any]],
        sources: Sequence[str],
        pool_over: Sequence[str] = (),
    ) -> "Measurement":
        """Build a rate from rows, keeping what the rows knew.

        `eligible` is the admissibility rule and `eligibility` is its
        description in words -- both are required, so a denominator that
        includes units which could not have moved (hospitals already
        matching all their own pairs) has to be an explicit decision.

        `config_of` extracts the configuration each row was produced under.
        If rows disagree on any key not named in `pool_over`, this raises:
        collapsing a K=2 and a K=3 arm into one figure must be deliberate.
        """
        if not unit.strip() or not eligibility.strip():
            raise ValueError("unit and eligibility are required and must be non-empty")

        num = den = excluded = 0
        seen: set = set()
        for r in rows:
            if not eligible(r):
                excluded += 1
                continue
            den += 1
            num += bool(hit(r))
            seen.add(_freeze(config_of(r)))

        if den == 0:
            raise ValueError("no eligible rows: a measurement over an empty denominator is not a number")

        pooled = tuple(sorted(pool_over))
        if len(seen) > 1:
            keys = {k for cfg in seen for k, _ in cfg}
            differing = {
                k for k in keys
                if len({dict(cfg).get(k, "<absent>") for cfg in seen}) > 1
            }
            undeclared = differing - set(pooled)
            if undeclared:
                raise HeterogeneousRowsError(
                    f"rows span several configurations, differing in {sorted(undeclared)}. "
                    f"Collapsing them into one number is a decision, not a default: either "
                    f"measure each group separately, or pass pool_over={sorted(differing)} "
                    f"to state that the distinction is deliberately being discarded."
                )

        return Measurement(
            value=num / den,
            numerator=num,
            denominator=den,
            unit=unit,
            eligibility=eligibility,
            configs=tuple(sorted(seen)),
            sources=tuple(sources),
            excluded=excluded,
            pooled_over=pooled,
        )

    # ---- the check that makes the plain-vs-IR error unrepresentable ---

    def compare_to(self, other: "Measurement", *, varies: Sequence[str]) -> dict:
        """Difference of two measurements, permitted only if the two arms
        differ in exactly the declared keys.

        This is the whole point of the type. `a.value - b.value` is always
        computable and frequently meaningless; this refuses when the arms
        are not otherwise matched.
        """
        if len(self.configs) != 1 or len(other.configs) != 1:
            raise IncommensurableError(
                "compare_to needs one configuration per arm; "
                f"got {len(self.configs)} and {len(other.configs)}. Measure subgroups separately."
            )
        ca, cb = dict(self.configs[0]), dict(other.configs[0])
        keys = set(ca) | set(cb)
        differing = {k for k in keys if ca.get(k, "<absent>") != cb.get(k, "<absent>")}
        declared = set(varies)

        undeclared = differing - declared
        if undeclared:
            detail = "; ".join(
                f"{k}: {ca.get(k, '<absent>')!r} vs {cb.get(k, '<absent>')!r}" for k in sorted(undeclared)
            )
            raise IncommensurableError(
                f"arms differ in undeclared key(s) {sorted(undeclared)} -- {detail}. "
                f"The difference cannot be attributed to {sorted(declared)} alone. "
                f"Hold the extra key(s) fixed and re-run, or widen `varies` and weaken the claim."
            )
        vacuous = declared - differing
        if vacuous:
            raise IncommensurableError(
                f"`varies` names {sorted(vacuous)} but both arms agree on those keys; "
                f"this comparison does not vary what it claims to vary."
            )
        if self.unit != other.unit:
            raise IncommensurableError(f"different units of analysis: {self.unit!r} vs {other.unit!r}")
        if self.eligibility != other.eligibility:
            raise IncommensurableError(
                f"different eligibility rules:\n  a: {self.eligibility}\n  b: {other.eligibility}\n"
                f"A difference in rates across different admissible populations is not an effect."
            )
        return {
            "a": self.as_dict(),
            "b": other.as_dict(),
            "difference_pp": (other.value - self.value) * 100,
            "varies": sorted(declared),
        }

    # ---- the check that slows down surprising numbers ------------------

    def is_extreme(self, min_units: int = 30) -> "str | None":
        """Why this number needs an adversarial check before it is believed.

        Returns EVERY applicable reason joined, or None. Returning only the
        first was itself a defect found by the historical-error suite: a
        denominator that had been stripped of 90% of its rows also happened
        to have a rate of exactly 0, and the exactly-0 message masked the far
        more diagnostic one about the eligibility rule. The least informative
        signal must not hide the most informative one.
        """
        reasons = []
        if self.denominator < min_units:
            reasons.append(f"rests on only {self.denominator} {self.unit}(s)")
        if self.numerator == 0:
            reasons.append(f"rate is exactly 0 over {self.denominator} {self.unit}(s)")
        if self.numerator == self.denominator:
            reasons.append(f"rate is exactly 1 over {self.denominator} {self.unit}(s)")
        if self.excluded > 4 * self.denominator:
            reasons.append(
                f"{self.excluded} rows were excluded against {self.denominator} kept; "
                f"the eligibility rule is doing most of the work"
            )
        return "; ".join(reasons) if reasons else None

    # ---- reporting -----------------------------------------------------

    def as_dict(self) -> dict:
        d = {
            "value": self.value,
            "numerator": self.numerator,
            "denominator": self.denominator,
            "unit": self.unit,
            "eligibility": self.eligibility,
            "excluded": self.excluded,
            "config": dict(self.configs[0]) if len(self.configs) == 1 else [dict(c) for c in self.configs],
            "sources": list(self.sources),
        }
        if self.pooled_over:
            d["pooled_over"] = list(self.pooled_over)
        reason = self.is_extreme()
        if reason:
            d["extreme"] = reason
        return d

    def __str__(self) -> str:
        base = f"{self.numerator}/{self.denominator} = {self.value*100:.2f}% [{self.unit}]"
        reason = self.is_extreme()
        return base + (f"  EXTREME: {reason}" if reason else "")


def load_jsonl(paths: Sequence[str]) -> list:
    """Rows plus the file each came from, so `sources` is never guessed."""
    out = []
    for p in paths:
        with open(p) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                r = json.loads(line)
                r.setdefault("_source_file", p)
                out.append(r)
    return out
