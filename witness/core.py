"""Core data model: markets, reported profiles, resolved priorities, config.

Terminology follows the school-choice literature (Abdulkadiroglu & Sonmez
2003), which is also the standard framing for the residency match with the
sides renamed:

    students          the proposing side
    schools           the receiving side, with capacity q_c
    report            a student's submitted ranking, strict and possibly
                      truncated; a school absent from the ranking is
                      *unacceptable* to that student
    priority classes  a school's coarse ranking of students, best class first
    tiebreak          the strict order applied inside one priority class

Two determinism rules hold throughout this package:

  1. No outcome-affecting iteration is over a dict or a set. Iteration that can
     affect an outcome goes over `Market.students`, `Market.schools`, a
     student's report, or a resolved strict priority order — all explicit,
     caller-declared tuples.

  2. `resolve_priorities` does not take a profile. School priority orders are
     therefore structurally incapable of depending on what students reported,
     which is what makes a truthful run and a misreport run comparable. If
     that guarantee were softer, every "manipulation" we found would be
     suspect.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Iterator, Mapping, Optional, Sequence

from witness.errors import ModelError
from witness.tiebreak import RejectTies, tiebreak_from_dict

#: A student's assignment is either a school id or `None` (unmatched).
Assigned = Optional[str]

#: Position of an unranked school, or of being unmatched, in a student's report.
#: Both are "worst"; a student is indifferent between them and, per
#: `strictly_prefers`, never strictly prefers one over the other.
WORST = float("inf")


def _as_id_tuple(values: Sequence[str], what: str) -> tuple[str, ...]:
    out = tuple(values)
    for v in out:
        if not isinstance(v, str) or not v:
            raise ModelError(f"{what}: ids must be non-empty strings, got {v!r}")
    if len(set(out)) != len(out):
        raise ModelError(f"{what}: duplicate ids in {list(out)!r}")
    return out


@dataclass(frozen=True)
class Market:
    """Everything about an instance except what the students reported.

    `students` and `schools` are ordered tuples. That order is the canonical
    enumeration order used anywhere this code needs "all students" or "all
    schools" — it is never taken from a dict.

    `priority_classes[c]` is a tuple of classes, best class first; each class
    is a tuple of student ids. A student listed in no class of `c` is handled
    by `MechanismConfig.unlisted_student_policy`.
    """

    students: tuple[str, ...]
    schools: tuple[str, ...]
    capacities: Mapping[str, int]
    priority_classes: Mapping[str, tuple[tuple[str, ...], ...]]

    def __post_init__(self) -> None:
        students = _as_id_tuple(self.students, "students")
        schools = _as_id_tuple(self.schools, "schools")
        if not students:
            raise ModelError("a market needs at least one student")
        if not schools:
            raise ModelError("a market needs at least one school")
        student_set = set(students)

        if set(self.capacities) != set(schools):
            raise ModelError(
                f"capacities must have exactly one entry per school; "
                f"got {sorted(self.capacities)}, expected {sorted(schools)}"
            )
        capacities = {}
        for c in schools:
            q = self.capacities[c]
            if isinstance(q, bool) or not isinstance(q, int) or q < 0:
                raise ModelError(f"capacity of {c!r} must be a non-negative int, got {q!r}")
            capacities[c] = q

        if set(self.priority_classes) != set(schools):
            raise ModelError(
                f"priority_classes must have exactly one entry per school; "
                f"got {sorted(self.priority_classes)}, expected {sorted(schools)}"
            )
        priority_classes = {}
        for c in schools:
            classes = tuple(
                _as_id_tuple(cls, f"priority class of {c!r}")
                for cls in self.priority_classes[c]
            )
            seen: set[str] = set()
            for cls in classes:
                for s in cls:
                    if s not in student_set:
                        raise ModelError(f"priority of {c!r} lists unknown student {s!r}")
                    if s in seen:
                        raise ModelError(
                            f"student {s!r} appears in more than one priority class of {c!r}"
                        )
                    seen.add(s)
            priority_classes[c] = classes

        object.__setattr__(self, "students", students)
        object.__setattr__(self, "schools", schools)
        object.__setattr__(self, "capacities", capacities)
        object.__setattr__(self, "priority_classes", priority_classes)

    def capacity(self, school: str) -> int:
        return self.capacities[school]

    def total_seats(self) -> int:
        return sum(self.capacities[c] for c in self.schools)

    def to_dict(self) -> dict:
        return {
            "students": list(self.students),
            "schools": list(self.schools),
            "capacities": {c: self.capacities[c] for c in self.schools},
            "priority_classes": {
                c: [list(cls) for cls in self.priority_classes[c]] for c in self.schools
            },
        }

    @staticmethod
    def from_dict(data: Mapping) -> "Market":
        return Market(
            students=tuple(data["students"]),
            schools=tuple(data["schools"]),
            capacities=dict(data["capacities"]),
            priority_classes={
                c: tuple(tuple(cls) for cls in classes)
                for c, classes in data["priority_classes"].items()
            },
        )


@dataclass(frozen=True)
class Profile:
    """What the students submitted: `rankings[s]` is a tuple, best first.

    A school absent from `rankings[s]` is unacceptable to `s` — that is the
    published definition of a truncated list, not a convenience.

    The same type carries a *truthful* preference profile and a *reported*
    profile. A witness records both, and `strictly_prefers` is always evaluated
    against the truthful one.
    """

    rankings: Mapping[str, tuple[str, ...]]

    def __post_init__(self) -> None:
        normalized: dict[str, tuple[str, ...]] = {}
        for s, ranking in self.rankings.items():
            if not isinstance(s, str) or not s:
                raise ModelError(f"profile: student ids must be non-empty strings, got {s!r}")
            normalized[s] = _as_id_tuple(ranking, f"ranking of {s!r}")
        object.__setattr__(self, "rankings", normalized)

    def report(self, student: str) -> tuple[str, ...]:
        try:
            return self.rankings[student]
        except KeyError:
            raise ModelError(f"no report for student {student!r}") from None

    def with_report(self, student: str, ranking: Sequence[str]) -> "Profile":
        """A copy in which `student` reports `ranking` instead. Used by the
        manipulation search to swap in one student's misreport."""
        updated = dict(self.rankings)
        updated[student] = tuple(ranking)
        return Profile(updated)

    def validate_against(self, market: Market) -> None:
        if set(self.rankings) != set(market.students):
            raise ModelError(
                f"profile must have exactly one report per student; got "
                f"{sorted(self.rankings)}, expected {sorted(market.students)}"
            )
        school_set = set(market.schools)
        for s in market.students:
            for c in self.rankings[s]:
                if c not in school_set:
                    raise ModelError(f"report of {s!r} lists unknown school {c!r}")

    def to_dict(self) -> dict:
        return {"rankings": {s: list(r) for s, r in sorted(self.rankings.items())}}

    @staticmethod
    def from_dict(data: Mapping) -> "Profile":
        return Profile({s: tuple(r) for s, r in data["rankings"].items()})


