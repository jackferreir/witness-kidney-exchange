"""Validation gate for `witness.kidney_ir` -- must pass before any
`scripts/kidney_ir_sweep.py` run is trusted. Four checks, per the assignment
that spawned this module:

  1. `IrJointModelAgreesWithIndependentBruteForce` -- on 100+ small random
     markets (4-8 pairs, 1-3 hospitals, K in {2,3}, BOTH truthful and
     withheld-report profiles), an INDEPENDENT itertools brute force (this
     file's own code, sharing nothing with `witness.kidney_ir`) confirms:
     the IR joint model's selection satisfies every hospital's IR
     constraint; its total cardinality over the reported pool equals the
     true max among IR-feasible packings; and IR-feasibility/infeasibility
     matches the brute force exactly.
  2. `CrossCheckedAgainstOraclesKidney` -- every selection `witness.kidney_ir`
     returns (central, reported-only local, and the realized post-central
     local residual) is independently re-validated as a genuine disjoint
     cycle packing by `witness.oracles_kidney.is_valid_selection` -- the
     same general-purpose checker the base mechanism's own tests use.
  3. `NonVacuityIrStrictlyBinds` -- a HAND-BUILT instance (traced by hand
     before running any code -- see the comment on `_kid3b_market`) where
     the unconstrained max-cardinality optimum VIOLATES hospital HA's IR
     (utility 1 < standalone 2) and the IR-constrained optimum is STRICTLY
     smaller (2 matched pairs, not 3) -- proving the constraint actually
     costs something, not vacuously always agreeing with the unconstrained
     optimum.
  4. `Deterministic` -- the identical market/profile produces the identical
     `IRClearingResult` across repeated in-process solves AND across a
     genuinely fresh subprocess.
"""

from __future__ import annotations

import random
import subprocess
import sys
import unittest
from itertools import combinations

from witness.kidney import (
    KidneyConfig,
    KidneyMarket,
    KidneyProfile,
    TIEBREAK_LEX_SMALLEST_BY_INDEX,
    clear_kidney_exchange,
)
from witness.kidney_ir import (
    find_hospital_manipulation_ir,
    ir_clear_kidney_exchange,
    standalone,
    standalone_all,
)
from witness.oracles_kidney import is_valid_selection
from witness.search_kidney import find_hospital_manipulation

PROJECT_ROOT_IMPORT = "import sys, os; sys.path.insert(0, os.getcwd())\n"


# ---------------------------------------------------------------------------
# Independent brute force -- shares NO code with witness/kidney_ir.py.
# ---------------------------------------------------------------------------


def _independent_true_cycles(market: KidneyMarket, pool, max_cycle_length: int):
    pool = tuple(pool)
    cycles = []
    for u, v in combinations(pool, 2):
        if market.has_edge(u, v) and market.has_edge(v, u):
            cycles.append((u, v))
    if max_cycle_length >= 3:
        for a, b, c in combinations(pool, 3):
            if market.has_edge(a, b) and market.has_edge(b, c) and market.has_edge(c, a):
                cycles.append((a, b, c))
            if market.has_edge(a, c) and market.has_edge(c, b) and market.has_edge(b, a):
                cycles.append((a, c, b))
    return cycles


def _independent_all_disjoint_packings(market: KidneyMarket, pool, max_cycle_length: int):
    """Every vertex-disjoint subset of true cycles within `pool` -- a fresh,
    from-scratch exhaustive enumeration (not calling `witness.kidney._feasible_
    selections` or anything in `witness.kidney_ir`)."""
    cycles = _independent_true_cycles(market, pool, max_cycle_length)
    n = len(cycles)
    packings = []
    for r in range(n, -1, -1):
        for combo in combinations(range(n), r):
            used: set = set()
            ok = True
            for i in combo:
                cyc = cycles[i]
                if any(p in used for p in cyc):
                    ok = False
                    break
                used.update(cyc)
            if ok:
                packings.append(tuple(cycles[i] for i in combo))
    return packings


def _independent_standalone(market: KidneyMarket, hospital: str, max_cycle_length: int) -> int:
    owned = market.pairs_of(hospital)
    packings = _independent_all_disjoint_packings(market, owned, max_cycle_length)
    return max((sum(len(c) for c in pk) for pk in packings), default=0)


