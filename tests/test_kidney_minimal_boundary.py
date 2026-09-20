"""The minimal witness of the k=2/k>=3 boundary in MODEL.md's Theorem (S:7.3).

That theorem says: at k=2, no withholding deviation gives a hospital more
than `U_true_max` -- its best outcome over every optimal central clearing.
The proof is a matroid-augmentation argument that only works because
2-cycle-packable sets form a matroid; it explicitly does not extend past
k=2 (S:7.5), and 341/2,669 real k=3 deviations exceed `U_true_max` in the
census (README.md). This file is the SMALLEST possible instance of that
failure, established by exhaustive search over every digraph on n pairs and
every ownership split (not sampling), per REVIEWER.md's "hand-work before
coding" discipline -- every value below was hand-derived first and is
CROSS-CHECKED against `witness.oracles_kidney`, an independently-written
brute-force oracle sharing no code with the mechanism.

MINIMALITY, PROVED NOT ASSUMED. An earlier draft of this fixture used 6
pairs and called it minimal because a search starting at n=6 found it
there; two of those six pairs turned out to be inert padding never touched
by any cycle. The claim below is not a habit this time: an exhaustive scan
over ALL 2^(n(n-1)) digraphs x ALL 2^n - 2 non-trivial ownership splits on
n=3 pairs finds ZERO instances where a determinate hospital can gain by
withholding at k=3 (0 of 372 determinate hospital-instances); the same
exhaustive scan at n=4 finds 204 (of 49,888). Four pairs is therefore
PROVABLY the minimum, not merely the smallest one found.

THE CONTROL. The identical exhaustive scan at k=2 finds 0 counterexamples
at BOTH n=3 (0/342) and n=4 (0/46,976) -- the theorem's zero is not an
artifact of n being too small to see a failure; the SAME search, on the
SAME n, sees 204 failures once cycles of length 3 are allowed. Reproduce
both scans with `scripts/kidney_minimal_boundary_search.py`.

THE INSTANCE (KIDMIN-A). Two hospitals, four pairs:

    h2 owns A=p2, B=p6         h1 owns C=p5, D=p4

    edges:  A->C  A->B  D->A  C->D  B->A
            (p2->p5 p2->p6 p4->p2 p5->p4 p6->p2)

    A<->B is a 2-cycle, entirely internal to h2.
    A->C->D->A is a 3-cycle spanning both hospitals.

    All five edges are load-bearing -- removing any one of them makes the
    deviation stop being profitable at k=3 (checked exhaustively below).

k=2: only the 2-cycle A<->B exists (no 3-cycle allowed). Central clears it.
    h2 gets both its own pairs, utility 2. Nothing to gain by lying.

k=3: the 3-cycle A->C->D->A matches 3 pairs, MORE than the 2-cycle's 2, so
    it is the UNIQUE maximum-cardinality clearing (proved by hand-
    enumeration below: exactly one optimal selection exists, so h2 is
    DETERMINATE -- no tie-breaking luck is involved at all). It uses A,
    leaving h2's B stranded with no partner: h2 gets 1.

    h2 withholds A. The 3-cycle can no longer form (it needs h2's A), so
    NOTHING clears centrally. h2 then privately runs A<->B in its own
    local clearing: h2 gets 2 -- MORE than the k=2 outcome, and more than
    ANY optimal k=3 clearing of the truthful pool could ever have given
    it (U_true_max = 1, since there is only one optimum). System cost:
    3 transplants fall to 2.
"""
from __future__ import annotations

import itertools
import unittest

from witness.kidney import (
    KidneyConfig,
    KidneyMarket,
    KidneyProfile,
    TIEBREAK_MAX_CARDINALITY_ILP,
    candidate_cycles,
    clear_kidney_exchange,
)
from witness.oracles_kidney import is_stable_kidney_result, recompute_utility
from witness.search_kidney import find_best_hospital_manipulation


