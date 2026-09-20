"""Declared, SEEDED hospital-ownership partitions with a tunable SIZE
DISTRIBUTION, for the kidney-exchange mechanism (`witness.kidney`).

WHY THIS EXISTS SEPARATELY FROM `witness.kidney_real_data`: that module's
`load_real_kidney_market` already builds one synthetic ownership partition
inline (seeded round-robin over a lottery-shuffled pair order, always
producing hospitals of roughly EQUAL size). Real transplant centers are not
remotely equal in size -- Agarwal et al. (AER 2019) document that 62% of US
kidney-exchange transplants occur WITHIN a single hospital, which is only
possible if a meaningful share of centers are large enough to clear
internally. Hospital size is also the theoretically obvious driver of the
withholding incentive this project searches for: a hospital that can match
many of its own pairs internally has something to gain by keeping them off
the central pool; a hospital that owns one or two pairs generally cannot.
Measuring the withholding rate only under artificially-equal ownership
cannot distinguish "the incentive is rare" from "the incentive concentrates
in large hospitals and we never built one." This module builds large
hospitals, on purpose, so that question can be asked directly.

WHAT IS AND ISN'T DECLARED HERE: exactly like `witness.kidney_real_data`'s
own ownership partition, every partition built by this module is SYNTHETIC
-- this file has no access to and makes no claim about real hospital
identities or real center sizes. What's new here is only the SIZE
DISTRIBUTION is now a declared, named, seeded choice instead of always being
uniform. Every regime below is a genuine partition (every pair owned by
EXACTLY one hospital) by construction: each regime reduces to (a) computing
a list of hospital SIZES that sums to exactly `len(pairs)`, each >= 1, via a
rule that is a deterministic function of the regime parameters alone (no
randomness in the SHAPE), then (b) taking one lottery-shuffled permutation
of `pairs` (seeded via `derive_seed` + `lottery_order`, the same
domain-separated construction `witness.kidney_real_data` and every other
generator in this codebase uses) and slicing it into CONTIGUOUS blocks of
those sizes, in order. Step (b) is what "seeded" buys here: a different
`draw_index` reshuffles WHICH real pairs land in which size-rank bucket,
while the shape of the size distribution itself stays exactly what the
regime parameters declare -- both are load-bearing and neither is hidden.
`assert_genuine_partition` re-checks the partition property directly from
its OUTPUT (never trusts the construction), and every regime's tests call
it over many seeds and sizes, per REVIEWER.md's "test the property, not a
proxy."

THE THREE REGIMES:

  * `REGIME_UNIFORM`: reproduces `witness.kidney_real_data.
    load_real_kidney_market`'s own inline ownership construction EXACTLY --
    same `derive_seed(seed, draw_index, "kidney-real/ownership")` purpose
    string, same `lottery_order(assign_seed, "assign", pairs)` shuffle, same
    round-robin `hospitals[i % n_hospitals]` assignment (NOT the contiguous-
    block construction the other two regimes use -- round-robin and
    contiguous-block give the same near-equal SIZES but a different exact
    pair-to-hospital map, so this regime deliberately keeps the original
    round-robin code path rather than reimplementing it as a size list, to
    guarantee byte-identical output, not just equal-cardinality output).
    `tests/test_kidney_ownership.py` asserts this equivalence directly
    against `witness.kidney_real_data.load_real_kidney_market`, over
    several (p, n_hospitals, seed, draw_index) combinations -- this is the
    baseline every skewed regime is compared against.

  * `REGIME_POWER_LAW`: Zipf-like sizes. Hospital rank `r` (0-indexed, `r=0`
    largest) gets EXTRA pairs (beyond a guaranteed floor of 1 each, so every
    declared hospital is non-empty, which `KidneyMarket` itself requires)
    proportional to `1 / (r + 1) ** exponent`, rounded to integers by the
    largest-remainder method (deterministic, ties broken by rank ascending
    -- declared, not incidental). `exponent` is a regime parameter (default
    1.0, standard Zipf); larger values concentrate more pairs in fewer
    hospitals.

  * `REGIME_CORE_PERIPHERY`: a small number (`n_large`) of large centers of
    exactly `large_size` pairs each, plus every remaining pair split into a
    long tail of `periphery_chunk`-pair (default 2, so mostly 2-pair
    centers with at most one leftover 1-pair center if the remainder is
    odd) hospitals -- the shape REVIEWER.md's brief asks for verbatim ("a
    small number of large centers plus a long tail of 1-2 pair centers").

Every regime's size list is computed by its own `_..._sizes` function,
independent of pair-shuffling; `_assign_contiguous_blocks` (shared by the
power-law and core-periphery regimes) is the ONLY code that turns a size
list into an actual partition, and it is exactly the "slice a shuffled
sequence into contiguous blocks" construction described above -- trivially
a genuine partition for ANY size list summing to `len(pairs)`, which is why
`assert_genuine_partition` is still run independently in tests rather than
taken on faith from this description.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping, Sequence

from witness.errors import ModelError
from witness.generate import derive_seed
from witness.tiebreak import lottery_order

REGIME_UNIFORM = "uniform"
REGIME_POWER_LAW = "power_law"
REGIME_CORE_PERIPHERY = "core_periphery"

REGIMES = (REGIME_UNIFORM, REGIME_POWER_LAW, REGIME_CORE_PERIPHERY)

#: The exact purpose string `witness.kidney_real_data.load_real_kidney_market`
#: uses for its own inline ownership draw -- reused verbatim (not just in
#: spirit) so `REGIME_UNIFORM` derives the identical `assign_seed`.
_UNIFORM_PURPOSE = "kidney-real/ownership"

#: Domain-separated purpose strings for the two new regimes -- distinct from
#: `_UNIFORM_PURPOSE` and from each other, per this codebase's "unrelated
#: draws must never collide" discipline (`witness.generate.derive_seed`'s
#: own docstring).
_POWER_LAW_PURPOSE = "kidney-skew/ownership/power_law"
_CORE_PERIPHERY_PURPOSE = "kidney-skew/ownership/core_periphery"


@dataclass(frozen=True)
class OwnershipMeta:
    """Provenance record for one drawn partition -- the honesty label this
    module's docstring requires: which regime, which declared parameters,
    which seed/draw produced this exact `hospital_of`."""

    regime: str
    regime_params: Mapping[str, object]
    seed: str
    draw_index: int
    n_hospitals: int
    hospital_sizes: "tuple[int, ...]"  # in `hospitals` order

    def to_dict(self) -> dict:
        return {
            "regime": self.regime,
            "regime_params": dict(sorted(self.regime_params.items())),
            "seed": self.seed,
            "draw_index": self.draw_index,
            "n_hospitals": self.n_hospitals,
            "hospital_sizes": list(self.hospital_sizes),
        }


def assert_genuine_partition(
    pairs: Sequence[str], hospital_of: Mapping[str, str], hospitals: Sequence[str]
) -> None:
    """Re-derive, from the OUTPUT alone, that every pair in `pairs` is owned
    by exactly one hospital in `hospitals` and nothing else is owned --
    never trusts the construction that produced `hospital_of`. Raises
    `ModelError` (not an assert statement) so this check survives `python -O`
    and so callers outside tests get the same guarantee."""
    pairs = tuple(pairs)
    hospitals = tuple(hospitals)
    if len(set(pairs)) != len(pairs):
        raise ModelError(f"assert_genuine_partition: `pairs` itself has duplicates: {pairs!r}")
    if set(hospital_of.keys()) != set(pairs):
        missing = set(pairs) - set(hospital_of.keys())
        extra = set(hospital_of.keys()) - set(pairs)
        raise ModelError(
            f"assert_genuine_partition: hospital_of does not cover exactly `pairs` -- "
            f"missing={sorted(missing)}, extra_unowned_keys={sorted(extra)}"
        )
    owners = set(hospital_of.values())
    if not owners <= set(hospitals):
        raise ModelError(
            f"assert_genuine_partition: hospital_of names owner(s) not in `hospitals`: "
            f"{sorted(owners - set(hospitals))}"
        )
    # Every pair owned exactly once is already implied by hospital_of being a
    # plain dict keyed by `pairs` (a dict key can't repeat) -- but reconstruct
    # the partition from scratch by hospital and cross-check cardinalities
    # too, so this is a check of the OUTPUT shape, not of dict semantics.
    by_hospital: dict = {h: [] for h in hospitals}
    for pair, h in hospital_of.items():
        by_hospital[h].append(pair)
    all_owned = [p for h in hospitals for p in by_hospital[h]]
    if sorted(all_owned) != sorted(pairs):
        raise ModelError(
            "assert_genuine_partition: union of per-hospital pair lists does not equal "
            "`pairs` exactly (a pair is duplicated across hospitals or dropped)"
        )
    if len(set(all_owned)) != len(all_owned):
        raise ModelError("assert_genuine_partition: some pair appears under more than one hospital")


def _largest_remainder_extra(weights: Sequence[float], extra_total: int) -> "tuple[int, ...]":
    """Distribute `extra_total` indivisible units across `len(weights)` bins
    proportional to `weights`, by the largest-remainder method: floor each
    bin's proportional share, then hand out the leftover units to the bins
    with the largest fractional remainder first, breaking ties by lowest
    index (declared, deterministic -- never Python sort-stability-by-
    accident on an unordered structure)."""
    n = len(weights)
    total_w = sum(weights)
    if total_w <= 0:
        raise ModelError(f"_largest_remainder_extra: weights must sum to a positive number, got {weights!r}")
    raw = [w / total_w * extra_total for w in weights]
    floor_vals = [math.floor(x) for x in raw]
    remainder = extra_total - sum(floor_vals)
    if remainder < 0 or remainder > n:
        raise ModelError(f"_largest_remainder_extra: internal invariant violated, remainder={remainder}")
    fracs = sorted(range(n), key=lambda i: (-(raw[i] - floor_vals[i]), i))
    extra = list(floor_vals)
    for i in fracs[:remainder]:
        extra[i] += 1
    assert sum(extra) == extra_total
    return tuple(extra)


def _power_law_sizes(p: int, n_hospitals: int, exponent: float) -> "tuple[int, ...]":
    """Sizes for `REGIME_POWER_LAW`: every hospital gets a floor of 1 pair
    (so no declared hospital is empty), then the remaining `p - n_hospitals`
    pairs are distributed by `_largest_remainder_extra` over Zipf weights
    `1 / (rank + 1) ** exponent`, rank 0 = the intended-largest hospital.
    Purely a function of (p, n_hospitals, exponent) -- no randomness in the
    SHAPE, only in which real pairs later land in which rank (see module
    docstring)."""
    if n_hospitals < 1:
        raise ModelError(f"_power_law_sizes: n_hospitals must be >= 1, got {n_hospitals!r}")
    if n_hospitals > p:
        raise ModelError(
            f"_power_law_sizes: n_hospitals={n_hospitals} exceeds p={p} pairs "
            f"(every hospital needs at least 1 pair)"
        )
    extra_total = p - n_hospitals
    weights = [1.0 / ((rank + 1) ** exponent) for rank in range(n_hospitals)]
    extra = _largest_remainder_extra(weights, extra_total)
    sizes = tuple(1 + e for e in extra)
    if sum(sizes) != p:
        raise ModelError(f"_power_law_sizes: internal invariant violated, sizes sum to {sum(sizes)}, expected {p}")
    return sizes


def _core_periphery_sizes(p: int, n_large: int, large_size: int, periphery_chunk: int) -> "tuple[int, ...]":
    """Sizes for `REGIME_CORE_PERIPHERY`: `n_large` hospitals of exactly
    `large_size` pairs each, then the remainder split into `periphery_chunk`
    -pair hospitals (default 2), with at most one final smaller hospital if
    the remainder does not divide evenly -- e.g. `periphery_chunk=2` on an
    odd remainder yields one trailing 1-pair hospital, giving the declared
    "1-2 pair centers" tail literally."""
    if n_large < 1:
        raise ModelError(f"_core_periphery_sizes: n_large must be >= 1, got {n_large!r}")
    if large_size < 1:
        raise ModelError(f"_core_periphery_sizes: large_size must be >= 1, got {large_size!r}")
    if periphery_chunk < 1:
        raise ModelError(f"_core_periphery_sizes: periphery_chunk must be >= 1, got {periphery_chunk!r}")
    core_total = n_large * large_size
    if core_total > p:
        raise ModelError(
            f"_core_periphery_sizes: n_large={n_large} * large_size={large_size} = {core_total} "
            f"exceeds p={p}"
        )
    remaining = p - core_total
    periphery_sizes: list = []
    while remaining > 0:
        chunk = periphery_chunk if remaining >= periphery_chunk else remaining
        periphery_sizes.append(chunk)
        remaining -= chunk
    sizes = tuple([large_size] * n_large + periphery_sizes)
    if sum(sizes) != p:
        raise ModelError(f"_core_periphery_sizes: internal invariant violated, sizes sum to {sum(sizes)}, expected {p}")
    return sizes


def _assign_contiguous_blocks(
    pairs: Sequence[str], sizes: Sequence[int], seed: str, draw_index: int, purpose: str
) -> "tuple[dict, tuple[str, ...]]":
    """Shuffle `pairs` (seeded, via the same `derive_seed` + `lottery_order`
    construction as every other generator in this codebase) and slice the
    shuffled order into contiguous blocks of `sizes`, in order -- hospital
    `i` (1-indexed, `h1`, `h2`, ...) gets the block of `sizes[i-1]` pairs.
    Trivially a genuine partition for any `sizes` summing to `len(pairs)`
    (each pair appears in exactly one contiguous slice of one permutation)
    -- `assert_genuine_partition` still re-checks this from the output in
    every caller/test, per REVIEWER.md's "test the property, not a proxy."
    """
    pairs = tuple(pairs)
    if sum(sizes) != len(pairs):
        raise ModelError(
            f"_assign_contiguous_blocks: sizes sum to {sum(sizes)}, expected len(pairs)={len(pairs)}"
        )
    assign_seed = derive_seed(seed, draw_index, purpose)
    shuffled = lottery_order(assign_seed, "assign", pairs)
    hospitals = tuple(f"h{i}" for i in range(1, len(sizes) + 1))
    hospital_of: dict = {}
    idx = 0
    for h, size in zip(hospitals, sizes):
        for pair in shuffled[idx : idx + size]:
            hospital_of[pair] = h
        idx += size
    assert idx == len(pairs)
    return hospital_of, hospitals


def _uniform_assignment(pairs: Sequence[str], n_hospitals: int, seed: str, draw_index: int) -> "tuple[dict, tuple[str, ...]]":
    """EXACTLY `witness.kidney_real_data.load_real_kidney_market`'s own
    inline ownership construction -- same purpose string, same shuffle
    scope, same round-robin assignment. See the module docstring's
    `REGIME_UNIFORM` entry for why this is kept as its own code path
    (round-robin, not contiguous blocks) rather than expressed as a size
    list: only this exact construction is proven byte-identical to the
    existing loader's output."""
    if n_hospitals < 1:
        raise ModelError(f"_uniform_assignment: n_hospitals must be >= 1, got {n_hospitals!r}")
    pairs = tuple(pairs)
    if n_hospitals > len(pairs):
        raise ModelError(
            f"_uniform_assignment: n_hospitals={n_hospitals} exceeds len(pairs)={len(pairs)} "
            f"(every hospital needs at least 1 pair)"
        )
    assign_seed = derive_seed(seed, draw_index, _UNIFORM_PURPOSE)
    shuffled = lottery_order(assign_seed, "assign", pairs)
    hospitals = tuple(f"h{i}" for i in range(1, n_hospitals + 1))
    hospital_of = {pair: hospitals[i % n_hospitals] for i, pair in enumerate(shuffled)}
    return hospital_of, hospitals