def _independent_ir_analysis(market: KidneyMarket, profile: KidneyProfile, max_cycle_length: int):
    """Ground truth for `ir_clear_kidney_exchange`'s REPORTED-POOL bookkeeping:
    enumerate every disjoint packing over the ENTIRE reported pool (a packing
    here plays the role of "central selection plus every hospital's local-
    over-reported-residual selection combined" -- a single packing, since
    (as `witness/kidney_ir.py`'s own module docstring argues) that achievable
    region is identical to the two-stage central+local one: any within-one-
    hospital cycle is already a legal 'central' candidate too). Returns
    `(ir_feasible, best_ir_cardinality)`."""
    reported_pool = tuple(p for h in market.hospitals for p in profile.report(h))
    standalone_vals = {h: _independent_standalone(market, h, max_cycle_length) for h in market.hospitals}
    packings = _independent_all_disjoint_packings(market, reported_pool, max_cycle_length)

    best = None
    for pk in packings:
        matched = set()
        for c in pk:
            matched.update(c)
        util = {h: sum(1 for p in matched if market.hospital(p) == h) for h in market.hospitals}
        if all(util[h] >= standalone_vals[h] for h in market.hospitals):
            total = sum(len(c) for c in pk)
            if best is None or total > best:
                best = total
    return (best is not None), best, standalone_vals


def _random_market(seed: int, n_pairs: int, n_hospitals: int, edge_prob: float) -> KidneyMarket:
    rng = random.Random(seed)
    pairs = tuple(f"p{i}" for i in range(1, n_pairs + 1))
    hospitals = tuple(f"h{i}" for i in range(1, n_hospitals + 1))
    hospital_of = {p: hospitals[i % n_hospitals] for i, p in enumerate(pairs)}
    edges = set()
    for u in pairs:
        for v in pairs:
            if u != v and rng.random() < edge_prob:
                edges.add((u, v))
    return KidneyMarket(pairs=pairs, hospital_of=hospital_of, hospitals=hospitals, edges=frozenset(edges))


def _random_profile(rng: random.Random, market: KidneyMarket) -> KidneyProfile:
    """Truthful with probability 0.5; otherwise each hospital independently
    withholds a random subset of its own pairs -- exercises the IR-
    infeasible regime, not just the always-feasible truthful one."""
    if rng.random() < 0.5:
        return KidneyProfile.truthful(market)
    reports = {}
    for h in market.hospitals:
        owned = market.pairs_of(h)
        kept = tuple(p for p in owned if rng.random() < 0.7)
        reports[h] = kept
    return KidneyProfile(reports=reports)


def _gen_instances(n_target: int, max_candidates: int = 18):
    """Yields `(seed, market, profile, K)` tuples, 4-8 pairs / 1-3 hospitals
    / K in {2,3}, rerolling (never editing the counts) whenever the reported
    pool's candidate-cycle count would make the independent brute force
    intractable (`2**max_candidates` subsets is already 262144 -- generous
    but bounded)."""
    out = []
    seed = 0
    while len(out) < n_target:
        rng = random.Random(seed)
        n_pairs = 4 + (seed % 5)  # 4..8
        n_hospitals = 1 + (seed % 3)  # 1..3
        max_cycle_length = 2 if seed % 2 == 0 else 3
        edge_prob = [0.15, 0.25, 0.35][seed % 3]
        market = _random_market(seed, n_pairs, n_hospitals, edge_prob)
        profile = _random_profile(rng, market)
        reported_pool = tuple(p for h in market.hospitals for p in profile.report(h))
        n_cand = len(_independent_true_cycles(market, reported_pool, max_cycle_length))
        if n_cand <= max_candidates:
            out.append((seed, market, profile, max_cycle_length))
        seed += 1
        if seed > 20000:  # pragma: no cover - safety valve, should never trigger
            raise RuntimeError("could not generate enough tractable instances")
    return out


class IrJointModelAgreesWithIndependentBruteForce(unittest.TestCase):
    """Validation test 1: 100+ small random markets, independent brute force."""

    @classmethod
    def setUpClass(cls):
        cls.instances = _gen_instances(120)

    def test_matches_independent_brute_force_on_120_instances(self):
        n_checked = 0
        n_feasible = 0
        n_infeasible = 0
        for seed, market, profile, K in self.instances:
            with self.subTest(seed=seed, K=K):
                bf_feasible, bf_best, bf_standalone = _independent_ir_analysis(market, profile, K)

                result = ir_clear_kidney_exchange(market, profile, max_cycle_length=K)

                self.assertEqual(
                    result.ir_feasible, bf_feasible,
                    msg=f"seed={seed} K={K}: kidney_ir says ir_feasible={result.ir_feasible}, "
                        f"brute force says {bf_feasible}",
                )

                for h in market.hospitals:
                    self.assertEqual(
                        standalone(market, h, K), bf_standalone[h],
                        msg=f"seed={seed} K={K} h={h}: standalone disagreement",
                    )

                if bf_feasible:
                    n_feasible += 1
                    reported_total = sum(result.ir_utility.values())
                    self.assertEqual(
                        reported_total, bf_best,
                        msg=f"seed={seed} K={K}: kidney_ir reported-pool total={reported_total}, "
                            f"brute force best IR-feasible total={bf_best}",
                    )
                    for h in market.hospitals:
                        self.assertGreaterEqual(
                            result.ir_utility[h], bf_standalone[h],
                            msg=f"seed={seed} K={K} h={h}: IR constraint violated in kidney_ir's own solution",
                        )
                else:
                    n_infeasible += 1
                    self.assertEqual(result.central_selection, ())
                    self.assertEqual(result.utility, {})

                n_checked += 1
        self.assertEqual(n_checked, 120)  # non-vacuity: every generated instance actually ran
        self.assertGreater(n_feasible, 0)
        self.assertGreater(n_infeasible, 0)  # non-vacuity: the infeasible branch is genuinely exercised


