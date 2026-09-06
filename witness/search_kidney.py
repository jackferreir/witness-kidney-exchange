"""The manipulation search for the kidney-exchange mechanism
(`witness.kidney`), re-derived independently (not inherited from
`witness.search` or `witness.search_couples`), per REVIEWER.md's "re-derive,
don't inherit, for each new mechanism" -- the target here is a HOSPITAL
withholding a subset of ITS OWN pairs, a genuinely different strategic
shape from a student's false ranking or a couple's false joint ROL of pairs.

REPORT SPACE: `KIDNEY_EXCHANGE_SCOPE.md`'s own declared enumeration order
-- "fewer withheld pairs first, then ground-truth pair order" -- every
subset of a hospital's `k` owned pairs except full revelation itself
(`2**k - 1` candidates). `hospital_misreport_space` implements exactly that
order via `itertools.combinations` over withheld-count ascending, which
gives canonical, deterministic, declared-pair-order enumeration -- never
Python set/dict order.

WHAT COUNTS AS A MANIPULATION: `clear_kidney_exchange` never fails to
produce SOME outcome (there is no loop-detector / non-existence status in
this mechanism, unlike `witness.couples`), so every candidate misreport is
comparable -- no analogue of `witness.search_couples`'s STATUS_STABLE
filter is needed. A misreport is a manipulation iff the target hospital's
OWN utility (its own recipients transplanted, across both stages) is
STRICTLY GREATER under the false report than under full revelation --
never judged by any other hospital's utility, and never by anything other
than the hospital's own truthful accounting.

RULES INHERITED FROM THIS PROJECT'S OWN SEARCH DISCIPLINE:
  1. Only the target hospital's OWN report changes between the truthful and
     misreport profile -- every other hospital's report is asserted
     byte-identical.
  2. The truthful run is computed once and reused, and recomputed a second
     time solely to assert `clear_kidney_exchange` is deterministic.
  3. Enumeration order is canonical (see above), so a search returns the
     SAME witness on every run.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from typing import Mapping, Optional, Sequence

from witness.core import content_hash
from witness.errors import ModelError
from witness.kidney import KidneyConfig, KidneyMarket, KidneyProfile, clear_kidney_exchange

#: Default cap on `2**k` (`k` = a hospital's own pair count) the search will
#: exhaustively enumerate -- see the module docstring. `2**24` pairs owned
#: by one hospital is already an absurd single-hospital market for this
#: exhaustive regime; kept generous but real, per KIDNEY_EXCHANGE_SCOPE.md's
#: "a hard `max_report_space` guard must raise before enumeration when `2**k`
#: is too large."
DEFAULT_MAX_REPORT_SPACE = 2 ** 20


def hospital_misreport_space(
    market: KidneyMarket, hospital: str, truthful_report: Sequence[str], *, max_space: int = DEFAULT_MAX_REPORT_SPACE
) -> "tuple[tuple[str, ...], ...]":
    """Every legal report `hospital` could submit instead of
    `truthful_report`: every subset of its OWNED pairs except full
    revelation, in canonical "fewer withheld first, then ground-truth pair
    order" order (see module docstring)."""
    owned = market.pairs_of(hospital)
    k = len(owned)
    if 2 ** k > max_space:
        raise ValueError(
            f"hospital_misreport_space: hospital {hospital!r} owns {k} pairs (2**{k} = "
            f"{2 ** k} legal reports), exceeding max_space={max_space}"
        )
    truthful = tuple(truthful_report)
    candidates = []
    for n_withhold in range(0, k + 1):
        for withhold_combo in combinations(owned, n_withhold):
            withheld = set(withhold_combo)
            report = tuple(p for p in owned if p not in withheld)
            candidates.append(report)
    return tuple(r for r in candidates if r != truthful)


