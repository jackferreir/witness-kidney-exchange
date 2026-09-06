"""Coverage instrumentation for `witness.generate` sweeps.

A sweep that never reaches a branch is not evidence about that branch. The
Step-3A narrow generator's own history is the cautionary tale: its
one-seat-over-subscribed setting silently made every instance hit the same
handful of branches (capacity contention, unmatched students) while NEVER
touching the unlisted-student branch or the school-unacceptable-rejection
branch at all -- and that silence was easy to miss because nothing printed
it. This module makes it visible instead of leaving it to be inferred (or
missed) by whoever reads a manipulation-rate number later.

`instance_coverage` reads what a *mechanism run actually did* from its own
recorded trace (`DAResult.steps` / `BostonResult.rounds`) rather than
re-deriving contention or unacceptable-rejection facts independently, so
coverage reflects the real execution, not a second guess at it. The one
exception is `subscription`, which is computed directly from the market's
actual capacities vs. student count -- deliberately NOT read off
`GeneratorConfig.subscription`, because the Step-3A legacy `capacity` alias
(see `witness.generate`) can produce any subscription level regardless of
what a config's `subscription` field says, and because subscription is a
property of the realized instance, not of the generator's intent.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from witness.boston import BostonResult
from witness.ttc import TTCResult
from witness.core import Market, MechanismConfig, Profile
from witness.da import DAResult
from witness.errors import ModelError
from witness.generate import SUBSCRIPTION_EXACT, SUBSCRIPTION_OVER, SUBSCRIPTION_UNDER

#: Every boolean branch this module tracks, in a fixed, greppable order --
#: the order `CoverageReport.format_report` and `unreached_branches` use.
BRANCH_NAMES = (
    "had_unmatched_student",
    "had_unlisted_student",
    "had_capacity_contention",
    "had_lottery_tie",
    "had_incomplete_list",
    "had_very_short_list",
    "had_school_unacceptable_rejection",
)

#: The three subscription levels a realized instance can land in; see
#: `witness.generate` for the OVER = fewer-seats-than-students convention.
_SUBSCRIPTIONS = (SUBSCRIPTION_OVER, SUBSCRIPTION_EXACT, SUBSCRIPTION_UNDER)


@dataclass(frozen=True)
class InstanceCoverage:
    """Which branches ONE (market, profile, config, result) instance hit."""

    had_unmatched_student: bool
    had_unlisted_student: bool
    had_capacity_contention: bool
    had_lottery_tie: bool
    had_incomplete_list: bool
    had_very_short_list: bool
    had_school_unacceptable_rejection: bool
    subscription: str

    def __post_init__(self) -> None:
        if self.subscription not in _SUBSCRIPTIONS:
            raise ModelError(
                f"InstanceCoverage.subscription must be one of {_SUBSCRIPTIONS}, "
                f"got {self.subscription!r}"
            )

    def to_dict(self) -> dict:
        data = {name: getattr(self, name) for name in BRANCH_NAMES}
        data["subscription"] = self.subscription
        return data


def _subscription_of(market: Market) -> str:
    total_seats = market.total_seats()
    n_students = len(market.students)
    if total_seats < n_students:
        return SUBSCRIPTION_OVER
    if total_seats > n_students:
        return SUBSCRIPTION_UNDER
    return SUBSCRIPTION_EXACT


def _had_unlisted_student(market: Market) -> bool:
    for c in market.schools:
        listed = {s for cls in market.priority_classes[c] for s in cls}
        if any(s not in listed for s in market.students):
            return True
    return False


def _had_lottery_tie(market: Market) -> bool:
    for c in market.schools:
        if any(len(cls) >= 2 for cls in market.priority_classes[c]):
            return True
    return False


def _had_incomplete_list(profile: Profile, market: Market) -> bool:
    n_schools = len(market.schools)
    return any(len(profile.report(s)) < n_schools for s in market.students)


def _had_very_short_list(profile: Profile, market: Market) -> bool:
    return any(len(profile.report(s)) <= 1 for s in market.students)


def _da_trace_flags(result: DAResult) -> "tuple[bool, bool]":
    """(had_capacity_contention, had_school_unacceptable_rejection) from a
    `DAResult`'s steps."""
    contention = any(bool(step.rejected_by_competition) for step in result.steps)
    unacceptable = any(bool(step.rejected_as_unacceptable) for step in result.steps)
    return contention, unacceptable


def _ttc_trace_flags(result: TTCResult) -> "tuple[bool, bool]":
    """(had_capacity_contention, had_school_unacceptable_rejection) from a
    `TTCResult`'s steps.

    TTC has no proposals and therefore no rejections, so neither flag can be
    read off the trace the way DA's is. The nearest true statements about
    what the run actually did:

      * CONTENTION -- a school was pointed at by two or more remaining
        students in the same step and did not take all of them. That is the
        moment scarcity actually bound: the students who did not lie on the
        cycle had to look further down their lists. Merely being pointed at
        twice is not enough, because a capacity-2 school can absorb both.
      * UNACCEPTABLE -- some student passed over a still-open school because
        that school finds her unacceptable (`skipped_unacceptable`). This is
        the direct analogue of DA's `rejected_as_unacceptable`: the same
        screening event, observed at the pointer rather than at a proposal,
        because in TTC the student never gets to propose in the first place.
    """
    contention = False
    for step in result.steps:
        demand: dict[str, int] = {}
        for _s, c in step.student_points_to:
            demand[c] = demand.get(c, 0) + 1
        taken: dict[str, int] = {}
        for _s, c in step.assigned:
            taken[c] = taken.get(c, 0) + 1
        if any(n > taken.get(c, 0) and n > 1 for c, n in demand.items()):
            contention = True
            break
    unacceptable = any(bool(step.skipped_unacceptable) for step in result.steps)
    return contention, unacceptable


