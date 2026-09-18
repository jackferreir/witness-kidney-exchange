"""Validation gate for `scripts/kidney_tiebreak_exact.py`'s joint-ILP
`joint_extreme`, mirroring `tests/test_kidney_tiebreak_robustness.py`'s own
discipline: before the joint-ILP checker is trusted on real witnesses, it
must agree EXACTLY with an independent brute-force re-derivation on 100+
random small markets, plus a hand-built instance demonstrating the SPECIFIC
bug class this script exists to rule out.

THE BUG CLASS: a NAIVE two-stage approach -- first pick, among central
selections achieving the proven maximum cardinality `C*`, the one that
maximizes (resp. minimizes) the target hospital's own CENTRAL footprint
size, THEN add whatever local matching that footprint's residual permits --
is not the same question as "the true joint optimum of footprint + local
combined." `HandBuiltNaiveFootprintBugFixture` below is engineered so the
two disagree: the footprint-maximizing central choice STRANDS three of the
hospital's own pairs that could otherwise form a 3-cycle locally, so
maximizing central-own matches yields a LOWER final utility (2) than the
true joint optimum (4), which instead prefers a SMALLER central footprint
that leaves the profitable local 3-cycle intact.

The brute force below shares no code with `scripts/kidney_tiebreak_exact.py`
(own cycle enumeration, own vertex-disjoint subset search) and no code with
`witness.kidney` itself (re-derived from the raw edge definition, like
`witness.oracles_kidney`) -- an independent second implementation of "across
every maximum-cardinality central clearing, what utility does hospital `h`
actually get once its own local stage also runs to ITS maximum?"
"""

from __future__ import annotations

