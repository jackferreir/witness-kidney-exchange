"""Explicit tiebreak rules for school priority orders.

A school's strict priority order over students is, by construction, exactly
two things:

    (1) the priority classes the caller declared (coarse, e.g. "walk-zone
        applicants", "siblings", "everyone else"), best class first; and
    (2) a tiebreak rule that strictly orders the students inside one class.

There is no third input. In particular the outcome never depends on the order
in which students happen to come out of a Python dict or set: every rule here
either refuses to break the tie, uses an order the caller wrote down, or uses a
lottery derived from a caller-supplied seed by the documented construction in
`lottery_key`.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Mapping, Sequence

from witness.errors import ModelError, TieError

#: Domain-separation string. Bump the version suffix if the derivation changes;
#: old seeds then provably cannot be confused with new ones.
LOTTERY_DOMAIN = "witness/tiebreak/v1"

#: Scope used by a single-lottery (STB) rule, where all schools share one order.
GLOBAL_SCOPE = "*GLOBAL*"

#: Key in an ExplicitTiebreak order map that applies to every school.
DEFAULT_SCOPE = "*"


def lottery_key(seed: str, scope: str, student: str) -> str:
    """The lottery number of `student` within `scope`, as a hex digest.

    Deliberately *not* `random.shuffle` / `random.sample` on a seeded
    `random.Random`: those depend on CPython's Mersenne Twister internals and
    on the order of the input sequence, so a lottery order built that way can
    change with the Python version or with the order the caller happened to
    list the students in. This construction depends on nothing but the triple
    (seed, scope, student), so it is stable across processes, machines, and
    Python versions.
    """
    payload = "\x1f".join((LOTTERY_DOMAIN, seed, scope, student))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def lottery_order(seed: str, scope: str, students: Sequence[str]) -> tuple[str, ...]:
    """`students` sorted by lottery number, best (smallest) first.

    The student id is the secondary sort key, so even a digest collision
    resolves deterministically instead of falling back to input order.
    """
    return tuple(sorted(students, key=lambda s: (lottery_key(seed, scope, s), s)))


@dataclass(frozen=True)
class RejectTies:
    """Refuse to break ties. The default.

    Forces the caller to say what happens inside a priority class instead of
    silently inheriting some incidental order. Hand-worked test cases use fully
    strict priorities, so this rule is what they run under.
    """

    name = "reject_ties"

    def order_within(
        self, scope: str, members: Sequence[str], canonical_students: Sequence[str]
    ) -> tuple[str, ...]:
        members = tuple(members)
        if len(members) > 1:
            raise TieError(
                f"priority tie at {scope!r} among {members!r}: the configured "
                f"tiebreak rule is {self.name!r}, which refuses to order them. "
                f"Declare an explicit order or configure a lottery."
            )
        return members

    def to_dict(self) -> dict:
        return {"rule": self.name}


@dataclass(frozen=True)
class DeclaredStudentOrderTiebreak:
    """Break ties by the caller's declared student order (`Market.students`).

    This is explicit — `Market.students` is an ordered tuple the caller wrote
    down, not an incidental dict ordering — but it couples the outcome to a
    field whose main job is enumeration, so prefer a lottery or an explicit
    order for anything but small illustrative cases.
    """

    name = "declared_student_order"

    def order_within(
        self, scope: str, members: Sequence[str], canonical_students: Sequence[str]
    ) -> tuple[str, ...]:
        position = {s: i for i, s in enumerate(canonical_students)}
        missing = [s for s in members if s not in position]
        if missing:
            raise ModelError(f"{self.name}: unknown students {missing!r} at {scope!r}")
        return tuple(sorted(members, key=lambda s: position[s]))

    def to_dict(self) -> dict:
        return {"rule": self.name}


@dataclass(frozen=True)
class ExplicitTiebreak:
    """Break ties by an order the caller supplies, per school.

    `orders` maps a school id to a sequence of students, best first. The key
    `"*"` supplies a default used by any school without its own entry. Every
    student being ordered must appear in the applicable order, otherwise this
    raises rather than guessing.
    """

    orders: Mapping[str, tuple[str, ...]]

    name = "explicit"

    def __post_init__(self) -> None:
        normalized: dict[str, tuple[str, ...]] = {}
        for scope, order in self.orders.items():
            order = tuple(order)
            if len(set(order)) != len(order):
                raise ModelError(f"{self.name}: duplicate student in order for {scope!r}")
            normalized[scope] = order
        object.__setattr__(self, "orders", normalized)

    def _order_for(self, scope: str) -> tuple[str, ...]:
        if scope in self.orders:
            return self.orders[scope]
        if DEFAULT_SCOPE in self.orders:
            return self.orders[DEFAULT_SCOPE]
        raise ModelError(
            f"{self.name}: no tiebreak order declared for {scope!r} and no "
            f"{DEFAULT_SCOPE!r} default"
        )

    def order_within(
        self, scope: str, members: Sequence[str], canonical_students: Sequence[str]
    ) -> tuple[str, ...]:
        order = self._order_for(scope)
        position = {s: i for i, s in enumerate(order)}
        missing = [s for s in members if s not in position]
        if missing:
            raise ModelError(
                f"{self.name}: students {missing!r} are in a priority class of "
                f"{scope!r} but absent from its tiebreak order {order!r}"
            )
        return tuple(sorted(members, key=lambda s: position[s]))

    def to_dict(self) -> dict:
        return {
            "rule": self.name,
            "orders": {k: list(v) for k, v in sorted(self.orders.items())},
        }


@dataclass(frozen=True)
class SingleLotteryTiebreak:
    """Single tiebreak (STB): one lottery order, shared by every school.

    This is what NYC high-school admissions uses.
    """

    seed: str

    name = "single_lottery"

    def order_within(
        self, scope: str, members: Sequence[str], canonical_students: Sequence[str]
    ) -> tuple[str, ...]:
        return lottery_order(self.seed, GLOBAL_SCOPE, members)

    def to_dict(self) -> dict:
        return {"rule": self.name, "seed": self.seed}


@dataclass(frozen=True)
class MultipleLotteryTiebreak:
    """Multiple tiebreak (MTB): an independent lottery order per school.

    Scoped by school id, so two schools' orders are independent draws of the
    same seed. Boston used MTB in its 2005 redesign.
    """

    seed: str

    name = "multiple_lottery"

    def order_within(
        self, scope: str, members: Sequence[str], canonical_students: Sequence[str]
    ) -> tuple[str, ...]:
        return lottery_order(self.seed, scope, members)

    def to_dict(self) -> dict:
        return {"rule": self.name, "seed": self.seed}


_RULES = {
    RejectTies.name: lambda d: RejectTies(),
    DeclaredStudentOrderTiebreak.name: lambda d: DeclaredStudentOrderTiebreak(),
    ExplicitTiebreak.name: lambda d: ExplicitTiebreak(
        {k: tuple(v) for k, v in d["orders"].items()}
    ),
    SingleLotteryTiebreak.name: lambda d: SingleLotteryTiebreak(seed=d["seed"]),
    MultipleLotteryTiebreak.name: lambda d: MultipleLotteryTiebreak(seed=d["seed"]),
}


def tiebreak_from_dict(data: Mapping) -> object:
    """Rebuild a tiebreak rule from its `to_dict()` form (for witness replay)."""
    rule = data.get("rule")
    if rule not in _RULES:
        raise ModelError(f"unknown tiebreak rule {rule!r}; known: {sorted(_RULES)}")
    return _RULES[rule](data)
