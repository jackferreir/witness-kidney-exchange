"""Definitional, brute-force stability checker for markets WITH couples --
independent of `witness.couples`, exactly the way `witness.oracles` is
independent of `witness.da` (see that module's docstring for why the
independence itself is the point).

Implements the blocking definitions from Roth & Peranson (1999), AER
89(4):748-780, Appendix C ("Formal Definitions of Stability" / "Complex
Matches"), quoted here directly from the PDF (`pdftotext -layout` over
`data/external/roth_peranson_1999/rothperansonaer.pdf`), not paraphrased from
memory:

    "A matching is blocked by an individual couple {a1, a2} if they are
    matched to a pair (ri, rj) not on their ROL. ... A residency program r
    and an applicant a in the set A1 together block a matching mu precisely
    as in the simple market, if they are not matched to one another and
    would both prefer to be. ... A couple {a1, a2} and residency programs r
    and r' block a matching mu if (r, r') >_c mu({a1,a2}) and if either:

      (i)  a1 not-in mu(r), a1 >_r sigma for some sigma in mu(r), and
           either a2 in mu(r') or a2 >_r' sigma' for some sigma' in mu(r'); or
      (ii) a2 not-in mu(r'), a2 >_r' sigma' for some sigma' in mu(r'), and
           either a1 in mu(r) or a1 >_r sigma for some sigma in mu(r)."

`a >_r sigma for some sigma in mu(r)` is the simple-market convention
(Appendix C, "Simple Matching Markets") applied to a program with an unfilled
seat too: an unfilled position at r counts as r being matched to a copy of
itself, and "an acceptable worker is one which the firm prefers to leaving a
position unfilled" -- so a program with any vacant seat, for which the
applicant is acceptable, always satisfies "a >_r sigma for some sigma in
mu(r)" trivially, exactly like `witness.oracles.blocking_pairs`'s own
`has_empty_seat or displaces_someone` test. `_preferred_to_occupant_or_vacancy`
below is that same test, re-derived independently here (not imported from
`witness.oracles`) so this module shares no code with the mechanism-adjacent
oracle it is meant to check.

WHY THE FLAT ORACLE DOES NOT APPLY TO COUPLES: `witness.oracles.blocking_pairs`
treats every applicant as an individual with her own report, and would check
a couple's two members against their OWN reports -- which do not exist for a
couple (see `witness.couples.CouplesProfile`: a couple's only report is a
joint ranking of PAIRS). Naively running the flat oracle over a couple's
members would either crash (no per-member report to read) or, if one tried
to paper over that by inventing a fake per-member report, would silently
check each member for an INDIVIDUAL blocking pair the couple never actually
has power to act on alone -- missing the joint-pair requirement entirely.
`tests/test_couples_handworked.py`'s `FlatOracleDoesNotApplyToCouples` pins
this directly, mirroring `tests/test_reserves_handworked.py`'s equivalent
non-inheritance check for `witness.reserves`.
"""

from __future__ import annotations

from itertools import product
from typing import Iterator, Mapping, Sequence

from witness.core import Market, ResolvedPriorities, WORST
from witness.couples import Couple, CouplesProfile
from witness.da import Assignment, build_assignment
from witness.errors import ModelError


def _preferred_to_occupant_or_vacancy(
    market: Market, priorities: ResolvedPriorities, assignment: Assignment, program: str, applicant: str
) -> bool:
    """True iff `program` prefers `applicant` to SOME current occupant, OR
    has a vacant seat and finds `applicant` acceptable -- i.e. "applicant >_r
    sigma for some sigma in mu(r)" under the simple-market vacant-seat
    convention (see module docstring)."""
    if not priorities.acceptable(program, applicant):
        return False
    roster = assignment.roster(program)
    if len(roster) < market.capacity(program):
        return True
    a_rank = priorities.rank(program, applicant)
    return any(
        priorities.rank(program, other) is not None and priorities.rank(program, other) > a_rank
        for other in roster
    )


def _pair_position(couple: Couple, pair: "tuple[str, str] | tuple[None, None]") -> float:
    """`pair`'s index in `couple.joint_rankings`, or `WORST` if absent --
    which also correctly covers a couple currently unmatched (pair == (None,
    None)), matching `witness.core.position`'s own unranked/unmatched
    convention."""
    try:
        return float(couple.joint_rankings.index(pair))  # type: ignore[arg-type]
    except ValueError:
        return WORST


def couple_blocking_pairs(
    market: Market,
    couple: Couple,
    priorities: ResolvedPriorities,
    assignment: Assignment,
) -> "tuple[tuple[str, str], ...]":
    """Every (r, r') pair from `couple.joint_rankings` that blocks
    `assignment`, per the Appendix C couple-blocking clause quoted in the
    module docstring. Deterministic order: `couple.joint_rankings`' own
    declared order.
    """
    a1, a2 = couple.members
    cur_r1 = assignment.of(a1)
    cur_r2 = assignment.of(a2)
    current_pair = (cur_r1, cur_r2)
    current_pos = _pair_position(couple, current_pair)  # type: ignore[arg-type]

    blocking: list[tuple[str, str]] = []
    for r, r2 in couple.joint_rankings:
        if _pair_position(couple, (r, r2)) >= current_pos:
            continue  # not strictly preferred to the current outcome
        a1_absent = a1 not in assignment.roster(r)
        a1_pref = _preferred_to_occupant_or_vacancy(market, priorities, assignment, r, a1)
        a2_present_or_pref = (
            a2 in assignment.roster(r2)
            or _preferred_to_occupant_or_vacancy(market, priorities, assignment, r2, a2)
        )
        cond_i = a1_absent and a1_pref and a2_present_or_pref

        a2_absent = a2 not in assignment.roster(r2)
        a2_pref = _preferred_to_occupant_or_vacancy(market, priorities, assignment, r2, a2)
        a1_present_or_pref = (
            a1 in assignment.roster(r)
            or _preferred_to_occupant_or_vacancy(market, priorities, assignment, r, a1)
        )
        cond_ii = a2_absent and a2_pref and a1_present_or_pref

        if cond_i or cond_ii:
            blocking.append((r, r2))
    return tuple(blocking)