import itertools
import random
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
for p in (str(PROJECT_ROOT), str(PROJECT_ROOT / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

from witness.kidney import (  # noqa: E402
    KidneyConfig,
    KidneyMarket,
    KidneyProfile,
    TIEBREAK_LEX_SMALLEST_BY_INDEX,
    clear_kidney_exchange,
)

from kidney_tiebreak_exact import joint_extreme  # noqa: E402


# ---------------------------------------------------------------------------
# Independent brute force -- own code path.
# ---------------------------------------------------------------------------


def _bf_true_cycles(market: KidneyMarket, pool, max_cycle_length: int):
    pool = list(pool)
    cycles = []
    for u, v in itertools.combinations(pool, 2):
        if market.has_edge(u, v) and market.has_edge(v, u):
            cycles.append((u, v))
    if max_cycle_length >= 3:
        for a, b, c in itertools.combinations(pool, 3):
            if market.has_edge(a, b) and market.has_edge(b, c) and market.has_edge(c, a):
                cycles.append((a, b, c))
            if market.has_edge(a, c) and market.has_edge(c, b) and market.has_edge(b, a):
                cycles.append((a, c, b))
    return cycles


def _bf_all_max_selections(market: KidneyMarket, pool, max_cycle_length: int):
    """Every vertex-disjoint subset of true cycles over `pool` achieving the
    GLOBAL maximum cardinality. Returns `(best_cardinality, [selection, ...])`."""
    cycles = _bf_true_cycles(market, pool, max_cycle_length)
    n = len(cycles)
    best = 0
    selections = [()]
    for r in range(1, n + 1):
        for combo in itertools.combinations(range(n), r):
            used = set()
            ok = True
            covered = 0
            for i in combo:
                cyc = cycles[i]
                if any(x in used for x in cyc):
                    ok = False
                    break
                used.update(cyc)
                covered += len(cyc)
            if not ok:
                continue
            if covered > best:
                best = covered
                selections = [tuple(cycles[i] for i in combo)]
            elif covered == best:
                selections.append(tuple(cycles[i] for i in combo))
    return best, selections


def _bf_max_cardinality(market: KidneyMarket, pool, max_cycle_length: int) -> int:
    best, _ = _bf_all_max_selections(market, pool, max_cycle_length)
    return best


def _bf_true_final_utilities(market: KidneyMarket, report_map, hospital: str, max_cycle_length: int):
    """For EVERY central selection achieving the global maximum cardinality
    `C*`, compute `hospital`'s TRUE final utility (its own central footprint
    from that specific selection, plus the true local maximum -- via the
    SAME general brute-force max-cardinality routine -- on the residual that
    footprint induces over `hospital`'s OWN TRUE pairs, mirroring the
    mechanism's own residual rule: `market.pairs_of(hospital)` minus
    whatever that selection matched). Returns `(c_star, set_of_utilities)`."""
    reported_pool = tuple(p for h in market.hospitals for p in report_map[h])
    c_star, central_selections = _bf_all_max_selections(market, reported_pool, max_cycle_length)

    owned = market.pairs_of(hospital)
    utilities = set()
    for sel in central_selections:
        matched = set()
        for cyc in sel:
            matched.update(cyc)
        footprint = [p for p in owned if p in matched]
        residual = [p for p in owned if p not in matched]
        local_max = _bf_max_cardinality(market, residual, max_cycle_length)
        utilities.add(len(footprint) + local_max)
    return c_star, utilities


def _bf_naive_footprint_first(market: KidneyMarket, report_map, hospital: str, max_cycle_length: int, sense: str):
    """THE BUG UNDER TEST: among central selections achieving `C*`, pick the
    one that maximizes (`sense="max"`) or minimizes (`sense="min"`) hospital's
    own footprint SIZE ALONE (ignoring what that choice does to the local
    stage), then add whatever local matching the resulting residual permits.
    This is the naive two-stage shortcut `joint_extreme` must NOT reduce to."""
    reported_pool = tuple(p for h in market.hospitals for p in report_map[h])
    c_star, central_selections = _bf_all_max_selections(market, reported_pool, max_cycle_length)
    owned = market.pairs_of(hospital)

    best_footprint_size = None
    chosen = None
    for sel in central_selections:
        matched = set()
        for cyc in sel:
            matched.update(cyc)
        fp_size = sum(1 for p in owned if p in matched)
        if best_footprint_size is None or (
            (sense == "max" and fp_size > best_footprint_size) or (sense == "min" and fp_size < best_footprint_size)
        ):
            best_footprint_size = fp_size
            chosen = sel
    matched = set()
    for cyc in chosen:
        matched.update(cyc)
    footprint = [p for p in owned if p in matched]
    residual = [p for p in owned if p not in matched]
    local_max = _bf_max_cardinality(market, residual, max_cycle_length)
    return len(footprint) + local_max


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


# ---------------------------------------------------------------------------
# Hand-built non-vacuity fixture: naive footprint-first != true joint optimum
# ---------------------------------------------------------------------------


class HandBuiltNaiveFootprintBugFixture(unittest.TestCase):
    """H1 owns p, q, r, m; H2 owns s. H1 reports (p, q, r) and WITHHOLDS m.
    True edges: p<->s and p<->q (two competing central 2-cycles, both using
    p), and q->r->m->q (a local-only 3-cycle -- m is never reported, so
    central clearing can never see it, but H1's own local clearing, which
    runs over `market.pairs_of(H1)`, can).

    Central pool = {p,q,r,s}; the ONLY true cycles in it are the 2-cycles
    (p,q) and (p,s) (verified in `test_central_candidates_are_exactly_the_
    two_competing_2cycles` below) -- no 3-cycle exists among {p,q,r,s}
    because r has no edge to p or s at all. C* = 2, achieved by EXACTLY two
    selections: {(p,s)} or {(p,q)} (they share p, mutually exclusive).

    Choosing {(p,s)}: H1's footprint = {p} (size 1). Residual = {q,r,m} --
    the full local 3-cycle survives. Local max = 3. Total H1 utility = 4.

    Choosing {(p,q)}: H1's footprint = {p,q} (size 2, LARGER). Residual =
    {r,m} only -- r->m is true but m->r is not, so no local cycle at all.
    Local max = 0. Total H1 utility = 2.

    So the footprint-MAXIMIZING central choice (size 2) yields the LOWER
    total utility (2); the true joint optimum (4) comes from the SMALLER
    footprint (size 1). A naive "maximize central-own matches, then add
    local" implementation would report U_true_max = 2 -- wrong by exactly
    the margin this fixture exists to catch.
    """

    def setUp(self):
        self.market = KidneyMarket(
            pairs=("p", "q", "r", "s", "m"),
            hospital_of={"p": "H1", "q": "H1", "r": "H1", "m": "H1", "s": "H2"},
            hospitals=("H1", "H2"),
            edges=frozenset({
                ("p", "s"), ("s", "p"),
                ("p", "q"), ("q", "p"),
                ("q", "r"),
                ("r", "m"),
                ("m", "q"),
            }),
        )
        self.report_map = {"H1": ("p", "q", "r"), "H2": ("s",)}

    def test_central_candidates_are_exactly_the_two_competing_2cycles(self):
        reported_pool = tuple(p for h in self.market.hospitals for p in self.report_map[h])
        c_star, selections = _bf_all_max_selections(self.market, reported_pool, max_cycle_length=3)
        self.assertEqual(c_star, 2)
        as_sets = sorted(sorted(sel) for sel in selections)
        self.assertEqual(as_sets, [[("p", "q")], [("p", "s")]])

    def test_brute_force_confirms_the_true_joint_optimum_is_4_and_2(self):
        c_star, utilities = _bf_true_final_utilities(self.market, self.report_map, "H1", max_cycle_length=3)
        self.assertEqual(c_star, 2)
        self.assertEqual(utilities, {2, 4}, msg="fixture no longer exhibits the intended two-outcome tie")

    def test_naive_footprint_maximization_gives_the_wrong_answer(self):
        """The bug, demonstrated non-vacuously: footprint-size-first picks
        the WORSE (2), not the true best (4)."""
        naive = _bf_naive_footprint_first(self.market, self.report_map, "H1", max_cycle_length=3, sense="max")
        self.assertEqual(naive, 2, msg="fixture no longer demonstrates the naive-footprint-first bug")

    def test_naive_footprint_minimization_also_gives_the_wrong_answer(self):
        """Symmetric check for the minimization side (used for the false
        report / U_false_min): footprint-size-first-minimizing picks the
        WORSE-for-the-adversary-checker (4), not the true worst (2)."""
        naive = _bf_naive_footprint_first(self.market, self.report_map, "H1", max_cycle_length=3, sense="min")
        self.assertEqual(naive, 4, msg="fixture no longer demonstrates the naive-footprint-first bug on the min side")

    def test_joint_ilp_finds_the_true_max_of_4_not_the_naive_2(self):
        result = joint_extreme(self.market, self.report_map, "H1", max_cycle_length=3, max_seconds=10.0, sense="max")
        self.assertEqual(result["status"], "ok", msg=result)
        self.assertEqual(result["value"], 4, msg="joint_extreme must find the TRUE joint optimum, not the naive footprint-maximizing answer")
        self.assertEqual(result["c_star"], 2)

    def test_joint_ilp_finds_the_true_min_of_2_not_the_naive_4(self):
        result = joint_extreme(self.market, self.report_map, "H1", max_cycle_length=3, max_seconds=10.0, sense="min")
        self.assertEqual(result["status"], "ok", msg=result)
        self.assertEqual(result["value"], 2, msg="joint_extreme must find the TRUE joint minimum, not the naive footprint-minimizing answer")
        self.assertEqual(result["c_star"], 2)

    def test_fixed_seed_mechanism_utility_lies_within_the_true_range(self):
        profile = KidneyProfile(reports=self.report_map)
        config = KidneyConfig(tiebreak_policy=TIEBREAK_LEX_SMALLEST_BY_INDEX, max_cycle_length=3, max_central_space=2 ** 12)
        result = clear_kidney_exchange(self.market, profile, config)
        # Local clearing sees H1's TRUE pairs including withheld `m`, so
        # `clear_kidney_exchange` itself must be called with a profile that
        # only reports (p,q,r) for H1 -- `m` stays owned-but-unreported.
        u = result.utility["H1"]
        self.assertIn(u, (2, 4))


# ---------------------------------------------------------------------------
# Randomized cross-check: joint_extreme (max AND min) vs. independent brute
# force, on 100+ small random markets, K in {2,3}.
# ---------------------------------------------------------------------------


class JointIlpMatchesBruteForceRandomized(unittest.TestCase):
    def test_extremes_match_on_120_random_instances(self):
        n_checked = 0
        for seed in range(240):
            n_pairs = 4 + (seed % 4)  # 4..7
            n_hospitals = 1 + (seed % 3)  # 1..3
            edge_prob = [0.2, 0.3, 0.45][seed % 3]
            max_cycle_length = 2 if seed % 2 == 0 else 3
            market = _random_market(seed, n_pairs, n_hospitals, edge_prob)

            rng = random.Random(seed * 7919 + 3)
            report_map = {}
            for h in market.hospitals:
                owned = market.pairs_of(h)
                report_map[h] = tuple(p for p in owned if rng.random() < 0.8)
            hospital = market.hospitals[seed % n_hospitals]
            if not market.pairs_of(hospital):
                continue  # hospital owns nothing -- degenerate, skip

            bf_c_star, bf_utilities = _bf_true_final_utilities(market, report_map, hospital, max_cycle_length)
            bf_min, bf_max = min(bf_utilities), max(bf_utilities)

            max_result = joint_extreme(market, report_map, hospital, max_cycle_length, max_seconds=15.0, sense="max")
            min_result = joint_extreme(market, report_map, hospital, max_cycle_length, max_seconds=15.0, sense="min")

            with self.subTest(seed=seed):
                self.assertEqual(max_result["status"], "ok", msg=f"seed={seed}: {max_result}")
                self.assertEqual(min_result["status"], "ok", msg=f"seed={seed}: {min_result}")
                self.assertEqual(max_result["c_star"], bf_c_star, msg=f"seed={seed}: central C* disagreement (max side)")
                self.assertEqual(min_result["c_star"], bf_c_star, msg=f"seed={seed}: central C* disagreement (min side)")
                self.assertEqual(max_result["value"], bf_max, msg=f"seed={seed}: joint max {max_result['value']} != brute force max {bf_max}")
                self.assertEqual(min_result["value"], bf_min, msg=f"seed={seed}: joint min {min_result['value']} != brute force min {bf_min}")

                profile = KidneyProfile(reports=report_map)
                config = KidneyConfig(tiebreak_policy=TIEBREAK_LEX_SMALLEST_BY_INDEX, max_cycle_length=max_cycle_length, max_central_space=2 ** 16)
                fixed_seed_result = clear_kidney_exchange(market, profile, config)
                fixed_u = fixed_seed_result.utility[hospital]
                self.assertTrue(
                    bf_min <= fixed_u <= bf_max,
                    msg=f"seed={seed}: fixed-seed mechanism utility {fixed_u} outside true range [{bf_min},{bf_max}]",
                )
            n_checked += 1
        self.assertGreaterEqual(n_checked, 100, msg="too many degenerate seeds were skipped -- widen the range checked")


if __name__ == "__main__":
    unittest.main()
