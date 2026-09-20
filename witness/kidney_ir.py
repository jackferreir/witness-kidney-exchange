"""An individually-rational-for-hospitals variant of kidney-exchange central
clearing (`witness.kidney.clear_kidney_exchange`), built to answer the exact
question Prof. Utku Unver asked: does making central clearing IR remove the
profitable hospital-withholding deviations `witness.search_kidney` finds
under plain max-cardinality clearing, and what does IR cost in total
transplants? Imports from `witness.kidney` (`KidneyMarket`, `KidneyProfile`,
`candidate_cycles`, `IlpTimeLimitExceeded`) rather than editing it -- this is
a NEW mechanism, not a patch to the old one.

THE STANDALONE VALUE, `standalone(h)`: the number of `h`'s OWN pairs it
could transplant using ONLY its own owned pairs and cycles of length <= K,
i.e. h's outcome if it never joins the exchange at all. A pure function of
the market (never the profile) -- computed once per market, independent of
what anyone reports.

THE IR CONSTRAINT: among all disjoint cycle packings over the REPORTED pool
(central candidates: any feasible cycle among ALL reported pairs, spanning
hospitals freely; local candidates, per hospital: feasible cycles entirely
within that ONE hospital's own reported pairs), maximize total pairs matched
subject to, for every hospital h,

    (h's own pairs matched by the CENTRAL selection)
  + (h's own pairs matched by h's LOCAL selection, over its remaining
     reported pairs)
  >= standalone(h)

This is intentionally the mechanism's OWN view of h's recourse: it only ever
sees REPORTED pairs (a withheld pair is invisible to it), so the constraint
can only ever protect a hospital relative to what it chose to disclose. See
"WHY IR CAN BE INFEASIBLE" below for the direct consequence of that.

ONE JOINT CP-SAT MODEL, not a post-hoc repair: central cycle variables `y`
(over the full reported pool) and per-hospital local cycle variables `z_h`
(over `h`'s own reported pairs only) are solved TOGETHER in a single
`cp_model.CpModel`, sharing one set of at-most-one-per-pair constraints and
subject to every hospital's IR inequality simultaneously, so the central
selection is never chosen first and then checked -- it is chosen already
knowing which choices would strand some hospital below its own floor.
(The central/local variable split is not strictly required for the
achievable objective value -- a central candidate can already be a
within-one-hospital cycle -- but it is kept because it mirrors
`witness.kidney`'s own two-stage output shape, `KidneyResult.central_
selection` / `local_selections`, so results are directly comparable, and it
keeps each hospital's own IR bookkeeping legible per term.)

WHY IR CAN BE INFEASIBLE: under a TRUTHFUL report (report = every pair
`h` owns), the trivial packing "central touches nothing" always satisfies
every hospital's IR constraint exactly, because each hospital's local
recourse over its full reported set IS the standalone computation itself --
so IR is never infeasible on the truthful profile (an invariant this
module's tests check directly). But once a hospital WITHHOLDS pairs, its
reported residual is smaller than its true pair set, so its local recourse
term can no longer reach `standalone(h)` even with an empty central
selection -- the joint model can then be genuinely, provably infeasible
(CP-SAT returns INFEASIBLE, not merely "did not find a good enough
answer"). This is recorded explicitly (`IRClearingResult.ir_feasible =
False`, no selection produced) rather than silently relaxed or repaired --
see the module's own note in `ir_clear_kidney_exchange`'s docstring.

REALIZED OUTCOME VS. THE IR BOOKKEEPING TERM: the IR constraint's local term
is deliberately restricted to REPORTED pairs, because that's all the
mechanism can see. But what actually happens to a hospital's WITHHELD pairs
is a separate, real fact: exactly like `witness.kidney.clear_kidney_
exchange`'s own residual local stage, a withheld pair a hospital owns is
still available for that hospital to privately clear on its own afterward.
So `ir_clear_kidney_exchange` computes TWO local quantities and keeps them
distinct: `local_selections_reported` (the IR bookkeeping term, over
reported pairs only -- used to prove the constraint held) and
`local_selections` (the REALIZED, post-hoc local clearing over every pair
`h` truly owns that the central selection didn't touch -- used for
`utility`, the number this module's manipulation search actually compares).
This is exactly the gap the search in `scripts/kidney_ir_sweep.py` part (B)
measures: the IR constraint only ever reasons about reported information, so
a hospital that withholds pairs can still realize more than its IR-protected
floor once its private local recourse over the withheld pairs is counted --
if so, withholding remains profitable even under this constrained mechanism.

DETERMINISM: every CP-SAT solve here (the joint IR model, `standalone`, and
the final realized local-residual solves) fixes `num_search_workers=1` and
`random_seed=0` -- the same properties `witness.kidney._select_maximum_
cycles_ilp` already relies on and has verified empirically to be
process-independent. On top of that, EVERY objective here adds a declared
secondary tiebreak: candidates are already in `witness.kidney.candidate_
cycles`'s own canonical (sorted-by-member-index) order, and each objective
is `BIG * (total pairs matched) - (sum of each selected candidate's
canonical rank)`, with `BIG` chosen larger than the maximum possible tie
penalty -- so among all cardinality-maximizing (IR-respecting, where
applicable) selections, the lexicographically-smallest-by-canonical-rank one
is always the unique optimum CP-SAT returns, never left to depend on
whatever the single-threaded search happens to settle on first.

TIMEOUTS: `max_ilp_seconds`, like `KidneyConfig.max_ilp_seconds`, bounds
every CP-SAT solve here. A solve that cannot be proven optimal (or
infeasible) within budget raises `witness.kidney.IlpTimeLimitExceeded`
(imported, not redefined) -- never a heuristic, unproven answer.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional, Sequence

from witness.core import content_hash
from witness.errors import ModelError
from witness.kidney import (
    IlpTimeLimitExceeded,
    KidneyMarket,
    KidneyProfile,
    candidate_cycles,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent

#: Cycle lengths this module supports -- mirrors `witness.kidney._MAX_CYCLE_
#: LENGTHS` exactly (this module never invents its own notion of a cycle).
_MAX_CYCLE_LENGTHS = (2, 3)

_RESULT_PREFIX = "RESULT_JSON:"


def _check_max_cycle_length(max_cycle_length: int) -> None:
    if max_cycle_length not in _MAX_CYCLE_LENGTHS:
        raise ModelError(f"max_cycle_length must be one of {_MAX_CYCLE_LENGTHS}, got {max_cycle_length!r}")


def _canonical_sort(market: KidneyMarket, selection: Sequence[tuple]) -> "tuple[tuple[str, ...], ...]":
    return tuple(sorted((tuple(c) for c in selection), key=lambda c: tuple(market.index(p) for p in c)))


def _solve_max_cardinality(
    market: KidneyMarket,
    candidates: "tuple[tuple[str, ...], ...]",
    max_seconds: "Optional[float]" = None,
) -> "tuple[int, tuple[tuple[str, ...], ...]]":
    """One reusable exact CP-SAT solve: the maximum-cardinality vertex-
    disjoint selection among `candidates` (already canonically ordered by
    `candidate_cycles`), with the declared lexicographic-by-canonical-rank
    tiebreak described in the module docstring. Returns `(cardinality,
    selection)`. Used for `standalone(h)` and for the final realized local-
    residual stage -- every genuinely single-hospital max-cardinality
    sub-problem in this module goes through here, so they share one
    determinism argument."""
    from ortools.sat.python import cp_model

    if not candidates:
        return 0, ()

    model = cp_model.CpModel()
    n = len(candidates)
    x = [model.NewBoolVar(f"c{i}") for i in range(n)]

    by_pair: "dict[str, list[int]]" = {}
    for i, cyc in enumerate(candidates):
        for p in cyc:
            by_pair.setdefault(p, []).append(i)
    for p in sorted(by_pair):
        model.Add(sum(x[i] for i in by_pair[p]) <= 1)

    max_tie_penalty = n * (n - 1) // 2 + n  # safe (loose) upper bound on sum of selected ranks
    big = max_tie_penalty + 1
    cardinality_term = sum(len(candidates[i]) * x[i] for i in range(n))
    tie_penalty_term = sum(i * x[i] for i in range(n))
    model.Maximize(big * cardinality_term - tie_penalty_term)

    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 0
    if max_seconds is not None:
        solver.parameters.max_time_in_seconds = max_seconds
    status = solver.Solve(model)

    if status != cp_model.OPTIMAL:
        if max_seconds is not None and status in (cp_model.FEASIBLE, cp_model.UNKNOWN):
            raise IlpTimeLimitExceeded(
                f"_solve_max_cardinality: solver did not prove optimality within "
                f"max_seconds={max_seconds} (status={solver.StatusName(status)!r}) over {n} candidates"
            )
        raise ModelError(
            f"_solve_max_cardinality: solver did not prove optimality (status="
            f"{solver.StatusName(status)!r}) over {n} candidates"
        )

    selection = tuple(candidates[i] for i in range(n) if solver.Value(x[i]) == 1)
    return sum(len(c) for c in selection), _canonical_sort(market, selection)


def standalone(
    market: KidneyMarket,
    hospital: str,
    max_cycle_length: int = 2,
    max_seconds: "Optional[float]" = None,
) -> int:
    """`h`'s own outside option: the max cardinality (number of `h`'s own
    pairs matched) achievable using ONLY `h`'s own owned pairs (true
    ownership -- `market.pairs_of`, never any report) and cycles of length
    <= `max_cycle_length`. A pure function of the market, independent of any
    `KidneyProfile` -- see the module docstring."""
    _check_max_cycle_length(max_cycle_length)
    owned = market.pairs_of(hospital)
    candidates = candidate_cycles(market, owned, max_cycle_length)
    cardinality, _ = _solve_max_cardinality(market, candidates, max_seconds=max_seconds)
    return cardinality


def standalone_all(
    market: KidneyMarket,
    max_cycle_length: int = 2,
    max_seconds: "Optional[float]" = None,
) -> "dict[str, int]":
    """`standalone(h)` for every hospital in `market.hospitals`, computed
    once -- callers that evaluate many reports on the SAME market (e.g. the
    manipulation search below, which tries up to `2**k - 1` reports per
    hospital) should compute this once and reuse it, since it never depends
    on the profile."""
    _check_max_cycle_length(max_cycle_length)
    return {h: standalone(market, h, max_cycle_length, max_seconds=max_seconds) for h in market.hospitals}


def _solve_ir_joint_model(
    market: KidneyMarket,
    profile: KidneyProfile,
    max_cycle_length: int,
    standalone_values: Mapping[str, int],
    max_seconds: "Optional[float]" = None,
):
    """The one joint CP-SAT model described in the module docstring: central
    variables `y` over the full reported pool, local variables `z[h]` over
    each hospital's own reported pairs, one at-most-one-per-pair constraint
    spanning both, one IR inequality per hospital, and a single objective
    (declared tiebreak included). Returns `None` if CP-SAT proves the model
    INFEASIBLE (a real possibility -- see the module docstring's "WHY IR CAN
    BE INFEASIBLE"), or `(central_selection, local_selections_reported)` on
    an OPTIMAL solve. Raises `IlpTimeLimitExceeded` if the solver exhausts
    `max_seconds` without proving EITHER optimality or infeasibility --
    "too hard to tell within budget" is never silently treated as either
    outcome."""
    from ortools.sat.python import cp_model

    reported_pool = tuple(p for h in market.hospitals for p in profile.report(h))
    central_candidates = candidate_cycles(market, reported_pool, max_cycle_length)
    local_candidates = {
        h: candidate_cycles(market, profile.report(h), max_cycle_length) for h in market.hospitals
    }

    model = cp_model.CpModel()
    y = [model.NewBoolVar(f"y{i}") for i in range(len(central_candidates))]
    z = {
        h: [model.NewBoolVar(f"z_{h}_{j}") for j in range(len(local_candidates[h]))]
        for h in market.hospitals
    }

    by_pair_central: "dict[str, list[int]]" = {}
    for i, cyc in enumerate(central_candidates):
        for p in cyc:
            by_pair_central.setdefault(p, []).append(i)
    by_pair_local: "dict[str, list[tuple[str, int]]]" = {}
    for h in market.hospitals:
        for j, cyc in enumerate(local_candidates[h]):
            for p in cyc:
                by_pair_local.setdefault(p, []).append((h, j))

    for p in sorted(set(reported_pool), key=market.index):
        terms = [y[i] for i in by_pair_central.get(p, ())]
        terms += [z[h][j] for h, j in by_pair_local.get(p, ())]
        if terms:
            model.Add(sum(terms) <= 1)

    for h in market.hospitals:
        central_term = [
            sum(1 for p in cyc if market.hospital(p) == h) * y[i]
            for i, cyc in enumerate(central_candidates)
            if any(market.hospital(p) == h for p in cyc)
        ]
        local_term = [len(local_candidates[h][j]) * z[h][j] for j in range(len(local_candidates[h]))]
        lhs = sum(central_term) + sum(local_term)
        model.Add(lhs >= standalone_values[h])

    n_central = len(central_candidates)
    n_local_total = sum(len(v) for v in local_candidates.values())
    n_total = n_central + n_local_total
    max_tie_penalty = n_total * (n_total - 1) // 2 + n_total
    big = max_tie_penalty + 1

    cardinality_terms = [len(central_candidates[i]) * y[i] for i in range(n_central)]
    tie_terms = [i * y[i] for i in range(n_central)]
    rank = n_central
    for h in market.hospitals:
        for j in range(len(local_candidates[h])):
            cardinality_terms.append(len(local_candidates[h][j]) * z[h][j])
            tie_terms.append(rank * z[h][j])
            rank += 1
    model.Maximize(big * sum(cardinality_terms) - sum(tie_terms))

    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 0
    if max_seconds is not None:
        solver.parameters.max_time_in_seconds = max_seconds
    status = solver.Solve(model)

    if status == cp_model.INFEASIBLE:
        return None

    if status != cp_model.OPTIMAL:
        if max_seconds is not None and status in (cp_model.FEASIBLE, cp_model.UNKNOWN):
            raise IlpTimeLimitExceeded(
                f"_solve_ir_joint_model: solver did not prove optimality or infeasibility within "
                f"max_seconds={max_seconds} (status={solver.StatusName(status)!r}) over "
                f"{n_central} central + {n_local_total} local candidates"
            )
        raise ModelError(
            f"_solve_ir_joint_model: solver did not prove optimality (status="
            f"{solver.StatusName(status)!r}) over {n_central} central + {n_local_total} local candidates"
        )

    central_selection = _canonical_sort(
        market, [central_candidates[i] for i in range(n_central) if solver.Value(y[i]) == 1]
    )
    local_selections_reported = {
        h: _canonical_sort(
            market,
            [local_candidates[h][j] for j in range(len(local_candidates[h])) if solver.Value(z[h][j]) == 1],
        )
        for h in market.hospitals
    }
    return central_selection, local_selections_reported


@dataclass(frozen=True)
class IRClearingResult:
    """Full, replayable record of one `ir_clear_kidney_exchange` call.
    Mirrors `witness.kidney.KidneyResult`'s shape where the concepts
    coincide, plus the fields specific to IR (`ir_feasible`, `standalone`,
    `ir_utility`, and the reported-only `local_selections_reported` kept
    distinct from the REALIZED `local_selections` -- see the module
    docstring's "REALIZED OUTCOME VS. THE IR BOOKKEEPING TERM")."""

    max_cycle_length: int
    ir_feasible: bool
    standalone: Mapping[str, int]
    central_selection: "tuple[tuple[str, ...], ...]"
    local_selections_reported: Mapping[str, "tuple[tuple[str, ...], ...]"]
    local_selections: Mapping[str, "tuple[tuple[str, ...], ...]"]
    matched_pairs: frozenset
    ir_utility: Mapping[str, int]
    utility: Mapping[str, int]

    def to_dict(self) -> dict:
        return {
            "max_cycle_length": self.max_cycle_length,
            "ir_feasible": self.ir_feasible,
            "standalone": dict(sorted(self.standalone.items())),
            "central_selection": [list(c) for c in self.central_selection],
            "local_selections_reported": {
                h: [list(c) for c in sel] for h, sel in sorted(self.local_selections_reported.items())
            },
            "local_selections": {h: [list(c) for c in sel] for h, sel in sorted(self.local_selections.items())},
            "matched_pairs": sorted(self.matched_pairs),
            "ir_utility": dict(sorted(self.ir_utility.items())),
            "utility": dict(sorted(self.utility.items())),
        }

    def format_trace(self) -> str:
        lines = [f"ir_feasible: {self.ir_feasible}", f"standalone: {dict(sorted(self.standalone.items()))}"]
        lines.append(f"central: {list(self.central_selection)}")
        for h, sel in sorted(self.local_selections_reported.items()):
            lines.append(f"  local_reported[{h}]: {list(sel)}")
        for h, sel in sorted(self.local_selections.items()):
            lines.append(f"  local_realized[{h}]: {list(sel)}")
        lines.append(f"ir_utility: {dict(sorted(self.ir_utility.items()))}")
        lines.append(f"utility: {dict(sorted(self.utility.items()))}")
        return "\n".join(lines)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, IRClearingResult):
            return NotImplemented
        return self.to_dict() == other.to_dict()


def ir_clear_kidney_exchange(
    market: KidneyMarket,
    profile: KidneyProfile,
    max_cycle_length: int = 2,
    max_ilp_seconds: "Optional[float]" = None,
    standalone_values: "Optional[Mapping[str, int]]" = None,
) -> IRClearingResult:
    """Run the IR-constrained mechanism described in the module docstring.
    `standalone_values`, if given, MUST equal `standalone_all(market,
    max_cycle_length)` -- passed in purely as a cache for callers evaluating
    many reports on the same market (`standalone` never depends on the
    profile); if omitted it is computed fresh here. When the joint model is
    infeasible (a real, recordable outcome -- see the module docstring),
    every selection/utility field is left empty and `ir_feasible=False`;
    callers must check that flag before reading anything else, never treat
    an empty result as "zero matched"."""
    _check_max_cycle_length(max_cycle_length)
    profile.validate_against(market)

    if standalone_values is None:
        standalone_values = standalone_all(market, max_cycle_length, max_seconds=max_ilp_seconds)
    else:
        missing = set(market.hospitals) - set(standalone_values)
        if missing:
            raise ModelError(f"standalone_values missing hospital(s) {sorted(missing)}")

    solved = _solve_ir_joint_model(market, profile, max_cycle_length, standalone_values, max_seconds=max_ilp_seconds)
    if solved is None:
        return IRClearingResult(
            max_cycle_length=max_cycle_length,
            ir_feasible=False,
            standalone=dict(standalone_values),
            central_selection=(),
            local_selections_reported={},
            local_selections={},
            matched_pairs=frozenset(),
            ir_utility={},
            utility={},
        )

    central_selection, local_selections_reported = solved

    ir_utility = {}
    for h in market.hospitals:
        central_own = sum(1 for c in central_selection for p in c if market.hospital(p) == h)
        local_own = sum(len(c) for c in local_selections_reported[h])
        ir_utility[h] = central_own + local_own
        if ir_utility[h] < standalone_values[h]:  # pragma: no cover - defense-in-depth, CP-SAT already enforced this
            raise ModelError(
                f"IR constraint violated for hospital {h!r} despite a claimed OPTIMAL solve: "
                f"ir_utility={ir_utility[h]} < standalone={standalone_values[h]}"
            )

    matched_centrally: set = set()
    for c in central_selection:
        matched_centrally.update(c)

    local_selections: "dict[str, tuple]" = {}
    matched: set = set(matched_centrally)
    for h in market.hospitals:
        residual = tuple(p for p in market.pairs_of(h) if p not in matched_centrally)
        residual_candidates = candidate_cycles(market, residual, max_cycle_length)
        _, sel = _solve_max_cardinality(market, residual_candidates, max_seconds=max_ilp_seconds)
        local_selections[h] = sel
        for c in sel:
            matched.update(c)

    utility = {h: sum(1 for p in market.pairs_of(h) if p in matched) for h in market.hospitals}

    return IRClearingResult(
        max_cycle_length=max_cycle_length,
        ir_feasible=True,
        standalone=dict(standalone_values),
        central_selection=central_selection,
        local_selections_reported=local_selections_reported,
        local_selections=local_selections,
        matched_pairs=frozenset(matched),
        ir_utility=ir_utility,
        utility=utility,
    )


# ---------------------------------------------------------------------------
# Manipulation search: does the IR constraint remove profitable withholding?
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class IRKidneyWitness:
    """A single confirmed hospital-withholding manipulation AGAINST the
    IR-constrained mechanism -- the `witness.search_kidney.KidneyWitness`
    analogue for `ir_clear_kidney_exchange`. `find_hospital_manipulation_ir`
    below is this module's OWN exhaustive search (reusing only the pure,
    profile-independent `witness.search_kidney.hospital_misreport_space`
    helper, never `witness.search_kidney.find_hospital_manipulation` itself,
    which is hardwired to plain `clear_kidney_exchange`)."""

    witness_version: int
    mechanism: str
    max_cycle_length: int
    market: Mapping
    truthful_profile: Mapping
    target_hospital: str
    truthful_report: "tuple[str, ...]"
    false_report: "tuple[str, ...]"
    truthful_result: Mapping
    false_result: Mapping
    truthful_utility: int
    false_utility: int
    preference_proof: str
    witness_id: str

    def to_dict(self) -> dict:
        return {
            "witness_version": self.witness_version,
            "mechanism": self.mechanism,
            "max_cycle_length": self.max_cycle_length,
            "market": dict(self.market),
            "truthful_profile": dict(self.truthful_profile),
            "target_hospital": self.target_hospital,
            "truthful_report": list(self.truthful_report),
            "false_report": list(self.false_report),
            "truthful_result": dict(self.truthful_result),
            "false_result": dict(self.false_result),
            "truthful_utility": self.truthful_utility,
            "false_utility": self.false_utility,
            "preference_proof": self.preference_proof,
            "witness_id": self.witness_id,
        }

    @staticmethod
    def from_dict(d: Mapping) -> "IRKidneyWitness":
        return IRKidneyWitness(
            witness_version=d["witness_version"],
            mechanism=d["mechanism"],
            max_cycle_length=d["max_cycle_length"],
            market=dict(d["market"]),
            truthful_profile=dict(d["truthful_profile"]),
            target_hospital=d["target_hospital"],
            truthful_report=tuple(d["truthful_report"]),
            false_report=tuple(d["false_report"]),
            truthful_result=dict(d["truthful_result"]),
            false_result=dict(d["false_result"]),
            truthful_utility=d["truthful_utility"],
            false_utility=d["false_utility"],
            preference_proof=d["preference_proof"],
            witness_id=d["witness_id"],
        )


def _build_ir_witness(
    *, market, truthful_profile, hospital, max_cycle_length, truthful_report, false_report,
    truthful_result, false_result, truthful_utility, false_utility,
) -> IRKidneyWitness:
    proof = (
        f"[IR-constrained clearing] hospital {hospital!r}'s truthful report is "
        f"{list(truthful_report)!r} (all its own pairs): under the IR-constrained full-revelation "
        f"run its REALIZED utility is {truthful_utility}, but reporting only {list(false_report)!r} "
        f"instead raises its REALIZED utility to {false_utility} -- strictly better for "
        f"{hospital!r}, judged solely by its own recipient count, even though every IR constraint "
        f"held (or was recorded infeasible) in both runs."
    )
    base = {
        "witness_version": 1,
        "mechanism": "kidney_ir",
        "max_cycle_length": max_cycle_length,
        "market": market.to_dict(),
        "truthful_profile": truthful_profile.to_dict(),
        "target_hospital": hospital,
        "truthful_report": list(truthful_report),
        "false_report": list(false_report),
        "truthful_result": truthful_result.to_dict(),
        "false_result": false_result.to_dict(),
        "truthful_utility": truthful_utility,
        "false_utility": false_utility,
        "preference_proof": proof,
    }
    witness_id = content_hash(base)
    full = dict(base)
    full["witness_id"] = witness_id
    return IRKidneyWitness.from_dict(full)


@dataclass(frozen=True)
class IRSearchStats:
    """Bookkeeping `find_hospital_manipulation_ir` returns alongside its
    witness (or `None`): how many of the candidate false reports it tried
    hit an IR-infeasible mechanism (recorded, not silently skipped-as-
    negative) versus were comparable."""

    n_reports_tried: int
    n_infeasible: int
    truthful_ir_feasible: bool


def find_hospital_manipulation_ir(
    market: KidneyMarket,
    truthful_profile: KidneyProfile,
    hospital: str,
    max_cycle_length: int = 2,
    max_ilp_seconds: "Optional[float]" = None,
    max_space: "Optional[int]" = None,
    standalone_values: "Optional[Mapping[str, int]]" = None,
) -> "tuple[Optional[IRKidneyWitness], IRSearchStats]":
    """The IR-mechanism analogue of `witness.search_kidney.find_hospital_
    manipulation`: the first report in canonical enumeration order (reusing
    `witness.search_kidney.hospital_misreport_space`, a pure function of the
    market/report, never touching `find_hospital_manipulation` itself) under
    which `hospital`'s REALIZED utility (`IRClearingResult.utility`, which
    already accounts for privately clearing withheld pairs locally -- see
    the module docstring) strictly exceeds its truthful REALIZED utility.

    A false report under which the IR-constrained mechanism is itself
    infeasible is NOT counted as a manipulation (there is no well-defined
    utility to compare) but IS counted in the returned `IRSearchStats.
    n_infeasible` -- per the module's "record, don't silently relax"
    discipline. The truthful profile's own IR-feasibility is always checked
    and reported (`IRSearchStats.truthful_ir_feasible`); per the module
    docstring this should always be `True`, so a `False` here would itself
    be a finding worth investigating, not just a skip."""
    from witness.search_kidney import hospital_misreport_space  # pure helper only, see module docstring

    _check_max_cycle_length(max_cycle_length)
    truthful_profile.validate_against(market)
    truthful_report = truthful_profile.report(hospital)

    if standalone_values is None:
        standalone_values = standalone_all(market, max_cycle_length, max_seconds=max_ilp_seconds)

    kwargs = {} if max_space is None else {"max_space": max_space}
    truthful_result = ir_clear_kidney_exchange(
        market, truthful_profile, max_cycle_length, max_ilp_seconds, standalone_values,
    )
    truthful_ir_feasible = truthful_result.ir_feasible
    truthful_utility = truthful_result.utility.get(hospital, 0) if truthful_ir_feasible else 0

    n_tried = 0
    n_infeasible = 0
    for false_report in hospital_misreport_space(market, hospital, truthful_report, **kwargs):
        n_tried += 1
        misreport_profile = truthful_profile.with_report(hospital, false_report)
        for h, report in truthful_profile.reports.items():
            if h == hospital:
                continue
            assert misreport_profile.reports.get(h) == report, (
                f"misreport for hospital {hospital!r} perturbed hospital {h!r}'s report"
            )

        false_result = ir_clear_kidney_exchange(
            market, misreport_profile, max_cycle_length, max_ilp_seconds, standalone_values,
        )
        if not false_result.ir_feasible:
            n_infeasible += 1
            continue

        false_utility = false_result.utility[hospital]
        if truthful_ir_feasible and false_utility > truthful_utility:
            witness = _build_ir_witness(
                market=market, truthful_profile=truthful_profile, hospital=hospital,
                max_cycle_length=max_cycle_length, truthful_report=truthful_report, false_report=false_report,
                truthful_result=truthful_result, false_result=false_result,
                truthful_utility=truthful_utility, false_utility=false_utility,
            )
            return witness, IRSearchStats(
                n_reports_tried=n_tried, n_infeasible=n_infeasible, truthful_ir_feasible=truthful_ir_feasible,
            )

    return None, IRSearchStats(
        n_reports_tried=n_tried, n_infeasible=n_infeasible, truthful_ir_feasible=truthful_ir_feasible,
    )


# ---------------------------------------------------------------------------
# Independent, fresh-subprocess replay -- REVIEWER.md: "Every finding
# replays from its saved witness alone, in a fresh subprocess."
# ---------------------------------------------------------------------------


def rebuild(d: Mapping) -> "tuple[KidneyMarket, KidneyProfile, int]":
    market = KidneyMarket.from_dict(d["market"])
    profile = KidneyProfile.from_dict(d["truthful_profile"])
    return market, profile, d["max_cycle_length"]


def verify_ir_witness(d: Mapping) -> "tuple[bool, tuple[str, ...]]":
    """Rebuilds market/truthful profile PURELY from the witness dict's own
    fields, re-runs `ir_clear_kidney_exchange` from scratch on both the
    truthful and false reports, and checks every recorded field is
    reproduced exactly, plus the strict-utility-improvement claim itself and
    that both runs are genuinely IR-feasible (a witness built over an
    infeasible run would be a bug, never a valid finding)."""
    reasons: "list[str]" = []

    if d.get("witness_version") != 1:
        reasons.append(f"witness_version: expected 1, got {d.get('witness_version')!r}")
    if d.get("mechanism") != "kidney_ir":
        reasons.append(f"mechanism: expected 'kidney_ir', got {d.get('mechanism')!r}")

    without_id = {k: v for k, v in d.items() if k != "witness_id"}
    expected_id = content_hash(without_id)
    actual_id = d.get("witness_id")
    if actual_id != expected_id:
        reasons.append(f"witness_id {actual_id!r} does not match content_hash (expected {expected_id!r})")

    market = profile = None
    max_cycle_length = None
    try:
        market, profile, max_cycle_length = rebuild(d)
    except Exception as exc:  # noqa: BLE001
        reasons.append(f"could not rebuild market/truthful profile from the witness dict alone: {exc!r}")
        return (False, tuple(reasons))

    hospital = d.get("target_hospital")
    truthful_report_claimed = d.get("truthful_report")
    actual_truthful_report = list(profile.report(hospital))
    if actual_truthful_report != truthful_report_claimed:
        reasons.append(
            f"truthful profile's report for {hospital!r} is {actual_truthful_report!r}, disagreeing "
            f"with truthful_report {truthful_report_claimed!r}"
        )

    standalone_values = standalone_all(market, max_cycle_length)

    truthful_result = ir_clear_kidney_exchange(market, profile, max_cycle_length, None, standalone_values)
    if not truthful_result.ir_feasible:
        reasons.append("re-running the truthful profile is IR-infeasible on replay (should never happen)")
    got_truthful = truthful_result.to_dict()
    expected_truthful = d.get("truthful_result")
    if got_truthful != expected_truthful:
        reasons.append(
            f"re-running the truthful profile does not reproduce truthful_result exactly: "
            f"got {got_truthful!r}, expected {expected_truthful!r}"
        )
    if truthful_result.ir_feasible and truthful_result.utility.get(hospital) != d.get("truthful_utility"):
        reasons.append(
            f"recomputed truthful utility {truthful_result.utility.get(hospital)!r} disagrees with "
            f"recorded truthful_utility {d.get('truthful_utility')!r}"
        )

    false_report = d.get("false_report")
    misreport_profile = profile.with_report(hospital, false_report)
    false_result = ir_clear_kidney_exchange(market, misreport_profile, max_cycle_length, None, standalone_values)
    if not false_result.ir_feasible:
        reasons.append("re-running the false report is IR-infeasible on replay -- not a valid witness")
    else:
        got_false = false_result.to_dict()
        expected_false = d.get("false_result")
        if got_false != expected_false:
            reasons.append(
                f"re-running the false report does not reproduce false_result exactly: "
                f"got {got_false!r}, expected {expected_false!r}"
            )
        if false_result.utility.get(hospital) != d.get("false_utility"):
            reasons.append(
                f"recomputed false utility {false_result.utility.get(hospital)!r} disagrees with "
                f"recorded false_utility {d.get('false_utility')!r}"
            )

    truthful_utility = d.get("truthful_utility")
    false_utility = d.get("false_utility")
    if not (isinstance(truthful_utility, int) and isinstance(false_utility, int) and false_utility > truthful_utility):
        reasons.append(
            f"recorded utilities do not show strict improvement: truthful={truthful_utility!r}, "
            f"false={false_utility!r}"
        )

    return (len(reasons) == 0, tuple(reasons))


def _verify_main() -> None:
    """Entry point for the fresh-subprocess runner below -- reads a witness
    dict as JSON on stdin, prints `RESULT_JSON:<...>` on stdout. Mirrors
    `witness.replay_kidney`'s own subprocess pattern exactly."""
    d = json.loads(sys.stdin.read())
    ok, reasons = verify_ir_witness(d)
    print(_RESULT_PREFIX + json.dumps({"ok": ok, "reasons": list(reasons)}))


def verify_in_subprocess(witness_dict: Mapping, timeout: float = 120.0) -> "tuple[bool, tuple[str, ...]]":
    """Runs `verify_ir_witness` in a genuinely fresh Python subprocess --
    REVIEWER.md: "Every finding replays from its saved witness alone, in a
    fresh subprocess. Not the same interpreter." Mirrors `witness.replay_
    kidney.verify_in_subprocess` exactly."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(witness_dict, f)
        input_path = f.name
    try:
        proc = subprocess.run(
            [sys.executable, "-c", "import witness.kidney_ir as m; m._verify_main()"],
            stdin=open(input_path, "r", encoding="utf-8"),
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(PROJECT_ROOT),
        )
    finally:
        Path(input_path).unlink(missing_ok=True)

    for line in proc.stdout.splitlines():
        if line.startswith(_RESULT_PREFIX):
            payload = json.loads(line[len(_RESULT_PREFIX):])
            return payload["ok"], tuple(payload["reasons"])
    return (False, (f"subprocess produced no RESULT_JSON line; stdout={proc.stdout!r} stderr={proc.stderr!r}",))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="ad hoc verify a single kidney_ir witness JSON file")
    p.add_argument("witness_path")
    args = p.parse_args()
    with open(args.witness_path, "r", encoding="utf-8") as fh:
        wd = json.load(fh)
    ok_, reasons_ = verify_in_subprocess(wd)
    print(json.dumps({"ok": ok_, "reasons": list(reasons_)}, indent=2))
