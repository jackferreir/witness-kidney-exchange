"""Hand-worked examples for the 3-cycle extension of the kidney-exchange
mechanism (`witness.kidney`, `max_cycle_length=3`) -- the exact regime the
field's own asymptotic-safety theorem is stated for (Ashlagi & Roth's
Theorem 6.2 is proved "using exchanges of size at most 3"), per REVIEWER.md's
literature-check discipline and this session's own research trail. Same
"Hand-specification gate" discipline as the 2-cycle model's own four traces
(`tests/test_kidney_handworked.py`): every expected value here was derived
BY HAND before being checked against the implementation.

KID3-A: full revelation with a genuine 3-cycle -- three pairs with NO
    2-cycle among them at all, only resolvable by a directed 3-cycle.
    Demonstrates the actual point of allowing 3-cycles (2-cycle-only
    clearing would leave all three unmatched).

KID3-B: profitable withholding where a hospital's pair is "poached" by a
    3-cycle instead of a competing 2-cycle. HA owns u1, u3 (an internal
    2-cycle). u1 also participates in a 3-cycle with HB's u2 and HC's u4.
    Central clearing STRICTLY prefers the 3-cycle (cardinality 3 > 2, no
    tie needed), leaving HA's u3 stranded. HA withholding u1 recovers its
    own internal 2-cycle, utility 1 -> 2 -- the 3-cycle analogue of KID-B.

KID3-C: a genuine TIE between two maximum-cardinality (5-pair) selections,
    one using {2-cycle, 3-cycle}, the other {3-cycle, 2-cycle} -- pins the
    tuple-prefix tiebreak convention across DIFFERENT-length cycles
    (documented in witness.kidney's module docstring).

KID3-D: isolation negative control, re-verified with a 3-cycle (not just a
    2-cycle) as the only internal recourse -- every one of a hospital's 7
    legal misreports ties full revelation exactly, checked exhaustively.
"""

from __future__ import annotations

import unittest
from itertools import chain, combinations

from witness.kidney import (
    KidneyConfig,
    KidneyMarket,
    KidneyProfile,
    clear_kidney_exchange,
)
from witness.oracles_kidney import is_stable_kidney_result


def _all_subsets(items):
    items = tuple(items)
    return list(chain.from_iterable(combinations(items, r) for r in range(len(items) + 1)))


class Kid3AGenuine3Cycle(unittest.TestCase):
    """KID3-A. Pairs u1, u2, u3 (each its own hospital): directed cycle
    u1->u2->u3->u1, NO reverse edges at all -- no 2-cycle exists among any
    pair. Only a 3-cycle can match any of them."""

    def setUp(self):
        self.market = KidneyMarket(
            pairs=("u1", "u2", "u3"),
            hospital_of={"u1": "HA", "u2": "HB", "u3": "HC"},
            hospitals=("HA", "HB", "HC"),
            edges=frozenset({("u1", "u2"), ("u2", "u3"), ("u3", "u1")}),
        )
        self.config = KidneyConfig(max_cycle_length=3)

    def test_no_2_cycle_clearing_matches_nobody(self):
        config2 = KidneyConfig(max_cycle_length=2)
        res = clear_kidney_exchange(self.market, KidneyProfile.truthful(self.market), config2)
        self.assertEqual(res.central_selection, (), msg=res.format_trace())
        self.assertEqual(res.utility, {"HA": 0, "HB": 0, "HC": 0}, msg=res.format_trace())

    def test_3_cycle_clearing_matches_all_three(self):
        res = clear_kidney_exchange(self.market, KidneyProfile.truthful(self.market), self.config)
        self.assertEqual(res.central_selection, (("u1", "u2", "u3"),), msg=res.format_trace())
        self.assertEqual(res.utility, {"HA": 1, "HB": 1, "HC": 1}, msg=res.format_trace())

    def test_independently_confirmed_by_the_oracle(self):
        profile = KidneyProfile.truthful(self.market)
        res = clear_kidney_exchange(self.market, profile, self.config)
        ok, reasons = is_stable_kidney_result(
            self.market, profile, res.central_selection, res.local_selections, res.utility, max_cycle_length=3
        )
        self.assertTrue(ok, msg=reasons)


