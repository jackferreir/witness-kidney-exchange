"""Seeded synthetic-instance generator for the couples mechanism
(`witness.couples`), for Deliverables A and B only (sequencing sensitivity
and non-existence frequency as a function of couples participation rate).

Reuses `witness.generate`'s own randomness primitives verbatim
(`derive_seed`, `witness.tiebreak.lottery_key` / `lottery_order`) rather than
inventing a new convention -- every draw here reduces to the same SHA-256
construction, scoped by a `purpose` string, so instances are byte-identical
across processes/machines exactly as `witness.generate`'s own module
docstring requires.

WHAT THIS GENERATOR DOES NOT CLAIM
    It is a small, declared, synthetic generator built to produce a
    measurable SWEEP over one parameter (couples participation rate) --
    it is NOT a calibrated model of real NRMP rank-order-list behavior, and
    Deliverable A's headline numbers should be read as "what this
    generator's synthetic markets show," not as a reproduction of Roth &
    Peranson's own 1993-1995 NRMP-data sequencing experiments (this project
    has no access to that data). Where a real, sourced NRMP figure IS used
    (the couples participation rate itself), the source is named at the
    call site, per REVIEWER.md's literature-check rule.

COUPLES PARTICIPATION RATE -- VERIFIED FIGURES (not assumed)
    Roth & Peranson (1999) Table 1A (`data/external/roth_peranson_1999/
    rothperansonaer.pdf`, verified via `pdftotext -layout`): coupled
    INDIVIDUAL applicants / active (primary-ROL) applicants, 1987/1993/
    1994/1995/1996 respectively: 694/20,071 = 3.46%, 854/20,916 = 4.08%,
    892/22,353 = 3.99%, 998/22,937 = 4.35%, 1,008/24,749 = 4.07%. So the
    paper's own era sits at roughly 3.5-4.3% of active applicants coupled.

    NRMP "Results and Data 2024 Main Residency Match" (fetched directly
    from nrmp.org, page text extracted with pdftotext): "In the 2024 Match,
    there were 1,218 couples... 2,436 individual applicants participated in
    the Match as a couple" against 44,853 active applicants that year --
    2,436 / 44,853 = 5.43%.

    So the VERIFIED range this module's sweep is calibrated against is
    roughly 3.5% (1987) to 5.4% (2024) of active applicants being part of a
    couple. `COUPLES_RATE_SWEEP` below extends past 5.4% up toward 20-30%
    purely as a labeled STRESS regime -- there is no source claiming NRMP
    couples participation is anywhere near that high; it is included only
    to see whether Deliverables A/B's trends continue, and is reported as
    such, not attributed to NRMP.

MODEL (declared, minimal, not a claim about real preference structure)
    `n_individuals` total; a `couples_rate` fraction of them are paired into
    couples (2 members per couple; an odd leftover count is rounded down so
    every couple has exactly 2 members, and the reduction is deterministic).
    Programs are `c1..cM`; capacities are apportioned so total seats equal
    `n_individuals` (an "exact subscription" regime, deliberately the
    highest-contention one per `witness.generate`'s own documented
    findings). Each program's priority order is an INDEPENDENT lottery over
    all individuals (mirrors `TIEBREAK_MTB`, chosen because a single shared
    lottery degenerates every mechanism in this codebase toward serial
    dictatorship -- see `witness.ttc.distinct_priority_orders`'s own
    docstring for why that is never a meaningful sweep). A single's report
    is a complete personal lottery permutation of the programs. A couple's
    joint ROL is built from two INDEPENDENT personal lottery permutations
    (one per member) zipped position-by-position into pairs -- i.e. the
    couple's k-th choice pairs each member's own k-th-favorite program. This
    is a simplification (real couples' preferences over PAIRS need not
    follow either member's individual order), declared here rather than
    presented as behaviorally realistic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from witness.core import Market
from witness.couples import Couple, CouplesProfile
from witness.errors import ModelError
from witness.generate import GENERATE_DOMAIN, _apportion, derive_seed
from witness.tiebreak import lottery_order

#: Verified from Roth & Peranson (1999) Table 1A -- see module docstring.
COUPLES_RATE_1990S_RANGE = (0.0346, 0.0435)

#: Verified from NRMP's 2024 Results and Data report -- see module docstring.
COUPLES_RATE_2024 = 0.0543

#: A sweep spanning the verified range and a labeled stress extrapolation.
#: Values above ~0.06 are NOT attributed to any NRMP source -- see the
#: module docstring's WHAT THIS GENERATOR DOES NOT CLAIM.
COUPLES_RATE_SWEEP: "tuple[float, ...]" = (
    0.0, 0.035, 0.0543, 0.08, 0.12, 0.20, 0.30,
)


@dataclass(frozen=True)
class CouplesGeneratorConfig:
    """Parameters of one synthetic-market draw. `seed` + `index` together
    determine everything, exactly like `witness.generate.GeneratorConfig`.
    """

    n_individuals: int
    n_schools: int
    couples_rate: float
    seed: str = "witness-couples"

    #: How many schools each single (and each half of each couple's joint
    #: pairs) actually ranks, out of `n_schools`. `None` (the default) means
    #: a COMPLETE list -- every school ranked. Real applicants rank far
    #: fewer programs than exist in the whole market; a complete-list
    #: synthetic market is a much DENSER, more contested regime than a real
    #: one, and this project's own generator docs (`witness/generate.py`,
    #: `witness/ttc.py`) repeatedly find that list-length shape changes
    #: measured rates substantially -- so it is a first-class, reported
    #: parameter here too, not left at its (unrealistic) complete default
    #: for every sweep.
    list_length: "int | None" = None

    def __post_init__(self) -> None:
        if (
            isinstance(self.n_individuals, bool)
            or not isinstance(self.n_individuals, int)
            or self.n_individuals < 2
        ):
            raise ModelError(f"n_individuals must be an int >= 2, got {self.n_individuals!r}")
        if isinstance(self.n_schools, bool) or not isinstance(self.n_schools, int) or self.n_schools < 1:
            raise ModelError(f"n_schools must be a positive int, got {self.n_schools!r}")
        if isinstance(self.couples_rate, bool) or not isinstance(self.couples_rate, (int, float)):
            raise ModelError(f"couples_rate must be a number, got {self.couples_rate!r}")
        if not (0.0 <= self.couples_rate <= 1.0):
            raise ModelError(f"couples_rate must be in [0.0, 1.0], got {self.couples_rate!r}")
        if not isinstance(self.seed, str) or not self.seed:
            raise ModelError(f"seed must be a non-empty string, got {self.seed!r}")
        if self.list_length is not None:
            if (
                isinstance(self.list_length, bool)
                or not isinstance(self.list_length, int)
                or not (1 <= self.list_length <= self.n_schools)
            ):
                raise ModelError(
                    f"list_length must be None or an int in [1, n_schools={self.n_schools}], "
                    f"got {self.list_length!r}"
                )


def _couples_derive_seed(gc: CouplesGeneratorConfig, index: int, purpose: str) -> str:
    """Identical construction to `witness.generate.derive_seed`, called
    through that function directly (same domain string) so this module's
    seeds live in the exact same derivation space, just scoped by a
    couples-specific `purpose` string that never collides with
    `witness.generate`'s own purposes for the same (seed, index)."""
    return derive_seed(gc.seed, index, f"couples/{purpose}")