def _boston_trace_flags(result: BostonResult) -> "tuple[bool, bool]":
    """(had_capacity_contention, had_school_unacceptable_rejection) from a
    `BostonResult`'s rounds.

    `rejected_by_competition` always means an acceptable proposer lost to
    another acceptable proposer for a seat (see `witness.boston`'s own
    trace construction: only students already found acceptable ever reach
    that list) -- straightforward capacity contention. `rejected_as_full`
    is recorded for EVERY proposer to an already-full school, acceptable or
    not, before acceptability is even checked -- so it only counts as
    capacity contention here when at least one of those rejected proposers
    was, independently, acceptable to that school (`result.priorities`,
    which is profile-free and unaffected by the round in question).
    """
    contention = False
    unacceptable = False
    for rd in result.rounds:
        if rd.rejected_by_competition:
            contention = True
        if rd.rejected_as_unacceptable:
            unacceptable = True
        if not contention:
            for s, c in rd.rejected_as_full:
                if result.priorities.acceptable(c, s):
                    contention = True
                    break
    return contention, unacceptable


def instance_coverage(
    market: Market,
    profile: Profile,
    config: MechanismConfig,
    result,
) -> InstanceCoverage:
    """Which branches this (market, profile, config, result) instance hit.

    `result` must be a `DAResult`, a `BostonResult` or a `TTCResult` -- each
    carries the per-step / per-round trace this reads contention and
    unacceptable-rejection from, rather than re-deriving them. What those two
    flags MEAN differs per mechanism (TTC has no rejections at all); see each
    `_*_trace_flags` for the exact reading. `config` is accepted (and
    not otherwise read) for symmetry with `witness.generate.generate_config`
    and so a future branch keyed on `config.unlisted_student_policy` or
    similar can be added without changing this function's signature.
    """
    if isinstance(result, DAResult):
        had_capacity_contention, had_school_unacceptable_rejection = _da_trace_flags(result)
    elif isinstance(result, BostonResult):
        had_capacity_contention, had_school_unacceptable_rejection = _boston_trace_flags(result)
    elif isinstance(result, TTCResult):
        had_capacity_contention, had_school_unacceptable_rejection = _ttc_trace_flags(result)
    else:
        raise ModelError(
            f"instance_coverage: result must be a DAResult, BostonResult or TTCResult, "
            f"got {type(result)!r}"
        )

    had_unmatched_student = any(
        result.assignment.of(s) is None for s in market.students
    )

    return InstanceCoverage(
        had_unmatched_student=had_unmatched_student,
        had_unlisted_student=_had_unlisted_student(market),
        had_capacity_contention=had_capacity_contention,
        had_lottery_tie=_had_lottery_tie(market),
        had_incomplete_list=_had_incomplete_list(profile, market),
        had_very_short_list=_had_very_short_list(profile, market),
        had_school_unacceptable_rejection=had_school_unacceptable_rejection,
        subscription=_subscription_of(market),
    )


@dataclass(frozen=True)
class CoverageReport:
    """Aggregate coverage over a sweep of `InstanceCoverage`s."""

    n_instances: int
    fractions: Mapping[str, float]
    subscription_counts: Mapping[str, int]

    def format_report(self) -> str:
        lines = [f"CoverageReport: n_instances={self.n_instances}"]
        lines.append(
            "subscription_counts: "
            + ", ".join(f"{k}={self.subscription_counts.get(k, 0)}" for k in _SUBSCRIPTIONS)
        )
        lines.append("branch coverage:")
        for name in BRANCH_NAMES:
            frac = self.fractions[name]
            lines.append(f"  {name:<35s} {frac * 100:6.2f}%")
        unreached = unreached_branches(self)
        if unreached:
            lines.append(
                "UNREACHED (0.0%, NO EVIDENCE about these branches): "
                + ", ".join(unreached)
            )
        else:
            lines.append("every tracked branch was reached at least once")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "n_instances": self.n_instances,
            "fractions": dict(self.fractions),
            "subscription_counts": dict(self.subscription_counts),
        }


def aggregate(coverages: Sequence[InstanceCoverage]) -> CoverageReport:
    """Fold a sweep's `InstanceCoverage`s into one `CoverageReport`.

    Iterates `coverages` by index and `BRANCH_NAMES` / `_SUBSCRIPTIONS` in
    their fixed declared order -- never a dict or a set where it could
    affect the result (it can't affect *correctness* here since these are
    plain counts, but the house rule is applied uniformly across this
    package regardless of whether a given spot is "load-bearing").
    """
    coverages = tuple(coverages)
    n = len(coverages)
    if n == 0:
        raise ModelError("aggregate: coverages must be non-empty")

    fractions = {name: sum(1 for cov in coverages if getattr(cov, name)) / n for name in BRANCH_NAMES}

    subscription_counts = {k: 0 for k in _SUBSCRIPTIONS}
    for cov in coverages:
        subscription_counts[cov.subscription] += 1

    return CoverageReport(
        n_instances=n, fractions=fractions, subscription_counts=subscription_counts
    )


def unreached_branches(report: CoverageReport) -> "tuple[str, ...]":
    """Every branch name in `BRANCH_NAMES` with fraction exactly 0.0 -- the
    ones this sweep provides NO evidence about."""
    return tuple(name for name in BRANCH_NAMES if report.fractions[name] == 0.0)
