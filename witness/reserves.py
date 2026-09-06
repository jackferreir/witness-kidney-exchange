"""Deferred acceptance with reserved seats: the slot model of Dur, Kominers,
Pathak & Sonmez (2018), "Reserve Design: Unintended Consequences and the
Demise of Boston's Walk Zones", Journal of Political Economy 126(6):2457-2479.

THE PUBLISHED CHOICE RULE, verbatim in structure (DKPS section 3.1):

    A school `a` has a set of slots S_a. Each slot s has its own linear
    priority order pi^s over students. The slots are ordered by a linear
    ORDER OF PRECEDENCE, s^1 > s^2 > ... > s^|S_a|. Given a set of applicants
    J, the choice C_a(J) is obtained by filling slots one at a time following
    the precedence order: the highest-priority student in J under pi^{s^1},
    say j_1, is chosen for slot s^1; the highest-priority student in
    J \\ {j_1} under pi^{s^2} is chosen for slot s^2; and so on.

    At OPEN slots, pi^s is the school's ordinary priority order. At RESERVE
    slots, every reserve-eligible student has priority over every
    reserve-ineligible student, and within each group the school's ordinary
    order applies.

DA itself is unchanged -- DKPS section 4 states the proposal loop verbatim as
Gale-Shapley with C_a substituted in. That is why this module supplies a
`choice_rule` to `witness.da.deferred_acceptance` instead of reimplementing
the loop: reimplementing it would create a second copy of the algorithm that
could drift from the one the negative control validates.

THE DISTINCTION THIS MODULE EXISTS TO KEEP STRAIGHT -- reserve vs quota:

    A RESERVE seat is a FLOOR for the target group. It is filled by the best
    eligible applicant if there is one, and OTHERWISE BY THE BEST INELIGIBLE
    APPLICANT. It never goes empty while an acceptable applicant is waiting.
    This is DKPS's model, and Boston's walk-zone seats.

    A QUOTA seat is EXCLUSIVE to the target group. If no eligible applicant
    is available it goes EMPTY, rejecting acceptable students while a seat
    sits unused.

These are different mechanisms with different properties, and every instance
in which enough eligible students apply produces the SAME answer under both.
Only the eligible-scarce case separates them, so that case is hand-worked
explicitly (see tests/test_reserves_handworked.py, RES-A). `reserve_type`
selects between them and both settings are tested.

MODELLING DECISION (declared, not inherited): DKPS assume a single master
priority order pi^0 uniform across all schools, because Boston used a single
tie-breaking lottery. This module instead derives each school's slot
priorities from that school's OWN resolved order in `ResolvedPriorities` --
which is what `Market.priority_classes` plus a tiebreak rule already produce.
The choice rule C_a never refers to any school but `a`, so this is a faithful
generalisation rather than a change: configuring `SingleLotteryTiebreak` with
uniform priority classes reproduces DKPS's uniform pi^0 exactly.

NOT IMPLEMENTED: arbitrary interleavings of reserve and open slots. DKPS
allow any linear precedence over individual slots; `precedence` here offers
the two block orders (all reserve first, or all open first), which are the
deployed cases and the two extreme points of DKPS Proposition 3(ii). An
interleaved precedence is a different configuration, not a special case of
these two, and must not be approximated by either.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Optional, Sequence

from witness.core import (
    Market,
    MechanismConfig,
    Profile,
    ResolvedPriorities,
    resolve_priorities,
)
from witness.da import DAConfig, DAResult, deferred_acceptance
from witness.errors import MechanismError, ModelError
from witness.tiebreak import tiebreak_from_dict

#: A seat with no group restriction: filled by the school's ordinary order.
SLOT_OPEN = "open"

#: A seat that favours the reserve-eligible group. What "favours" means is
#: fixed by `reserve_type`, never by which branch happens to run first.
SLOT_RESERVE = "reserve"

#: Reserve seats are a FLOOR: an ineligible student may take one that no
#: eligible student claims. DKPS / Boston walk zones.
RESERVE_SOFT = "soft_reserve"

#: Reserve seats are EXCLUSIVE: unclaimed ones go empty. A hard type-specific
#: quota, in the sense of Abdulkadiroglu & Sonmez (2003) controlled choice.
RESERVE_HARD = "hard_quota"

_RESERVE_TYPES = (RESERVE_SOFT, RESERVE_HARD)

#: Reserve slots are filled before open slots. This is what Boston did, and
#: DKPS's central finding is that it is the setting that HURT the reserve
#: group relative to the alternative.
PRECEDENCE_RESERVE_FIRST = "reserve_first"

#: Open slots are filled before reserve slots.
PRECEDENCE_OPEN_FIRST = "open_first"

_PRECEDENCE_ORDERS = (PRECEDENCE_RESERVE_FIRST, PRECEDENCE_OPEN_FIRST)


@dataclass(frozen=True)
class SchoolReserve:
    """One school's reserve policy: how many seats, and who is eligible.

    `eligible` is a SET of students, recorded as a sorted tuple. Its order is
    deliberately not semantic: the order among eligible students at a reserve
    slot comes from the school's resolved priority order, never from the
    order the caller happened to list them in.
    """

    reserved_seats: int
    eligible: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        q = self.reserved_seats
        if isinstance(q, bool) or not isinstance(q, int) or q < 0:
            raise ModelError(
                f"reserved_seats must be a non-negative int, got {q!r}"
            )
        elig = tuple(self.eligible)
        if len(set(elig)) != len(elig):
            raise ModelError(f"duplicate student in reserve eligibility {elig!r}")
        object.__setattr__(self, "eligible", tuple(sorted(elig)))

    def is_eligible(self, student: str) -> bool:
        return student in self.eligible

    def to_dict(self) -> dict:
        return {"reserved_seats": self.reserved_seats, "eligible": list(self.eligible)}

    @staticmethod
    def from_dict(data: Mapping) -> "SchoolReserve":
        return SchoolReserve(
            reserved_seats=data["reserved_seats"],
            eligible=tuple(data.get("eligible", ())),
        )


@dataclass(frozen=True)
class ReserveConfig(DAConfig):
    """`DAConfig` plus the reserve structure and the precedence order.

    A school absent from `reserves` has ZERO reserved seats -- every one of
    its slots is open, so it behaves exactly as it would under plain DA. That
    is checked directly rather than assumed: with no reserves anywhere,
    `reserve_da` must reproduce `deferred_acceptance` trace for trace.

    `precedence` is an outcome-affecting parameter in the strongest sense.
    Unlike `proposal_policy`, whose two settings provably CANNOT change the
    matching, the two `precedence` settings PROVABLY CAN (DKPS Proposition 3
    (ii)), and the tests pin a specific instance where they do. An
    implementation in which precedence never mattered would be wrong, and
    that is a distinct failure from one in which it mattered inconsistently.
    """

    reserves: Mapping[str, SchoolReserve] = field(default_factory=dict)
    reserve_type: str = RESERVE_SOFT
    precedence: str = PRECEDENCE_RESERVE_FIRST
    mechanism: str = "reserve_da"

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.reserve_type not in _RESERVE_TYPES:
            raise ModelError(
                f"reserve_type must be one of {_RESERVE_TYPES}, got {self.reserve_type!r}"
            )
        if self.precedence not in _PRECEDENCE_ORDERS:
            raise ModelError(
                f"precedence must be one of {_PRECEDENCE_ORDERS}, got {self.precedence!r}"
            )
        normalized: dict[str, SchoolReserve] = {}
        for school, spec in self.reserves.items():
            if not isinstance(school, str) or not school:
                raise ModelError(f"reserves: school ids must be non-empty strings, got {school!r}")
            if not isinstance(spec, SchoolReserve):
                raise ModelError(
                    f"reserves[{school!r}] must be a SchoolReserve, got {spec!r}"
                )
            normalized[school] = spec
        object.__setattr__(self, "reserves", normalized)

    def reserve_for(self, school: str) -> SchoolReserve:
        """`school`'s reserve policy; an all-open policy if it declared none."""
        return self.reserves.get(school, SchoolReserve(reserved_seats=0, eligible=()))

    def to_dict(self) -> dict:
        data = super().to_dict()
        data["reserve_type"] = self.reserve_type
        data["precedence"] = self.precedence
        data["reserves"] = {
            c: self.reserves[c].to_dict() for c in sorted(self.reserves)
        }
        return data

    @classmethod
    def from_dict(cls, data: Mapping) -> "ReserveConfig":
        return cls(
            tiebreak=tiebreak_from_dict(data["tiebreak"]),
            unlisted_student_policy=data["unlisted_student_policy"],
            proposal_policy=data["proposal_policy"],
            mechanism=data.get("mechanism", "reserve_da"),
            reserves={
                c: SchoolReserve.from_dict(d)
                for c, d in data.get("reserves", {}).items()
            },
            reserve_type=data.get("reserve_type", RESERVE_SOFT),
            precedence=data.get("precedence", PRECEDENCE_RESERVE_FIRST),
        )


