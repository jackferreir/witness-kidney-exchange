"""The manipulation search: exhaustive and complete over the declared report space.

Correct and complete beats fast here -- nothing in this module prunes the search. The
whole point of a *witness* is that its counterexample can be independently replayed and
checked (see `witness.mechanisms`, `witness.journal`, `witness.replay`), so the search
that produced it must be exhaustive over what a strategic student could actually submit,
not a heuristic that might miss one.

RULES THIS SEARCH OBEYS (the epistemics of the whole project):

  1. Improvement is judged ONLY by the target's TRUTHFUL report, via
     `witness.core.strictly_prefers(truthful_report, false_outcome, truthful_outcome)`.
     Never by the false report. Strict preference only -- ties are not manipulations.
  2. Only the TARGET's report changes between the truthful run and a misreport run.
     Every other participant's report is byte-identical; this is asserted, not just
     assumed.
  3. Both runs call `mechanism.run(market, profile, config)`. Priorities are never
     pre-resolved and shared across the two runs -- see the interface note in
     `witness.mechanisms`.
  4. The truthful run is computed once per (market, profile, mechanism, config) and
     reused across every candidate misreport for that target. It is recomputed a second
     time solely to assert it is deterministic.
  5. Enumeration order is canonical and deterministic (see `ordered_subsets`), so
     `find_manipulation` returns the SAME witness on every run, in every process.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import permutations
from typing import Mapping, Optional, Sequence

from witness.core import Assigned, Market, Profile, content_hash, strictly_prefers
from witness.da import Assignment
from witness.depth import ReportDepth, report_depth
from witness.errors import ModelError
from witness.mechanisms import get_mechanism

#: Default cap on the size of an enumerated misreport space; see `misreport_space`.
DEFAULT_MAX_SPACE = 200_000


def ordered_subsets(items: Sequence[str]) -> tuple[tuple[str, ...], ...]:
    """Every ordered subset of `items`, including the empty tuple.

    Canonical, deterministic order: by length ascending, then lexicographic by index
    in `items` (i.e. `itertools.permutations(items, r)`'s own order, which is
    lexicographic in the *positions* of `items`, not in their values -- so this is
    stable even when `items` is not sorted). For 3 items this yields 16 tuples
    (1 + 3 + 6 + 6); for 4 items, 65 (1 + 4 + 12 + 24 + 24).
    """
    items = tuple(items)
    n = len(items)
    out: list[tuple[str, ...]] = []
    for r in range(n + 1):
        out.extend(permutations(items, r))
    return tuple(out)


def misreport_space(
    market: Market,
    target: str,
    truthful_report: Sequence[str],
    *,
    max_space: int = DEFAULT_MAX_SPACE,
) -> tuple[tuple[str, ...], ...]:
    """Every legal misreport `target` could submit instead of `truthful_report`.

    This is every ordered subset of ALL of `market.schools` -- not just schools
    `target` truthfully finds acceptable. A misreport may legally list a school that
    is unacceptable in `target`'s truthful ranking (this is explicitly in scope: a
    truncated list is a strategic choice, not a constraint on what can be
    submitted). The truthful report itself is excluded.

    Raises `ValueError` before doing any enumeration work if the number of ordered
    subsets of `market.schools` would exceed `max_space`.
    """
    schools = market.schools
    n = len(schools)
    total = sum(math.perm(n, k) for k in range(n + 1))
    if total > max_space:
        raise ValueError(
            f"misreport_space: {total} ordered subsets of {n} schools "
            f"(for target {target!r}) exceeds max_space={max_space}"
        )
    truthful = tuple(truthful_report)
    return tuple(r for r in ordered_subsets(schools) if r != truthful)


def _rank_or_none(report: Sequence[str], outcome: Assigned) -> Optional[int]:
    """`outcome`'s index in `report`, or `None` if unmatched or unranked (both
    are WORST -- see `witness.core.position`)."""
    if outcome is None:
        return None
    try:
        return tuple(report).index(outcome)
    except ValueError:
        return None


def _describe_rank(rank: Optional[int]) -> str:
    return "WORST (unmatched or unranked)" if rank is None else f"rank {rank}"


def _preference_proof(
    target: str,
    truthful_report: Sequence[str],
    truthful_outcome: Assigned,
    false_outcome: Assigned,
    truthful_rank: Optional[int],
    false_rank: Optional[int],
) -> str:
    return (
        f"{target}'s truthful ranking is {list(truthful_report)!r}: under that ranking, "
        f"the truthful-report outcome {truthful_outcome!r} is at "
        f"{_describe_rank(truthful_rank)} while the false-report outcome "
        f"{false_outcome!r} is at {_describe_rank(false_rank)}, so {target} strictly "
        f"prefers the false-report outcome to the truthful-report outcome."
    )


@dataclass(frozen=True)
class Witness:
    """A single confirmed manipulation, in the exact schema another agent's replay
    verifier reads. Every field is a plain JSON-able type (or a tuple of them)."""

    witness_version: int
    mechanism: str
    config: Mapping
    market: Mapping
    truthful_profile: Mapping
    target: str
    truthful_report: tuple[str, ...]
    false_report: tuple[str, ...]
    truthful_assignment: Mapping
    false_assignment: Mapping
    truthful_outcome: Assigned
    false_outcome: Assigned
    truthful_outcome_rank: Optional[int]
    false_outcome_rank: Optional[int]
    preference_proof: str
    depth: ReportDepth
    witness_id: str

    def to_dict(self) -> dict:
        return {
            "witness_version": self.witness_version,
            "mechanism": self.mechanism,
            "config": dict(self.config),
            "market": dict(self.market),
            "truthful_profile": dict(self.truthful_profile),
            "target": self.target,
            "truthful_report": list(self.truthful_report),
            "false_report": list(self.false_report),
            "truthful_assignment": dict(self.truthful_assignment),
            "false_assignment": dict(self.false_assignment),
            "truthful_outcome": self.truthful_outcome,
            "false_outcome": self.false_outcome,
            "truthful_outcome_rank": self.truthful_outcome_rank,
            "false_outcome_rank": self.false_outcome_rank,
            "preference_proof": self.preference_proof,
            "depth": self.depth.to_dict(),
            "witness_id": self.witness_id,
        }

    @staticmethod
    def from_dict(d: Mapping) -> "Witness":
        return Witness(
            witness_version=d["witness_version"],
            mechanism=d["mechanism"],
            config=dict(d["config"]),
            market=dict(d["market"]),
            truthful_profile=dict(d["truthful_profile"]),
            target=d["target"],
            truthful_report=tuple(d["truthful_report"]),
            false_report=tuple(d["false_report"]),
            truthful_assignment=dict(d["truthful_assignment"]),
            false_assignment=dict(d["false_assignment"]),
            truthful_outcome=d["truthful_outcome"],
            false_outcome=d["false_outcome"],
            truthful_outcome_rank=d["truthful_outcome_rank"],
            false_outcome_rank=d["false_outcome_rank"],
            preference_proof=d["preference_proof"],
            depth=ReportDepth.from_dict(d["depth"]),
            witness_id=d["witness_id"],
        )


def _build_witness(
    *,
    market: Market,
    truthful_profile: Profile,
    target: str,
    mechanism_name: str,
    config: object,
    truthful_report: tuple[str, ...],
    false_report: tuple[str, ...],
    truthful_assignment: Assignment,
    false_assignment: Assignment,
    truthful_outcome: Assigned,
    false_outcome: Assigned,
) -> Witness:
    truthful_rank = _rank_or_none(truthful_report, truthful_outcome)
    false_rank = _rank_or_none(truthful_report, false_outcome)
    proof = _preference_proof(
        target, truthful_report, truthful_outcome, false_outcome, truthful_rank, false_rank
    )
    # `report_depth` is purely descriptive -- it measures how far `false_report`
    # sits from `truthful_report` for later analysis (see `witness.depth`), and
    # never influences which misreport was found or how `find_manipulation`'s
    # canonical enumeration order proceeds.
    depth = report_depth(truthful_report, false_report)
    base = {
        "witness_version": 1,
        "mechanism": mechanism_name,
        "config": config.to_dict(),
        "market": market.to_dict(),
        "truthful_profile": truthful_profile.to_dict(),
        "target": target,
        "truthful_report": list(truthful_report),
        "false_report": list(false_report),
        "truthful_assignment": truthful_assignment.to_dict(),
        "false_assignment": false_assignment.to_dict(),
        "truthful_outcome": truthful_outcome,
        "false_outcome": false_outcome,
        "truthful_outcome_rank": truthful_rank,
        "false_outcome_rank": false_rank,
        "preference_proof": proof,
        "depth": depth.to_dict(),
    }
    witness_id = content_hash(base)
    full = dict(base)
    full["witness_id"] = witness_id
    return Witness.from_dict(full)


def _check_mechanism_config_agreement(mechanism_name: str, config: object) -> None:
    """Fail loudly, at search time, if `config`'s own idea of which mechanism
    it belongs to disagrees with `mechanism_name`.

    This guard exists because a config whose mechanism identity disagrees
    with the mechanism actually run produces witnesses that fail replay --
    `config.to_dict()` is embedded verbatim in every `Witness` (see
    `_build_witness`), and `witness.replay.verify_witness` independently
    checks that `config["mechanism"]` agrees with the witness's top-level
    `"mechanism"` field. We discovered this end-to-end (a real witness from
    `first_choice_bonus_da`, produced with a `DAConfig` that still claimed
    "student_proposing_da", was rejected on replay), not from any unit test --
    so a search that is about to build an unreplayable witness raises here
    instead of silently doing so.
    """
    config_mechanism = config.to_dict().get("mechanism")
    if config_mechanism != mechanism_name:
        raise ModelError(
            f"config.to_dict()['mechanism'] is {config_mechanism!r}, which "
            f"disagrees with the mechanism actually being searched, "
            f"{mechanism_name!r}; the resulting witness would embed a config "
            f"claiming the wrong mechanism and would fail replay "
            f"(witness.replay.verify_witness check 2), so refusing to search"
        )


def _truthful_run_with_determinism_check(
    spec, market: Market, profile: Profile, config: object
) -> Assignment:
    """Run the mechanism twice on the identical truthful inputs and assert
    agreement (rule 4), returning the (shared) result."""
    first = spec.run(market, profile, config)
    second = spec.run(market, profile, config)
    if first != second:
        raise ModelError(
            f"mechanism {spec.name!r} is not deterministic: two runs on the "
            f"identical truthful (market, profile, config) produced different "
            f"assignments {first.to_dict()!r} vs {second.to_dict()!r}"
        )
    return first


def _search_target(
    market: Market,
    truthful_profile: Profile,
    target: str,
    mechanism_name: str,
    config: object,
    *,
    stop_at_first: bool,
) -> tuple[Witness, ...]:
    spec = get_mechanism(mechanism_name)
    _check_mechanism_config_agreement(mechanism_name, config)
    truthful_profile.validate_against(market)
    truthful_report = truthful_profile.report(target)

    truthful_assignment = _truthful_run_with_determinism_check(
        spec, market, truthful_profile, config
    )
    truthful_outcome = truthful_assignment.of(target)

    witnesses: list[Witness] = []
    for false_report in misreport_space(market, target, truthful_report):
        misreport_profile = truthful_profile.with_report(target, false_report)

        # Rule 2: only `target`'s report may differ from the truthful profile.
        for s in market.students:
            if s == target:
                continue
            assert misreport_profile.report(s) == truthful_profile.report(s), (
                f"misreport for {target!r} perturbed {s!r}'s report: "
                f"{misreport_profile.report(s)!r} != {truthful_profile.report(s)!r}"
            )

        false_assignment = spec.run(market, misreport_profile, config)
        false_outcome = false_assignment.of(target)

        if strictly_prefers(truthful_report, false_outcome, truthful_outcome):
            witnesses.append(
                _build_witness(
                    market=market,
                    truthful_profile=truthful_profile,
                    target=target,
                    mechanism_name=mechanism_name,
                    config=config,
                    truthful_report=truthful_report,
                    false_report=false_report,
                    truthful_assignment=truthful_assignment,
                    false_assignment=false_assignment,
                    truthful_outcome=truthful_outcome,
                    false_outcome=false_outcome,
                )
            )
            if stop_at_first:
                break
    return tuple(witnesses)


def find_manipulation(
    market: Market,
    truthful_profile: Profile,
    target: str,
    mechanism_name: str,
    config: object,
) -> Optional[Witness]:
    """The first profitable misreport for `target`, in canonical enumeration
    order, or `None` if none exists in the declared report space."""
    found = _search_target(
        market, truthful_profile, target, mechanism_name, config, stop_at_first=True
    )
    return found[0] if found else None


def find_all_manipulations(
    market: Market,
    truthful_profile: Profile,
    target: str,
    mechanism_name: str,
    config: object,
) -> tuple[Witness, ...]:
    """Every profitable misreport for `target`, in canonical enumeration order."""
    return _search_target(
        market, truthful_profile, target, mechanism_name, config, stop_at_first=False
    )


def search_all_students(
    market: Market,
    truthful_profile: Profile,
    mechanism_name: str,
    config: object,
) -> tuple[Witness, ...]:
    """The first manipulation per student, iterating `market.students` in their
    declared order. A student with no profitable misreport contributes nothing."""
    _check_mechanism_config_agreement(mechanism_name, config)
    truthful_profile.validate_against(market)
    witnesses: list[Witness] = []
    for s in market.students:
        w = find_manipulation(market, truthful_profile, s, mechanism_name, config)
        if w is not None:
            witnesses.append(w)
    return tuple(witnesses)
