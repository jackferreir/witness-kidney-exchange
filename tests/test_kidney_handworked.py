"""Hand-worked examples for the kidney-exchange mechanism (`witness.kidney`),
per `KIDNEY_EXCHANGE_SCOPE.md`'s "Hand-specification gate": full revelation,
one profitable withholding example, a central-clearing tiebreak example with
multiple optima, and a no-cross-hospital-edge isolation negative control.
Every expected value below was derived BY HAND from the model in that
scope file BEFORE being checked against the implementation. DO NOT change
an expected value to make a test pass -- a disagreement here is a finding
about the implementation, not the fixture.

KID-A/KID-C share one market (three pairs, two hospitals): pairs u1, u3
owned by HA, pair u2 owned by HB. TRUE edges: u1<->u3 (internal to HA) and
u1<->u2 (cross-hospital); u2/u3 have no edge. Under full revelation there
are exactly two maximum-cardinality (2 pairs) central selections -- {(u1,u3)}
or {(u1,u2)} -- genuinely tied, so the declared tiebreak
(lexicographically-smallest-by-index among tied selections) is what decides
between them: comparing canonical index-pairs (0,1) [[[u1,u2]]] vs (0,2)
[[u1,u3]], (0,1) is smaller, so {(u1,u2)} wins and u3 is left unmatched.

KID-A pins that full-revelation outcome. KID-B (SAME market) pins that HA
can do STRICTLY BETTER by withholding u1 from the central pool: central then
sees only u2/u3 reported, which have no edge, so it selects nothing; both
u1 and u3 become residual to HA (u1 was never centrally reported at all;
u3 was reported but not selected), and HA's own local clearing finds the
internal u1<->u3 edge and matches both -- HA's utility rises from 1 (full
revelation) to 2 (withholding u1). KID-C pins the SAME full-revelation
instance as KID-A but asserts the tie and the specific losing alternative
directly, rather than only the winning selection.

KID-D is a SEPARATE, fully isolated market (no cross-hospital edges
anywhere) and pins the negative control KIDNEY_EXCHANGE_SCOPE.md requires:
every legal report for the isolated hospital ties the same utility full
revelation achieves, over its ENTIRE 2^k - 1 legal misreport space (checked
exhaustively, not sampled).
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


class KidASharedMarketFullRevelation(unittest.TestCase):
    """KID-A. Full revelation on the 3-pair, 2-hospital market."""

    def setUp(self):
        self.market = KidneyMarket(
            pairs=("u1", "u2", "u3"),
            hospital_of={"u1": "HA", "u2": "HB", "u3": "HA"},
            hospitals=("HA", "HB"),
            edges=frozenset({("u1", "u2"), ("u2", "u1"), ("u1", "u3"), ("u3", "u1")}),
        )
        self.config = KidneyConfig()

    def test_central_selects_the_cross_hospital_cycle(self):
        profile = KidneyProfile.truthful(self.market)
        res = clear_kidney_exchange(self.market, profile, self.config)
        self.assertEqual(res.central_selection, (("u1", "u2"),), msg=res.format_trace())

    def test_u3_is_left_unmatched_with_no_local_recourse(self):
        profile = KidneyProfile.truthful(self.market)
        res = clear_kidney_exchange(self.market, profile, self.config)
        self.assertEqual(res.local_selections["HA"], (), msg=res.format_trace())
        self.assertNotIn("u3", res.matched_pairs)

    def test_utility_matches_hand_derivation(self):
        profile = KidneyProfile.truthful(self.market)
        res = clear_kidney_exchange(self.market, profile, self.config)
        self.assertEqual(res.utility, {"HA": 1, "HB": 1}, msg=res.format_trace())

    def test_independently_confirmed_by_the_oracle(self):
        profile = KidneyProfile.truthful(self.market)
        res = clear_kidney_exchange(self.market, profile, self.config)
        ok, reasons = is_stable_kidney_result(
            self.market, profile, res.central_selection, res.local_selections, res.utility
        )
        self.assertTrue(ok, msg=reasons)


class KidBProfitableWithholding(unittest.TestCase):
    """KID-B. SAME market as KID-A. HA withholds u1 (reports only u3) and
    strictly improves its own utility from 1 to 2."""

    def setUp(self):
        self.market = KidneyMarket(
            pairs=("u1", "u2", "u3"),
            hospital_of={"u1": "HA", "u2": "HB", "u3": "HA"},
            hospitals=("HA", "HB"),
            edges=frozenset({("u1", "u2"), ("u2", "u1"), ("u1", "u3"), ("u3", "u1")}),
        )
        self.config = KidneyConfig()

    def test_withholding_u1_yields_no_central_cycle(self):
        profile = KidneyProfile(reports={"HA": ("u3",), "HB": ("u2",)})
        res = clear_kidney_exchange(self.market, profile, self.config)
        self.assertEqual(res.central_selection, (), msg=res.format_trace())

    def test_withholding_u1_recovers_the_internal_cycle_locally(self):
        profile = KidneyProfile(reports={"HA": ("u3",), "HB": ("u2",)})
        res = clear_kidney_exchange(self.market, profile, self.config)
        self.assertEqual(res.local_selections["HA"], (("u1", "u3"),), msg=res.format_trace())

    def test_ha_utility_strictly_improves_over_full_revelation(self):
        truthful_res = clear_kidney_exchange(self.market, KidneyProfile.truthful(self.market), self.config)
        false_profile = KidneyProfile(reports={"HA": ("u3",), "HB": ("u2",)})
        false_res = clear_kidney_exchange(self.market, false_profile, self.config)
        self.assertEqual(truthful_res.utility["HA"], 1, msg=truthful_res.format_trace())
        self.assertEqual(false_res.utility["HA"], 2, msg=false_res.format_trace())
        self.assertGreater(false_res.utility["HA"], truthful_res.utility["HA"])

    def test_both_outcomes_independently_confirmed(self):
        false_profile = KidneyProfile(reports={"HA": ("u3",), "HB": ("u2",)})
        false_res = clear_kidney_exchange(self.market, false_profile, self.config)
        ok, reasons = is_stable_kidney_result(
            self.market, false_profile, false_res.central_selection, false_res.local_selections, false_res.utility
        )
        self.assertTrue(ok, msg=reasons)


class KidCTiebreakMultipleOptima(unittest.TestCase):
    """KID-C. Same market as KID-A/B: pins the TIE itself (both {(u1,u2)}
    and {(u1,u3)} are cardinality-2 feasible selections) and that the
    declared tiebreak, not incidental order, is what picks the winner."""

    def setUp(self):
        self.market = KidneyMarket(
            pairs=("u1", "u2", "u3"),
            hospital_of={"u1": "HA", "u2": "HB", "u3": "HA"},
            hospitals=("HA", "HB"),
            edges=frozenset({("u1", "u2"), ("u2", "u1"), ("u1", "u3"), ("u3", "u1")}),
        )

    def test_both_alternatives_are_valid_cardinality_two_selections(self):
        from witness.oracles_kidney import is_valid_selection, is_maximum_cardinality

        pool = ("u1", "u2", "u3")
        for selection in (( ("u1", "u2"),), (("u1", "u3"),)):
            with self.subTest(selection=selection):
                ok, reasons = is_valid_selection(self.market, selection, pool)
                self.assertTrue(ok, msg=reasons)
                ok2, reasons2 = is_maximum_cardinality(self.market, selection, pool)
                self.assertTrue(ok2, msg=reasons2)

    def test_tiebreak_picks_the_cross_hospital_cycle_not_the_internal_one(self):
        profile = KidneyProfile.truthful(self.market)
        res = clear_kidney_exchange(self.market, profile, KidneyConfig())
        self.assertEqual(res.central_selection, (("u1", "u2"),))
        self.assertNotEqual(res.central_selection, (("u1", "u3"),))


class KidDIsolationNegativeControl(unittest.TestCase):
    """KID-D. A hospital with NO cross-hospital edges anywhere in the
    market. KIDNEY_EXCHANGE_SCOPE.md's required negative control: every
    legal report ties full revelation's utility, checked over the ENTIRE
    legal report space (2^3 - 1 = 7 misreports), not sampled.

    HA owns u1, u2, u3: u1<->u2 compatible (internal), u3 has no edges at
    all (not even to u1/u2). HB owns v1, fully disconnected from HA's pairs
    and from u3. No withholding by HA can ever do better than full
    revelation, because nothing HA owns can ever be claimed by another
    hospital (no cross edges exist) -- so whatever HA withholds from the
    central pool comes back to it, unchanged, for local clearing, and the
    internal u1<->u2 match is recovered either way.
    """

    def setUp(self):
        self.market = KidneyMarket(
            pairs=("u1", "u2", "u3", "v1"),
            hospital_of={"u1": "HA", "u2": "HA", "u3": "HA", "v1": "HB"},
            hospitals=("HA", "HB"),
            edges=frozenset({("u1", "u2"), ("u2", "u1")}),
        )
        self.config = KidneyConfig()

    def test_full_revelation_utility(self):
        profile = KidneyProfile.truthful(self.market)
        res = clear_kidney_exchange(self.market, profile, self.config)
        self.assertEqual(res.utility, {"HA": 2, "HB": 0}, msg=res.format_trace())

    def test_every_legal_report_ties_full_revelation_exhaustively(self):
        truthful_report = self.market.pairs_of("HA")
        truthful_utility = clear_kidney_exchange(
            self.market, KidneyProfile.truthful(self.market), self.config
        ).utility["HA"]
        self.assertEqual(truthful_utility, 2)

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


class KidneyModelValidation(unittest.TestCase):
    """Structural mutation targets `KIDNEY_EXCHANGE_SCOPE.md`'s "Required
    tests and controls" names explicitly: a one-way edge must never be
    accepted as a cycle, and a hospital can never report a pair it does not
    own or benefit from an invented edge."""

    def setUp(self):
        self.market = KidneyMarket(
            pairs=("u1", "u2"),
            hospital_of={"u1": "HA", "u2": "HB"},
            hospitals=("HA", "HB"),
            edges=frozenset({("u1", "u2")}),  # ONE-WAY ONLY: u1->u2, no u2->u1
        )

    def test_one_way_edge_is_not_a_cycle(self):
        from witness.kidney import candidate_cycles

        self.assertEqual(candidate_cycles(self.market, ("u1", "u2")), ())
        res = clear_kidney_exchange(self.market, KidneyProfile.truthful(self.market), KidneyConfig())
        self.assertEqual(res.central_selection, (), msg=res.format_trace())
        self.assertEqual(res.utility, {"HA": 0, "HB": 0}, msg=res.format_trace())

    def test_hospital_cannot_report_another_hospitals_pair(self):
        from witness.errors import ModelError

        profile = KidneyProfile(reports={"HA": ("u1", "u2"), "HB": ()})
        with self.assertRaises(ModelError):
            profile.validate_against(self.market)

    def test_market_rejects_a_self_loop_edge(self):
        from witness.errors import ModelError

        with self.assertRaises(ModelError):
            KidneyMarket(
                pairs=("u1",),
                hospital_of={"u1": "HA"},
                hospitals=("HA",),
                edges=frozenset({("u1", "u1")}),
            )


if __name__ == "__main__":
    unittest.main()