def slot_sequence(capacity: int, reserved_seats: int, precedence: str) -> tuple[str, ...]:
    """The school's slots, in the order of precedence.

    Length is exactly `capacity`: the reserve is a way of SPLITTING the
    school's seats, never a way of adding to them.
    """
    if precedence not in _PRECEDENCE_ORDERS:
        raise ModelError(f"unknown precedence {precedence!r}")
    if reserved_seats > capacity:
        raise ModelError(
            f"reserved_seats {reserved_seats} exceeds capacity {capacity}: reserve "
            f"slots are a split of the school's seats, not extra ones"
        )
    reserve = (SLOT_RESERVE,) * reserved_seats
    open_ = (SLOT_OPEN,) * (capacity - reserved_seats)
    if precedence == PRECEDENCE_RESERVE_FIRST:
        return reserve + open_
    return open_ + reserve


def fill_slots(
    market: Market,
    priorities: ResolvedPriorities,
    config: ReserveConfig,
    school: str,
    pool: Sequence[str],
) -> tuple[tuple[str, Optional[str]], ...]:
    """`C_school(pool)`, as a slot-by-slot record in precedence order.

    Each entry is `(slot_kind, student_or_None)`. A `None` can only arise at a
    RESERVE slot under `RESERVE_HARD`, where the seat is exclusive and no
    eligible applicant remains. Under `RESERVE_SOFT` a slot is left empty only
    when the pool is exhausted.

    Returning the slot assignment, rather than just the chosen set, is what
    lets a hand-worked test check that the right student took the right KIND
    of seat -- two configurations can choose the same students by different
    routes, and only the slot record distinguishes them.
    """
    spec = config.reserve_for(school)
    slots = slot_sequence(market.capacity(school), spec.reserved_seats, config.precedence)
    remaining = sorted(pool, key=lambda s: priorities.rank(school, s))
    filled: list[tuple[str, Optional[str]]] = []
    for kind in slots:
        pick: Optional[str] = None
        if kind == SLOT_OPEN:
            if remaining:
                pick = remaining[0]
        else:
            eligible = [s for s in remaining if spec.is_eligible(s)]
            if eligible:
                pick = eligible[0]
            elif config.reserve_type == RESERVE_SOFT and remaining:
                # The reserve is a floor, not a cap: with no eligible
                # applicant left, the seat goes to the best remaining
                # applicant rather than sitting empty.
                pick = remaining[0]
            # RESERVE_HARD: the seat is exclusive, so it stays empty.
        if pick is not None:
            remaining.remove(pick)
        filled.append((kind, pick))
    return tuple(filled)