class CrossCheckedAgainstOraclesKidney(unittest.TestCase):
    """Validation test 2: every selection kidney_ir returns is re-validated
    by `witness.oracles_kidney.is_valid_selection` -- a true, vertex-disjoint,
    fully-directed-compatible cycle set within the claimed pool."""

    def test_random_instances_selections_are_all_valid(self):
        n_checked = 0
        for seed, market, profile, K in _gen_instances(60):
            result = ir_clear_kidney_exchange(market, profile, max_cycle_length=K)
            reported_pool = tuple(p for h in market.hospitals for p in profile.report(h))
            with self.subTest(seed=seed, K=K):
                ok, reasons = is_valid_selection(market, result.central_selection, reported_pool, max_cycle_length=K)
                self.assertTrue(ok, msg=f"seed={seed}: central invalid: {reasons}")

                if result.ir_feasible:
                    for h in market.hospitals:
                        ok, reasons = is_valid_selection(
                            market, result.local_selections_reported[h], profile.report(h), max_cycle_length=K,
                        )
                        self.assertTrue(ok, msg=f"seed={seed} h={h}: local_reported invalid: {reasons}")

                        matched_centrally = {p for c in result.central_selection for p in c}
                        residual = tuple(p for p in market.pairs_of(h) if p not in matched_centrally)
                        ok, reasons = is_valid_selection(
                            market, result.local_selections[h], residual, max_cycle_length=K,
                        )
                        self.assertTrue(ok, msg=f"seed={seed} h={h}: local_realized invalid: {reasons}")
            n_checked += 1
        self.assertEqual(n_checked, 60)

    def test_hand_fixture_selections_are_valid(self):
        market, profile = _kid3b_market()
        result = ir_clear_kidney_exchange(market, profile, max_cycle_length=3)
        reported_pool = tuple(p for h in market.hospitals for p in profile.report(h))
        ok, reasons = is_valid_selection(market, result.central_selection, reported_pool, max_cycle_length=3)
        self.assertTrue(ok, msg=reasons)


# ---------------------------------------------------------------------------
# Hand-worked fixture -- traced BY HAND (see comments) before any code ran.
# Reuses KID3-B's own market (tests/test_kidney3_handworked.py), already an
# established, independently-traced fixture in this codebase: HA owns u1, u3
# with an internal 2-cycle; u1 also sits in a 3-cycle with HB's u2 and HC's
# u4. By hand: standalone(HA) = 2 (its own internal 2-cycle is its whole
# outside option). Plain max-cardinality clearing strictly prefers the
# 3-cycle (cardinality 3 > 2), giving HA only u1 -> utility 1 < standalone 2
# -- a genuine IR violation under the UNCONSTRAINED mechanism. Under the IR
# constraint, using the 3-cycle is provably infeasible for HA (its only
# reported recourse after losing u1 to the 3-cycle is the lone pair u3,
# which cannot form any cycle alone), so the ONLY IR-feasible packing is
# HA's own internal 2-cycle alone -- total matched pairs 2, not 3.
# ---------------------------------------------------------------------------


def _kid3b_market():
    market = KidneyMarket(
        pairs=("u1", "u2", "u3", "u4"),
        hospital_of={"u1": "HA", "u2": "HB", "u3": "HA", "u4": "HC"},
        hospitals=("HA", "HB", "HC"),
        edges=frozenset({
            ("u1", "u3"), ("u3", "u1"),  # HA's internal 2-cycle
            ("u1", "u2"), ("u2", "u4"), ("u4", "u1"),  # the competing 3-cycle
        }),
    )
    return market, KidneyProfile.truthful(market)


