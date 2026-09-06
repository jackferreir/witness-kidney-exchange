"""Boston mechanism / immediate acceptance.

Implemented directly from the published algorithm: Abdulkadiroglu & Sonmez
(2003), "School Choice: A Mechanism Design Approach", American Economic
Review 93(3) -- the paper that gave the "Boston mechanism" its name and its
canonical description as an immediate-acceptance procedure. The citation
below is for the CORE mechanism only (the round structure, immediate and
irrevocable acceptance); see the ADMINISTRATIVE PLACEMENT section further
down for what is and is not attributed to that paper.

The algorithm, verbatim in structure:

    Round k. Every student not yet assigned proposes to the k-th school on
    their submitted list. Each school considers ONLY that round's proposers
    (never anyone from an earlier round -- there is no holding), rejects any
    it finds unacceptable, and from the rest accepts the highest-priority
    proposers up to its REMAINING capacity. Those acceptances are FINAL: a
    school never releases a seat once given, and an accepted student can
    never be displaced by a higher-priority student who proposes later. A
    student whose list is exhausted before being assigned ends unmatched.
    Terminate when no student proposes.

DECLARED CONVENTION (this is load-bearing and has its own test,
`test_convention_ab_vs_skip_full`): in round k, a student proposes to their
k-th listed school EVEN IF THAT SCHOOL IS ALREADY FULL. The proposal is
rejected (`rejected_as_full`) and the round is consumed regardless -- the
student does NOT get to try their (k+1)-th choice until round k+1. This is
the Abdulkadiroglu & Sonmez (2003) convention: "propose to the next school on
the list," full or not, one school consumed per round.

The alternative "skip-full" convention -- skip any already-full school and
propose to the next listed school that still has a seat, all within the same
round -- is NOT a flag on this implementation and never will be: it is a
DIFFERENT MECHANISM that can and does produce different final assignments
(see the convention test below for a concrete instance). Do not add a
"skip_full" option here; implement it, if ever needed, as its own function.

CITATION DISCIPLINE: Abdulkadiroglu & Sonmez (2003) is cited for the core
round-based immediate-acceptance mechanism above ONLY. We have not verified
against any primary source what the historical Boston Public Schools
assignment system actually did administratively with leftover seats once the
round-based procedure stopped producing proposals, so we make NO claim of
historical fidelity there. The administrative placement step below is OUR
OWN MODELING CHOICE, documented as such.

ADMINISTRATIVE PLACEMENT (`BostonConfig.placement`, our modeling choice, not
A&S, not claimed historically faithful):

    Only when `placement == PLACEMENT_ON`, run AFTER every round above has
    finished (i.e. after no student proposes). For each still-unmatched
    student, in `placement_student_order` order (currently only
    `PLACEMENT_DECLARED_STUDENTS`, meaning `Market.students` order): scan
    schools in `placement_school_order` order (currently only
    `PLACEMENT_DECLARED_SCHOOLS`, meaning `Market.schools` order); place the
    student in the FIRST school that has a remaining seat and -- when
    `placement_acceptability == ACCEPTABILITY_BINDS` -- finds the student
    acceptable (`priorities.rank(c, s) is not None`). Under
    `ACCEPTABILITY_IGNORED`, remaining capacity is the only constraint;
    acceptability is overridden. If NO school qualifies, the student stays
    unmatched -- this must not crash and must not force an assignment. Both
    `placement_acceptability` variants are real, selectable configurations;
    neither is hardcoded as "the" behavior.

    Because placement can seat a student at a school absent from their own
    report (always true under `ACCEPTABILITY_IGNORED`, and also possible in
    spirit even under `ACCEPTABILITY_BINDS` since acceptability to the school
    says nothing about the student's own preferences), placement CAN break
    individual rationality by design. That is expected and is asserted
    directly in the hand-worked tests, not treated as a bug.

Two determinism rules hold, matching the rest of this package:

  * No outcome-affecting iteration is over a dict or a set: rounds iterate
    `market.students` for proposers and `market.schools` for evaluation, and
    placement iterates `market.students` then `market.schools` explicitly.
  * Within a school, proposers are ordered by the strict resolved priority
    rank (`ResolvedPriorities.rank`), which has no residual ties.

Termination: a round consumes at least one item from some student's
remaining list-position (every free student advances `next_choice` by
exactly one per round they participate in), and there are only
`len(market.schools)` possible list positions, so the number of rounds is
bounded by `len(market.schools)`. Exceeding that bound is a bug and raises
`MechanismError` rather than looping.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Optional

from witness.core import (
    Assigned,
    Market,
    MechanismConfig,
    Profile,
    ResolvedPriorities,
    resolve_priorities,
)
from witness.da import Assignment, build_assignment
from witness.errors import MechanismError, ModelError

#: Administrative placement step is disabled; unmatched-after-rounds students
#: stay unmatched.
PLACEMENT_OFF = "off"

#: Administrative placement step runs after the round-based procedure ends.
PLACEMENT_ON = "on"

_PLACEMENT_MODES = (PLACEMENT_OFF, PLACEMENT_ON)

#: Placement respects school acceptability: a student is only placed at a
#: school that finds them acceptable.
ACCEPTABILITY_BINDS = "binds"

#: Placement ignores school acceptability: only remaining capacity matters.
ACCEPTABILITY_IGNORED = "ignored"

_ACCEPTABILITY_MODES = (ACCEPTABILITY_BINDS, ACCEPTABILITY_IGNORED)

#: Unmatched students are placed in `Market.students` order.
PLACEMENT_DECLARED_STUDENTS = "declared_students"

_STUDENT_ORDER_MODES = (PLACEMENT_DECLARED_STUDENTS,)

#: Candidate schools are scanned in `Market.schools` order.
PLACEMENT_DECLARED_SCHOOLS = "declared_schools"

_SCHOOL_ORDER_MODES = (PLACEMENT_DECLARED_SCHOOLS,)

#: Explicit mechanism name, mirroring `witness.da.DAConfig.mechanism`.
_MECHANISM_NAME = "boston_immediate_acceptance"


@dataclass(frozen=True)
class BostonConfig(MechanismConfig):
    """`MechanismConfig` plus Boston's administrative-placement parameters.

    Deliberately subclasses `MechanismConfig`, NOT `DAConfig`: Boston has no
    `proposal_policy` to configure -- rounds are inherently synchronized (the
    whole point of "immediate acceptance" is that a round is a round, not a
    sequence of individual proposals with an order that could vary).

    `mechanism` is an explicit, validated field for the same reason
    `DAConfig.mechanism` is: see that class's docstring. It must never be a
    hardcoded literal at a use site.
    """

    mechanism: str = _MECHANISM_NAME
    placement: str = PLACEMENT_OFF
    placement_acceptability: str = ACCEPTABILITY_BINDS
    placement_student_order: str = PLACEMENT_DECLARED_STUDENTS
    placement_school_order: str = PLACEMENT_DECLARED_SCHOOLS

    def __post_init__(self) -> None:
        super().__post_init__()
        if not isinstance(self.mechanism, str) or not self.mechanism:
            raise ModelError(
                f"mechanism must be a non-empty string, got {self.mechanism!r}"
            )
        if self.placement not in _PLACEMENT_MODES:
            raise ModelError(
                f"placement must be one of {_PLACEMENT_MODES}, got {self.placement!r}"
            )
        if self.placement_acceptability not in _ACCEPTABILITY_MODES:
            raise ModelError(
                f"placement_acceptability must be one of {_ACCEPTABILITY_MODES}, "
                f"got {self.placement_acceptability!r}"
            )
        if self.placement_student_order not in _STUDENT_ORDER_MODES:
            raise ModelError(
                f"placement_student_order must be one of {_STUDENT_ORDER_MODES}, "
                f"got {self.placement_student_order!r}"
            )
        if self.placement_school_order not in _SCHOOL_ORDER_MODES:
            raise ModelError(
                f"placement_school_order must be one of {_SCHOOL_ORDER_MODES}, "
                f"got {self.placement_school_order!r}"
            )

    def to_dict(self) -> dict:
        data = super().to_dict()
        data["mechanism"] = self.mechanism
        data["placement"] = self.placement
        data["placement_acceptability"] = self.placement_acceptability
        data["placement_student_order"] = self.placement_student_order
        data["placement_school_order"] = self.placement_school_order
        return data

    @classmethod
    def from_dict(cls, data: Mapping) -> "BostonConfig":
        base = MechanismConfig.from_dict(data)
        return cls(
            tiebreak=base.tiebreak,
            unlisted_student_policy=base.unlisted_student_policy,
            mechanism=data.get("mechanism", _MECHANISM_NAME),
            placement=data.get("placement", PLACEMENT_OFF),
            placement_acceptability=data.get(
                "placement_acceptability", ACCEPTABILITY_BINDS
            ),
            placement_student_order=data.get(
                "placement_student_order", PLACEMENT_DECLARED_STUDENTS
            ),
            placement_school_order=data.get(
                "placement_school_order", PLACEMENT_DECLARED_SCHOOLS
            ),
        )


@dataclass(frozen=True)
class BostonRound:
    """One round of the algorithm, recorded for inspection.

    The three rejection categories are distinct and must never be merged:
    `rejected_as_unacceptable` (the school's priority classes never listed
    this student), `rejected_as_full` (the school had zero remaining seats
    before even looking at acceptability), and `rejected_by_competition`
    (acceptable, but outranked by other proposers for the remaining seats).
    `accepted` proposals are FINAL -- there is no later round in which they
    can be undone.
    """

    index: int
    proposals: tuple[tuple[str, str], ...]
    rejected_as_unacceptable: tuple[tuple[str, str], ...]
    rejected_as_full: tuple[tuple[str, str], ...]
    rejected_by_competition: tuple[tuple[str, str], ...]
    accepted: tuple[tuple[str, str], ...]
    seats_remaining_after: tuple[tuple[str, int], ...]

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "proposals": [list(p) for p in self.proposals],
            "rejected_as_unacceptable": [list(p) for p in self.rejected_as_unacceptable],
            "rejected_as_full": [list(p) for p in self.rejected_as_full],
            "rejected_by_competition": [list(p) for p in self.rejected_by_competition],
            "accepted": [list(p) for p in self.accepted],
            "seats_remaining_after": [list(p) for p in self.seats_remaining_after],
        }


@dataclass(frozen=True)
class BostonResult:
    assignment: Assignment
    rounds: tuple[BostonRound, ...]
    n_proposals: int
    priorities: ResolvedPriorities
    placements: tuple[tuple[str, str], ...]
    placement_unplaced: tuple[str, ...]

    def format_trace(self) -> str:
        lines = []
        for rd in self.rounds:
            lines.append(f"round {rd.index}:")
            lines.append(
                "  proposals: " + ", ".join(f"{s}->{c}" for s, c in rd.proposals)
            )
            if rd.rejected_as_unacceptable:
                lines.append(
                    "  rejected (unacceptable): "
                    + ", ".join(f"{s} by {c}" for s, c in rd.rejected_as_unacceptable)
                )
            if rd.rejected_as_full:
                lines.append(
                    "  rejected (full): "
                    + ", ".join(f"{s} by {c}" for s, c in rd.rejected_as_full)
                )
            if rd.rejected_by_competition:
                lines.append(
                    "  rejected (competition): "
                    + ", ".join(f"{s} by {c}" for s, c in rd.rejected_by_competition)
                )
            lines.append(
                "  accepted: " + ", ".join(f"{s}->{c}" for s, c in rd.accepted)
            )
            lines.append(
                "  seats remaining: "
                + ", ".join(f"{c}={n}" for c, n in rd.seats_remaining_after)
            )
        lines.append(f"total proposals: {self.n_proposals}")
        if self.placements:
            lines.append(
                "placements: " + ", ".join(f"{s}->{c}" for s, c in self.placements)
            )
        if self.placement_unplaced:
            lines.append("placement unplaced: " + ", ".join(self.placement_unplaced))
        return "\n".join(lines)


def boston_immediate_acceptance(
    market: Market,
    profile: Profile,
    config: Optional[BostonConfig] = None,
    *,
    priorities: Optional[ResolvedPriorities] = None,
) -> BostonResult:
    """Run Boston / immediate acceptance and return the matching plus trace.

    `priorities` may be passed in to reuse an already-resolved order, exactly
    as `witness.da.deferred_acceptance` allows -- see that function's
    docstring. Resolving priorities is profile-free (`witness.core`'s module
    docstring), so passing it or recomputing it gives the same orders either
    way.
    """
    config = config if config is not None else BostonConfig()
    profile.validate_against(market)
    if priorities is None:
        priorities = resolve_priorities(market, config)

    # Per-student state. Read only via market.students, never iterated for order.
    report = {s: profile.report(s) for s in market.students}
    next_choice = {s: 0 for s in market.students}
    assigned: dict[str, Assigned] = {s: None for s in market.students}
    remaining: dict[str, int] = {c: market.capacity(c) for c in market.schools}

    # A round consumes one list-position per participating student; there are
    # only len(market.schools) possible positions.
    max_rounds = len(market.schools)
    rounds: list[BostonRound] = []
    n_proposals = 0
    round_index = 0

    while True:
        # Every student not yet assigned, whose list is not exhausted,
        # proposes -- even to a school already full (the declared A&S
        # convention; see the module docstring).
        proposers = tuple(
            s
            for s in market.students
            if assigned[s] is None and next_choice[s] < len(report[s])
        )
        if not proposers:
            break

        round_index += 1
        if round_index > max_rounds:
            raise MechanismError(
                f"Boston ran {round_index} rounds, exceeding the algorithm's own "
                f"bound of {max_rounds} (= number of schools): some student "
                f"proposed to more schools than exist"
            )

        proposals: list[tuple[str, str]] = []
        for s in proposers:
            c = report[s][next_choice[s]]
            next_choice[s] += 1
            proposals.append((s, c))
            n_proposals += 1

        rejected_unacceptable: list[tuple[str, str]] = []
        rejected_full: list[tuple[str, str]] = []
        rejected_competition: list[tuple[str, str]] = []
        accepted: list[tuple[str, str]] = []

        # Schools evaluate ONLY this round's proposers. Iterate
        # market.schools explicitly; within a school, order by the strict
        # priority rank, which has no ties.
        for c in market.schools:
            applicants = tuple(s for s, target in proposals if target == c)
            if not applicants:
                continue
            if remaining[c] <= 0:
                for s in applicants:
                    rejected_full.append((s, c))
                continue
            acceptable = []
            for s in applicants:
                if priorities.rank(c, s) is None:
                    rejected_unacceptable.append((s, c))
                else:
                    acceptable.append(s)
            if not acceptable:
                continue
            ranked = sorted(acceptable, key=lambda s: priorities.rank(c, s))
            keep = tuple(ranked[: remaining[c]])
            drop = tuple(ranked[remaining[c] :])
            for s in keep:
                assigned[s] = c
                accepted.append((s, c))
            for s in drop:
                rejected_competition.append((s, c))
            remaining[c] -= len(keep)

        rounds.append(
            BostonRound(
                index=round_index,
                proposals=tuple(proposals),
                rejected_as_unacceptable=tuple(rejected_unacceptable),
                rejected_as_full=tuple(rejected_full),
                rejected_by_competition=tuple(rejected_competition),
                accepted=tuple(accepted),
                seats_remaining_after=tuple((c, remaining[c]) for c in market.schools),
            )
        )

    placements: list[tuple[str, str]] = []
    placement_unplaced: list[str] = []
    if config.placement == PLACEMENT_ON:
        # PLACEMENT_DECLARED_STUDENTS / PLACEMENT_DECLARED_SCHOOLS are the
        # only configured orders: Market.students / Market.schools, in that
        # order -- both explicit, caller-declared tuples, never a dict/set.
        for s in market.students:
            if assigned[s] is not None:
                continue
            placed = None
            for c in market.schools:
                if remaining[c] <= 0:
                    continue
                if (
                    config.placement_acceptability == ACCEPTABILITY_BINDS
                    and priorities.rank(c, s) is None
                ):
                    continue
                placed = c
                break
            if placed is not None:
                assigned[s] = placed
                remaining[placed] -= 1
                placements.append((s, placed))
            else:
                placement_unplaced.append(s)

    # Administrative placement, when it ignores acceptability, deliberately
    # seats students at schools that find them unacceptable (see the module
    # docstring's ADMINISTRATIVE PLACEMENT section). That is the ONLY
    # configuration in which an unranked hold is intended, so it is the ONLY
    # configuration that relaxes build_assignment's strict default -- every
    # other Boston configuration (including placement="on" with
    # placement_acceptability="binds") keeps allow_unranked=False, so a
    # genuine bug in the round-based procedure still raises MechanismError
    # instead of being silently absorbed into roster ordering.
    allow_unranked = (
        config.placement == PLACEMENT_ON
        and config.placement_acceptability == ACCEPTABILITY_IGNORED
    )
    assignment = build_assignment(
        market, priorities, assigned, allow_unranked=allow_unranked
    )
    return BostonResult(
        assignment=assignment,
        rounds=tuple(rounds),
        n_proposals=n_proposals,
        priorities=priorities,
        placements=tuple(placements),
        placement_unplaced=tuple(placement_unplaced),
    )