@dataclass(frozen=True)
class KidneyWitness:
    """A single confirmed hospital-withholding manipulation. Every field is
    a plain JSON-able type -- the schema `witness.replay_kidney.verify_witness`
    reads independently."""

    witness_version: int
    mechanism: str
    config: Mapping
    market: Mapping
    truthful_profile: Mapping
    target_hospital: str
    truthful_report: tuple[str, ...]
    false_report: tuple[str, ...]
    truthful_result: Mapping
    false_result: Mapping
    truthful_utility: int
    false_utility: int
    preference_proof: str
    witness_id: str

    def to_dict(self) -> dict:
        return {
            "witness_version": self.witness_version,
            "mechanism": self.mechanism,
            "config": dict(self.config),
            "market": dict(self.market),
            "truthful_profile": dict(self.truthful_profile),
            "target_hospital": self.target_hospital,
            "truthful_report": list(self.truthful_report),
            "false_report": list(self.false_report),
            "truthful_result": dict(self.truthful_result),
            "false_result": dict(self.false_result),
            "truthful_utility": self.truthful_utility,
            "false_utility": self.false_utility,
            "preference_proof": self.preference_proof,
            "witness_id": self.witness_id,
        }

    @staticmethod
    def from_dict(d: Mapping) -> "KidneyWitness":
        return KidneyWitness(
            witness_version=d["witness_version"],
            mechanism=d["mechanism"],
            config=dict(d["config"]),
            market=dict(d["market"]),
            truthful_profile=dict(d["truthful_profile"]),
            target_hospital=d["target_hospital"],
            truthful_report=tuple(d["truthful_report"]),
            false_report=tuple(d["false_report"]),
            truthful_result=dict(d["truthful_result"]),
            false_result=dict(d["false_result"]),
            truthful_utility=d["truthful_utility"],
            false_utility=d["false_utility"],
            preference_proof=d["preference_proof"],
            witness_id=d["witness_id"],
        )


def _run_twice_and_check_determinism(market: KidneyMarket, profile: KidneyProfile, config: KidneyConfig):
    first = clear_kidney_exchange(market, profile, config)
    second = clear_kidney_exchange(market, profile, config)
    if first != second:
        raise ModelError(
            "clear_kidney_exchange is not deterministic: two runs on the identical "
            f"truthful (market, profile, config) produced {first.to_dict()!r} vs {second.to_dict()!r}"
        )
    return first


def _assert_only_target_changed(truthful: KidneyProfile, misreport: KidneyProfile, hospital: str) -> None:
    for h, report in truthful.reports.items():
        if h == hospital:
            continue
        assert misreport.reports.get(h) == report, (
            f"misreport for hospital {hospital!r} perturbed hospital {h!r}'s report"
        )


def find_hospital_manipulation(
    market: KidneyMarket,
    truthful_profile: KidneyProfile,
    hospital: str,
    config: KidneyConfig,
    *,
    max_space: int = DEFAULT_MAX_REPORT_SPACE,
) -> Optional[KidneyWitness]:
    """The first profitable withholding report for `hospital`, in canonical
    enumeration order, or `None` if none exists in the declared report space."""
    truthful_profile.validate_against(market)
    truthful_report = truthful_profile.report(hospital)

    truthful_result = _run_twice_and_check_determinism(market, truthful_profile, config)
    truthful_utility = truthful_result.utility[hospital]

    for false_report in hospital_misreport_space(market, hospital, truthful_report, max_space=max_space):
        misreport_profile = truthful_profile.with_report(hospital, false_report)
        _assert_only_target_changed(truthful_profile, misreport_profile, hospital)

        false_result = clear_kidney_exchange(market, misreport_profile, config)
        false_utility = false_result.utility[hospital]

        if false_utility > truthful_utility:
            return _build_kidney_witness(
                market=market, truthful_profile=truthful_profile, hospital=hospital, config=config,
                truthful_report=truthful_report, false_report=false_report,
                truthful_result=truthful_result, false_result=false_result,
                truthful_utility=truthful_utility, false_utility=false_utility,
            )
    return None