def build_ownership(
    pairs: Sequence[str],
    seed: str,
    draw_index: int,
    regime: str,
    **regime_params,
) -> "tuple[dict, tuple[str, ...], OwnershipMeta]":
    """The single entry point: build a declared, seeded ownership partition
    of `pairs` under `regime`, returning `(hospital_of, hospitals, meta)`.
    `regime_params` are regime-specific (see each `REGIME_*` in the module
    docstring); an unrecognized regime or missing/invalid parameter raises
    `ModelError` rather than silently defaulting. Reproducible: the SAME
    `(pairs, seed, draw_index, regime, regime_params)` always produces the
    byte-identical partition (no `dict`/`set` iteration order anywhere in
    the construction -- see the two helper functions above)."""
    pairs = tuple(pairs)
    if len(pairs) == 0:
        raise ModelError("build_ownership: `pairs` must be non-empty")

    if regime == REGIME_UNIFORM:
        n_hospitals = regime_params.pop("n_hospitals", None)
        if n_hospitals is None:
            raise ModelError(f"{REGIME_UNIFORM!r} requires regime_params['n_hospitals']")
        if regime_params:
            raise ModelError(f"{REGIME_UNIFORM!r} got unexpected regime_params: {sorted(regime_params)}")
        hospital_of, hospitals = _uniform_assignment(pairs, n_hospitals, seed, draw_index)
        sizes = tuple(sum(1 for p in pairs if hospital_of[p] == h) for h in hospitals)
        meta = OwnershipMeta(
            regime=regime, regime_params={"n_hospitals": n_hospitals}, seed=seed,
            draw_index=draw_index, n_hospitals=len(hospitals), hospital_sizes=sizes,
        )

    elif regime == REGIME_POWER_LAW:
        n_hospitals = regime_params.pop("n_hospitals", None)
        exponent = regime_params.pop("exponent", 1.0)
        if n_hospitals is None:
            raise ModelError(f"{REGIME_POWER_LAW!r} requires regime_params['n_hospitals']")
        if regime_params:
            raise ModelError(f"{REGIME_POWER_LAW!r} got unexpected regime_params: {sorted(regime_params)}")
        sizes = _power_law_sizes(len(pairs), n_hospitals, exponent)
        hospital_of, hospitals = _assign_contiguous_blocks(pairs, sizes, seed, draw_index, _POWER_LAW_PURPOSE)
        meta = OwnershipMeta(
            regime=regime, regime_params={"n_hospitals": n_hospitals, "exponent": exponent}, seed=seed,
            draw_index=draw_index, n_hospitals=len(hospitals), hospital_sizes=sizes,
        )

    elif regime == REGIME_CORE_PERIPHERY:
        n_large = regime_params.pop("n_large", None)
        large_size = regime_params.pop("large_size", None)
        periphery_chunk = regime_params.pop("periphery_chunk", 2)
        if n_large is None or large_size is None:
            raise ModelError(f"{REGIME_CORE_PERIPHERY!r} requires regime_params['n_large'] and ['large_size']")
        if regime_params:
            raise ModelError(f"{REGIME_CORE_PERIPHERY!r} got unexpected regime_params: {sorted(regime_params)}")
        sizes = _core_periphery_sizes(len(pairs), n_large, large_size, periphery_chunk)
        hospital_of, hospitals = _assign_contiguous_blocks(pairs, sizes, seed, draw_index, _CORE_PERIPHERY_PURPOSE)
        meta = OwnershipMeta(
            regime=regime,
            regime_params={"n_large": n_large, "large_size": large_size, "periphery_chunk": periphery_chunk},
            seed=seed, draw_index=draw_index, n_hospitals=len(hospitals), hospital_sizes=sizes,
        )

    else:
        raise ModelError(f"build_ownership: unknown regime {regime!r}, expected one of {REGIMES}")

    assert_genuine_partition(pairs, hospital_of, hospitals)
    return hospital_of, hospitals, meta
