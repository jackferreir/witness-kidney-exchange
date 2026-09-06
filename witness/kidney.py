"""The two-way kidney-exchange clearing mechanism, per `KIDNEY_EXCHANGE_SCOPE.md`
("What the first model is"). A genuinely different domain from every other
mechanism in this codebase: the strategic actor is a HOSPITAL that owns a
BUNDLE of pairs and can withhold a subset, not an individual submitting a
false preference list -- see that file for why this is the right next
target and the evidence boundary on what it does/does not claim.

THE MODEL (still deliberately narrow -- see KIDNEY_EXCHANGE_SCOPE.md for the
full list of deliberate exclusions that STILL apply: no altruistic donors/
chains, no crossmatch failure, no time/scheduling, no post-offer decline.
3-CYCLES ARE THE ONE EXCLUSION THIS MODULE NOW LIFTS, per `KidneyConfig.
max_cycle_length` -- see "CYCLES OF LENGTH 2 OR 3" below for why this one
specifically, and REVIEWER.md's own literature-check discipline: the field's
own asymptotic-safety theorem (Ashlagi & Roth) is stated for exchanges "of
size at most 3," so testing it in its own regime requires 3-cycles, not a
2-cycle simplification of it.)

    `KidneyMarket`: an ordered tuple of PAIRS, each owned by exactly one
    HOSPITAL, plus a directed compatibility graph (`u -> v` means the donor
    of pair `u` is compatible with the recipient of pair `v`). No rankings,
    no capacities, no priority orders -- those belong to every OTHER
    mechanism in this codebase, not this one.

    A feasible EXCHANGE is a vertex-disjoint directed CYCLE of length 2 or 3
    (`KidneyConfig.max_cycle_length` picks which; see below): a 2-cycle is
    pairs `u, v` with BOTH `u -> v` and `v -> u` true; a 3-cycle is pairs
    `u, v, w` with `u -> v`, `v -> w`, AND `w -> u` all true (note: a
    DIRECTED cycle, not requiring any reverse edge -- `u -> v -> w -> u` and
    `u -> w -> v -> u` are two DIFFERENT candidate cycles on the same three
    pairs, each needing its own three edges, and either, both, or neither
    may be feasible). Selecting a cycle transplants EVERY member's recipient
    simultaneously. CANONICAL REPRESENTATION: a cycle is stored as the
    tuple, in its own directed order, ROTATED so its smallest-`market.index`
    member comes first -- rotation is the only transformation that preserves
    the SAME directed edges (reversal would generally require a different,
    possibly nonexistent, edge set), so it is the only legal canonicalization.
    A 2-cycle's canonical form is simply `(u, v)` with `index(u) < index(v)`,
    unchanged from before.

CYCLES OF LENGTH 2 OR 3: `KidneyConfig.max_cycle_length` (2, the original
default, or 3) is a declared, code-visible choice, exactly like `tiebreak_
policy` below -- never silently assumed. Central and local clearing both
call the SAME `candidate_cycles(market, pool, max_cycle_length)` and the
SAME `_select_maximum_cycles`, so raising the cap to 3 changes what BOTH
stages can find, symmetrically.

    TWO STAGES, per KIDNEY_EXCHANGE_SCOPE.md's "Strategic action and
    utility" (this is the load-bearing design choice: naively measuring only
    "did the central solution change" tests a different, weaker question):

      1. CENTRAL CLEARING sees only each hospital's REPORTED subset of its
         own pairs (never another hospital's pairs, never a false edge --
         `KidneyProfile` enforces this). It selects a MAXIMUM CARDINALITY
         (most pairs) set of vertex-disjoint feasible cycles among exactly
         the reported pairs, breaking ties by the declared canonical rule
         (`_select_maximum_cycles`) -- an outcome-affecting choice, so it is
         a named, code-visible rule, never incidental enumeration order.

      2. RESIDUAL LOCAL CLEARING: every pair a hospital OWNS that was not
         selected centrally -- whether because it was withheld entirely, or
         because it was reported but not chosen -- becomes available to that
         hospital's own local clearing, which reruns the SAME maximum-
         cardinality rule but restricted to edges between pairs THAT SAME
         HOSPITAL owns (its "true internal graph"; never another hospital's
         pairs, and never an edge unreported by either endpoint's owner).

    A hospital's UTILITY is the number of ITS OWN pairs transplanted across
    BOTH stages combined. Every pair is used in at most one cycle,
    central or local, never both.

THREE CLEARING IMPLEMENTATIONS, ONE DECLARED CHOICE OF WHICH TO TRUST:
maximum-cardinality matching in a general (non-bipartite) graph has a known
polynomial algorithm (Edmonds' Blossom algorithm) -- but once 3-cycles are
allowed, "maximum-cardinality vertex-disjoint cycle packing" is NP-hard in
general (this is precisely why the real kidney-exchange literature solves
it via branch-and-price/column generation, e.g. the Petris et al. paper
behind this project's own downloaded benchmark -- see KIDNEY_EXCHANGE_
SCOPE.md). This codebase's own standing discipline (`witness.search`'s
docstring: "correct and complete beats fast... nothing in this module
prunes the search") distrusts a clever algorithm whose correctness a reader
would have to take on faith regardless. So there are THREE implementations
of `_select_maximum_cycles`, and `KidneyConfig.tiebreak_policy` (a real,
outcome-affecting choice, never a silent default) picks between them:

  * `TIEBREAK_LEX_SMALLEST_BY_INDEX` (the original, still the default):
    brute-force enumeration of every vertex-disjoint subset of candidate
    cycles, tie-broken by a fully specified, code-visible rule (cycles of
    DIFFERENT lengths compare as index-tuples of different lengths, where
    Python's own tuple-prefix rule applies -- e.g. `(0, 1)` sorts before
    `(0, 1, 2)` -- a declared, deterministic convention, not an apology).
    Trivially auditable; `KidneyConfig.max_central_space` bounds it to
    markets where `2**(candidate cycles)` is actually enumerable -- exactly
    the "small hospitals only" regime `KIDNEY_EXCHANGE_SCOPE.md` scopes the
    first increment to. Works for 2- or 3-cycles identically.

  * `TIEBREAK_MAX_CARDINALITY_BLOSSOM`: NetworkX's `max_weight_matching`
    (Galil's implementation of Edmonds' Blossom algorithm), which scales to
    hundreds of pairs -- but ONLY for `max_cycle_length == 2` (general graph
    matching has no notion of a 3-cycle; `KidneyConfig.__post_init__`
    refuses the combination outright rather than silently truncating).
    Verified (`tests/test_kidney_blossom_matches_oracle.py`) to reach the
    IDENTICAL cardinality as the independent oracle (`witness.
    oracles_kidney`) on every hand fixture and hundreds of random small
    instances before ever being trusted at a scale the oracle cannot reach.
    NOT claimed to reproduce the SAME tie-broken selection as `TIEBREAK_
    LEX_SMALLEST_BY_INDEX` -- only the same cardinality is verified, so a
    specific hospital's utility in a genuine tie CAN differ between the two
    policies. This mirrors `witness.couples`'s own honesty about `couple_
    order_policy`: a declared, real, NOT-proven-invariant choice, not a
    hidden implementation detail. Determinism (required for replay) rests
    on always building the underlying graph with pairs/edges in
    `KidneyMarket`'s own declared order (verified directly: NetworkX's
    matching result is invariant to `PYTHONHASHSEED` but NOT to edge
    insertion order, so a fixed insertion order is load-bearing, not
    cosmetic -- see `_select_maximum_cycles_blossom`).

  * `TIEBREAK_MAX_CARDINALITY_ILP`: an exact integer program (OR-Tools
    CP-SAT), the standard cycle-packing formulation this literature itself
    uses -- one binary variable per candidate cycle, one at-most-one
    constraint per pair, maximize total pairs covered. Works for 2- AND
    3-cycles (this is the policy `max_cycle_length=3` needs at any scale
    the exhaustive policy cannot reach). CP-SAT PROVES optimality (checked:
    `_select_maximum_cycles_ilp` raises if the solver does not return
    OPTIMAL, never silently accepts a merely-feasible bound), so this is an
    exact solve, not a heuristic. Same cardinality-only verification
    discipline as Blossom (`tests/test_kidney3_ilp_matches_oracle.py`), and
    the same determinism caveat: verified empirically to depend only on
    variable-creation order, not process/hash-seed, given `num_search_
    workers=1` and a fixed `random_seed` -- see `_select_maximum_cycles_ilp`.

WHAT IS NOT REGISTERED IN `witness.mechanisms`: exactly the same reasoning
as `witness.couples`'s own "WHAT IS NOT REGISTERED" note -- a hospital's
report (a subset of its own pairs) is not a `witness.core.Profile` ranking,
and `KidneyMarket` has no rankings/priorities/capacities at all. Called
directly, never through the flat registry.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations
from typing import Mapping, Optional, Sequence

from witness.errors import ModelError

#: The only implemented central/local tiebreak: among maximum-cardinality
#: feasible cycle selections, prefer the one whose cycles -- each canonical
#: as `(u, v)` with `index(u) < index(v)`, sorted by `(index(u), index(v))`
#: ascending -- form the lexicographically smallest tuple of index-pairs.
#: Declared here as a named constant (not hardcoded inline) so a future
#: second policy has somewhere to register, per REVIEWER.md's "any outcome-
#: affecting choice is declared configuration."
TIEBREAK_LEX_SMALLEST_BY_INDEX = "lex_smallest_by_index"

#: The polynomial-time alternative -- see the module docstring's "TWO
#: CLEARING IMPLEMENTATIONS." Scales to hundreds of pairs; verified for
#: CARDINALITY agreement with the exhaustive oracle, not for reproducing
#: the same tie-broken selection.
TIEBREAK_MAX_CARDINALITY_BLOSSOM = "max_cardinality_blossom"

#: The exact-ILP alternative that also handles 3-cycles -- see the module
#: docstring's "THREE CLEARING IMPLEMENTATIONS."
TIEBREAK_MAX_CARDINALITY_ILP = "max_cardinality_ilp"

_TIEBREAK_POLICIES = (
    TIEBREAK_LEX_SMALLEST_BY_INDEX,
    TIEBREAK_MAX_CARDINALITY_BLOSSOM,
    TIEBREAK_MAX_CARDINALITY_ILP,
)

#: Cycle lengths this module implements at all -- see "CYCLES OF LENGTH 2
#: OR 3" in the module docstring. Not 1 (a pair can't transplant with
#: itself) and not >3 (out of scope for this increment, per KIDNEY_EXCHANGE_
#: SCOPE.md's own declared "next expansion after that is 3-cycles, then
#: altruist-started chains").
_MAX_CYCLE_LENGTHS = (2, 3)

#: Default cap on `2**n` (`n` = the number of CANDIDATE cycles a single
#: clearing call -- central or local -- would need to enumerate subsets of),
#: NOT a cap on `n` itself -- see `_feasible_selections`'s own guard and the
#: module docstring's "WHY CENTRAL CLEARING IS EXHAUSTIVE ENUMERATION."
#: `n=20` (2**20 subsets) is already generous for the small/medium fixtures
#: this exhaustive regime targets while still failing loudly on anything a
#: brute force truly cannot do -- matches `witness.search_kidney.DEFAULT_
#: MAX_REPORT_SPACE`'s own order of magnitude.
DEFAULT_MAX_CENTRAL_SPACE = 2 ** 20


@dataclass(frozen=True)
class KidneyMarket:
    """Ground truth: pairs, their hospital owners, and the TRUE directed
    compatibility graph. Immutable and validated -- see the module docstring."""

    pairs: tuple[str, ...]
    hospital_of: Mapping[str, str]
    hospitals: tuple[str, ...]
    edges: frozenset

    def __post_init__(self) -> None:
        pairs = tuple(self.pairs)
        if len(set(pairs)) != len(pairs) or not all(isinstance(p, str) and p for p in pairs):
            raise ModelError(f"KidneyMarket.pairs must be distinct non-empty strings, got {pairs!r}")
        hospital_of = dict(self.hospital_of)
        if set(hospital_of) != set(pairs):
            raise ModelError(
                f"KidneyMarket.hospital_of must cover exactly `pairs`; got {sorted(hospital_of)}, "
                f"expected {sorted(pairs)}"
            )
        hospitals = tuple(self.hospitals)
        if len(set(hospitals)) != len(hospitals) or not all(isinstance(h, str) and h for h in hospitals):
            raise ModelError(f"KidneyMarket.hospitals must be distinct non-empty strings, got {hospitals!r}")
        if set(hospital_of.values()) != set(hospitals):
            raise ModelError(
                f"every hospital named in hospital_of must appear in `hospitals` and vice versa; "
                f"hospital_of names {sorted(set(hospital_of.values()))}, hospitals declares {sorted(hospitals)}"
            )
        edges = frozenset((u, v) for u, v in self.edges)
        for u, v in edges:
            if u not in hospital_of or v not in hospital_of:
                raise ModelError(f"edge {(u, v)!r} references a pair not in `pairs`")
            if u == v:
                raise ModelError(f"edge {(u, v)!r}: a pair cannot be compatible with itself")
        object.__setattr__(self, "pairs", pairs)
        object.__setattr__(self, "hospital_of", hospital_of)
        object.__setattr__(self, "hospitals", hospitals)
        object.__setattr__(self, "edges", edges)

    def index(self, pair: str) -> int:
        return self.pairs.index(pair)

    def hospital(self, pair: str) -> str:
        return self.hospital_of[pair]

    def pairs_of(self, hospital: str) -> tuple[str, ...]:
        """`hospital`'s own pairs, in `self.pairs`' own declared order."""
        return tuple(p for p in self.pairs if self.hospital_of[p] == hospital)

    def has_edge(self, u: str, v: str) -> bool:
        return (u, v) in self.edges

    def to_dict(self) -> dict:
        return {
            "pairs": list(self.pairs),
            "hospital_of": dict(sorted(self.hospital_of.items())),
            "hospitals": list(self.hospitals),
            "edges": sorted(list(e) for e in self.edges),
        }

    @staticmethod
    def from_dict(d: Mapping) -> "KidneyMarket":
        return KidneyMarket(
            pairs=tuple(d["pairs"]),
            hospital_of=dict(d["hospital_of"]),
            hospitals=tuple(d["hospitals"]),
            edges=frozenset(tuple(e) for e in d["edges"]),
        )


@dataclass(frozen=True)
class KidneyProfile:
    """What every hospital reported: a subset of ITS OWN owned pairs. Never
    another hospital's pair, never a fabricated edge (edges live only in
    `KidneyMarket`, which a profile cannot alter)."""

    reports: Mapping[str, tuple[str, ...]]

    def __post_init__(self) -> None:
        reports = {h: tuple(r) for h, r in self.reports.items()}
        for h, r in reports.items():
            if len(set(r)) != len(r):
                raise ModelError(f"hospital {h!r}'s report repeats a pair: {r!r}")
        object.__setattr__(self, "reports", reports)

    def report(self, hospital: str) -> tuple[str, ...]:
        return self.reports.get(hospital, ())

    def validate_against(self, market: KidneyMarket) -> None:
        if set(self.reports) != set(market.hospitals):
            raise ModelError(
                f"KidneyProfile must report for exactly market.hospitals; got "
                f"{sorted(self.reports)}, expected {sorted(market.hospitals)}"
            )
        for h, r in self.reports.items():
            owned = set(market.pairs_of(h))
            extra = set(r) - owned
            if extra:
                raise ModelError(
                    f"hospital {h!r} reported pair(s) {sorted(extra)} it does not own "
                    f"(owns {sorted(owned)}) -- illegal report"
                )

    @staticmethod
    def truthful(market: KidneyMarket) -> "KidneyProfile":
        """Full revelation: every hospital reports exactly the pairs it owns."""
        return KidneyProfile(reports={h: market.pairs_of(h) for h in market.hospitals})

    def with_report(self, hospital: str, new_report: Sequence[str]) -> "KidneyProfile":
        reports = dict(self.reports)
        reports[hospital] = tuple(new_report)
        return KidneyProfile(reports=reports)

    def to_dict(self) -> dict:
        return {"reports": {h: list(r) for h, r in sorted(self.reports.items())}}

    @staticmethod
    def from_dict(d: Mapping) -> "KidneyProfile":
        return KidneyProfile(reports={h: tuple(r) for h, r in d["reports"].items()})


@dataclass(frozen=True)
class KidneyConfig:
    """Every outcome-affecting choice this mechanism makes, declared. See
    the module docstring's "THREE CLEARING IMPLEMENTATIONS" for the
    `tiebreak_policy` values, "CYCLES OF LENGTH 2 OR 3" for `max_cycle_
    length`, and why `max_central_space` exists at all (only consulted by
    the exhaustive policy -- see `_select_maximum_cycles`)."""

    tiebreak_policy: str = TIEBREAK_LEX_SMALLEST_BY_INDEX
    max_central_space: int = DEFAULT_MAX_CENTRAL_SPACE
    max_cycle_length: int = 2
    #: Only consulted by `TIEBREAK_MAX_CARDINALITY_ILP` -- see
    #: `_select_maximum_cycles_ilp`'s own docstring for why a per-instance
    #: time cap is needed at all (NP-hard cycle packing has real per-instance
    #: variance) and why exceeding it raises `IlpTimeLimitExceeded` rather
    #: than ever returning a merely-feasible, unproven answer. `None` (the
    #: default) means no limit -- unchanged behavior for every config built
    #: before this field existed.
    max_ilp_seconds: "Optional[float]" = None
    mechanism: str = "kidney_two_way"

    def __post_init__(self) -> None:
        if self.tiebreak_policy not in _TIEBREAK_POLICIES:
            raise ModelError(f"tiebreak_policy must be one of {_TIEBREAK_POLICIES}, got {self.tiebreak_policy!r}")
        if isinstance(self.max_central_space, bool) or not isinstance(self.max_central_space, int) or self.max_central_space < 0:
            raise ModelError(f"max_central_space must be a non-negative int, got {self.max_central_space!r}")
        if self.max_ilp_seconds is not None and (
            isinstance(self.max_ilp_seconds, bool) or not isinstance(self.max_ilp_seconds, (int, float)) or self.max_ilp_seconds <= 0
        ):
            raise ModelError(f"max_ilp_seconds must be None or a positive number, got {self.max_ilp_seconds!r}")
        if isinstance(self.max_cycle_length, bool) or self.max_cycle_length not in _MAX_CYCLE_LENGTHS:
            raise ModelError(f"max_cycle_length must be one of {_MAX_CYCLE_LENGTHS}, got {self.max_cycle_length!r}")
        if self.tiebreak_policy == TIEBREAK_MAX_CARDINALITY_BLOSSOM and self.max_cycle_length != 2:
            raise ModelError(
                f"tiebreak_policy={TIEBREAK_MAX_CARDINALITY_BLOSSOM!r} only supports max_cycle_length=2 "
                f"(general graph matching has no notion of a 3-cycle); got max_cycle_length="
                f"{self.max_cycle_length!r} -- use {TIEBREAK_MAX_CARDINALITY_ILP!r} or "
                f"{TIEBREAK_LEX_SMALLEST_BY_INDEX!r} instead"
            )
        if not isinstance(self.mechanism, str) or not self.mechanism:
            raise ModelError(f"mechanism must be a non-empty string, got {self.mechanism!r}")

    def to_dict(self) -> dict:
        return {
            "tiebreak_policy": self.tiebreak_policy,
            "max_central_space": self.max_central_space,
            "max_cycle_length": self.max_cycle_length,
            "max_ilp_seconds": self.max_ilp_seconds,
            "mechanism": self.mechanism,
        }

    @staticmethod
    def from_dict(d: Mapping) -> "KidneyConfig":
        return KidneyConfig(
            tiebreak_policy=d.get("tiebreak_policy", TIEBREAK_LEX_SMALLEST_BY_INDEX),
            max_central_space=d.get("max_central_space", DEFAULT_MAX_CENTRAL_SPACE),
            max_cycle_length=d.get("max_cycle_length", 2),
            max_ilp_seconds=d.get("max_ilp_seconds"),
            mechanism=d.get("mechanism", "kidney_two_way"),
        )


def _canonical_cycle_tuple(market: KidneyMarket, cycle: Sequence[str]) -> "tuple[str, ...]":
    """Rotate `cycle` (a directed cycle -- order matters) so its smallest-
    `market.index` member comes first, preserving cyclic order -- the only
    rotation that keeps the SAME directed edges (reversal would generally
    require a different, possibly nonexistent, edge set). For a 2-cycle
    this reduces exactly to the old `index(u) < index(v)` convention."""
    cycle = tuple(cycle)
    min_i = min(range(len(cycle)), key=lambda i: market.index(cycle[i]))
    return cycle[min_i:] + cycle[:min_i]


def _canonical_cycle(market: KidneyMarket, u: str, v: str) -> tuple[str, str]:
    return (u, v) if market.index(u) < market.index(v) else (v, u)


def candidate_cycles(
    market: KidneyMarket, pool: Sequence[str], max_cycle_length: int = 2
) -> "tuple[tuple[str, ...], ...]":
    """Every feasible directed cycle of length 2 up to `max_cycle_length`
    with ALL members in `pool` and every consecutive directed edge true.
    Canonicalized by `_canonical_cycle_tuple`, sorted by the tuple of
    member indices (Python's own tuple-prefix rule handles comparing a
    2-cycle's 2-index tuple against a 3-cycle's 3-index tuple) --
    deterministic, declared order, never Python set/dict order.

    For 3 pairs `a, b, c`, BOTH `a -> b -> c -> a` and `a -> c -> b -> a`
    are checked as DISTINCT candidates (different edge sets); either, both,
    or neither may be feasible."""
    if max_cycle_length not in _MAX_CYCLE_LENGTHS:
        raise ModelError(f"candidate_cycles: max_cycle_length must be one of {_MAX_CYCLE_LENGTHS}, got {max_cycle_length!r}")
    pool = tuple(sorted(set(pool), key=market.index))
    out: "list[tuple[str, ...]]" = []
    for u, v in combinations(pool, 2):
        if market.has_edge(u, v) and market.has_edge(v, u):
            out.append(_canonical_cycle(market, u, v))
    if max_cycle_length >= 3:
        for a, b, c in combinations(pool, 3):
            if market.has_edge(a, b) and market.has_edge(b, c) and market.has_edge(c, a):
                out.append(_canonical_cycle_tuple(market, (a, b, c)))
            if market.has_edge(a, c) and market.has_edge(c, b) and market.has_edge(b, a):
                out.append(_canonical_cycle_tuple(market, (a, c, b)))
    return tuple(sorted(out, key=lambda cyc: tuple(market.index(p) for p in cyc)))


def _feasible_selections(
    market: KidneyMarket, candidates: "tuple[tuple[str, ...], ...]", max_space: int
) -> "tuple[tuple[tuple[str, ...], ...], ...]":
    """Every vertex-disjoint subset of `candidates` (cycles of any declared
    length), as tuples-of-cycles. Exhaustive: `2**len(candidates)` subsets,
    guarded by `max_space` -- see the module docstring."""
    n = len(candidates)
    if 2 ** n > max_space:
        raise ModelError(
            f"_feasible_selections: {n} candidate cycles ({2 ** n} subsets) exceeds "
            f"max_central_space={max_space}"
        )
    out = []
    for r in range(n, -1, -1):  # larger subsets first -- irrelevant to correctness, just locality
        for combo in combinations(range(n), r):
            used: set = set()
            ok = True
            for i in combo:
                cyc = candidates[i]
                if any(p in used for p in cyc):
                    ok = False
                    break
                used.update(cyc)
            if ok:
                out.append(tuple(candidates[i] for i in combo))
    return tuple(out)


def _select_maximum_cycles_exhaustive(
    market: KidneyMarket, candidates: "tuple[tuple[str, ...], ...]", config: KidneyConfig
) -> "tuple[tuple[str, ...], ...]":
    """`TIEBREAK_LEX_SMALLEST_BY_INDEX`: the original brute-force selection,
    generalized to cycles of any declared length. See the module docstring
    for the tuple-prefix tiebreak convention across mixed cycle lengths."""
    selections = _feasible_selections(market, candidates, config.max_central_space)
    if not selections:
        return ()
    best_cardinality = max(sum(len(c) for c in s) for s in selections)
    tied = [s for s in selections if sum(len(c) for c in s) == best_cardinality]

    def sort_key(selection: "tuple[tuple[str, ...], ...]"):
        ordered = tuple(sorted(selection, key=lambda cyc: tuple(market.index(p) for p in cyc)))
        return tuple(tuple(market.index(p) for p in cyc) for cyc in ordered)

    tied_sorted = sorted(tied, key=sort_key)
    return tied_sorted[0]


def _select_maximum_cycles_blossom(
    market: KidneyMarket, candidates: "tuple[tuple[str, ...], ...]"
) -> "tuple[tuple[str, ...], ...]":
    """`TIEBREAK_MAX_CARDINALITY_BLOSSOM`: NetworkX's Blossom-algorithm
    maximum matching -- 2-cycles ONLY (see the module docstring; `KidneyConfig.
    __post_init__` already refuses this policy with `max_cycle_length != 2`,
    this is a second, defense-in-depth check on the candidates actually
    received). DETERMINISM DEPENDS ON FIXED INSERTION ORDER (verified
    empirically -- NetworkX's result is invariant to `PYTHONHASHSEED` but
    NOT to edge insertion order): nodes and edges are added in exactly
    `candidates`' own canonical order (already sorted by `(index(u),
    index(v))` by `candidate_cycles`), never via a set or dict whose
    iteration order could vary. See the module docstring for what this
    policy does and does not guarantee relative to the exhaustive one."""
    import networkx as nx

    if not candidates:
        return ()
    if any(len(c) != 2 for c in candidates):
        raise ModelError(
            f"{TIEBREAK_MAX_CARDINALITY_BLOSSOM!r} only supports 2-cycles; received a candidate of "
            f"length != 2 (general graph matching has no notion of a 3-cycle)"
        )
    graph = nx.Graph()
    # Node order matters for the same reason edge order does -- add every
    # pair that appears in ANY candidate, in `candidates`' own order, before
    # any edge (a pair with no feasible cycle still gets no edges, which is
    # fine -- unmatched nodes are simply absent from the returned matching).
    seen_nodes: list = []
    seen_set: set = set()
    for u, v in candidates:
        for p in (u, v):
            if p not in seen_set:
                seen_set.add(p)
                seen_nodes.append(p)
    graph.add_nodes_from(seen_nodes)
    for u, v in candidates:
        graph.add_edge(u, v, weight=1)

    matching = nx.algorithms.matching.max_weight_matching(graph, maxcardinality=True)
    selection = tuple(_canonical_cycle(market, u, v) for u, v in matching)
    return tuple(sorted(selection, key=lambda c: (market.index(c[0]), market.index(c[1]))))


#: A DISTINCT exception from `ModelError` for exactly one failure mode: the
#: solver ran out of its allotted time without proving optimality. Kept
#: separate from other `ModelError`s (a malformed model, an unknown policy)
#: so a caller running a large batch can catch SPECIFICALLY "this one
#: instance was too hard within budget" and skip it, without also silently
#: swallowing a genuine bug elsewhere in the same call stack.
class IlpTimeLimitExceeded(ModelError):
    pass


def _select_maximum_cycles_ilp(
    market: KidneyMarket, candidates: "tuple[tuple[str, ...], ...]", max_seconds: "Optional[float]" = None
) -> "tuple[tuple[str, ...], ...]":
    """`TIEBREAK_MAX_CARDINALITY_ILP`: exact integer program (OR-Tools
    CP-SAT) -- the standard cycle-packing formulation (one binary variable
    per candidate cycle, one at-most-one constraint per pair, maximize
    total pairs covered). Works for 2- AND 3-cycles. Raises unless the
    solver PROVES optimality -- never silently accepts a merely-feasible
    bound (a time-limited run that fails to prove optimality raises
    `IlpTimeLimitExceeded` specifically, distinct from any other failure).
    DETERMINISM: variables are created in `candidates`' own canonical order
    (never a set/dict), and `num_search_workers=1` + `random_seed=0` are
    fixed -- verified empirically (`tests/test_kidney3_ilp_matches_oracle.py`)
    to reproduce the identical selection across repeated fresh-process runs.
    `max_seconds` (from `KidneyConfig.max_ilp_seconds`) bounds worst-case
    wall time per solve -- NP-hard cycle packing has real per-instance
    variance (verified empirically: some 500-pair instances solve in
    seconds, some take much longer), so a batch of many searches needs a
    per-call cap to stay boundable, at the cost of occasionally reporting
    "too hard within budget" (`IlpTimeLimitExceeded`) rather than an answer.
    A witness is only ever built from a call that actually proved OPTIMAL,
    so raising this exception can only ever make a search UNDER-count
    manipulations it could not finish checking, never over-count. See the
    module docstring for what this policy does and does not guarantee
    relative to the exhaustive one (cardinality only, not the same
    tie-broken selection)."""
    from ortools.sat.python import cp_model

    if not candidates:
        return ()

    model = cp_model.CpModel()
    x = [model.NewBoolVar(f"cycle_{i}") for i in range(len(candidates))]

    by_pair: "dict[str, list[int]]" = {}
    for i, cyc in enumerate(candidates):
        for p in cyc:
            by_pair.setdefault(p, []).append(i)
    for p in sorted(by_pair):  # sorted: constraint-creation order must also be deterministic
        idxs = by_pair[p]
        model.Add(sum(x[i] for i in idxs) <= 1)

    model.Maximize(sum(len(candidates[i]) * x[i] for i in range(len(candidates))))

    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 0
    if max_seconds is not None:
        solver.parameters.max_time_in_seconds = max_seconds
    status = solver.Solve(model)
    if status != cp_model.OPTIMAL:
        if max_seconds is not None and status in (cp_model.FEASIBLE, cp_model.UNKNOWN):
            raise IlpTimeLimitExceeded(
                f"_select_maximum_cycles_ilp: solver did not prove optimality within "
                f"max_seconds={max_seconds} (status={solver.StatusName(status)!r}) over "
                f"{len(candidates)} candidate cycles"
            )
        raise ModelError(
            f"_select_maximum_cycles_ilp: solver did not prove optimality (status="
            f"{solver.StatusName(status)!r}) over {len(candidates)} candidate cycles"
        )

    selection = tuple(candidates[i] for i in range(len(candidates)) if solver.Value(x[i]) == 1)
    return tuple(sorted(selection, key=lambda cyc: tuple(market.index(p) for p in cyc)))


def _select_maximum_cycles(
    market: KidneyMarket, candidates: "tuple[tuple[str, ...], ...]", config: KidneyConfig
) -> "tuple[tuple[str, ...], ...]":
    """The declared, tie-broken maximum-cardinality vertex-disjoint
    selection over `candidates` -- used identically for BOTH the central
    stage and every hospital's local stage (same rule, different candidate
    pool), per the module docstring. Dispatches on `config.tiebreak_policy`;
    see the module docstring's "THREE CLEARING IMPLEMENTATIONS" for what
    each one does and does not guarantee."""
    if config.tiebreak_policy == TIEBREAK_LEX_SMALLEST_BY_INDEX:
        return _select_maximum_cycles_exhaustive(market, candidates, config)
    if config.tiebreak_policy == TIEBREAK_MAX_CARDINALITY_BLOSSOM:
        return _select_maximum_cycles_blossom(market, candidates)
    if config.tiebreak_policy == TIEBREAK_MAX_CARDINALITY_ILP:
        return _select_maximum_cycles_ilp(market, candidates, max_seconds=config.max_ilp_seconds)
    raise ModelError(f"unknown tiebreak_policy {config.tiebreak_policy!r}")  # pragma: no cover - guarded in __post_init__


@dataclass(frozen=True)
class KidneyEvent:
    kind: str
    data: Mapping[str, object]

    def to_dict(self) -> dict:
        return {"kind": self.kind, "data": dict(self.data)}


@dataclass(frozen=True)
class KidneyResult:
    """Both stages' outcomes plus per-hospital utility -- the full,
    replayable record of one `clear_kidney_exchange` call."""

    central_selection: "tuple[tuple[str, str], ...]"
    local_selections: Mapping[str, "tuple[tuple[str, str], ...]"]
    matched_pairs: frozenset
    utility: Mapping[str, int]
    events: "tuple[KidneyEvent, ...]"

    def format_trace(self) -> str:
        lines = [f"central: {list(self.central_selection)}"]
        for h, sel in sorted(self.local_selections.items()):
            lines.append(f"  local[{h}]: {list(sel)}")
        lines.append(f"utility: {dict(sorted(self.utility.items()))}")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "central_selection": [list(c) for c in self.central_selection],
            "local_selections": {h: [list(c) for c in sel] for h, sel in sorted(self.local_selections.items())},
            "matched_pairs": sorted(self.matched_pairs),
            "utility": dict(sorted(self.utility.items())),
        }

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, KidneyResult):
            return NotImplemented
        return self.to_dict() == other.to_dict()


def clear_kidney_exchange(
    market: KidneyMarket, profile: "KidneyProfile", config: Optional[KidneyConfig] = None
) -> KidneyResult:
    """Run both stages: central clearing over each hospital's REPORTED
    pairs, then every hospital's residual local clearing over its own
    TRUE internal graph. See the module docstring for the full model."""
    config = config if config is not None else KidneyConfig()
    profile.validate_against(market)

    reported_pool = tuple(p for h in market.hospitals for p in profile.report(h))
    central_candidates = candidate_cycles(market, reported_pool, config.max_cycle_length)
    central_selection = _select_maximum_cycles(market, central_candidates, config)

    events = [KidneyEvent(kind="central_cycle_selected", data={"cycle": list(c)}) for c in central_selection]

    matched: set = set()
    for cycle in central_selection:
        matched.update(cycle)

    local_selections: dict[str, tuple] = {}
    for h in market.hospitals:
        residual = tuple(p for p in market.pairs_of(h) if p not in matched)
        local_candidates = candidate_cycles(market, residual, config.max_cycle_length)
        local_selection = _select_maximum_cycles(market, local_candidates, config)
        local_selections[h] = local_selection
        for cycle in local_selection:
            matched.update(cycle)
            events.append(
                KidneyEvent(kind="local_cycle_selected", data={"hospital": h, "cycle": list(cycle)})
            )

    utility = {h: sum(1 for p in market.pairs_of(h) if p in matched) for h in market.hospitals}

    return KidneyResult(
        central_selection=central_selection,
        local_selections=local_selections,
        matched_pairs=frozenset(matched),
        utility=utility,
        events=tuple(events),
    )