def _build_kidney_witness(
    *, market, truthful_profile, hospital, config, truthful_report, false_report,
    truthful_result, false_result, truthful_utility, false_utility,
) -> KidneyWitness:
    proof = (
        f"hospital {hospital!r}'s truthful report is {list(truthful_report)!r} (all its own "
        f"pairs): under the full-revelation run its utility is {truthful_utility}, but "
        f"reporting only {list(false_report)!r} instead raises its utility to {false_utility} "
        f"-- strictly better for {hospital!r}, judged solely by its own recipient count."
    )
    base = {
        "witness_version": 1,
        "mechanism": config.mechanism,
        "config": config.to_dict(),
        "market": market.to_dict(),
        "truthful_profile": truthful_profile.to_dict(),
        "target_hospital": hospital,
        "truthful_report": list(truthful_report),
        "false_report": list(false_report),
        "truthful_result": truthful_result.to_dict(),
        "false_result": false_result.to_dict(),
        "truthful_utility": truthful_utility,
        "false_utility": false_utility,
        "preference_proof": proof,
    }
    witness_id = content_hash(base)
    full = dict(base)
    full["witness_id"] = witness_id
    return KidneyWitness.from_dict(full)


def find_best_hospital_manipulation(
    market: KidneyMarket,
    truthful_profile: KidneyProfile,
    hospital: str,
    config: KidneyConfig,
    *,
    max_space: int = DEFAULT_MAX_REPORT_SPACE,
) -> Optional[KidneyWitness]:
    """The BEST (maximum-gain) profitable withholding report for `hospital`,
    over the ENTIRE declared misreport space -- unlike `find_hospital_
    manipulation`, which stops at the first profitable one it finds in
    canonical (fewest-withheld-first) order and can therefore report a
    much smaller gain than what's actually achievable. Same exhaustiveness
    guarantee, same rules (only `hospital`'s report changes, judged solely
    by its own truthful utility) -- just doesn't stop early. Ties in gain
    are broken by canonical enumeration order (first such report found)."""
    truthful_profile.validate_against(market)
    truthful_report = truthful_profile.report(hospital)

    truthful_result = _run_twice_and_check_determinism(market, truthful_profile, config)
    truthful_utility = truthful_result.utility[hospital]

    best_gain = 0
    best = None
    for false_report in hospital_misreport_space(market, hospital, truthful_report, max_space=max_space):
        misreport_profile = truthful_profile.with_report(hospital, false_report)
        _assert_only_target_changed(truthful_profile, misreport_profile, hospital)

        false_result = clear_kidney_exchange(market, misreport_profile, config)
        false_utility = false_result.utility[hospital]
        gain = false_utility - truthful_utility
        if gain > best_gain:
            best_gain = gain
            best = _build_kidney_witness(
                market=market, truthful_profile=truthful_profile, hospital=hospital, config=config,
                truthful_report=truthful_report, false_report=false_report,
                truthful_result=truthful_result, false_result=false_result,
                truthful_utility=truthful_utility, false_utility=false_utility,
            )
    return best


def search_all_hospitals(
    market: KidneyMarket,
    truthful_profile: KidneyProfile,
    config: KidneyConfig,
    *,
    max_space: int = DEFAULT_MAX_REPORT_SPACE,
) -> "tuple[KidneyWitness, ...]":
    """The first manipulation per hospital, iterating `market.hospitals` in
    declared order. A hospital with no profitable withholding contributes
    nothing -- mirrors `witness.search.search_all_students`."""
    truthful_profile.validate_against(market)
    witnesses: list[KidneyWitness] = []
    for h in market.hospitals:
        w = find_hospital_manipulation(market, truthful_profile, h, config, max_space=max_space)
        if w is not None:
            witnesses.append(w)
    return tuple(witnesses)
