"""Seeded synthetic-instance generator for the kidney-exchange mechanism
(`witness.kidney`), for an exploratory manipulation-rate sweep -- NOT a
calibrated model of real compatibility-graph structure or real hospital
pair ownership. Reuses `witness.generate`'s own randomness primitives
verbatim (`derive_seed`, `_unit_from_key`) and `witness.tiebreak.lottery_order`,
rather than inventing a new convention, so instances are byte-identical
across processes/machines exactly as every other generator in this codebase.

WHAT THIS GENERATOR DOES NOT CLAIM: `KIDNEY_EXCHANGE_SCOPE.md`'s own data
plan is explicit that a downloadable, provenance-verified compatibility-
graph benchmark (Petris et al., `Instances_KEP.zip`) is the primary source
this project intends to use, with hospital ownership partitioned only by a
"declared deterministic or seeded synthetic rule," reported as "benchmark
graph with synthetic ownership," never "real hospitals." This module is a
STAND-IN for that whole pipeline (graph AND ownership both synthetic) --
useful for exercising and characterizing `witness.search_kidney` before the
real benchmark is imported, but every rate measured against it inherits
that same caveat one level further: not even the compatibility graph is
real here yet.

MODEL (declared, minimal): `n_pairs` total pairs, split as evenly as
possible across `n_hospitals` via a lottery-shuffled round-robin (never
Python's own iteration order). For every ORDERED pair of distinct pairs
`(u, v)`, an independent deterministic coin flip (`_unit_from_key`) decides
whether the directed edge `u -> v` exists, at probability `edge_density` --
so `u -> v` and `v -> u` are independent draws, matching the model's own
directed-graph primitive (a 2-cycle needs BOTH, which is not guaranteed
just because one direction was drawn).
"""

from __future__ import annotations

from dataclasses import dataclass

from witness.errors import ModelError
from witness.generate import GENERATE_DOMAIN, derive_seed, _unit_from_key
from witness.kidney import KidneyMarket, KidneyProfile
from witness.tiebreak import lottery_order


@dataclass(frozen=True)
class KidneyGeneratorConfig:
    """Parameters of one synthetic-market draw. `seed` + index together
    determine everything, exactly like every other generator config here."""

    n_pairs: int
    n_hospitals: int
    edge_density: float
    seed: str = "witness-kidney"

    def __post_init__(self) -> None:
        if isinstance(self.n_pairs, bool) or not isinstance(self.n_pairs, int) or self.n_pairs < 2:
            raise ModelError(f"n_pairs must be an int >= 2, got {self.n_pairs!r}")
        if isinstance(self.n_hospitals, bool) or not isinstance(self.n_hospitals, int) or not (1 <= self.n_hospitals <= self.n_pairs):
            raise ModelError(f"n_hospitals must be an int in [1, n_pairs], got {self.n_hospitals!r}")
        if isinstance(self.edge_density, bool) or not isinstance(self.edge_density, (int, float)) or not (0.0 <= self.edge_density <= 1.0):
            raise ModelError(f"edge_density must be a number in [0.0, 1.0], got {self.edge_density!r}")
        if not isinstance(self.seed, str) or not self.seed:
            raise ModelError(f"seed must be a non-empty string, got {self.seed!r}")


def _kidney_derive_seed(gc: KidneyGeneratorConfig, index: int, purpose: str) -> str:
    return derive_seed(gc.seed, index, f"kidney/{purpose}")


def generate_kidney_instance(gc: KidneyGeneratorConfig, index: int) -> "tuple[KidneyMarket, KidneyProfile]":
    """Build the `index`-th synthetic (market, truthful profile) pair."""
    pairs = tuple(f"p{i}" for i in range(1, gc.n_pairs + 1))
    hospitals = tuple(f"h{i}" for i in range(1, gc.n_hospitals + 1))

    assign_seed = _kidney_derive_seed(gc, index, "assign")
    shuffled = lottery_order(assign_seed, "assign", pairs)
    hospital_of = {p: hospitals[i % len(hospitals)] for i, p in enumerate(shuffled)}

    edge_seed = _kidney_derive_seed(gc, index, "edges")
    edges = set()
    for u in pairs:
        for v in pairs:
            if u == v:
                continue
            if _unit_from_key(edge_seed, "edge", f"{u}->{v}") < gc.edge_density:
                edges.add((u, v))

    market = KidneyMarket(
        pairs=pairs, hospital_of=hospital_of, hospitals=hospitals, edges=frozenset(edges)
    )
    profile = KidneyProfile.truthful(market)
    return market, profile