class Kid3BProfitableWithholdingVia3Cycle(unittest.TestCase):
    """KID3-B. HA owns u1, u3 (internal 2-cycle). u1 ALSO sits in a 3-cycle
    with HB's u2 and HC's u4. The 3-cycle strictly beats the 2-cycle on
    cardinality (3 > 2), so full revelation stably picks the 3-cycle,
    stranding u3. Withholding u1 recovers HA's own 2-cycle instead."""

    def setUp(self):
        self.market = KidneyMarket(
            pairs=("u1", "u2", "u3", "u4"),
            hospital_of={"u1": "HA", "u2": "HB", "u3": "HA", "u4": "HC"},
            hospitals=("HA", "HB", "HC"),
            edges=frozenset({
                ("u1", "u3"), ("u3", "u1"),  # HA's internal 2-cycle
                ("u1", "u2"), ("u2", "u4"), ("u4", "u1"),  # the competing 3-cycle
            }),
        )
        self.config = KidneyConfig(max_cycle_length=3)

    def test_full_revelation_picks_the_3_cycle_over_the_2_cycle(self):
        res = clear_kidney_exchange(self.market, KidneyProfile.truthful(self.market), self.config)
        self.assertEqual(res.central_selection, (("u1", "u2", "u4"),), msg=res.format_trace())
        self.assertEqual(res.utility["HA"], 1, msg=res.format_trace())  # only u1; u3 stranded

    def test_ha_withholding_u1_recovers_its_internal_2_cycle(self):
        profile = KidneyProfile(reports={"HA": ("u3",), "HB": ("u2",), "HC": ("u4",)})
        res = clear_kidney_exchange(self.market, profile, self.config)
        self.assertEqual(res.central_selection, (), msg=res.format_trace())
        self.assertEqual(res.local_selections["HA"], (("u1", "u3"),), msg=res.format_trace())
        self.assertEqual(res.utility["HA"], 2, msg=res.format_trace())

    def test_ha_utility_strictly_improves(self):
        truthful_res = clear_kidney_exchange(self.market, KidneyProfile.truthful(self.market), self.config)
        false_profile = KidneyProfile(reports={"HA": ("u3",), "HB": ("u2",), "HC": ("u4",)})
        false_res = clear_kidney_exchange(self.market, false_profile, self.config)
        self.assertEqual(truthful_res.utility["HA"], 1)
        self.assertEqual(false_res.utility["HA"], 2)
        self.assertGreater(false_res.utility["HA"], truthful_res.utility["HA"])

    def test_both_outcomes_independently_confirmed(self):
        false_profile = KidneyProfile(reports={"HA": ("u3",), "HB": ("u2",), "HC": ("u4",)})
        false_res = clear_kidney_exchange(self.market, false_profile, self.config)
        ok, reasons = is_stable_kidney_result(
            self.market, false_profile, false_res.central_selection, false_res.local_selections,
            false_res.utility, max_cycle_length=3,
        )
        self.assertTrue(ok, msg=reasons)