def position(ranking: Sequence[str], school: Assigned) -> float:
    """Where `school` sits in `ranking`; `WORST` if unranked or unmatched."""
    if school is None:
        return WORST
    try:
        return float(ranking.index(school))
    except ValueError:
        return WORST


def strictly_prefers(ranking: Sequence[str], a: Assigned, b: Assigned) -> bool:
    """True iff `a` is strictly better than `b` under `ranking`.

    Being unmatched and being assigned an unranked school are both `WORST`, so
    neither is strictly preferred to the other. That is the conservative
    direction: it can only make us *miss* a manipulation, never invent one.
    """
    return position(ranking, a) < position(ranking, b)


@dataclass(frozen=True)
class ResolvedPriorities:
    """Each school's strict priority order, after tiebreaking.

    `orders[c]` lists exactly the students acceptable to `c`, best first. A
    student absent from `orders[c]` is unacceptable to `c` and can never be
    held by it — not even when `c` has an empty seat.
    """

    orders: Mapping[str, tuple[str, ...]]

    def __post_init__(self) -> None:
        normalized: dict[str, tuple[str, ...]] = {}
        ranks: dict[str, dict[str, int]] = {}
        for c, order in self.orders.items():
            order = _as_id_tuple(order, f"priority order of {c!r}")
            normalized[c] = order
            ranks[c] = {s: i for i, s in enumerate(order)}
        object.__setattr__(self, "orders", normalized)
        object.__setattr__(self, "_ranks", ranks)

    def rank(self, school: str, student: str) -> Optional[int]:
        """`student`'s position in `school`'s strict order, or None if
        unacceptable. Ranks within a school are distinct by construction, so
        comparing them is a strict total order with no residual ties."""
        return self._ranks[school].get(student)  # type: ignore[attr-defined]

    def acceptable(self, school: str, student: str) -> bool:
        return student in self._ranks[school]  # type: ignore[attr-defined]

    def prefers(self, school: str, student: str, other: str) -> bool:
        """True iff `school` ranks `student` strictly above `other`.
        Both must be acceptable to `school`."""
        a, b = self.rank(school, student), self.rank(school, other)
        if a is None or b is None:
            raise ModelError(
                f"prefers({school!r}, {student!r}, {other!r}): both students must "
                f"be acceptable to the school"
            )
        return a < b

    def to_dict(self) -> dict:
        return {"orders": {c: list(o) for c, o in sorted(self.orders.items())}}


