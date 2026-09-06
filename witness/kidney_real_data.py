"""Loads REAL kidney-exchange compatibility-graph instances (Pansart et al.
2022, via `data/external/pansart2022_kep/` -- see that directory's
`SOURCE.txt`) into a `witness.kidney.KidneyMarket` + truthful
`KidneyProfile`, with a DECLARED SYNTHETIC hospital-ownership partition on
top. See `KIDNEY_EXCHANGE_SCOPE.md`'s "Data plan and evidence boundary" for
why ownership must be synthetic here and must never be described as real.

WHY THIS IS SEPARATE FROM `data/external/pansart2022_kep/parsed.py`: that
script is pure data-validation plumbing (header-vs-matrix-shape checks,
density stats) -- see `data/external/README.md`'s own top-level discipline
("Nothing here is wired into witness/"). This module is the wiring: building
an actual Market/Profile pair a mechanism can run. Per this project's
established convention (`witness.stephenson`, `witness.sfusd2017` both read
their raw files directly rather than importing their sibling `data/external`
`parsed.py`), this module reads the raw zip member directly instead of
importing that sibling script.

WHAT IS REAL AND WHAT IS SYNTHETIC, STATED PLAINLY: the COMPATIBILITY GRAPH
(which patient-donor pairs can transplant to which) is REAL, from a
published, peer-reviewed kidney-exchange benchmark. The HOSPITAL OWNERSHIP
PARTITION is NOT -- this file format has no notion of hospital ownership at
all (confirmed directly against `ORIGINAL_DATA_README.md`'s own format
description, which has no such field). Every `KidneyMarket` this module
builds carries that fact in `RealKidneyInstanceMeta`, and any report built
from it must say "real compatibility graph, synthetic ownership," never
"real hospitals."

MODEL RESTRICTION: `witness.kidney` is two-way-only (no altruistic donors,
no chains -- see that module's docstring). This loader DROPS every
altruistic-donor row from the source file entirely (real KEP benchmarks
also solve for chains, which this project deliberately does not model) and
uses only the P x P patient-donor-pair-to-patient-donor-pair submatrix.

MULTIPLE "INSTANCES" FROM ONE REAL FILE FORMAT: unlike
`witness.generate_kidney`'s synthetic generator (infinitely many seeded
draws), the Pansart2022 benchmark is a FIXED, finite set of real graphs --
6 pair-counts x 3 altruistic-donor-counts x 5 replicates = 90 distinct real
P x P submatrices once chain-length L is ignored (irrelevant to our no-
chains model, so the `l3` variant is used arbitrarily among the three
identical-graph L-variants -- see SOURCE.txt). For a like-for-like
comparison against `scripts/kidney_size_sweep.py`'s synthetic curve, this
module additionally varies the SYNTHETIC ownership partition (many seeded
draws per real graph) to get more independent hospital-checks per real
graph than the raw file count alone would allow -- each such draw is a
legitimate new sample of "one declared synthetic partition of this same
real compatibility graph," never a new real graph.
"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from witness.errors import ModelError
from witness.generate import derive_seed
from witness.kidney import KidneyMarket, KidneyProfile
from witness.tiebreak import lottery_order

DEFAULT_ZIP = Path(__file__).resolve().parent.parent / "data" / "external" / "pansart2022_kep" / "Pansart2022.zip"

_INSTANCE_PREFIX = "Pansart2022/KEP_"

#: The 6 pair-counts this benchmark ships, and (per P) the smallest
#: altruistic-donor count available -- chosen deliberately (fewest rows
#: dropped is irrelevant to correctness, since dropped rows are dropped
#: regardless of count; smallest N is chosen only so `n_dropped` in the
#: metadata stays a small, clearly-inert number rather than a large one a
#: reader might mistake for mattering).
REAL_P_VALUES = (50, 100, 250, 500, 750, 1000)


def list_real_instances(zip_path: "Path | str" = DEFAULT_ZIP) -> "tuple[str, ...]":
    with zipfile.ZipFile(zip_path) as zf:
        return tuple(
            sorted(n for n in zf.namelist() if n.startswith(_INSTANCE_PREFIX) and n.endswith(".txt"))
        )


def _read_raw_instance(zip_path: "Path | str", member: str) -> "tuple[int, int, list[list[int]]]":
    """Direct, minimal re-parse of one instance file (P, N, and the full
    (N+P) x P matrix) -- deliberately NOT importing
    `data/external/pansart2022_kep/parsed.py` (see module docstring)."""
    with zipfile.ZipFile(zip_path) as zf:
        text = zf.read(member).decode("utf-8")
    lines = [ln for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("//")]
    p, n, _k, _l = (int(x) for x in lines[:4])
    matrix_lines = lines[4:]
    if len(matrix_lines) != n + p:
        raise ModelError(
            f"{member}: declared P={p} N={n} implies {n + p} matrix rows, found {len(matrix_lines)}"
        )
    matrix = [[int(x) for x in ln.strip().split("\t")] for ln in matrix_lines]
    for row in matrix:
        if len(row) != p:
            raise ModelError(f"{member}: a matrix row has {len(row)} columns, expected P={p}")
    return p, n, matrix


@dataclass(frozen=True)
class RealKidneyInstanceMeta:
    """Provenance record embedded alongside any market this module builds --
    the honesty label KIDNEY_EXCHANGE_SCOPE.md requires: which part is real,
    which part is a declared synthetic choice."""

    source_zip: str
    source_member: str
    declared_p: int
    n_altruistic_dropped: int
    n_hospitals: int
    ownership_seed: str
    ownership_draw_index: int
    note: str = (
        "compatibility graph is REAL (Pansart et al. 2022 published KEP benchmark); "
        "hospital ownership partition is SYNTHETIC (declared seeded round-robin over a "
        "lottery-shuffled pair order) -- never real hospital behavior"
    )

    def to_dict(self) -> dict:
        return {
            "source_zip": self.source_zip,
            "source_member": self.source_member,
            "declared_p": self.declared_p,
            "n_altruistic_dropped": self.n_altruistic_dropped,
            "n_hospitals": self.n_hospitals,
            "ownership_seed": self.ownership_seed,
            "ownership_draw_index": self.ownership_draw_index,
            "note": self.note,
        }


def load_real_kidney_market(
    member: str,
    n_hospitals: int,
    ownership_seed: str,
    ownership_draw_index: int = 0,
    *,
    zip_path: "Path | str" = DEFAULT_ZIP,
) -> "tuple[KidneyMarket, KidneyProfile, RealKidneyInstanceMeta]":
    """Build one (market, truthful profile) pair from a REAL instance file,
    with a declared synthetic hospital-ownership partition. `ownership_seed`
    + `ownership_draw_index` together determine the partition (same
    `derive_seed`/`lottery_order` construction every other generator in this
    codebase uses) -- so re-running with the same arguments reproduces the
    byte-identical market, and a different `ownership_draw_index` gives a
    genuinely different (still declared, still synthetic) partition of the
    SAME real compatibility graph.
    """
    p, n, matrix = _read_raw_instance(zip_path, member)
    submatrix = [row for row in matrix[n : n + p]]  # drop the N altruistic-donor rows entirely

    pairs = tuple(f"p{i}" for i in range(1, p + 1))
    edges = frozenset(
        (pairs[i], pairs[j])
        for i in range(p)
        for j in range(p)
        if i != j and submatrix[i][j] != -1
    )

    assign_seed = derive_seed(ownership_seed, ownership_draw_index, "kidney-real/ownership")
    shuffled = lottery_order(assign_seed, "assign", pairs)
    hospitals = tuple(f"h{i}" for i in range(1, n_hospitals + 1))
    hospital_of = {pair: hospitals[i % n_hospitals] for i, pair in enumerate(shuffled)}

    market = KidneyMarket(pairs=pairs, hospital_of=hospital_of, hospitals=hospitals, edges=edges)
    profile = KidneyProfile.truthful(market)
    meta = RealKidneyInstanceMeta(
        source_zip=str(zip_path),
        source_member=member,
        declared_p=p,
        n_altruistic_dropped=n,
        n_hospitals=n_hospitals,
        ownership_seed=ownership_seed,
        ownership_draw_index=ownership_draw_index,
    )
    return market, profile, meta


def real_instances_for_p(p: int, zip_path: "Path | str" = DEFAULT_ZIP) -> "tuple[str, ...]":
    """Every real instance member for a given pair-count `p` -- 3 altruistic-
    donor-count variants x 5 replicates = 15 distinct real graphs (the
    `l3` chain-length variant is used arbitrarily; irrelevant to this
    project's no-chains model -- see module docstring)."""
    all_members = list_real_instances(zip_path)
    prefix = f"{_INSTANCE_PREFIX}p{p}_"
    return tuple(m for m in all_members if m.startswith(prefix) and "_l3_" in m)