def is_individually_rational_couples(
    market: Market,
    profile: CouplesProfile,
    priorities: ResolvedPriorities,
    assignment: Assignment,
) -> "tuple[bool, tuple[str, ...]]":
    """Individual rationality for a couples market, from the definition
    directly (Appendix C):

      * a single's assignment must be on her own report (or unmatched);
      * a couple matched to a pair NOT on its own joint ROL is "blocked by
        an individual couple" -- i.e. individually irrational for the couple;
      * every program holds only applicants it finds acceptable, does not
        exceed capacity, and `student_to_school` / `school_to_students`
        agree with each other -- these are structural and identical in kind
        to `witness.oracles.is_individually_rational`'s own checks, just
        re-derived here independently rather than imported.
    """
    reasons: list[str] = []

    for s, report in profile.singles.items():
        c = assignment.of(s)
        if c is not None and c not in report:
            reasons.append(
                f"single {s!r} is assigned {c!r}, which is absent from their own report {report!r}"
            )

    for couple in profile.couples:
        a1, a2 = couple.members
        r1, r2 = assignment.of(a1), assignment.of(a2)
        if r1 is None and r2 is None:
            continue  # unmatched is always individually rational for a couple
        if (r1, r2) not in couple.joint_rankings:
            reasons.append(
                f"couple {couple.members!r} is matched to {(r1, r2)!r}, which is not on "
                f"their own joint ROL {couple.joint_rankings!r} (blocked by the individual couple)"
            )

    for c in market.schools:
        roster = assignment.roster(c)
        for s in roster:
            if priorities.rank(c, s) is None:
                reasons.append(f"program {c!r} holds applicant {s!r}, who is unacceptable to it")
        if len(roster) > market.capacity(c):
            reasons.append(
                f"program {c!r} holds {len(roster)} applicants {roster!r}, exceeding capacity "
                f"{market.capacity(c)}"
            )

    for s in market.students:
        n_rosters = sum(1 for c in market.schools if s in assignment.roster(c))
        if n_rosters > 1:
            reasons.append(f"applicant {s!r} appears in more than one program roster")

    for s in market.students:
        c = assignment.of(s)
        if c is not None and s not in assignment.roster(c):
            reasons.append(
                f"student_to_school says {s!r} -> {c!r}, but school_to_students[{c!r}] does "
                f"not include {s!r}"
            )
    for c in market.schools:
        for s in assignment.roster(c):
            if assignment.of(s) != c:
                reasons.append(
                    f"school_to_students[{c!r}] includes {s!r}, but student_to_school says "
                    f"{s!r} -> {assignment.of(s)!r}"
                )

    return (len(reasons) == 0, tuple(reasons))


def blocking_pairs_couples(
    market: Market,
    profile: CouplesProfile,
    priorities: ResolvedPriorities,
    assignment: Assignment,
) -> "tuple[tuple, ...]":
    """Every blocking entity, in the Appendix C sense, against `assignment`:

      * `("single", s, c)` -- a single applicant s and program c block, in
        exactly the flat sense of `witness.oracles.blocking_pairs`, re-derived
        independently here rather than shared with it;
      * `("couple", (a1, a2), (r, r'))` -- a couple and a pair of programs
        block, per `couple_blocking_pairs`.

    Deterministic order: singles in `market.students` order (skipping couple
    members entirely -- see the module docstring's WHY), then couples in
    `profile.couples`' own declared order.
    """
    from witness.core import strictly_prefers

    pairs: list[tuple] = []
    couple_members = {a for c in profile.couples for a in c.members}
    for s in market.students:
        if s in couple_members:
            continue
        report = profile.singles[s]
        current = assignment.of(s)
        for c in market.schools:
            if c not in report:
                continue
            if priorities.rank(c, s) is None:
                continue
            if not strictly_prefers(report, c, current):
                continue
            if _preferred_to_occupant_or_vacancy(market, priorities, assignment, c, s):
                pairs.append(("single", s, c))

    for couple in profile.couples:
        for r, r2 in couple_blocking_pairs(market, couple, priorities, assignment):
            pairs.append(("couple", couple.members, (r, r2)))
    return tuple(pairs)


def is_stable_couples(
    market: Market,
    profile: CouplesProfile,
    priorities: ResolvedPriorities,
    assignment: Assignment,
) -> bool:
    """Stable iff individually rational and free of every blocking entity
    above -- the couples-aware analogue of `witness.oracles.is_stable`."""
    ok, _ = is_individually_rational_couples(market, profile, priorities, assignment)
    if not ok:
        return False
    return len(blocking_pairs_couples(market, profile, priorities, assignment)) == 0


def candidate_assignment(
    market: Market,
    priorities: ResolvedPriorities,
    student_to_school: Mapping[str, "str | None"],
) -> Assignment:
    """Build one candidate `Assignment` for enumeration in a hand-worked
    test (see `tests/test_couples_handworked.py`'s CPL-B), via the same
    `build_assignment` every mechanism in this codebase uses -- so a
    candidate's roster order is the same declared convention as everywhere
    else, and equality comparisons behave identically."""
    return build_assignment(market, priorities, dict(student_to_school), allow_unranked=False)
