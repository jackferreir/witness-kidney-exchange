"""Definitional, brute-force checker for the kidney-exchange mechanism --
independent of `witness.kidney`, exactly the way `witness.oracles` is
independent of `witness.da` and `witness.oracles_couples` is independent of
`witness.couples` (see either module's docstring for why the independence
itself is the point: this module is written from the DEFINITION directly,
never by calling `witness.kidney`'s own cycle-enumeration/selection/
tiebreak functions).

Handles cycles of length 2 OR 3 (`max_cycle_length`, mirroring
`witness.kidney.KidneyConfig.max_cycle_length`) -- re-derived independently
here rather than reusing `witness.kidney.candidate_cycles` at all, so this
module shares no code with the mechanism it checks.

Three checks, each usable standalone:

  * `is_valid_selection` -- every claimed cycle is a TRUE, vertex-disjoint,
    fully-directed-compatible cycle (every consecutive edge present) among
    a given pool of pairs.
  * `is_maximum_cardinality` -- re-enumerates EVERY vertex-disjoint subset
    of feasible cycles over the pool from scratch (its own brute force, not
    `witness.kidney._feasible_selections`) and checks no selection beats the
    claimed one's cardinality.
  * `recompute_utility` -- independently counts, for each hospital, how many
    of its own pairs appear in the union of the central selection and every
    hospital's local selection -- the ground-truth definition of utility,
    re-derived rather than read off `KidneyResult.utility`.
"""

from __future__ import annotations

from itertools import combinations
from typing import Mapping, Sequence

from witness.kidney import KidneyMarket

DEFAULT_MAX_CYCLE_LENGTH = 2


def _is_true_directed_cycle(market: KidneyMarket, cycle: Sequence[str]) -> bool:
    """True iff EVERY consecutive directed edge of `cycle` (wrapping around)
    is a TRUE edge in `market` -- the general definition of a feasible
    cycle, independent of length."""
    n = len(cycle)
    return all(market.has_edge(cycle[i], cycle[(i + 1) % n]) for i in range(n))


def is_valid_selection(
    market: KidneyMarket, selection: Sequence[tuple], pool: Sequence[str], max_cycle_length: int = DEFAULT_MAX_CYCLE_LENGTH
) -> "tuple[bool, tuple[str, ...]]":
    """True iff every cycle in `selection` is a genuine directed cycle of
    length 2 or 3 (every consecutive edge true per `market`'s TRUE edges,
    every pair in `pool`), and no pair appears in more than one cycle."""
    reasons: list[str] = []
    pool_set = set(pool)
    seen: set = set()
    for cycle in selection:
        cycle = tuple(cycle)
        if len(cycle) not in (2, 3) or len(cycle) > max_cycle_length:
            reasons.append(f"{cycle!r} has length {len(cycle)}, not a valid cycle length (<= {max_cycle_length})")
            continue
        if len(set(cycle)) != len(cycle):
            reasons.append(f"cycle {cycle!r} repeats a pair within itself")
            continue
        missing = [p for p in cycle if p not in pool_set]
        if missing:
            reasons.append(f"cycle {cycle!r} references pair(s) {missing!r} outside the given pool {sorted(pool_set)}")
        if not _is_true_directed_cycle(market, cycle):
            reasons.append(f"cycle {cycle!r} is not a true fully-directed cycle in the market's real edges")
        reused = [p for p in cycle if p in seen]
        if reused:
            reasons.append(f"cycle {cycle!r} reuses pair(s) {reused!r} already used by another selected cycle")
        seen.update(cycle)
    return (len(reasons) == 0, tuple(reasons))


def _all_true_cycles(market: KidneyMarket, pool: Sequence[str], max_cycle_length: int) -> "tuple[tuple[str, ...], ...]":
    """Every TRUE feasible cycle of length 2 up to `max_cycle_length` within
    `pool`, independently re-enumerated from the raw edge definition (never
    calling `witness.kidney.candidate_cycles`). For 3 pairs `a, b, c`, BOTH
    directed 3-cycles (`a->b->c->a` and `a->c->b->a`) are checked as
    distinct candidates, matching the mechanism's own model (re-derived
    independently here, not imported)."""
    pool = tuple(pool)
    cycles: "list[tuple[str, ...]]" = []
    for u, v in combinations(pool, 2):
        if market.has_edge(u, v) and market.has_edge(v, u):
            cycles.append((u, v))
    if max_cycle_length >= 3:
        for a, b, c in combinations(pool, 3):
            if market.has_edge(a, b) and market.has_edge(b, c) and market.has_edge(c, a):
                cycles.append((a, b, c))
            if market.has_edge(a, c) and market.has_edge(c, b) and market.has_edge(b, a):
                cycles.append((a, c, b))
    return tuple(cycles)