#: A student listed in no priority class of a school is unacceptable to it.
#: Standard when schools screen applicants (e.g. residency programs).
UNLISTED_UNACCEPTABLE = "unacceptable"

#: A student listed in no priority class joins one extra class below all
#: declared classes, tiebroken by the configured rule. Standard when every
#: student is eligible everywhere and priority classes only express advantage
#: (e.g. most public school-choice systems).
UNLISTED_LOWEST_CLASS = "lowest_priority_class"

_UNLISTED_POLICIES = (UNLISTED_UNACCEPTABLE, UNLISTED_LOWEST_CLASS)


@dataclass(frozen=True)
class MechanismConfig:
    """Configuration shared by every mechanism in this package.

    Both `unlisted_student_policy` settings are real deployed conventions, so
    neither is treated as the "obvious" one: the tests exercise both.
    """

    tiebreak: object = field(default_factory=RejectTies)
    unlisted_student_policy: str = UNLISTED_UNACCEPTABLE

    def __post_init__(self) -> None:
        if self.unlisted_student_policy not in _UNLISTED_POLICIES:
            raise ModelError(
                f"unlisted_student_policy must be one of {_UNLISTED_POLICIES}, "
                f"got {self.unlisted_student_policy!r}"
            )
        if not hasattr(self.tiebreak, "order_within"):
            raise ModelError(f"tiebreak rule {self.tiebreak!r} has no order_within()")

    def to_dict(self) -> dict:
        return {
            "tiebreak": self.tiebreak.to_dict(),
            "unlisted_student_policy": self.unlisted_student_policy,
        }

    @classmethod
    def from_dict(cls, data: Mapping) -> "MechanismConfig":
        return cls(
            tiebreak=tiebreak_from_dict(data["tiebreak"]),
            unlisted_student_policy=data["unlisted_student_policy"],
        )


def resolve_priorities(market: Market, config: MechanismConfig) -> ResolvedPriorities:
    """Turn (priority classes + tiebreak rule) into a strict order per school.

    Takes no profile, by design: see the module docstring. Iterates
    `market.schools` and the declared class tuples, never a dict or set.
    """
    orders: dict[str, tuple[str, ...]] = {}
    for c in market.schools:
        classes = market.priority_classes[c]
        if config.unlisted_student_policy == UNLISTED_LOWEST_CLASS:
            listed = {s for cls in classes for s in cls}
            unlisted = tuple(s for s in market.students if s not in listed)
            if unlisted:
                classes = classes + (unlisted,)
        order: list[str] = []
        for cls in classes:
            order.extend(config.tiebreak.order_within(c, cls, market.students))
        orders[c] = tuple(order)
    return ResolvedPriorities(orders)


def canonical_json(obj) -> str:
    """Byte-stable JSON: sorted keys, no incidental whitespace.

    Lists keep their order because list order is semantic here (a ranking, a
    priority order); only mapping key order is normalized.
    """
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def content_hash(obj) -> str:
    """SHA-256 of `canonical_json(obj)`. Identifies a witness bundle."""
    return hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()