class NonVacuityIrStrictlyBinds(unittest.TestCase):
    """Validation test 3: IR strictly reduces the achievable total, and the
    unconstrained optimum genuinely violates a hospital's IR -- proving the
    constraint isn't vacuous."""

    def test_standalone_ha_is_2_by_hand(self):
        market, _ = _kid3b_market()
        self.assertEqual(standalone(market, "HA", max_cycle_length=3), 2)
        self.assertEqual(standalone(market, "HB", max_cycle_length=3), 0)
        self.assertEqual(standalone(market, "HC", max_cycle_length=3), 0)

    def test_unconstrained_optimum_violates_has_ir(self):
        market, profile = _kid3b_market()
        plain = clear_kidney_exchange(
            market, profile, KidneyConfig(tiebreak_policy=TIEBREAK_LEX_SMALLEST_BY_INDEX, max_cycle_length=3),
        )
        self.assertEqual(plain.central_selection, (("u1", "u2", "u4"),), msg=plain.format_trace())
        self.assertEqual(len(plain.matched_pairs), 3)
        self.assertEqual(plain.utility["HA"], 1)
        standalone_ha = standalone(market, "HA", max_cycle_length=3)
        self.assertLess(plain.utility["HA"], standalone_ha, msg="the unconstrained optimum must violate HA's IR here")

    def test_ir_constrained_optimum_is_strictly_smaller(self):
        market, profile = _kid3b_market()
        result = ir_clear_kidney_exchange(market, profile, max_cycle_length=3)
        self.assertTrue(result.ir_feasible, msg=result.format_trace())
        self.assertEqual(len(result.matched_pairs), 2, msg=result.format_trace())  # 2 < 3: strictly smaller
        self.assertEqual(result.utility["HA"], 2, msg=result.format_trace())  # HA now meets its own standalone
        self.assertEqual(result.utility["HB"], 0, msg=result.format_trace())
        self.assertEqual(result.utility["HC"], 0, msg=result.format_trace())
        for h in market.hospitals:
            self.assertGreaterEqual(result.utility[h], result.standalone[h])

    def test_ir_removes_has_specific_manipulation_here(self):
        """The plain mechanism's own manipulation search finds HA profitably
        withholding u1 here (an already-established fact of KID3-B). Confirm
        the IR-constrained search finds NONE for HA on this same instance --
        HA is already matched all of its own pairs (2/2), so no report can
        do better."""
        market, profile = _kid3b_market()
        cfg = KidneyConfig(tiebreak_policy=TIEBREAK_LEX_SMALLEST_BY_INDEX, max_cycle_length=3)
        plain_witness = find_hospital_manipulation(market, profile, "HA", cfg)
        self.assertIsNotNone(plain_witness)
        self.assertEqual(plain_witness.false_report, ("u3",))

        ir_witness, stats = find_hospital_manipulation_ir(market, profile, "HA", max_cycle_length=3)
        self.assertIsNone(ir_witness, msg=stats)
        self.assertTrue(stats.truthful_ir_feasible)


# ---------------------------------------------------------------------------
# Validation test 4: determinism.
# ---------------------------------------------------------------------------


class Deterministic(unittest.TestCase):
    def test_repeated_in_process_solves_agree(self):
        market, profile = _kid3b_market()
        results = [ir_clear_kidney_exchange(market, profile, max_cycle_length=3) for _ in range(5)]
        dicts = [r.to_dict() for r in results]
        self.assertTrue(all(d == dicts[0] for d in dicts), msg=dicts)

    def test_repeated_in_process_solves_agree_on_random_instance(self):
        _, market, profile, K = _gen_instances(4)[3]
        results = [ir_clear_kidney_exchange(market, profile, max_cycle_length=K).to_dict() for _ in range(4)]
        self.assertTrue(all(r == results[0] for r in results), msg=results)

    def test_fresh_subprocess_reproduces_the_identical_result(self):
        script = (
            PROJECT_ROOT_IMPORT
            + "from witness.kidney import KidneyMarket, KidneyProfile\n"
            "from witness.kidney_ir import ir_clear_kidney_exchange\n"
            "market = KidneyMarket(\n"
            "    pairs=('u1','u2','u3','u4'),\n"
            "    hospital_of={'u1':'HA','u2':'HB','u3':'HA','u4':'HC'},\n"
            "    hospitals=('HA','HB','HC'),\n"
            "    edges=frozenset({('u1','u3'),('u3','u1'),('u1','u2'),('u2','u4'),('u4','u1')}),\n"
            ")\n"
            "profile = KidneyProfile.truthful(market)\n"
            "res = ir_clear_kidney_exchange(market, profile, max_cycle_length=3)\n"
            "import json\n"
            "print(json.dumps(res.to_dict(), sort_keys=True))\n"
        )
        market, profile = _kid3b_market()
        in_process = ir_clear_kidney_exchange(market, profile, max_cycle_length=3).to_dict()

        import json
        outputs = set()
        for _ in range(3):
            proc = subprocess.run(
                [sys.executable, "-c", script], capture_output=True, text=True, timeout=60,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr)
            outputs.add(proc.stdout.strip())
        self.assertEqual(len(outputs), 1, msg=f"result varied across fresh subprocesses: {outputs}")
        self.assertEqual(json.loads(outputs.pop()), in_process)


if __name__ == "__main__":
    unittest.main()