def _minimal_market() -> KidneyMarket:
    return KidneyMarket(
        pairs=("p2", "p4", "p5", "p6"),
        hospital_of={"p2": "h2", "p4": "h1", "p5": "h1", "p6": "h2"},
        hospitals=("h1", "h2"),
        edges=frozenset({
            ("p2", "p5"),  # A -> C
            ("p2", "p6"),  # A -> B
            ("p4", "p2"),  # D -> A
            ("p5", "p4"),  # C -> D
            ("p6", "p2"),  # B -> A
        }),
    )


class KidminAMinimalBoundary(unittest.TestCase):
    """KIDMIN-A: 4 pairs, hand-derived, cross-checked against the
    independent oracle. See module docstring for the full derivation."""

    def setUp(self):
        self.market = _minimal_market()
        self.truth = KidneyProfile(reports={"h1": ("p4", "p5"), "h2": ("p2", "p6")})

    def test_k2_central_clearing_is_the_internal_2cycle(self):
        cfg = KidneyConfig(tiebreak_policy=TIEBREAK_MAX_CARDINALITY_ILP, max_cycle_length=2)
        res = clear_kidney_exchange(self.market, self.truth, cfg)
        self.assertEqual(res.central_selection, (("p2", "p6"),), msg=res.format_trace())
        self.assertEqual(res.utility, {"h1": 0, "h2": 2}, msg=res.format_trace())
        # independent oracle agrees this is a valid, stable outcome
        ok, reasons = is_stable_kidney_result(
            self.market, self.truth, res.central_selection, res.local_selections,
            res.utility, max_cycle_length=2,
        )
        self.assertTrue(ok, msg=reasons)

    def test_k2_no_profitable_withholding_by_h2(self):
        cfg = KidneyConfig(tiebreak_policy=TIEBREAK_MAX_CARDINALITY_ILP, max_cycle_length=2)
        w = find_best_hospital_manipulation(self.market, self.truth, "h2", cfg)
        self.assertIsNone(w, msg="the boundary case must be SAFE at k=2 -- if this fails, "
                                  "it is not witnessing the k=2/k>=3 boundary at all")

    def test_k3_unique_optimal_clearing_h2_is_determinate(self):
        """Hand-enumerate EVERY maximum-cardinality selection at k=3. There
        must be exactly one: this is what makes h2 'determinate' (its
        outcome cannot depend on tie-breaking luck), which is the whole
        point -- the gain below is not a lucky-tiebreak artifact."""
        pool = tuple(p for h in self.market.hospitals for p in self.truth.report(h))
        candidates = candidate_cycles(self.market, pool, max_cycle_length=3)
        best_card, optimal_selections = -1, []
        for r in range(len(candidates) + 1):
            for subset in itertools.combinations(candidates, r):
                used: set = set()
                ok = True
                for c in subset:
                    if used & set(c):
                        ok = False
                        break
                    used |= set(c)
                if not ok:
                    continue
                if len(used) > best_card:
                    best_card, optimal_selections = len(used), [subset]
                elif len(used) == best_card:
                    optimal_selections.append(subset)
        self.assertEqual(best_card, 3)
        self.assertEqual(
            len(optimal_selections), 1,
            msg=f"expected a UNIQUE optimum (determinacy); found {len(optimal_selections)}: "
                f"{optimal_selections}",
        )
        self.assertEqual(optimal_selections[0], (("p2", "p5", "p4"),))

    def test_k3_full_revelation_utility_is_one(self):
        cfg = KidneyConfig(tiebreak_policy=TIEBREAK_MAX_CARDINALITY_ILP, max_cycle_length=3)
        res = clear_kidney_exchange(self.market, self.truth, cfg)
        self.assertEqual(res.central_selection, (("p2", "p5", "p4"),), msg=res.format_trace())
        self.assertEqual(res.utility, {"h1": 2, "h2": 1}, msg=res.format_trace())
        ok, reasons = is_stable_kidney_result(
            self.market, self.truth, res.central_selection, res.local_selections,
            res.utility, max_cycle_length=3,
        )
        self.assertTrue(ok, msg=reasons)
        # cross-check utility independently: h2 owns p2,p6; only p2 is centrally
        # matched (in the 3-cycle, which also uses h1's p5,p4); p6 has no local
        # partner among h2's residual pairs, so local_selections["h2"] is empty
        # and recompute_utility must also say h2=1 -- sharing no code with
        # clear_kidney_exchange's own bookkeeping.
        independent = recompute_utility(self.market, res.central_selection, res.local_selections)
        self.assertEqual(independent["h2"], 1)
        self.assertEqual(independent, res.utility)

    def test_k3_withholding_A_strictly_beats_every_k2_and_every_k3_optimum(self):
        """The actual counterexample. h2 reports only {p6} (withholds p2 ==
        A). No central clearing is possible at all (the 3-cycle needs A;
        no 2-cycle exists without it), so h2's local clearing sees BOTH its
        true pairs, p2 and p6, still connected by the withheld A<->B edge,
        and matches them for utility 2. That is not just a gain over the
        REALIZED truthful outcome (1) -- 2 > 1 == U_true_max, the best ANY
        optimal truthful clearing could have given h2, since determinacy
        (previous test) makes U_true_min == U_true_max == 1."""
        cfg = KidneyConfig(tiebreak_policy=TIEBREAK_MAX_CARDINALITY_ILP, max_cycle_length=3)
        false_profile = self.truth.with_report("h2", ("p6",))
        res = clear_kidney_exchange(self.market, false_profile, cfg)
        self.assertEqual(res.central_selection, (), msg=res.format_trace())
        self.assertEqual(res.utility["h2"], 2, msg=res.format_trace())
        self.assertGreater(res.utility["h2"], 1, msg="must exceed U_true_max=1 -- this is the claim")

        w = find_best_hospital_manipulation(self.market, self.truth, "h2", cfg)
        self.assertIsNotNone(w)
        d = w.to_dict()
        self.assertEqual(d["truthful_utility"], 1)
        self.assertEqual(d["false_utility"], 2)
        self.assertEqual(tuple(d["false_report"]), ("p6",))

    def test_all_five_edges_are_load_bearing(self):
        """Minimality is not just about pair count: every edge in this
        4-pair market is necessary. Removing any single one destroys the
        k=3 profitable-withholding property -- checked exhaustively, not
        asserted."""
        base = frozenset({("p2", "p5"), ("p2", "p6"), ("p4", "p2"), ("p5", "p4"), ("p6", "p2")})
        cfg = KidneyConfig(tiebreak_policy=TIEBREAK_MAX_CARDINALITY_ILP, max_cycle_length=3)
        for dropped in sorted(base):
            with self.subTest(dropped=dropped):
                trimmed = KidneyMarket(
                    pairs=self.market.pairs, hospital_of=self.market.hospital_of,
                    hospitals=self.market.hospitals, edges=base - {dropped},
                )
                w = find_best_hospital_manipulation(trimmed, self.truth, "h2", cfg)
                gain = 0 if w is None else w.to_dict()["false_utility"] - w.to_dict()["truthful_utility"]
                self.assertEqual(
                    gain, 0,
                    msg=f"removing edge {dropped} should destroy the deviation, but gain={gain}",
                )

    def test_n3_is_exhaustively_impossible(self):
        """The other half of minimality: no 3-pair market of ANY shape
        contains this phenomenon. Full corroboration is
        `scripts/kidney_minimal_boundary_search.py` (0/372 at k=3, 0/342 at
        k=2, over every digraph and every split on 3 pairs); this is a
        fast spot-check that the exhaustive claim is not stale."""
        import scripts.kidney_minimal_boundary_search as search
        checked, hits = search.scan(3, 3)
        self.assertEqual(hits, 0, msg=f"a 3-pair counterexample exists ({hits}/{checked}) -- "
                                       f"minimality claim in this file's docstring is FALSE")


if __name__ == "__main__":
    unittest.main()
