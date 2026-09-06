"""Seeded random instance generator -- Step 3B, the WIDE generator.

WHY THIS REPLACES THE STEP-3A NARROW GENERATOR:

    The Step-3A generator (kept only in spirit here, not in code -- see
    BACKWARD COMPATIBILITY below) was NARROW ON PURPOSE: every student
    submitted a complete ranking, every school listed every student in one
    lottery-broken class, capacities were uniform, and the unlisted-student
    branch never fired. We measured its 4-students/3-schools/capacity-1
    setting and found it is OVER-SUBSCRIBED BY EXACTLY ONE SEAT (3 seats,
    4 students) in EVERY instance it produces -- so exactly one student is
    unmatched in every instance, never zero, never two. That single
    structural fact drove a measured 75-80% Boston manipulation rate, of
    which 241/258 gains came from students who were truthfully unmatched.
    Measured per-student manipulation rates by subscription level:
    under-subscribed 0.0%, exactly-subscribed 4.2-8.4%, over-subscribed
    20.4-28.3%. Subscription level is therefore promoted here to a
    FIRST-CLASS generator parameter (`GeneratorConfig.subscription` /
    `subscription_ratio`), not an incidental consequence of whatever
    `capacity` happens to be -- a sweep that never varies subscription level
    is measuring one structural regime and mislabeling it "the" rate.

    This module also widens every other axis the narrow generator held
    fixed: truncated/short student reports (`list_length_mode`), schools that
    do not list every student in their priority classes
    (`school_lists_fraction`, which is what makes the unlisted-student
    branch -- and `UNLISTED_LOWEST_CLASS` in particular -- actually bite),
    coarse multi-class priority structures (`n_priority_classes`),
    heterogeneous per-school capacities (`capacity_mode`), and a choice
    between a single shared lottery and an independent per-school lottery
    (`tiebreak_family`). `witness.coverage` exists specifically to make it
    VISIBLE, per sweep, which of these branches a given `GeneratorConfig`
    actually reaches -- a sweep that never reaches a branch is not evidence
    about that branch, and silently assuming otherwise is exactly the
    mistake this module's WHY calls out.

DETERMINISM (non-negotiable house rule, unchanged from Step 3A):

    `generate_instance(gc, i)` must return byte-identical results across
    processes, machines, and Python versions -- exercised directly by a
    fresh-subprocess test. ALL randomness is derived from `hashlib.sha256`
    over the tuple (domain, seed, index/scope, purpose-string) -- the exact
    construction `witness.tiebreak.lottery_key` uses (see that module's
    docstring for why: the stdlib `random` module's `Random` class,
    `shuffle`, and `sample` all depend on CPython's Mersenne Twister
    internals and on input order, neither of which this module accepts as a
    source of randomness). Every permutation, subset, weight, and partition
    drawn here reduces to `witness.tiebreak.lottery_key` / `lottery_order`
    calls scoped by (seed, index, purpose, id) -- never the stdlib `random`
    module, never `dict`/`set` iteration order. `derive_seed` mints the
    purpose-scoped seed strings that keep every draw -- a student's report,
    a school's listed-student subset, a priority-class partition, a
    capacity weight, a mechanism's tiebreak -- from ever colliding with any
    other draw for the same or a different instance index.

    Student ids are "s1".."sN" and school ids are "c1".."cM", in that
    declared order -- never a dict or a set where it could affect an
    outcome.

BACKWARD COMPATIBILITY:

    `GeneratorConfig(n_students=..., n_schools=..., capacity=..., seed=...)`
    and `generate_instance(gc, i)` -- the Step-3A call shape used by
    `tests/test_boston_positive_control.py` and `scripts/search_power.py` --
    keep working unmodified. `capacity` is kept as a field: when given (not
    `None`), it is a LEGACY ALIAS that sets every school's capacity to that
    single uniform value directly, bypassing the `subscription` /
    `subscription_ratio` / `capacity_mode` derivation entirely, exactly
    reproducing Step 3A's behavior (and, with `n_students=4, n_schools=3,
    capacity=1`, its measured one-seat over-subscription). `priority_tiebreak`
    is also kept, unchanged in behavior: it always returns a
    `SingleLotteryTiebreak`, regardless of `tiebreak_family`, matching what
    Step 3A's callers already depend on. No existing call site needed to
    change.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from typing import Optional, Sequence

from witness.boston import BostonConfig
from witness.core import UNLISTED_LOWEST_CLASS, UNLISTED_UNACCEPTABLE, Market, Profile
from witness.da import DAConfig
from witness.errors import ModelError
from witness.ttc import TTCConfig
from witness.reserves import (
    PRECEDENCE_OPEN_FIRST,
    PRECEDENCE_RESERVE_FIRST,
    RESERVE_HARD,
    RESERVE_SOFT,
    ReserveConfig,
    SchoolReserve,
)
from witness.tiebreak import (
    MultipleLotteryTiebreak,
    SingleLotteryTiebreak,
    lottery_key,
    lottery_order,
)

#: Domain-separation string for this module's derived seeds, mirroring
#: `witness.tiebreak.LOTTERY_DOMAIN`. Bump the version suffix if the
#: derivation ever changes, so old and new seeds can never be confused.
GENERATE_DOMAIN = "witness/generate/v1"

# --- subscription: seats relative to students -----------------------------

#: Fewer seats than students: some student is structurally guaranteed to be
#: unmatched. `subscription_ratio` must be < 1.0.
SUBSCRIPTION_OVER = "over"

#: Seats exactly equal to students. `subscription_ratio` must be == 1.0.
SUBSCRIPTION_EXACT = "exact"

#: More seats than students. `subscription_ratio` must be > 1.0.
SUBSCRIPTION_UNDER = "under"

_SUBSCRIPTIONS = (SUBSCRIPTION_OVER, SUBSCRIPTION_EXACT, SUBSCRIPTION_UNDER)

# --- capacity distribution across schools ----------------------------------

#: Seats distributed as evenly as possible across schools (differing by at
#: most one seat -- the total seat count implied by `subscription` need not
#: be divisible by `n_schools`).
CAPACITY_UNIFORM = "uniform"

#: Seats distributed with deliberate, deterministic spread across schools
#: (see `_school_capacity_weights`), so some schools have visibly more seats
#: than others.
CAPACITY_HETEROGENEOUS = "heterogeneous"

_CAPACITY_MODES = (CAPACITY_UNIFORM, CAPACITY_HETEROGENEOUS)

# --- student preference lists ----------------------------------------------

#: Every student ranks every school -- a full permutation of `market.schools`.
LIST_COMPLETE = "complete"

#: Every student's report has exactly `GeneratorConfig.list_length` schools.
LIST_FIXED = "fixed"

#: Each student's report length is independently drawn (deterministically)
#: from 1..n_schools.
LIST_UNIFORM = "uniform"

#: Each student's report length is independently drawn (deterministically)
#: from {0, 1} -- i.e. always `had_very_short_list`-eligible.
LIST_SHORT = "short"

_LIST_LENGTH_MODES = (LIST_COMPLETE, LIST_FIXED, LIST_UNIFORM, LIST_SHORT)

# --- tiebreak family --------------------------------------------------------

#: Single tiebreak: one lottery order shared by every school.
TIEBREAK_STB = "stb"

#: Multiple tiebreak: an independent lottery order per school.
TIEBREAK_MTB = "mtb"

_TIEBREAK_FAMILIES = (TIEBREAK_STB, TIEBREAK_MTB)

# --- reserve structure (reserve_da only) ------------------------------------
#
# These four settings drive `generate_reserves` (the reserve-seat / eligibility
# analogue of `_derive_capacities` / `_derive_priority_classes` above) and,
# via `generate_config`, `witness.reserves.ReserveConfig`. They are inert for
# every mechanism except `MECHANISM_RESERVE_DA`.

#: Every school reserves 0 seats -- an all-open policy, identical in effect to
#: plain DA (see `witness.reserves.ReserveConfig`'s own docstring: a school
#: absent from `reserves` behaves exactly like this).
RESERVE_MODE_NONE = "none"

#: Each school reserves `ceil(capacity / 2)` seats -- Boston's 50/50 walk-zone
#: split, the case Dur, Kominers, Pathak & Sonmez (2018) study.
RESERVE_MODE_HALF = "half"

#: Each school reserves ALL of its seats.
RESERVE_MODE_ALL = "all"

#: Each school reserves a count drawn uniformly (deterministically) from
#: `0..capacity` inclusive -- see `generate_reserves`.
RESERVE_MODE_RANDOM = "random"

_RESERVE_MODES = (RESERVE_MODE_NONE, RESERVE_MODE_HALF, RESERVE_MODE_ALL, RESERVE_MODE_RANDOM)

#: `witness.reserves.RESERVE_SOFT` / `RESERVE_HARD`, re-declared locally as
#: their own greppable, validated tuple here -- same reasoning as
#: `_UNLISTED_POLICIES` below: this module's own validation gets its own
#: named constant rather than reaching into another module's private tuple.
_RESERVE_TYPES = (RESERVE_SOFT, RESERVE_HARD)

#: `witness.reserves.PRECEDENCE_RESERVE_FIRST` / `PRECEDENCE_OPEN_FIRST`,
#: re-declared locally for the same reason as `_RESERVE_TYPES` above.
_PRECEDENCE_ORDERS = (PRECEDENCE_RESERVE_FIRST, PRECEDENCE_OPEN_FIRST)

# --- mechanisms this generator can build a config for -----------------------

#: Mirrors `witness.da.DAConfig.mechanism`'s default value.
MECHANISM_STUDENT_PROPOSING_DA = "student_proposing_da"

#: Mirrors `witness.boston.BostonConfig.mechanism`'s default value.
MECHANISM_BOSTON_IMMEDIATE_ACCEPTANCE = "boston_immediate_acceptance"

#: Mirrors `witness.reserves.ReserveConfig.mechanism`'s default value, and
#: the name `witness.mechanisms` registers `reserve_da` under.
MECHANISM_RESERVE_DA = "reserve_da"

#: Top Trading Cycles (Abdulkadiroglu & Sonmez 2003). Like plain DA and
#: `reserve_da`, this is a strategy-proof NEGATIVE control, not a hunting
#: target -- see `witness.ttc`'s module docstring.
MECHANISM_TOP_TRADING_CYCLES = "top_trading_cycles"

_MECHANISMS = (
    MECHANISM_STUDENT_PROPOSING_DA,
    MECHANISM_BOSTON_IMMEDIATE_ACCEPTANCE,
    MECHANISM_RESERVE_DA,
    MECHANISM_TOP_TRADING_CYCLES,
)

#: Both `witness.core` unlisted-student policies are selectable here too --
#: re-declared locally (rather than importing `witness.core`'s private
#: tuple) so this module's own validation has its own named, greppable
#: constant, per the "every setting gets a named module constant" rule.
_UNLISTED_POLICIES = (UNLISTED_UNACCEPTABLE, UNLISTED_LOWEST_CLASS)


def derive_seed(seed: str, index: int, purpose: str) -> str:
    """A purpose-scoped seed string, derived by SHA-256 over (domain, seed,
    index, purpose) -- the same construction as `witness.tiebreak.lottery_key`,
    just with one more field (`purpose`) so unrelated draws for the same
    instance (e.g. student reports vs. the priority lottery vs. capacity
    weights) can never collide. Stable across processes, machines, and
    Python versions: it depends on nothing but these four strings.
    """
    payload = "\x1f".join((GENERATE_DOMAIN, seed, str(index), purpose))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _hash_int(seed: str, scope: str, item: str, modulus: int) -> int:
    """A deterministic integer in `[0, modulus)`, derived from `lottery_key`.

    Used for every "pick a small deterministic number" decision below (report
    lengths, capacity weights) that isn't itself a permutation or subset --
    still nothing but `hashlib.sha256` under the hood, via `lottery_key`.
    """
    digest = lottery_key(seed, scope, item)
    return int(digest, 16) % modulus


def _unit_from_key(seed: str, scope: str, item: str) -> float:
    """A deterministic float in `[0.0, 1.0)`, derived from `lottery_key`.

    DECLARED CONVENTION: this module had no float-uniform draw before
    `eligible_fraction` needed one (every existing numeric draw -- report
    lengths, capacity weights -- is an integer modulus via `_hash_int`, which
    doesn't fit a probability threshold). Introduced here: the top 16 hex
    characters (64 bits) of the `lottery_key` digest, as a fraction of
    `16**16`. Always strictly less than 1.0 (the numerator is at most
    `16**16 - 1`), so a threshold of exactly `1.0` matches every draw and a
    threshold of exactly `0.0` matches none -- see `generate_reserves`.
    """
    digest = lottery_key(seed, scope, item)
    return int(digest[:16], 16) / 16**16


def _apportion(total: int, weights: Sequence[int]) -> tuple[int, ...]:
    """Split non-negative int `total` into `len(weights)` non-negative ints
    summing exactly to `total`, proportional to `weights` (the largest-
    remainder / Hamilton method). Deterministic: ties in the fractional
    remainder are broken by ascending index in `weights`, never by dict/set
    order.
    """
    n = len(weights)
    if n == 0:
        if total != 0:
            raise ModelError(f"_apportion: total={total} but no weights to distribute it over")
        return ()
    sum_w = sum(weights)
    if sum_w <= 0:
        raise ModelError(f"_apportion: weights must sum to a positive number, got {weights!r}")
    shares = [total * w / sum_w for w in weights]
    floors = [math.floor(x) for x in shares]
    remainder = total - sum(floors)
    order = sorted(range(n), key=lambda i: (-(shares[i] - floors[i]), i))
    caps = list(floors)
    for i in range(remainder):
        caps[order[i]] += 1
    return tuple(caps)


def _target_total_seats(gc: "GeneratorConfig") -> int:
    """The total seat count `_derive_capacities` must sum to, given
    `gc.subscription` / `gc.subscription_ratio`, respecting OVER means
    FEWER seats than students, UNDER means MORE seats than students, and
    the relation is always made STRICT (never accidentally equal) by
    clamping after rounding.
    """
    n = gc.n_students
    if gc.subscription == SUBSCRIPTION_EXACT:
        return n
    if gc.subscription == SUBSCRIPTION_OVER:
        raw = math.floor(gc.subscription_ratio * n)
        return max(0, min(n - 1, raw))
    # SUBSCRIPTION_UNDER; validated in __post_init__.
    raw = math.ceil(gc.subscription_ratio * n)
    return max(n + 1, raw)


def _school_capacity_weights(gc: "GeneratorConfig", index: int, schools: Sequence[str]) -> tuple[int, ...]:
    """Per-school apportionment weights. Uniform under `CAPACITY_UNIFORM`
    (equal weights, so `_apportion` spreads seats as evenly as possible);
    deliberately spread under `CAPACITY_HETEROGENEOUS` (a deterministic
    weight in 1..4 per school, derived from `lottery_key`, scoped by index so
    different instances of the same `gc` need not share a capacity shape).
    """
    if gc.capacity_mode == CAPACITY_UNIFORM:
        return tuple(1 for _ in schools)
    seed = derive_seed(gc.seed, index, "capacity-weight")
    return tuple(1 + _hash_int(seed, "capacity-weight", c, 4) for c in schools)


def _derive_capacities(gc: "GeneratorConfig", index: int, schools: Sequence[str]) -> dict:
    """Every school's capacity for instance `index` of `gc`.

    `gc.capacity` (the Step-3A legacy alias) short-circuits this entirely:
    when set, every school gets that exact uniform value, independent of
    `subscription` / `subscription_ratio` / `capacity_mode`.
    """
    if gc.capacity is not None:
        return {c: gc.capacity for c in schools}
    total = _target_total_seats(gc)
    weights = _school_capacity_weights(gc, index, schools)
    caps = _apportion(total, weights)
    return {c: caps[i] for i, c in enumerate(schools)}


def _reserve_size_for(gc: "GeneratorConfig", seed: str, school: str, capacity: int) -> int:
    """The reserved-seat count for `school` (of `capacity` seats), under
    `gc.reserve_mode`. `seed` is already scoped to (`gc.seed`, `index`,
    "reserve_size") by the caller (`generate_reserves`), mirroring
    `_school_capacity_weights`'s own two-step derive_seed-then-lottery_key
    shape.
    """
    if gc.reserve_mode == RESERVE_MODE_NONE:
        return 0
    if gc.reserve_mode == RESERVE_MODE_HALF:
        return math.ceil(capacity / 2)
    if gc.reserve_mode == RESERVE_MODE_ALL:
        return capacity
    # RESERVE_MODE_RANDOM; validated in __post_init__. Uniform integer in
    # 0..capacity inclusive, i.e. a modulus draw of size capacity + 1.
    return _hash_int(seed, "reserve_size", school, capacity + 1)


def _report_length(gc: "GeneratorConfig", seed: str, student: str) -> int:
    """The length of `student`'s report under `gc.list_length_mode`."""
    n = gc.n_schools
    if gc.list_length_mode == LIST_COMPLETE:
        return n
    if gc.list_length_mode == LIST_FIXED:
        return gc.list_length
    if gc.list_length_mode == LIST_UNIFORM:
        return 1 + _hash_int(seed, "list-length", student, n)
    # LIST_SHORT; validated in __post_init__.
    return _hash_int(seed, "list-length-short", student, 2)


def _derive_report(gc: "GeneratorConfig", index: int, student: str, schools: Sequence[str]) -> tuple:
    """`student`'s report for instance `index`: a length-`_report_length`
    prefix of a full random permutation of `schools`, scoped to `student` so
    distinct students (and the same student across distinct instances) draw
    independently.
    """
    seed = derive_seed(gc.seed, index, "report")
    full = lottery_order(seed, student, schools)
    length = _report_length(gc, seed, student)
    return full[:length]


def _derive_priority_classes(gc: "GeneratorConfig", index: int, students: Sequence[str], schools: Sequence[str]) -> dict:
    """Every school's priority classes for instance `index` of `gc`.

    Per school `c`: draw a school-scoped lottery order over ALL students,
    keep only the first `round(school_lists_fraction * n_students)` of them
    (all of them, in lottery order, when the fraction is 1.0 -- so nobody is
    ever left off), then split that "listed" tuple into exactly
    `n_priority_classes` contiguous chunks (near-even, via `_apportion`),
    best chunk first.
    """
    seed = derive_seed(gc.seed, index, "priority-order")
    n_students = len(students)
    priority_classes = {}
    for c in schools:
        order = lottery_order(seed, c, students)
        if gc.school_lists_fraction >= 1.0:
            listed = order
        else:
            listed_count = math.floor(gc.school_lists_fraction * n_students)
            listed = order[:listed_count]
        sizes = _apportion(len(listed), tuple(1 for _ in range(gc.n_priority_classes)))
        classes = []
        pos = 0
        for size in sizes:
            classes.append(tuple(listed[pos : pos + size]))
            pos += size
        priority_classes[c] = tuple(classes)
    return priority_classes


@dataclass(frozen=True)
class GeneratorConfig:
    """Parameters of the Step-3B wide random-instance generator.

    Every setting below is a named module constant at its use sites (never a
    bare string literal), and every one is validated in `__post_init__`,
    raising `ModelError` and listing the allowed values on an unknown one, or
    explaining the conflict when two settings are mutually inconsistent.

    `seed` is the root of all derived randomness; two `GeneratorConfig`s with
    the same `seed` and the same other fields produce byte-identical
    instances for every `index`.
    """

    n_students: int
    n_schools: int
    seed: str = "witness"

    # --- subscription: seats relative to students ---
    subscription: str = SUBSCRIPTION_EXACT
    subscription_ratio: float = 1.0

    capacity_mode: str = CAPACITY_UNIFORM

    # --- student preference lists ---
    list_length_mode: str = LIST_COMPLETE
    list_length: int = 0

    # --- school priority structure ---
    school_lists_fraction: float = 1.0
    n_priority_classes: int = 1
    unlisted_student_policy: str = UNLISTED_UNACCEPTABLE
    tiebreak_family: str = TIEBREAK_STB

    # --- reserve structure (reserve_da only; see `generate_reserves`) ---
    #: How many seats each school reserves. One of `RESERVE_MODE_NONE`
    #: (every school reserves 0 -- an all-open policy, the default),
    #: `RESERVE_MODE_HALF` (each school reserves `ceil(capacity / 2)` --
    #: Boston's 50/50 walk-zone split, the case Dur, Kominers, Pathak &
    #: Sonmez (2018) study), `RESERVE_MODE_ALL` (each school reserves all of
    #: its seats), or `RESERVE_MODE_RANDOM` (each school reserves a count
    #: drawn uniformly, deterministically, from `0..capacity` inclusive).
    reserve_mode: str = RESERVE_MODE_NONE

    #: For each (school, student) pair INDEPENDENTLY, the probability that
    #: student is reserve-eligible AT THAT SCHOOL (this models a walk zone --
    #: eligibility is per-school, never a global student attribute: the same
    #: student can be eligible at one school and ineligible at another).
    #: Must be in `[0.0, 1.0]`.
    eligible_fraction: float = 0.5

    #: `witness.reserves.RESERVE_SOFT` (a reserve seat is a FLOOR: an
    #: ineligible student may take it if no eligible one claims it -- DKPS /
    #: Boston walk zones, the default) or `RESERVE_HARD` (a reserve seat is
    #: EXCLUSIVE: it goes empty rather than seat an ineligible student).
    reserve_type: str = RESERVE_SOFT

    #: `witness.reserves.PRECEDENCE_RESERVE_FIRST` (reserve slots filled
    #: before open slots -- what Boston did, the default) or
    #: `PRECEDENCE_OPEN_FIRST` (open slots filled first).
    precedence: str = PRECEDENCE_RESERVE_FIRST

    #: Step-3A LEGACY ALIAS: when not `None`, every school gets exactly this
    #: uniform capacity, bypassing `subscription` entirely. See the module
    #: docstring's BACKWARD COMPATIBILITY section.
    capacity: "int | None" = None

    def __post_init__(self) -> None:
        if isinstance(self.n_students, bool) or not isinstance(self.n_students, int) or self.n_students < 1:
            raise ModelError(f"n_students must be a positive int, got {self.n_students!r}")
        if isinstance(self.n_schools, bool) or not isinstance(self.n_schools, int) or self.n_schools < 1:
            raise ModelError(f"n_schools must be a positive int, got {self.n_schools!r}")
        if not isinstance(self.seed, str) or not self.seed:
            raise ModelError(f"seed must be a non-empty string, got {self.seed!r}")

        if self.subscription not in _SUBSCRIPTIONS:
            raise ModelError(
                f"subscription must be one of {_SUBSCRIPTIONS}, got {self.subscription!r}"
            )
        if isinstance(self.subscription_ratio, bool) or not isinstance(self.subscription_ratio, (int, float)):
            raise ModelError(
                f"subscription_ratio must be a number, got {self.subscription_ratio!r}"
            )
        if self.subscription_ratio <= 0:
            raise ModelError(
                f"subscription_ratio must be positive, got {self.subscription_ratio!r}"
            )
        if self.subscription == SUBSCRIPTION_OVER and not self.subscription_ratio < 1.0:
            raise ModelError(
                f"subscription={SUBSCRIPTION_OVER!r} (fewer seats than students) requires "
                f"subscription_ratio < 1.0, got {self.subscription_ratio!r} -- this "
                f"combination is impossible"
            )
        if self.subscription == SUBSCRIPTION_EXACT and self.subscription_ratio != 1.0:
            raise ModelError(
                f"subscription={SUBSCRIPTION_EXACT!r} requires subscription_ratio == 1.0, "
                f"got {self.subscription_ratio!r} -- this combination is impossible"
            )
        if self.subscription == SUBSCRIPTION_UNDER and not self.subscription_ratio > 1.0:
            raise ModelError(
                f"subscription={SUBSCRIPTION_UNDER!r} (more seats than students) requires "
                f"subscription_ratio > 1.0, got {self.subscription_ratio!r} -- this "
                f"combination is impossible"
            )

        if self.capacity_mode not in _CAPACITY_MODES:
            raise ModelError(
                f"capacity_mode must be one of {_CAPACITY_MODES}, got {self.capacity_mode!r}"
            )

        if self.list_length_mode not in _LIST_LENGTH_MODES:
            raise ModelError(
                f"list_length_mode must be one of {_LIST_LENGTH_MODES}, "
                f"got {self.list_length_mode!r}"
            )
        if self.list_length_mode == LIST_FIXED:
            if (
                isinstance(self.list_length, bool)
                or not isinstance(self.list_length, int)
                or not (0 <= self.list_length <= self.n_schools)
            ):
                raise ModelError(
                    f"list_length_mode={LIST_FIXED!r} requires list_length to be an int in "
                    f"[0, n_schools={self.n_schools}], got {self.list_length!r}"
                )

        if isinstance(self.school_lists_fraction, bool) or not isinstance(
            self.school_lists_fraction, (int, float)
        ):
            raise ModelError(
                f"school_lists_fraction must be a number, got {self.school_lists_fraction!r}"
            )
        if not (0.0 <= self.school_lists_fraction <= 1.0):
            raise ModelError(
                f"school_lists_fraction must be in [0.0, 1.0], got "
                f"{self.school_lists_fraction!r}"
            )

        if (
            isinstance(self.n_priority_classes, bool)
            or not isinstance(self.n_priority_classes, int)
            or self.n_priority_classes < 1
        ):
            raise ModelError(
                f"n_priority_classes must be a positive int, got {self.n_priority_classes!r}"
            )

        if self.unlisted_student_policy not in _UNLISTED_POLICIES:
            raise ModelError(
                f"unlisted_student_policy must be one of {_UNLISTED_POLICIES}, "
                f"got {self.unlisted_student_policy!r}"
            )

        if self.tiebreak_family not in _TIEBREAK_FAMILIES:
            raise ModelError(
                f"tiebreak_family must be one of {_TIEBREAK_FAMILIES}, "
                f"got {self.tiebreak_family!r}"
            )

        if self.reserve_mode not in _RESERVE_MODES:
            raise ModelError(
                f"reserve_mode must be one of {_RESERVE_MODES}, got {self.reserve_mode!r}"
            )
        if isinstance(self.eligible_fraction, bool) or not isinstance(
            self.eligible_fraction, (int, float)
        ):
            raise ModelError(
                f"eligible_fraction must be a number, got {self.eligible_fraction!r}"
            )
        if not (0.0 <= self.eligible_fraction <= 1.0):
            raise ModelError(
                f"eligible_fraction must be in [0.0, 1.0], got {self.eligible_fraction!r}"
            )
        if self.reserve_type not in _RESERVE_TYPES:
            raise ModelError(
                f"reserve_type must be one of {_RESERVE_TYPES}, got {self.reserve_type!r}"
            )
        if self.precedence not in _PRECEDENCE_ORDERS:
            raise ModelError(
                f"precedence must be one of {_PRECEDENCE_ORDERS}, got {self.precedence!r}"
            )

        if self.capacity is not None:
            if isinstance(self.capacity, bool) or not isinstance(self.capacity, int) or self.capacity < 1:
                raise ModelError(f"capacity must be a positive int, got {self.capacity!r}")


def priority_tiebreak(gc: GeneratorConfig, index: int) -> SingleLotteryTiebreak:
    """BACKWARD-COMPATIBILITY HELPER (Step 3A): the `SingleLotteryTiebreak` a
    `MechanismConfig` built around instance `index` of `gc` should use.

    Always returns a `SingleLotteryTiebreak`, regardless of
    `gc.tiebreak_family` -- existing callers (`tests/test_boston_positive_
    control.py`, `scripts/search_power.py`) depend on exactly this. New code
    that wants `tiebreak_family` honored should use `generate_config` instead.
    """
    return SingleLotteryTiebreak(seed=derive_seed(gc.seed, index, "priority"))


def _tiebreak_for(gc: GeneratorConfig, index: int):
    seed = derive_seed(gc.seed, index, "priority")
    if gc.tiebreak_family == TIEBREAK_STB:
        return SingleLotteryTiebreak(seed=seed)
    return MultipleLotteryTiebreak(seed=seed)  # TIEBREAK_MTB; validated in __post_init__.


def generate_instance(gc: GeneratorConfig, index: int) -> "tuple[Market, Profile]":
    """Build the `index`-th instance of `gc`.

    Students "s1".."sN" and schools "c1".."cM", in that declared order.
    Capacities come from `_derive_capacities` (subscription-driven, or the
    legacy `capacity` alias). Priority classes come from
    `_derive_priority_classes` (school-listing fraction and coarse-class
    count). Reports come from `_derive_report` (list-length mode). Every
    draw is scoped by (`gc.seed`, `index`, a purpose string, and where
    applicable a student or school id) via `derive_seed` / `lottery_key` /
    `lottery_order` -- never the stdlib `random` module, never dict/set
    iteration order.
    """
    students = tuple(f"s{i}" for i in range(1, gc.n_students + 1))
    schools = tuple(f"c{i}" for i in range(1, gc.n_schools + 1))

    capacities = _derive_capacities(gc, index, schools)
    priority_classes = _derive_priority_classes(gc, index, students, schools)

    market = Market(
        students=students,
        schools=schools,
        capacities=capacities,
        priority_classes=priority_classes,
    )

    rankings = {s: _derive_report(gc, index, s, schools) for s in students}
    profile = Profile(rankings)

    return market, profile


def generate_reserves(gc: GeneratorConfig, index: int, market: Market) -> "dict[str, SchoolReserve]":
    """Every school's `SchoolReserve` for instance `index` of `gc`, given the
    already-built `market` (its declared school/student order and its
    capacities -- see `generate_instance`).

    Reserved-seat count per school comes from `_reserve_size_for`, dispatched
    on `gc.reserve_mode`:

        * `RESERVE_MODE_NONE`: 0 for every school.
        * `RESERVE_MODE_HALF`: `ceil(capacity / 2)` -- Boston's 50/50 split.
        * `RESERVE_MODE_ALL`: the school's full capacity.
        * `RESERVE_MODE_RANDOM`: a count drawn uniformly, deterministically,
          from `0..capacity` inclusive, scoped by school id so different
          schools (and different instances of the same `gc`) draw
          independently.

    Eligibility is drawn separately, for each (school, student) PAIR
    independently: student `s` is reserve-eligible at school `c` iff
    `_unit_from_key(elig_seed, c, s) < gc.eligible_fraction`, where
    `elig_seed` is scoped by (`gc.seed`, `index`, "reserve_eligible"). This is
    deliberately per-school (it models a walk zone), never a single
    school-independent draw per student -- the same student can come out
    eligible at one school and ineligible at another.

    `market.schools` and `market.students` are iterated explicitly and in
    their declared order throughout; nothing here depends on dict or set
    iteration order.
    """
    size_seed = derive_seed(gc.seed, index, "reserve_size")
    elig_seed = derive_seed(gc.seed, index, "reserve_eligible")

    reserves: dict[str, SchoolReserve] = {}
    for c in market.schools:
        capacity = market.capacity(c)
        reserved_seats = _reserve_size_for(gc, size_seed, c, capacity)
        eligible = tuple(
            s for s in market.students if _unit_from_key(elig_seed, c, s) < gc.eligible_fraction
        )
        reserves[c] = SchoolReserve(reserved_seats=reserved_seats, eligible=eligible)
    return reserves


def generate_config(
    gc: GeneratorConfig, index: int, mechanism: str, *, market: "Market | None" = None
):
    """Build the `MechanismConfig` instance `index` of `gc` should run
    `mechanism` under: the right tiebreak family (STB or MTB, seeded per
    instance via `derive_seed(gc.seed, index, "priority")`) and
    `gc.unlisted_student_policy`, with `mechanism` set so that
    `config.to_dict()["mechanism"] == mechanism` -- required by
    `witness.search`'s mechanism/config agreement check.

    Supports `MECHANISM_STUDENT_PROPOSING_DA`,
    `MECHANISM_BOSTON_IMMEDIATE_ACCEPTANCE`, `MECHANISM_TOP_TRADING_CYCLES`,
    and `MECHANISM_RESERVE_DA`; raises `ModelError`, listing the allowed
    values, on anything else.

    `market` is required (keyword-only) when `mechanism` is
    `MECHANISM_RESERVE_DA`: building a `witness.reserves.ReserveConfig`
    means calling `generate_reserves(gc, index, market)`, which needs the
    market's declared school/student order and capacities, and
    `generate_config` itself has no market of its own to build one from. When
    `mechanism == MECHANISM_RESERVE_DA` and `market is None`, this raises
    `ModelError` rather than silently building an empty reserve set -- an
    empty `reserves` mapping is indistinguishable from a deliberate
    `RESERVE_MODE_NONE` policy (see `ReserveConfig`'s docstring: a school
    absent from `reserves` has zero reserved seats), so silently defaulting
    to it would make a sweep that asked for `reserve_da` actually test plain
    DA instead, without saying so.
    """
    if mechanism not in _MECHANISMS:
        raise ModelError(f"mechanism must be one of {_MECHANISMS}, got {mechanism!r}")
    tiebreak = _tiebreak_for(gc, index)
    if mechanism == MECHANISM_STUDENT_PROPOSING_DA:
        return DAConfig(
            tiebreak=tiebreak,
            unlisted_student_policy=gc.unlisted_student_policy,
            mechanism=MECHANISM_STUDENT_PROPOSING_DA,
        )
    if mechanism == MECHANISM_TOP_TRADING_CYCLES:
        return TTCConfig(
            tiebreak=tiebreak,
            unlisted_student_policy=gc.unlisted_student_policy,
            mechanism=MECHANISM_TOP_TRADING_CYCLES,
        )
    if mechanism == MECHANISM_RESERVE_DA:
        if market is None:
            raise ModelError(
                "generate_config: mechanism='reserve_da' needs the market to build its "
                "reserve structure (reserved-seat counts and eligibility are drawn "
                "against the market's own schools, students, and capacities) -- pass "
                "market=<the Market generate_instance built for this same (gc, index)>"
            )
        reserves = generate_reserves(gc, index, market)
        return ReserveConfig(
            tiebreak=tiebreak,
            unlisted_student_policy=gc.unlisted_student_policy,
            mechanism=MECHANISM_RESERVE_DA,
            reserves=reserves,
            reserve_type=gc.reserve_type,
            precedence=gc.precedence,
        )
    return BostonConfig(
        tiebreak=tiebreak,
        unlisted_student_policy=gc.unlisted_student_policy,
        mechanism=MECHANISM_BOSTON_IMMEDIATE_ACCEPTANCE,
    )
