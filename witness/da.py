"""Student-proposing Deferred Acceptance.

Implemented directly from the published algorithm: Gale & Shapley (1962),
"College Admissions and the Stability of Marriage", in the many-to-one form
with school capacities q_c and possibly-truncated student lists (Roth 1985).

The algorithm, verbatim in structure:

    Step k. Each student not currently held by any school, and who has not yet
    proposed to every school on their list, proposes to the most-preferred
    school on their list to which they have not yet proposed. Each school
    considers the students it currently holds together with the new proposers,
    rejects any that are unacceptable to it, and from the rest holds the q_c
    most-preferred by its priority order, rejecting all others. Rejections are
    not final for the student — a rejected student proposes again at step k+1.
    Terminate when no student is both unheld and has an unexhausted list. Every
    held pair becomes final.

Two properties of this algorithm are relied on elsewhere and asserted here:

  * Termination: a student never proposes to the same school twice, so there
    are at most |students| x |schools| proposals. Exceeding that bound is a
    bug, and raises `MechanismError` rather than looping.

  * Order independence: the final matching does not depend on which eligible
    student proposes when. `proposal_policy` makes the order explicit and
    configurable so that this can be *tested* rather than assumed — if the two
    policies ever disagree, the implementation is wrong.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping, Optional, Sequence

from witness.core import (
    Assigned,
    Market,
    MechanismConfig,
    Profile,
    ResolvedPriorities,
    resolve_priorities,
)
from witness.errors import MechanismError, ModelError

#: Every currently-unheld student with an unexhausted list proposes in the same
#: step. This is the textbook presentation.
ALL_FREE_SIMULTANEOUS = "all_free_simultaneous"

#: Exactly one student proposes per step: the first unheld student with an
#: unexhausted list, in `Market.students` order. This is the sequential
#: presentation, and how most production implementations are written.
ONE_AT_A_TIME_DECLARED_ORDER = "one_at_a_time_declared_order"

_PROPOSAL_POLICIES = (ALL_FREE_SIMULTANEOUS, ONE_AT_A_TIME_DECLARED_ORDER)


@dataclass(frozen=True)
class DAConfig(MechanismConfig):
    """`MechanismConfig` plus DA's proposal order.

    The proposal order provably cannot change the final matching. It is a
    configuration parameter anyway, because "provably cannot" is a claim about
    the published algorithm, not about this code — and the two policies
    disagreeing is exactly how we would learn this code diverges from it.

    `mechanism` is ALSO an explicit config field, not a hardcoded literal in
    `to_dict()`. `DAConfig` is reused verbatim by the `first_choice_bonus_da`
    control mechanism (see `witness.controls`), which runs plain DA against
    differently-resolved priorities but otherwise shares this exact config
    shape. If the mechanism name were baked into `to_dict()` as a constant,
    every witness produced by a mechanism that reuses `DAConfig` under a
    different name would carry a config claiming the wrong mechanism, and
    `witness.replay.verify_witness`'s config/mechanism agreement check would
    reject it -- a real bug this project hit end-to-end (a genuine witness
    from `first_choice_bonus_da` failed replay because its config insisted it
    came from `student_proposing_da`). Making the mechanism name an explicit,
    validated field closes that off structurally.
    """

    proposal_policy: str = ALL_FREE_SIMULTANEOUS
    mechanism: str = "student_proposing_da"

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.proposal_policy not in _PROPOSAL_POLICIES:
            raise ModelError(
                f"proposal_policy must be one of {_PROPOSAL_POLICIES}, "
                f"got {self.proposal_policy!r}"
            )
        if not isinstance(self.mechanism, str) or not self.mechanism:
            raise ModelError(
                f"mechanism must be a non-empty string, got {self.mechanism!r}"
            )

    def to_dict(self) -> dict:
        data = super().to_dict()
        data["mechanism"] = self.mechanism
        data["proposal_policy"] = self.proposal_policy
        return data

    @classmethod
    def from_dict(cls, data: Mapping) -> "DAConfig":
        base = MechanismConfig.from_dict(data)
        return cls(
            tiebreak=base.tiebreak,
            unlisted_student_policy=base.unlisted_student_policy,
            proposal_policy=data.get("proposal_policy", ALL_FREE_SIMULTANEOUS),
            mechanism=data.get("mechanism", "student_proposing_da"),
        )


@dataclass(frozen=True)
class Assignment:
    """The outcome. `student_to_school[s]` is a school id or None (unmatched).

    `school_to_students[c]` lists c's assigned students in c's own priority
    order — an ordered tuple, so two Assignments compare equal only if the
    rosters really are identical.
    """

    student_to_school: Mapping[str, Assigned]
    school_to_students: Mapping[str, tuple[str, ...]]

    def __post_init__(self) -> None:
        object.__setattr__(self, "student_to_school", dict(self.student_to_school))
        object.__setattr__(
            self,
            "school_to_students",
            {c: tuple(r) for c, r in self.school_to_students.items()},
        )

    def of(self, student: str) -> Assigned:
        return self.student_to_school[student]

    def roster(self, school: str) -> tuple[str, ...]:
        return self.school_to_students[school]

    def unmatched(self, market: Market) -> tuple[str, ...]:
        return tuple(s for s in market.students if self.student_to_school[s] is None)

    def to_dict(self) -> dict:
        return {
            "student_to_school": dict(sorted(self.student_to_school.items())),
            "school_to_students": {
                c: list(r) for c, r in sorted(self.school_to_students.items())
            },
        }

    @staticmethod
    def from_dict(data: Mapping) -> "Assignment":
        return Assignment(
            student_to_school=dict(data["student_to_school"]),
            school_to_students={c: tuple(r) for c, r in data["school_to_students"].items()},
        )


def build_assignment(
    market: Market,
    priorities: ResolvedPriorities,
    student_to_school: Mapping[str, Assigned],
    *,
    allow_unranked: bool = False,
) -> Assignment:
    """Assemble an Assignment, putting each roster in the school's priority order.

    Roster order is not incidental: it feeds `Assignment` equality directly
    (see that class's docstring), and `Assignment` equality is what witness
    replay checks. So the rule for ordering a roster has to be an explicit,
    declared convention -- not whatever `sorted()` happens to do -- and this
    function is the one place that convention lives.

    `allow_unranked` controls what happens when a school ends up holding a
    student it finds unacceptable (`priorities.rank(c, s) is None`):

      * `allow_unranked=False` (the default): that is an error. Every
        mechanism that computes assignments by running its own priority-based
        competition (DA above all) should NEVER produce an unranked hold --
        if one appears, the mechanism has a bug, and this raises loudly
        rather than silently accepting (and, worse, silently *ordering*) a
        result that should have been impossible.

      * `allow_unranked=True`: schools MAY hold students they find
        unacceptable -- the one legitimate case today is Boston's
        administrative placement step with `placement_acceptability=
        "ignored"`, which deliberately overrides acceptability to fill
        leftover seats. The DECLARED roster order in that case is: every
        RANKED student first, in ascending priority rank (exactly as
        before), followed by every UNRANKED student in `Market.students`
        declared order. This has to be declared rather than left to
        incidental sort behavior, because comparing `None` priority ranks
        against each other (or against an int) is not well-ordered --
        `sorted()` on a mixed/None-only key raises `TypeError` -- and because
        whichever order is picked changes `Assignment` equality and hence
        whether a witness replays.
    """
    rosters: dict[str, tuple[str, ...]] = {}
    for c in market.schools:
        members = [s for s in market.students if student_to_school.get(s) == c]
        if allow_unranked:
            ranked = sorted(
                (s for s in members if priorities.rank(c, s) is not None),
                key=lambda s: priorities.rank(c, s),
            )
            unranked = tuple(s for s in members if priorities.rank(c, s) is None)
            rosters[c] = tuple(ranked) + unranked
        else:
            for s in members:
                if priorities.rank(c, s) is None:
                    raise MechanismError(
                        f"build_assignment: student {s!r} is assigned to school "
                        f"{c!r}, which finds them unacceptable "
                        f"(priorities.rank({c!r}, {s!r}) is None); a mechanism "
                        f"assigned a student to a school that finds them "
                        f"unacceptable, which must never happen under the "
                        f"strict default (pass allow_unranked=True only when "
                        f"an unranked hold is actually intended)"
                    )
            rosters[c] = tuple(sorted(members, key=lambda s: priorities.rank(c, s)))
    return Assignment(
        student_to_school={s: student_to_school.get(s) for s in market.students},
        school_to_students=rosters,
    )


@dataclass(frozen=True)
class ProposalStep:
    """One step of the algorithm, recorded for inspection.

    The trace is what makes a hand-worked test check the *algorithm* and not
    just its final answer: a wrong tiebreak or an off-by-one in the proposal
    order shows up here even when the final matching happens to coincide.
    """

    index: int
    proposals: tuple[tuple[str, str], ...]
    rejected_as_unacceptable: tuple[tuple[str, str], ...]
    rejected_by_competition: tuple[tuple[str, str], ...]
    holds_after: tuple[tuple[str, tuple[str, ...]], ...]

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "proposals": [list(p) for p in self.proposals],
            "rejected_as_unacceptable": [list(p) for p in self.rejected_as_unacceptable],
            "rejected_by_competition": [list(p) for p in self.rejected_by_competition],
            "holds_after": {c: list(r) for c, r in self.holds_after},
        }


@dataclass(frozen=True)
class DAResult:
    assignment: Assignment
    steps: tuple[ProposalStep, ...]
    n_proposals: int
    priorities: ResolvedPriorities

    def format_trace(self) -> str:
        lines = []
        for st in self.steps:
            lines.append(f"step {st.index}:")
            lines.append(
                "  proposals: " + ", ".join(f"{s}->{c}" for s, c in st.proposals)
            )
            if st.rejected_as_unacceptable:
                lines.append(
                    "  rejected (unacceptable): "
                    + ", ".join(f"{s} by {c}" for s, c in st.rejected_as_unacceptable)
                )
            if st.rejected_by_competition:
                lines.append(
                    "  rejected (competition): "
                    + ", ".join(f"{s} by {c}" for s, c in st.rejected_by_competition)
                )
            lines.append(
                "  holding: "
                + ", ".join(f"{c}[{' '.join(r)}]" for c, r in st.holds_after)
            )
        lines.append(f"total proposals: {self.n_proposals}")
        return "\n".join(lines)


def default_choice_rule(
    market: Market, priorities: ResolvedPriorities, school: str, pool: Sequence[str]
) -> tuple[str, ...]:
    """The classical school choice rule: the `q_c` best students in `pool`.

    This is `C_c(J)` for a school with a single strict priority order and no
    slot structure. It is factored out, rather than inlined in the DA loop,
    only so that a mechanism with a richer choice rule (see
    `witness.reserves`) can substitute its own while running the identical
    proposal loop -- which is exactly how Dur, Kominers, Pathak & Sonmez
    (2018) present DA with reserves: the loop is unchanged, `C_c` is swapped.
    """
    return tuple(
        sorted(pool, key=lambda s: priorities.rank(school, s))[: market.capacity(school)]
    )


def deferred_acceptance(
    market: Market,
    profile: Profile,
    config: Optional[DAConfig] = None,
    *,
    priorities: Optional[ResolvedPriorities] = None,
    choice_rule: Optional[Callable[..., Sequence[str]]] = None,
) -> DAResult:
    """Run student-proposing DA and return the matching plus the full trace.

    `priorities` may be passed in to reuse an already-resolved order across
    runs — required by the manipulation search, where the truthful run and the
    misreport run must face the identical lottery. Resolving is profile-free,
    so passing it or recomputing it gives the same orders either way.

    `choice_rule(market, priorities, school, pool) -> chosen` decides which of
    the students in `pool` a school keeps. It defaults to
    `default_choice_rule` (top q_c by priority), which is plain DA. A rule
    returning students not in `pool`, or more than `q_c` of them, is a bug in
    that rule and raises `MechanismError` here rather than being trusted.

    Whatever order a choice rule returns, the students it keeps are stored --
    and reported in the trace -- in the school's own priority-rank order, and
    the students it drops likewise. Roster order feeds `Assignment` equality
    and hence whether a witness replays, so it is fixed here by declaration
    and is never inherited from the order a choice rule happened to build.
    """
    config = config if config is not None else DAConfig()
    choose = choice_rule if choice_rule is not None else default_choice_rule
    profile.validate_against(market)
    if priorities is None:
        priorities = resolve_priorities(market, config)

    # Per-student state. Read only via market.students, never iterated for order.
    report = {s: profile.report(s) for s in market.students}
    next_choice = {s: 0 for s in market.students}
    holder: dict[str, Assigned] = {s: None for s in market.students}
    held: dict[str, tuple[str, ...]] = {c: () for c in market.schools}

    max_proposals = len(market.students) * len(market.schools)
    steps: list[ProposalStep] = []
    n_proposals = 0
    step_index = 0

    while True:
        # "Each student not held by any school, who has not exhausted their list."
        # Explicit iteration over the declared student order.
        free = tuple(
            s
            for s in market.students
            if holder[s] is None and next_choice[s] < len(report[s])
        )
        if not free:
            break

        if config.proposal_policy == ALL_FREE_SIMULTANEOUS:
            proposers = free
        else:  # ONE_AT_A_TIME_DECLARED_ORDER; validated in DAConfig
            proposers = free[:1]

        step_index += 1
        proposals: list[tuple[str, str]] = []
        for s in proposers:
            c = report[s][next_choice[s]]
            next_choice[s] += 1
            proposals.append((s, c))
            n_proposals += 1
        if n_proposals > max_proposals:
            raise MechanismError(
                f"DA made {n_proposals} proposals, exceeding the algorithm's own "
                f"bound of {max_proposals}: a student proposed to some school twice"
            )

        rejected_unacceptable: list[tuple[str, str]] = []
        rejected_competition: list[tuple[str, str]] = []

        # Schools evaluate. Iterate market.schools explicitly; within a school,
        # the pool is ordered by the strict priority rank, which has no ties.
        for c in market.schools:
            applicants = tuple(s for s, target in proposals if target == c)
            if not applicants:
                continue
            acceptable = []
            for s in applicants:
                if priorities.rank(c, s) is None:
                    rejected_unacceptable.append((s, c))
                else:
                    acceptable.append(s)
            if not acceptable:
                continue
            pool = held[c] + tuple(acceptable)
            chosen = tuple(choose(market, priorities, c, pool))
            pool_set = set(pool)
            if len(set(chosen)) != len(chosen) or not set(chosen) <= pool_set:
                raise MechanismError(
                    f"choice rule for {c!r} returned {chosen!r}, which is not a "
                    f"set of distinct students drawn from the pool {pool!r}"
                )
            if len(chosen) > market.capacity(c):
                raise MechanismError(
                    f"choice rule for {c!r} chose {len(chosen)} students, "
                    f"exceeding its capacity {market.capacity(c)}"
                )
            chosen_set = set(chosen)
            by_rank = sorted(pool, key=lambda s: priorities.rank(c, s))
            keep = tuple(s for s in by_rank if s in chosen_set)
            drop = tuple(s for s in by_rank if s not in chosen_set)
            held[c] = keep
            for s in keep:
                holder[s] = c
            for s in drop:
                holder[s] = None
                rejected_competition.append((s, c))

        steps.append(
            ProposalStep(
                index=step_index,
                proposals=tuple(proposals),
                rejected_as_unacceptable=tuple(rejected_unacceptable),
                rejected_by_competition=tuple(rejected_competition),
                holds_after=tuple((c, held[c]) for c in market.schools if held[c]),
            )
        )

    assignment = build_assignment(market, priorities, holder)
    # Every tentative hold becomes final: the rosters must be exactly `held`.
    for c in market.schools:
        if assignment.roster(c) != held[c]:
            raise MechanismError(
                f"final roster of {c!r} {assignment.roster(c)!r} disagrees with the "
                f"algorithm's last holds {held[c]!r}"
            )
    return DAResult(
        assignment=assignment,
        steps=tuple(steps),
        n_proposals=n_proposals,
        priorities=priorities,
    )