def reserve_choice_rule(
    config: ReserveConfig,
    market: Market,
    priorities: ResolvedPriorities,
    school: str,
    pool: Sequence[str],
) -> tuple[str, ...]:
    """The `choice_rule` `witness.da.deferred_acceptance` calls: the students
    `fill_slots` seated, in slot order."""
    return tuple(s for _, s in fill_slots(market, priorities, config, school, pool) if s is not None)


def validate_reserves(market: Market, config: ReserveConfig) -> None:
    """Check the reserve structure against the market it will be run on.

    Kept separate from `ReserveConfig.__post_init__` because a config is
    market-independent: the same policy can be replayed against the market
    stored in a witness, and it is at that join that these must agree.
    """
    schools = set(market.schools)
    students = set(market.students)
    for school in sorted(config.reserves):
        spec = config.reserves[school]
        if school not in schools:
            raise ModelError(
                f"reserves names unknown school {school!r}; market has {sorted(schools)}"
            )
        unknown = [s for s in spec.eligible if s not in students]
        if unknown:
            raise ModelError(
                f"reserve eligibility of {school!r} names unknown students {unknown!r}"
            )
        if spec.reserved_seats > market.capacity(school):
            raise ModelError(
                f"school {school!r} reserves {spec.reserved_seats} of its "
                f"{market.capacity(school)} seats: reserve slots are a split of the "
                f"school's seats, not extra ones"
            )


def reserve_da(
    market: Market,
    profile: Profile,
    config: Optional[ReserveConfig] = None,
    *,
    priorities: Optional[ResolvedPriorities] = None,
) -> DAResult:
    """Student-proposing DA under the DKPS slot choice rule."""
    config = config if config is not None else ReserveConfig()
    if not isinstance(config, ReserveConfig):
        raise ModelError(f"reserve_da needs a ReserveConfig, got {config!r}")
    validate_reserves(market, config)
    if priorities is None:
        priorities = resolve_priorities(market, config)

    def rule(m: Market, p: ResolvedPriorities, school: str, pool: Sequence[str]):
        return reserve_choice_rule(config, m, p, school, pool)

    return deferred_acceptance(
        market, profile, config, priorities=priorities, choice_rule=rule
    )


def reserve_seats_used(
    market: Market,
    priorities: ResolvedPriorities,
    config: ReserveConfig,
    school: str,
    roster: Sequence[str],
) -> tuple[int, int]:
    """(eligible admitted, ineligible admitted) at `school`.

    The measurement DKPS Proposition 3 is stated in terms of. Reported rather
    than asserted: which direction it moves is a claim about the published
    comparative static, and the tests check it against hand-worked instances
    rather than against this function's own output.
    """
    spec = config.reserve_for(school)
    eligible = sum(1 for s in roster if spec.is_eligible(s))
    return eligible, len(roster) - eligible