def generate_couples_instance(
    gc: CouplesGeneratorConfig, index: int
) -> "tuple[Market, CouplesProfile]":
    """Build the `index`-th synthetic (market, profile) pair of `gc`.

    Individuals are `s1..sN`, schools `c1..cM`, both in that declared order.
    `round(gc.couples_rate * n_individuals)` individuals are selected (via
    `lottery_order`, never `random`) to be paired into couples; the count is
    rounded DOWN to the nearest even number so every couple has exactly two
    members. The remaining individuals are singles.
    """
    n = gc.n_individuals
    individuals = tuple(f"s{i}" for i in range(1, n + 1))
    schools = tuple(f"c{i}" for i in range(1, gc.n_schools + 1))

    assign_seed = _couples_derive_seed(gc, index, "assign")
    order = lottery_order(assign_seed, "assign", individuals)
    n_paired = int(round(gc.couples_rate * n))
    n_paired -= n_paired % 2  # exactly two members per couple
    n_paired = max(0, min(n, n_paired))
    paired = order[:n_paired]
    single_ids = order[n_paired:]

    length = gc.list_length if gc.list_length is not None else gc.n_schools

    pref_seed = _couples_derive_seed(gc, index, "joint-pref")
    couples = []
    for i in range(0, len(paired), 2):
        a, b = paired[i], paired[i + 1]
        order_a = lottery_order(pref_seed, f"{a}", schools)[:length]
        order_b = lottery_order(pref_seed, f"{b}", schools)[:length]
        joint = tuple(zip(order_a, order_b))
        couples.append(Couple(members=(a, b), joint_rankings=joint))

    # Uniform apportionment needs no randomness (equal weights); seats sum
    # to exactly `n` individuals -- the highest-contention "exact
    # subscription" regime, per `witness.generate`'s own documented
    # rationale for why that regime is the one worth measuring.
    caps = _apportion(n, tuple(1 for _ in schools))
    capacities = {c: caps[i] for i, c in enumerate(schools)}

    pri_seed = _couples_derive_seed(gc, index, "priority")
    priority_classes = {
        c: tuple((x,) for x in lottery_order(pri_seed, c, individuals)) for c in schools
    }

    market = Market(
        students=individuals,
        schools=schools,
        capacities=capacities,
        priority_classes=priority_classes,
    )

    report_seed = _couples_derive_seed(gc, index, "report")
    singles_reports = {s: lottery_order(report_seed, s, schools)[:length] for s in single_ids}

    profile = CouplesProfile(singles=singles_reports, couples=tuple(couples))
    return market, profile
