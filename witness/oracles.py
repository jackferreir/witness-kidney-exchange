"""Definitional, brute-force checkers — independent of `witness.da`.

Every function here is written directly from a published definition, not by
calling `deferred_acceptance` or reusing its internals. That independence is
the entire point: if the algorithmic implementation in `witness.da` has a
bug, we want a *different* piece of code — one that cannot share that bug —
to catch the disagreement. Agreement between the two is then real evidence
that a matching is correct, not a coincidence of shared code.

Definitions implemented, each named after its usual citation in the matching
literature:

  * Individual rationality (Roth & Sotomayor 1990, ch. 5): a matching in
    which every student is assigned only to a school on their own report,
    every school holds only students it finds acceptable, no school exceeds
    its capacity, and no student is double-booked.

  * Blocking pair / stability (Gale & Shapley 1962, extended to the
    many-to-one college-admissions model by Roth 1985): (s, c) blocks a
    matching if s prefers c to their assignment, c is acceptable to s, and
    either c has a free seat or c would rather hold s than one of the
    students it currently holds. A matching is stable iff it is individually
    rational and has no blocking pair.

  * Student-optimal stable matching (Gale & Shapley 1962, Theorem 2): among
    all stable matchings, there is a unique one that every student weakly
    prefers to every other stable matching. Deferred Acceptance is claimed to
    compute exactly this matching; `student_optimal_stable_matching` finds it
    by brute force, independently, so that claim can be tested.

Deliberately slow: `all_matchings` enumerates the full product of each
student's own options and filters, rather than doing anything clever. Style
matches the rest of the package: explicit iteration over `market.students`
and `market.schools` wherever order could affect a result, never over a dict
or set.
"""

from __future__ import annotations

from itertools import product
from typing import Iterator

from witness.core import Assigned, Market, Profile, ResolvedPriorities, strictly_prefers
from witness.da import Assignment, build_assignment
from witness.errors import ModelError


def is_individually_rational(
    market: Market,
    profile: Profile,
    priorities: ResolvedPriorities,
    assignment: Assignment,
) -> tuple[bool, tuple[str, ...]]:
    """Check individual rationality directly from its definition.

    Violations detected, each recorded as a human-readable reason:
      * a student assigned a school absent from their own report;
      * a school holding a student it finds unacceptable;
      * a school holding more students than its capacity;
      * a student appearing in more than one school's roster;
      * `student_to_school` and `school_to_students` disagreeing with each
        other about who is assigned where.
    """
    reasons: list[str] = []

    for s in market.students:
        c = assignment.of(s)
        if c is not None and c not in profile.report(s):
            reasons.append(
                f"student {s!r} is assigned {c!r}, which is absent from their own "
                f"report {profile.report(s)!r}"
            )

    for c in market.schools:
        roster = assignment.roster(c)
        for s in roster:
            if priorities.rank(c, s) is None:
                reasons.append(
                    f"school {c!r} holds student {s!r}, who is unacceptable to it "
                    f"(priorities.rank({c!r}, {s!r}) is None)"
                )
        if len(roster) > market.capacity(c):
            reasons.append(
                f"school {c!r} holds {len(roster)} students {roster!r}, exceeding "
                f"its capacity of {market.capacity(c)}"
            )

    for s in market.students:
        n_rosters = sum(1 for c in market.schools if s in assignment.roster(c))
        if n_rosters > 1:
            hosts = tuple(c for c in market.schools if s in assignment.roster(c))
            reasons.append(
                f"student {s!r} appears in {n_rosters} school rosters {hosts!r}, "
                f"not at most one"
            )

    for s in market.students:
        c = assignment.of(s)
        if c is not None and s not in assignment.roster(c):
            reasons.append(
                f"student_to_school says {s!r} -> {c!r}, but school_to_students[{c!r}] "
                f"= {assignment.roster(c)!r} does not include {s!r}"
            )
    for c in market.schools:
        for s in assignment.roster(c):
            if assignment.of(s) != c:
                reasons.append(
                    f"school_to_students[{c!r}] includes {s!r}, but student_to_school "
                    f"says {s!r} -> {assignment.of(s)!r}"
                )

    return (len(reasons) == 0, tuple(reasons))


def blocking_pairs(
    market: Market,
    profile: Profile,
    priorities: ResolvedPriorities,
    assignment: Assignment,
) -> tuple[tuple[str, str], ...]:
    """Every blocking pair (s, c), in the textbook many-to-one definition.

    (s, c) blocks `assignment` iff:
      * c is on s's own report, and s is acceptable to c, and
      * s strictly prefers c to their current assignment (by s's report), and
      * c has an empty seat, OR c holds some s' it ranks strictly below s.

    Deterministic order: `market.students` outer loop, `market.schools` inner.
    """
    pairs: list[tuple[str, str]] = []
    for s in market.students:
        current = assignment.of(s)
        report = profile.report(s)
        for c in market.schools:
            if c not in report:
                continue
            if priorities.rank(c, s) is None:
                continue
            if not strictly_prefers(report, c, current):
                continue
            roster = assignment.roster(c)
            has_empty_seat = len(roster) < market.capacity(c)
            s_rank = priorities.rank(c, s)
            displaces_someone = any(
                priorities.rank(c, other) is not None and priorities.rank(c, other) > s_rank
                for other in roster
            )
            if has_empty_seat or displaces_someone:
                pairs.append((s, c))
    return tuple(pairs)


