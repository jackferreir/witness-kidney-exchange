"""The singleton-sufficiency invariant: does a length-1 misreport always match the
best any misreport can do?

MEASURED RESULT (established elsewhere, not re-derived here): for the Boston
mechanism, over manipulable (instance, student) cases at 4 through 8 schools --
including m=8, where the 8 singleton reports are 0.007% of a 109,601-report
misreport space -- some SINGLETON misreport (a report naming exactly one school)
always achieves the BEST gain available from ANY misreport, not merely some gain.
100% in every generator configuration tested.

STRUCTURAL ARGUMENT (why it is a theorem for immediate acceptance with placement
off, not a curve fit): the other students' round-1 proposals to a school c do not
depend on what the target s reports. Under immediate acceptance, if s names c
first, s competes for c's seats in round 1; if s does not, round 1 fills c from
that same fixed pool and, because acceptances are irrevocable, those seats never
come back. So proposing to c in round 1 weakly dominates every other way of
reaching c, and the m singleton reports reveal exactly s's attainable set: the
best any misreport can do for s is the best a singleton can do for s.

SCOPE -- this is the load-bearing distinction in this module, get it exactly
right:

  * Boston (`boston_immediate_acceptance`) WITH PLACEMENT OFF: the argument
    above is a PROOF. A violation here means either the argument is wrong or
    this implementation of Boston is buggy -- either is worth catching
    immediately, so `assert_singleton_sufficiency` is a HARD ASSERTION in this
    regime, and `is_proved_regime` is the single place that says so.

  * Boston WITH PLACEMENT ON: the premise weakens. A failed singleton leaves s
    unmatched after the round-based procedure, and administrative placement can
    then seat s somewhere a longer report would not have reached (placement
    scans schools in a fixed declared order, independent of s's own report
    length). This was measured at 100% here too, but on few cases and WITHOUT a
    proof. So under placement on, the property is RECORDED, never asserted --
    callers use `check_instance` / `check_singleton_sufficiency` and accumulate,
    they do not call `assert_singleton_sufficiency` expecting it to hold as a
    theorem.

  * EVERY OTHER MECHANISM (plain `student_proposing_da`, `first_choice_bonus_da`,
    anything else registered in `witness.mechanisms`): this is an OBSERVATION
    with no proof behind it. It was measured to hold for `first_choice_bonus_da`
    too (100% over 121 cases), which suggests the property may be broader than
    immediate acceptance alone -- but that is not proved either. Record, never
    assert.

`is_proved_regime` is the single place that decides assert-vs-record, so this
three-way distinction cannot drift out of sync between callers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from witness.core import Market, Profile, position, strictly_prefers
from witness.errors import MechanismError
from witness.mechanisms import get_mechanism
from witness.search import misreport_space

#: The only mechanism name for which `is_proved_regime` can ever return True.
#: Matches the name Boston is registered under in `witness.mechanisms`
#: (`witness.boston._MECHANISM_NAME`) -- kept as a literal here, the same way
#: `witness.mechanisms` itself uses literal mechanism names at each
#: `register_mechanism` call, rather than importing a private module constant.
PROVED_MECHANISM = "boston_immediate_acceptance"

#: Matches `witness.boston.PLACEMENT_OFF` -- kept as a literal for the same
#: reason as `PROVED_MECHANISM` above (this module has no other dependency on
#: `witness.boston`, and duplicating one string constant is cheaper than an
#: import solely to avoid it).
_PLACEMENT_OFF = "off"

#: Default cap on the size of an enumerated misreport space, mirroring
#: `witness.search.DEFAULT_MAX_SPACE` -- see `misreport_space` for what
#: exceeding it does.
DEFAULT_MAX_SPACE = 200_000


@dataclass(frozen=True)
class SingletonCheck:
    """The singleton-sufficiency verdict for one (market, profile, target).

    `best_rank_any` / `best_rank_singleton` are positions in the target's own
    TRUTHFUL report (via `witness.core.position` -- `WORST` semantics for
    unmatched/unranked), never in the false report. Both are `None` when
    `manipulable` is False (there is nothing to rank). `best_rank_singleton`
    is `None` whenever no length-1 misreport is profitable at all, which can
    happen even when `manipulable` is True (some longer misreport helps, no
    singleton does) -- exactly the failure mode `holds` exists to catch.
    """

    target: str
    manipulable: bool
    best_rank_any: Optional[float]
    best_rank_singleton: Optional[float]
    best_misreports: "tuple[tuple[str, ...], ...]"
    holds: bool

    def to_dict(self) -> dict:
        return {
            "target": self.target,
            "manipulable": self.manipulable,
            "best_rank_any": self.best_rank_any,
            "best_rank_singleton": self.best_rank_singleton,
            "best_misreports": [list(r) for r in self.best_misreports],
            "holds": self.holds,
        }


def check_singleton_sufficiency(
    market: Market,
    profile: Profile,
    target: str,
    mechanism_name: str,
    config: object,
    *,
    max_space: int = DEFAULT_MAX_SPACE,
) -> SingletonCheck:
    """Exhaustively check whether some length-1 misreport achieves `target`'s
    best available gain, among ALL misreports in the declared report space.

    Improvement is judged ONLY by `target`'s TRUTHFUL report, via
    `witness.core.strictly_prefers` / `witness.core.position` -- never the
    false report, matching `witness.search`'s own rule 1. Raises `ValueError`
    (propagated straight from `witness.search.misreport_space`) if the report
    space exceeds `max_space`: this check is only meaningful where exhaustive
    enumeration is actually feasible.
    """
    profile.validate_against(market)
    spec = get_mechanism(mechanism_name)
    truthful_report = profile.report(target)

    truthful_assignment = spec.run(market, profile, config)
    truthful_outcome = truthful_assignment.of(target)

    space = misreport_space(market, target, truthful_report, max_space=max_space)

    manipulable = False
    best_rank_any: Optional[float] = None
    best_rank_singleton: Optional[float] = None
    best_misreports: list = []

    for false_report in space:
        misreport_profile = profile.with_report(target, false_report)
        false_assignment = spec.run(market, misreport_profile, config)
        false_outcome = false_assignment.of(target)

        if not strictly_prefers(truthful_report, false_outcome, truthful_outcome):
            continue

        manipulable = True
        rank = position(truthful_report, false_outcome)

        if best_rank_any is None or rank < best_rank_any:
            best_rank_any = rank
            best_misreports = [false_report]
        elif rank == best_rank_any:
            best_misreports.append(false_report)

        if len(false_report) == 1:
            if best_rank_singleton is None or rank < best_rank_singleton:
                best_rank_singleton = rank

    holds = (not manipulable) or (best_rank_singleton == best_rank_any)

    return SingletonCheck(
        target=target,
        manipulable=manipulable,
        best_rank_any=best_rank_any,
        best_rank_singleton=best_rank_singleton,
        best_misreports=tuple(best_misreports),
        holds=holds,
    )


def check_instance(
    market: Market,
    profile: Profile,
    mechanism_name: str,
    config: object,
    *,
    max_space: int = DEFAULT_MAX_SPACE,
) -> "tuple[SingletonCheck, ...]":
    """One `SingletonCheck` per student, in `market.students` order."""
    profile.validate_against(market)
    return tuple(
        check_singleton_sufficiency(
            market, profile, s, mechanism_name, config, max_space=max_space
        )
        for s in market.students
    )


def assert_singleton_sufficiency(
    market: Market,
    profile: Profile,
    mechanism_name: str,
    config: object,
    *,
    max_space: int = DEFAULT_MAX_SPACE,
) -> None:
    """Raise `MechanismError`, naming the full failing case, if any student's
    `SingletonCheck.holds` is False.

    Intended for the PROVED regime only (see the module docstring and
    `is_proved_regime`) -- calling this outside that regime treats a merely
    OBSERVED property as though it were a theorem, which is exactly the
    scope confusion this module exists to prevent.
    """
    checks = check_instance(market, profile, mechanism_name, config, max_space=max_space)
    for check in checks:
        if check.holds:
            continue
        truthful_report = profile.report(check.target)
        raise MechanismError(
            f"singleton sufficiency violated for target {check.target!r} under "
            f"mechanism {mechanism_name!r} with config {config.to_dict()!r}: "
            f"{check.target}'s truthful report is {truthful_report!r}; the best "
            f"rank ANY misreport achieved (by {check.target}'s own truthful "
            f"ranking) was {check.best_rank_any!r}, achieved by misreport(s) "
            f"{check.best_misreports!r}, but the best rank achieved by any "
            f"SINGLETON misreport was only {check.best_rank_singleton!r}. "
            f"market={market.to_dict()!r} profile={profile.to_dict()!r}"
        )


def is_proved_regime(mechanism_name: str, config: object) -> bool:
    """True ONLY for Boston (`boston_immediate_acceptance`) with administrative
    placement OFF -- the single regime in which singleton sufficiency is a
    proof, not an observation (see the module docstring's SCOPE section). This
    is the one place that decision is made, so callers never have to
    re-derive or duplicate it.
    """
    if mechanism_name != PROVED_MECHANISM:
        return False
    placement = getattr(config, "placement", None)
    return placement == _PLACEMENT_OFF