class Kid3CTiebreakAcrossMixedCycleLengths(unittest.TestCase):
    """KID3-C. Pairs u1..u5 (own hospital each). Exactly two maximum-
    cardinality (5-pair) selections exist:
      Selection A: {(u1,u2) 2-cycle, (u3,u4,u5) 3-cycle}
      Selection B: {(u1,u2,u3) 3-cycle, (u4,u5) 2-cycle}
    Canonical index-tuples: A's first cycle is (0,1); B's first cycle is
    (0,1,2). Python's tuple-prefix rule: (0,1) < (0,1,2), so A wins.
    """

    def setUp(self):
        self.market = KidneyMarket(
            pairs=("u1", "u2", "u3", "u4", "u5"),
            hospital_of={"u1": "H1", "u2": "H2", "u3": "H3", "u4": "H4", "u5": "H5"},
            hospitals=("H1", "H2", "H3", "H4", "H5"),
            edges=frozenset({
                ("u1", "u2"), ("u2", "u1"),  # 2-cycle for selection A
                ("u3", "u4"), ("u4", "u5"), ("u5", "u3"),  # 3-cycle for selection A
                ("u2", "u3"), ("u3", "u1"),  # completes 3-cycle u1->u2->u3->u1 for selection B
                ("u5", "u4"),  # completes 2-cycle u4<->u5 for selection B
            }),
        )
        self.config = KidneyConfig(max_cycle_length=3)

    def test_both_alternatives_are_valid_maximum_cardinality_selections(self):
        from witness.oracles_kidney import is_valid_selection, is_maximum_cardinality

        pool = self.market.pairs
        selection_a = (("u1", "u2"), ("u3", "u4", "u5"))
        selection_b = (("u1", "u2", "u3"), ("u4", "u5"))
        for selection in (selection_a, selection_b):
            with self.subTest(selection=selection):
                ok, reasons = is_valid_selection(self.market, selection, pool, max_cycle_length=3)
                self.assertTrue(ok, msg=reasons)
                ok2, reasons2 = is_maximum_cardinality(self.market, selection, pool, max_cycle_length=3)
                self.assertTrue(ok2, msg=reasons2)

    def test_tiebreak_picks_selection_a(self):
        res = clear_kidney_exchange(self.market, KidneyProfile.truthful(self.market), self.config)
        self.assertEqual(res.central_selection, (("u1", "u2"), ("u3", "u4", "u5")), msg=res.format_trace())
        self.assertNotEqual(res.central_selection, (("u1", "u2", "u3"), ("u4", "u5")))


class Kid3DIsolationNegativeControlWith3Cycle(unittest.TestCase):
    """KID3-D. HA owns u1, u2, u3 with an internal 3-cycle (NO 2-cycle among
    them at all -- so this specifically exercises 3-cycle recovery, not the
    2-cycle path KID-D already covers). No cross-hospital edges anywhere.
    Every one of HA's 7 legal misreports ties full revelation exactly,
    checked exhaustively."""

    def setUp(self):
        self.market = KidneyMarket(
            pairs=("u1", "u2", "u3", "v1"),
            hospital_of={"u1": "HA", "u2": "HA", "u3": "HA", "v1": "HB"},
            hospitals=("HA", "HB"),
            edges=frozenset({("u1", "u2"), ("u2", "u3"), ("u3", "u1")}),
        )
        self.config = KidneyConfig(max_cycle_length=3)

    def test_full_revelation_utility(self):
        res = clear_kidney_exchange(self.market, KidneyProfile.truthful(self.market), self.config)
        self.assertEqual(res.utility, {"HA": 3, "HB": 0}, msg=res.format_trace())

    def test_every_legal_report_ties_full_revelation_exhaustively(self):
        truthful_report = self.market.pairs_of("HA")
        truthful_utility = clear_kidney_exchange(
            self.market, KidneyProfile.truthful(self.market), self.config
        ).utility["HA"]
        self.assertEqual(truthful_utility, 3)

        legal_reports = [r for r in _all_subsets(truthful_report) if tuple(r) != tuple(truthful_report)]
        self.assertEqual(len(legal_reports), 2 ** len(truthful_report) - 1)  # non-vacuity: 7 misreports
        for report in legal_reports:
            with self.subTest(report=report):
                profile = KidneyProfile.truthful(self.market).with_report("HA", report)
                res = clear_kidney_exchange(self.market, profile, self.config)
                self.assertLessEqual(
                    res.utility["HA"], truthful_utility,
                    msg=f"report {report!r} beat full revelation ({res.utility['HA']} > {truthful_utility})",
                )
                self.assertEqual(
                    res.utility["HA"], truthful_utility,
                    msg=f"report {report!r} tied at a DIFFERENT utility than full revelation, unexpectedly",
                )


if __name__ == "__main__":
    unittest.main()