def is_stable(
    market: Market,
    profile: Profile,
    priorities: ResolvedPriorities,
    assignment: Assignment,
) -> bool:
    """Stable iff individually rational and free of blocking pairs (Gale & Shapley 1962)."""
    ok, _ = is_individually_rational(market, profile, priorities, assignment)
    if not ok:
        return False
    return len(blocking_pairs(market, profile, priorities, assignment)) == 0


def all_matchings(
    market: Market,
    profile: Profile,
    priorities: ResolvedPriorities,
    max_space: int = 2_000_000,
) -> Iterator[Assignment]:
    """Every feasible assignment, by brute force over the product of each
    student's own options.

    Each student's option set is their own report, restricted to schools that
    find them acceptable, plus `None` (unmatched) — so every yielded
    assignment is automatically individually rational on the student side and
    on the school-acceptability side. Capacity is checked and enforced by
    filtering. Raises `ValueError` before doing any work if the size of the
    option-space product exceeds `max_space`, so a caller can't accidentally
    wait on something astronomical.
    """
    options: list[tuple[Assigned, ...]] = []
    for s in market.students:
        report = profile.report(s)
        acceptable = tuple(c for c in report if priorities.rank(c, s) is not None)
        options.append(acceptable + (None,))

    space = 1
    for opts in options:
        space *= len(opts)
    if space > max_space:
        raise ValueError(
            f"all_matchings: option-space size {space} exceeds max_space={max_space} "
            f"({len(market.students)} students, option counts {[len(o) for o in options]!r}); "
            f"pass a larger max_space if you really mean to enumerate this"
        )

    for combo in product(*options):
        student_to_school: dict[str, Assigned] = {
            s: combo[i] for i, s in enumerate(market.students)
        }
        feasible = True
        for c in market.schools:
            n_here = sum(1 for s in market.students if student_to_school[s] == c)
            if n_here > market.capacity(c):
                feasible = False
                break
        if not feasible:
            continue
        yield build_assignment(market, priorities, student_to_school)


def all_stable_matchings(
    market: Market,
    profile: Profile,
    priorities: ResolvedPriorities,
    max_space: int = 2_000_000,
) -> tuple[Assignment, ...]:
    """Every stable matching, found by brute force. Deterministic order
    (the order `all_matchings` produces them in, i.e. the product order over
    `market.students`' own option lists)."""
    return tuple(
        a
        for a in all_matchings(market, profile, priorities, max_space=max_space)
        if is_stable(market, profile, priorities, a)
    )


def student_optimal_stable_matching(
    market: Market,
    profile: Profile,
    priorities: ResolvedPriorities,
    max_space: int = 2_000_000,
) -> Assignment:
    """The stable matching every student weakly prefers to every other stable
    matching (Gale & Shapley 1962, Theorem 2: student-proposing DA computes
    exactly this matching, and it is unique). Found here independently of DA,
    by brute-force enumeration of the stable set followed by a pairwise
    domination check.

    If no matching in the enumerated stable set dominates every other one —
    which the cited theorem says cannot happen — raises `ModelError` naming a
    concrete pair of stable matchings and the students who disagree about
    which is better. That would itself be a real finding, not a bug in this
    function: the theorem's premise is that *the* set of stable matchings was
    enumerated, so a failure here most plausibly means the DA implementation
    is producing something that is not actually stable, or `all_matchings`
    was truncated (see `max_space`).
    """
    stable = all_stable_matchings(market, profile, priorities, max_space=max_space)
    if not stable:
        raise ModelError(
            "student_optimal_stable_matching: no stable matching was found among the "
            "enumerated assignments; a stable matching always exists (Gale & Shapley "
            "1962), so either all_matchings was truncated or is_stable is wrong"
        )

    optimal: list[Assignment] = []
    for candidate in stable:
        dominated_by_someone = False
        for other in stable:
            if other is candidate:
                continue
            if any(
                strictly_prefers(profile.report(s), other.of(s), candidate.of(s))
                for s in market.students
            ):
                dominated_by_someone = True
                break
        if not dominated_by_someone:
            optimal.append(candidate)

    if not optimal:
        # No candidate is weakly preferred by every student to every other
        # stable matching. Locate a concrete witnessing pair: two stable
        # matchings where different students disagree about which is better.
        for i, a in enumerate(stable):
            for b in stable[i + 1 :]:
                prefers_a = tuple(
                    s
                    for s in market.students
                    if strictly_prefers(profile.report(s), a.of(s), b.of(s))
                )
                prefers_b = tuple(
                    s
                    for s in market.students
                    if strictly_prefers(profile.report(s), b.of(s), a.of(s))
                )
                if prefers_a and prefers_b:
                    raise ModelError(
                        "student_optimal_stable_matching: no student-optimal stable "
                        "matching exists among the enumerated stable matchings, which "
                        "contradicts Gale & Shapley (1962) Theorem 2 and is a genuine "
                        f"finding. Students {prefers_a!r} strictly prefer matching "
                        f"{a.to_dict()!r} while students {prefers_b!r} strictly prefer "
                        f"matching {b.to_dict()!r}."
                    )
        raise ModelError(
            "student_optimal_stable_matching: no student-optimal stable matching "
            "exists among the enumerated stable matchings, but no pairwise "
            f"disagreement could be located either; stable set was {stable!r}"
        )

    if len(optimal) > 1:
        first = optimal[0]
        for other in optimal[1:]:
            if other.student_to_school != first.student_to_school:
                raise ModelError(
                    "student_optimal_stable_matching: found multiple undominated "
                    "'student-optimal' matchings that disagree with each other, which "
                    "contradicts uniqueness (Gale & Shapley 1962, Theorem 2) and is a "
                    f"genuine finding: {first.to_dict()!r} vs {other.to_dict()!r}"
                )
    return optimal[0]
