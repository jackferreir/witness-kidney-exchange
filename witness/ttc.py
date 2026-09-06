"""Top Trading Cycles for school choice (Abdulkadiroglu & Sonmez 2003).

The published algorithm, AER 93(3):729-747:

    Each school gets a counter initialised to its capacity. Each remaining
    student points to her favourite remaining school; each remaining school
    points to the remaining student with the highest priority. Because every
    node has out-degree exactly one in a finite graph, at least one cycle
    exists. Every student in a cycle is assigned the school she points to and
    is removed; that school's counter drops by one, and the school is removed
    once the counter hits zero. Repeat until no student remains.

WHAT THIS MECHANISM IS FOR, IN THIS PROJECT
TTC is strategy-proof (A&S Theorem 1) and Pareto efficient for students, but
it need not be stable. How often it actually IS stable depends almost
entirely on instance size, so the bare phrase "TTC is unstable" should never
be used without one attached: measured here, the share of instances whose TTC
outcome has a blocking pair runs from about 9% at 3 students x 3 schools to
about 92% at 12 x 6. At the sizes hand-worked fixtures live at, TTC is stable
in the large majority of instances. So it enters the suite as a THIRD
NEGATIVE CONTROL, next to
plain DA and DA-with-reserves -- not as a hunting ground. Anyone reading a
"0 manipulations found" result off this mechanism should read it as the
control passing, exactly as designed, and not as evidence about deployed
systems. The published place where TTC *does* become manipulable is when the
mechanism caps how many schools a student may rank, so the truthful report is
not even submittable (Haeringer & Klijn 2009, "Constrained school choice",
JET 144(5):1921-1947). That is a different mechanism and is not implemented
here.

TWO EXTENSIONS A&S DO NOT NEED AND THIS CODEBASE DOES
A&S assume every student is acceptable to every school. `MechanismConfig`
does not (see `unlisted_student_policy`), so the pointer rules are stated
against ACCEPTABILITY, not merely against remaining-ness:

  * a student points to her favourite remaining school THAT FINDS HER
    ACCEPTABLE. If she pointed at a school that can never take her, she would
    sit behind it forever whenever that school never fills -- a non-
    terminating loop, not a wrong answer.
  * a school with no acceptable remaining student is removed, its seats
    unfilled, because it cannot point at all.

Both prunings run to a fixed point at the START of every step (removing a
school can exhaust a student; removing a student can empty a school). That
fixed point is what re-establishes "out-degree exactly one at every node",
which is the precondition making "at least one cycle exists" a theorem rather
than an assumption. `_find_cycles` raises rather than looping if it is ever
violated.

WHY CYCLE POLICY IS DECLARED CONFIGURATION
Within a step the cycles are vertex-disjoint (out-degree one means every node
lies on at most one cycle), and removing one cannot destroy another: if
school c pointed at a student on cycle A then c is on A too. So the order in
which cycles are processed provably cannot change the outcome. That is
exactly the situation of `DAConfig.proposal_policy`, and it gets the same
treatment for the same reason -- "provably cannot" is a claim about the
published algorithm, not about this code, and the two policies disagreeing is
how we would learn this code diverges from it. Cycle detection also walks an
explicitly declared node order, never a dict or set iteration order.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Optional, Sequence

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

#: Process every cycle present in a step, then rebuild the graph.
CYCLES_ALL_SIMULTANEOUS = "all_cycles_simultaneous"

#: Process exactly ONE cycle -- the one containing the earliest student in
#: `Market.students` declared order -- then rebuild the graph from scratch.
CYCLES_ONE_AT_A_TIME_DECLARED_ORDER = "one_cycle_at_a_time_declared_order"

_CYCLE_POLICIES = (CYCLES_ALL_SIMULTANEOUS, CYCLES_ONE_AT_A_TIME_DECLARED_ORDER)

_STUDENT = "S"
_SCHOOL = "C"


@dataclass(frozen=True)
class TTCConfig(MechanismConfig):
    """`MechanismConfig` plus TTC's cycle-processing policy.

    `mechanism` is an explicit validated field for the same reason it is one
    on `DAConfig`: every witness embeds `config.to_dict()`, and
    `witness.replay.verify_witness` independently checks that the config's
    own mechanism name agrees with the witness's. A hardcoded literal here
    would be a silent replay failure for any future mechanism that reuses
    this config shape.
    """

    cycle_policy: str = CYCLES_ALL_SIMULTANEOUS
    mechanism: str = "top_trading_cycles"

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.cycle_policy not in _CYCLE_POLICIES:
            raise ModelError(
                f"cycle_policy must be one of {_CYCLE_POLICIES}, "
                f"got {self.cycle_policy!r}"
            )
        if not isinstance(self.mechanism, str) or not self.mechanism:
            raise ModelError(
                f"mechanism must be a non-empty string, got {self.mechanism!r}"
            )

    def to_dict(self) -> dict:
        data = super().to_dict()
        data["mechanism"] = self.mechanism
        data["cycle_policy"] = self.cycle_policy
        return data

    @classmethod
    def from_dict(cls, data: Mapping) -> "TTCConfig":
        base = MechanismConfig.from_dict(data)
        return cls(
            tiebreak=base.tiebreak,
            unlisted_student_policy=base.unlisted_student_policy,
            cycle_policy=data.get("cycle_policy", CYCLES_ALL_SIMULTANEOUS),
            mechanism=data.get("mechanism", "top_trading_cycles"),
        )


@dataclass(frozen=True)
class TTCStep:
    """One round of the algorithm, recorded for inspection.

    `skipped_unacceptable` records (student, school) pairs where the student
    passed over a school that was still open, because that school finds her
    unacceptable. It is the TTC analogue of DA's "rejected as unacceptable"
    and is what `witness.coverage` reads to tell whether an instance actually
    exercised school-side screening at all.

    `cycles` holds each cycle as a tuple of (student, school) trades, rotated
    to begin at the earliest student in `Market.students` declared order so
    that the same cycle always prints the same way. `exhausted_students` and
    `closed_schools` are the fixed-point prunings that happened at the START
    of this step; `filled_schools` are schools that ran out of seats at its
    end.
    """

    index: int
    exhausted_students: tuple[str, ...]
    closed_schools: tuple[str, ...]
    student_points_to: tuple[tuple[str, str], ...]
    skipped_unacceptable: tuple[tuple[str, str], ...]
    school_points_to: tuple[tuple[str, str], ...]
    cycles: tuple[tuple[tuple[str, str], ...], ...]
    assigned: tuple[tuple[str, str], ...]
    filled_schools: tuple[str, ...]
    seats_left_after: tuple[tuple[str, int], ...]

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "exhausted_students": list(self.exhausted_students),
            "closed_schools": list(self.closed_schools),
            "student_points_to": [list(p) for p in self.student_points_to],
            "skipped_unacceptable": [list(p) for p in self.skipped_unacceptable],
            "school_points_to": [list(p) for p in self.school_points_to],
            "cycles": [[list(t) for t in cyc] for cyc in self.cycles],
            "assigned": [list(p) for p in self.assigned],
            "filled_schools": list(self.filled_schools),
            "seats_left_after": {c: n for c, n in self.seats_left_after},
        }


@dataclass(frozen=True)
class TTCResult:
    assignment: Assignment
    steps: tuple[TTCStep, ...]
    priorities: ResolvedPriorities

    def format_trace(self) -> str:
        lines = []
        for st in self.steps:
            lines.append(f"step {st.index}:")
            if st.exhausted_students:
                lines.append(
                    "  exhausted (unmatched): " + ", ".join(st.exhausted_students)
                )
            if st.skipped_unacceptable:
                lines.append(
                    "  skipped (school will not have them): "
                    + ", ".join(f"{s}/{c}" for s, c in st.skipped_unacceptable)
                )
            if st.closed_schools:
                lines.append(
                    "  closed (no acceptable student): " + ", ".join(st.closed_schools)
                )
            lines.append(
                "  students point: "
                + ", ".join(f"{s}->{c}" for s, c in st.student_points_to)
            )
            lines.append(
                "  schools point:  "
                + ", ".join(f"{c}->{s}" for c, s in st.school_points_to)
            )
            for cyc in st.cycles:
                lines.append(
                    "  cycle: " + " ".join(f"({s} gets {c})" for s, c in cyc)
                )
            if st.filled_schools:
                lines.append("  filled: " + ", ".join(st.filled_schools))
            lines.append(
                "  seats left: "
                + (
                    ", ".join(f"{c}={n}" for c, n in st.seats_left_after)
                    if st.seats_left_after
                    else "(none)"
                )
            )
        return "\n".join(lines)


def _student_pointer(
    profile: Profile,
    priorities: ResolvedPriorities,
    student: str,
    remaining_schools: Sequence[str],
) -> "tuple[Optional[str], tuple[tuple[str, str], ...]]":
    """(`student`'s pointer, the still-open schools she had to pass over).

    Her pointer is her favourite remaining school THAT FINDS HER ACCEPTABLE;
    the second element lists the still-open schools ahead of it on her list
    that do not, which is what `TTCStep.skipped_unacceptable` records.

    Both the start-of-step prune and the pointer-graph construction call this
    one function. They were briefly two separate pieces of code doing the same
    thing, which is how a mechanism silently develops two different opinions
    about what a student points at -- and mutation testing caught it, because
    breaking the shared helper stopped changing the graph.
    """
    available = set(remaining_schools)
    skipped: list[tuple[str, str]] = []
    for c in profile.report(student):
        if c not in available:
            continue
        if not priorities.acceptable(c, student):
            skipped.append((student, c))
            continue
        return c, tuple(skipped)
    return None, tuple(skipped)


def _school_points_at(
    priorities: ResolvedPriorities,
    school: str,
    remaining_students: Sequence[str],
) -> Optional[str]:
    """`school`'s highest-priority remaining ACCEPTABLE student.

    Iterates `remaining_students` (which is kept in `Market.students` declared
    order) and compares priority ranks explicitly, rather than sorting -- an
    unacceptable student has rank `None`, which is not orderable against an
    int, and silently sorting around that is exactly the kind of incidental
    ordering this project bans.
    """
    best: Optional[str] = None
    best_rank: Optional[int] = None
    for s in remaining_students:
        r = priorities.rank(school, s)
        if r is None:
            continue
        if best_rank is None or r < best_rank:
            best, best_rank = s, r
    return best


def _find_cycles(
    pointer: Mapping[tuple[str, str], tuple[str, str]],
    nodes: Sequence[tuple[str, str]],
) -> list[list[tuple[str, str]]]:
    """Every cycle of a functional graph, walking `nodes` in the given order.

    Standard three-colour walk. `nodes` is an explicitly declared order
    (students in `Market.students` order, then schools in `Market.schools`
    order), so which cycle is discovered first is a declared fact, not a dict
    artefact.
    """
    color: dict[tuple[str, str], int] = {}
    cycles: list[list[tuple[str, str]]] = []
    for node in nodes:
        if color.get(node, 0) != 0:
            continue
        path: list[tuple[str, str]] = []
        pos: dict[tuple[str, str], int] = {}
        cur = node
        while True:
            state = color.get(cur, 0)
            if state == 1:
                cycles.append(path[pos[cur] :])
                break
            if state == 2:
                break
            color[cur] = 1
            pos[cur] = len(path)
            path.append(cur)
            try:
                cur = pointer[cur]
            except KeyError:  # pragma: no cover - guarded by the prune
                raise MechanismError(
                    f"_find_cycles: node {cur!r} has no outgoing pointer; the "
                    f"start-of-step pruning is supposed to guarantee "
                    f"out-degree exactly one at every node"
                ) from None
        for n in path:
            color[n] = 2
    return cycles


def _as_trades(
    raw_cycle: Sequence[tuple[str, str]], student_index: Mapping[str, int]
) -> tuple[tuple[str, str], ...]:
    """A raw node cycle as (student, school) trades, rotated to start at the
    earliest student in declared order."""
    students_on = [n[1] for n in raw_cycle if n[0] == _STUDENT]
    if not students_on or len(raw_cycle) % 2 != 0:
        raise MechanismError(
            f"_as_trades: {raw_cycle!r} is not a well-formed alternating cycle"
        )
    start = min(students_on, key=lambda s: student_index[s])
    k = raw_cycle.index((_STUDENT, start))
    rotated = list(raw_cycle[k:]) + list(raw_cycle[:k])
    trades = []
    for i in range(0, len(rotated), 2):
        kind_s, s = rotated[i]
        kind_c, c = rotated[i + 1]
        if kind_s != _STUDENT or kind_c != _SCHOOL:
            raise MechanismError(
                f"_as_trades: cycle {raw_cycle!r} does not alternate "
                f"student/school as a top-trading cycle must"
            )
        trades.append((s, c))
    return tuple(trades)


def top_trading_cycles(
    market: Market,
    profile: Profile,
    config: Optional[TTCConfig] = None,
    *,
    priorities: Optional[ResolvedPriorities] = None,
) -> TTCResult:
    """Run TTC and return the assignment plus the full step trace."""
    if config is None:
        config = TTCConfig()
    profile.validate_against(market)
    if priorities is None:
        priorities = resolve_priorities(market, config)

    student_index = {s: i for i, s in enumerate(market.students)}
    seats = {c: market.capacity(c) for c in market.schools}
    remaining_students = list(market.students)
    remaining_schools = [c for c in market.schools if seats[c] > 0]
    assigned: dict[str, Assigned] = {}
    steps: list[TTCStep] = []
    index = 0

    while remaining_students:
        index += 1

        # ---- prune to a fixed point (see module docstring) ----
        exhausted: list[str] = []
        closed: list[str] = []
        while True:
            changed = False
            drop_students = [
                s
                for s in remaining_students
                if _student_pointer(profile, priorities, s, remaining_schools)[0]
                is None
            ]
            if drop_students:
                dropped = set(drop_students)
                for s in drop_students:
                    assigned[s] = None
                remaining_students = [
                    s for s in remaining_students if s not in dropped
                ]
                exhausted.extend(drop_students)
                changed = True
            drop_schools = [
                c
                for c in remaining_schools
                if _school_points_at(priorities, c, remaining_students) is None
            ]
            if drop_schools:
                dropped_c = set(drop_schools)
                remaining_schools = [
                    c for c in remaining_schools if c not in dropped_c
                ]
                closed.extend(drop_schools)
                changed = True
            if not changed:
                break

        if not remaining_students:
            if exhausted or closed:
                steps.append(
                    TTCStep(
                        index=index,
                        exhausted_students=tuple(exhausted),
                        closed_schools=tuple(closed),
                        student_points_to=(),
                        skipped_unacceptable=(),
                        school_points_to=(),
                        cycles=(),
                        assigned=(),
                        filled_schools=(),
                        seats_left_after=tuple(
                            (c, seats[c]) for c in remaining_schools
                        ),
                    )
                )
            break

        # ---- build the pointer graph ----
        pointer: dict[tuple[str, str], tuple[str, str]] = {}
        student_points: list[tuple[str, str]] = []
        skipped: list[tuple[str, str]] = []
        for s in remaining_students:
            target, passed_over = _student_pointer(
                profile, priorities, s, remaining_schools
            )
            skipped.extend(passed_over)
            if target is None:  # pragma: no cover - the prune above removed these
                raise MechanismError(
                    f"student {s!r} survived pruning with no school to point at"
                )
            pointer[(_STUDENT, s)] = (_SCHOOL, target)
            student_points.append((s, target))
        school_points: list[tuple[str, str]] = []
        for c in remaining_schools:
            s = _school_points_at(priorities, c, remaining_students)
            if s is None:  # pragma: no cover - the prune above removed these
                raise MechanismError(
                    f"school {c!r} survived pruning with no student to point at"
                )
            pointer[(_SCHOOL, c)] = (_STUDENT, s)
            school_points.append((c, s))

        nodes = [(_STUDENT, s) for s in remaining_students] + [
            (_SCHOOL, c) for c in remaining_schools
        ]
        raw_cycles = _find_cycles(pointer, nodes)
        if not raw_cycles:
            raise MechanismError(
                "top_trading_cycles: no cycle found although every node has "
                "out-degree one, which is impossible in a finite graph; this "
                "means the pointer graph was built wrong"
            )

        cycles = sorted(
            (_as_trades(rc, student_index) for rc in raw_cycles),
            key=lambda cyc: student_index[cyc[0][0]],
        )
        chosen = (
            cycles
            if config.cycle_policy == CYCLES_ALL_SIMULTANEOUS
            else cycles[:1]
        )

        # ---- execute the trades ----
        newly_assigned: list[tuple[str, str]] = []
        for cyc in chosen:
            for s, c in cyc:
                assigned[s] = c
                seats[c] -= 1
                if seats[c] < 0:  # pragma: no cover - one cycle per school per step
                    raise MechanismError(
                        f"school {c!r} was over-filled: a school appeared in "
                        f"more than one cycle in a single step, which "
                        f"out-degree one forbids"
                    )
                newly_assigned.append((s, c))
        newly_assigned.sort(key=lambda p: student_index[p[0]])

        done = {s for cyc in chosen for s, _ in cyc}
        remaining_students = [s for s in remaining_students if s not in done]
        filled = [c for c in remaining_schools if seats[c] <= 0]
        remaining_schools = [c for c in remaining_schools if seats[c] > 0]

        steps.append(
            TTCStep(
                index=index,
                exhausted_students=tuple(exhausted),
                closed_schools=tuple(closed),
                student_points_to=tuple(student_points),
                skipped_unacceptable=tuple(skipped),
                school_points_to=tuple(school_points),
                cycles=tuple(cycles) if config.cycle_policy == CYCLES_ALL_SIMULTANEOUS
                else tuple(chosen),
                assigned=tuple(newly_assigned),
                filled_schools=tuple(filled),
                seats_left_after=tuple((c, seats[c]) for c in remaining_schools),
            )
        )

    assignment = build_assignment(
        market,
        priorities,
        {s: assigned.get(s) for s in market.students},
        allow_unranked=False,
    )
    return TTCResult(assignment=assignment, steps=tuple(steps), priorities=priorities)


def distinct_priority_orders(
    market: Market, priorities: ResolvedPriorities
) -> int:
    """How many DIFFERENT strict priority orders the schools actually have.

    This is a non-vacuity measurement for any TTC result, and it exists
    because a sweep can otherwise report a perfectly true "0 manipulations"
    about a mechanism it never really ran.

    WHEN THIS RETURNS 1, TTC IS NOT TTC. If every school shares one priority
    order, the top-priority remaining student always forms a two-cycle with
    her own favourite remaining school, so TTC degenerates to serial
    dictatorship over that common order -- and so does student-proposing DA.
    The two mechanisms are then provably identical, no step ever contains
    more than one cycle, and "TTC is strategy-proof" reduces to the much
    weaker "serial dictatorship is strategy-proof."

    This is not hypothetical. The generator's own defaults at the time TTC
    was added (`tiebreak_family=stb` with `n_priority_classes=1`) produce
    exactly one common order: a single lottery, applied to a single class,
    is the same permutation at every school. Measured over 300 generated
    instances at 5 students x 3 schools, TTC and DA disagreed on 0 of them
    and no step ever held two cycles. Switching to per-school lotteries
    (`mtb`) or to several priority classes moved that to about 26%
    disagreement and 40% of instances containing a multi-cycle step AT THAT
    SAME SHAPE.

    The shape qualifier is not decoration. That disagreement rate is a
    function of instance size, not a constant of the mechanism: measured at
    300 instances per shape it runs 8.7% (3x3), 25.7% (5x3), 46.3% (6x4),
    59.3% (8x4), 81.0% (10x5), 91.7% (12x6). Quoting "about 26%" without the
    shape invites reading a generator artefact as a property of TTC.

    So: any sweep of this mechanism should record this number, and any sweep
    that reports 1 is a sweep of serial dictatorship wearing TTC's name.
    """
    return len({priorities.orders[c] for c in market.schools})


def ttc_differs_from_da_iff_unstable(
    ttc_assignment, da_assignment, market, profile, priorities
) -> bool:
    """The proved identity: TTC's outcome differs from DA's EXACTLY when
    TTC's outcome has a blocking pair.

    Proof. DA (student-proposing) returns the student-optimal STABLE matching.
    TTC returns a Pareto-efficient one. If TTC's outcome were stable, then DA's
    being student-optimal among stable matchings would make it weakly better
    for every student than TTC's; Pareto efficiency of TTC's outcome then
    forbids that from being a strict improvement for anyone, so the two
    coincide. Conversely if the two coincide then TTC's outcome is DA's, which
    is stable. Hence differs <=> unstable.

    This matters for how results get reported, not just for correctness. "TTC
    disagrees with DA on X% of instances" and "TTC's outcome is unstable on
    X% of instances" are NOT two pieces of evidence -- they are one
    measurement written twice, and quoting both as if they corroborated each
    other double-counts. REVIEWER.md asks for a measurement to become an
    assertion wherever a proof exists, so this is the assertion; it is
    exercised by `tests/test_ttc_properties.py`.
    """
    from witness.oracles import blocking_pairs

    return (ttc_assignment != da_assignment) == bool(
        blocking_pairs(market, profile, priorities, ttc_assignment)
    )