def _all_feasible_cardinalities(
    market: KidneyMarket, pool: Sequence[str], max_cycle_length: int = DEFAULT_MAX_CYCLE_LENGTH
) -> "tuple[int, ...]":
    """Every achievable cardinality (number of PAIRS covered) over EVERY
    vertex-disjoint subset of true cycles (length <= `max_cycle_length`)
    within `pool`, via a from-scratch brute force over the independently
    re-enumerated true-cycle list (`_all_true_cycles`) -- the most literal
    possible re-derivation of "maximum cardinality vertex-disjoint cycle
    packing" from the definition, sharing no code with `witness.kidney`.
    """
    cycles = _all_true_cycles(market, pool, max_cycle_length)
    m = len(cycles)
    cardinalities = {0}
    for r in range(m, 0, -1):
        for combo in combinations(range(m), r):
            used: set = set()
            ok = True
            covered = 0
            for i in combo:
                cyc = cycles[i]
                if any(p in used for p in cyc):
                    ok = False
                    break
                used.update(cyc)
                covered += len(cyc)
            if ok:
                cardinalities.add(covered)
    return tuple(sorted(cardinalities))


def is_maximum_cardinality(
    market: KidneyMarket, selection: Sequence[tuple], pool: Sequence[str], max_cycle_length: int = DEFAULT_MAX_CYCLE_LENGTH
) -> "tuple[bool, tuple[str, ...]]":
    """True iff the total pairs covered by `selection` equals the largest
    cardinality achievable by ANY vertex-disjoint set of true cycles within
    `pool`, per an independent brute-force re-derivation
    (`_all_feasible_cardinalities`), never by consulting `witness.kidney`'s
    own selection."""
    ok, reasons = is_valid_selection(market, selection, pool, max_cycle_length)
    reasons = list(reasons)
    claimed = sum(len(c) for c in selection)
    best_possible = max(_all_feasible_cardinalities(market, pool, max_cycle_length), default=0)
    if claimed != best_possible:
        reasons.append(
            f"selection covers {claimed} pairs, but the independent brute force finds a "
            f"vertex-disjoint set covering {best_possible} pairs is achievable -- not maximum cardinality"
        )
    return (len(reasons) == 0, tuple(reasons))


def recompute_utility(
    market: KidneyMarket,
    central_selection: Sequence[tuple],
    local_selections: Mapping[str, Sequence[tuple]],
) -> "dict[str, int]":
    """Independently counts each hospital's transplanted-recipient count
    from the union of matched pairs across both stages -- re-derived from
    the definition (KIDNEY_EXCHANGE_SCOPE.md: "Its utility is the number of
    its recipients transplanted in either stage"), not read off any
    `KidneyResult` field."""
    matched: set = set()
    for cycle in central_selection:
        matched.update(cycle)
    for sel in local_selections.values():
        for cycle in sel:
            matched.update(cycle)
    return {h: sum(1 for p in market.pairs_of(h) if p in matched) for h in market.hospitals}


def is_stable_kidney_result(
    market: KidneyMarket,
    profile,
    central_selection: Sequence[tuple],
    local_selections: Mapping[str, Sequence[tuple]],
    claimed_utility: Mapping[str, int],
    max_cycle_length: int = DEFAULT_MAX_CYCLE_LENGTH,
) -> "tuple[bool, tuple[str, ...]]":
    """The single entry point a test should call: every structural check
    above, applied to a full `KidneyResult`'s claims, none of them calling
    into `witness.kidney` itself."""
    reasons: list[str] = []

    reported_pool = tuple(p for h in market.hospitals for p in profile.report(h))
    ok, r = is_valid_selection(market, central_selection, reported_pool, max_cycle_length)
    reasons.extend(f"central: {x}" for x in r)
    ok2, r2 = is_maximum_cardinality(market, central_selection, reported_pool, max_cycle_length)
    reasons.extend(f"central: {x}" for x in r2)

    matched_centrally: set = set()
    for cycle in central_selection:
        matched_centrally.update(cycle)

    for h in market.hospitals:
        residual = tuple(p for p in market.pairs_of(h) if p not in matched_centrally)
        sel = local_selections.get(h, ())
        ok3, r3 = is_valid_selection(market, sel, residual, max_cycle_length)
        reasons.extend(f"local[{h}]: {x}" for x in r3)
        ok4, r4 = is_maximum_cardinality(market, sel, residual, max_cycle_length)
        reasons.extend(f"local[{h}]: {x}" for x in r4)
        for cycle in sel:
            wrong_owner = [p for p in cycle if market.hospital(p) != h]
            if wrong_owner:
                reasons.append(f"local[{h}]: cycle {cycle!r} includes pair(s) {wrong_owner!r} not owned by {h!r}")

    recomputed = recompute_utility(market, central_selection, local_selections)
    if recomputed != dict(claimed_utility):
        reasons.append(f"claimed utility {dict(claimed_utility)!r} disagrees with recomputed {recomputed!r}")

    return (len(reasons) == 0, tuple(reasons))
