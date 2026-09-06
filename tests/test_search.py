"""Tests for the manipulation search (`witness.search`) and its control mechanism
(`witness.controls`).

A note on the positive control ("canary") test below: the task's hand-verified
"VERIFIED CONTROL INSTANCE" computes that s2 misreporting the full permutation
`("c2","c1")` is profitable under `first_choice_bonus_da`, and that is confirmed here
byte-for-byte (see `test_canary_hand_verified_full_permutation_misreport_is_present`).
But `find_manipulation` is specified to return the FIRST profitable misreport in
*canonical* order (`ordered_subsets`: length ascending, then lexicographic by index),
and the misreport space is explicitly ALL ordered subsets of the schools -- including
truncated ones. Exhaustively searching that full space (as the search is required to,
per its own "do not prune" rule) finds a SHORTER profitable misreport first:
s2 submitting only `("c2",)` also wins c2 under this mechanism (verified below by
direct computation, independent of the search). So `find_manipulation` correctly
returns `false_report == ("c2",)`, not `("c2","c1")`. This is a real property of the
exhaustive search, not a bug: `("c2","c1")` remains a genuine manipulation and is
confirmed present in `find_all_manipulations`'s output. The essential canary property
-- the search finds a profitable manipulation for s2 under `first_choice_bonus_da`
(truthful_outcome None, false_outcome "c2"), and finds none under plain
`student_proposing_da` on the identical instance -- holds either way.
"""

from __future__ import annotations

import itertools
import math
import subprocess
import sys
import unittest
from pathlib import Path

from witness.controls import first_choice_bonus_priorities, run_first_choice_bonus_da
from witness.core import Market, Profile, canonical_json, content_hash
from witness.da import DAConfig, deferred_acceptance
from witness.search import (
    Witness,
    find_all_manipulations,
    find_manipulation,
    misreport_space,
    ordered_subsets,
    search_all_students,
)
from witness.tiebreak import RejectTies

PROJECT_ROOT = Path(__file__).resolve().parent.parent

#: Every key the exact witness dict schema must carry.
WITNESS_SCHEMA_KEYS = (
    "witness_version",
    "mechanism",
    "config",
    "market",
    "truthful_profile",
    "target",
    "truthful_report",
    "false_report",
    "truthful_assignment",
    "false_assignment",
    "truthful_outcome",
    "false_outcome",
    "truthful_outcome_rank",
    "false_outcome_rank",
    "preference_proof",
    "depth",
    "witness_id",
)


class OrderedSubsetsTestCase(unittest.TestCase):
    def test_counts_for_three_and_four_items(self):
        self.assertEqual(len(ordered_subsets(("a", "b", "c"))), 16)
        self.assertEqual(len(ordered_subsets(("a", "b", "c", "d"))), 65)

    def test_includes_empty_tuple(self):
        self.assertIn((), ordered_subsets(("a", "b", "c")))

    def test_no_duplicates(self):
        subsets = ordered_subsets(("a", "b", "c", "d"))
        self.assertEqual(len(subsets), len(set(subsets)))

    def test_identical_across_two_calls(self):
        self.assertEqual(ordered_subsets(("a", "b", "c")), ordered_subsets(("a", "b", "c")))

    def test_matches_documented_canonical_order(self):
        """Length ascending, then lexicographic by index in `items`."""
        expected = (
            (),
            ("a",),
            ("b",),
            ("c",),
            ("a", "b"),
            ("a", "c"),
            ("b", "a"),
            ("b", "c"),
            ("c", "a"),
            ("c", "b"),
            ("a", "b", "c"),
            ("a", "c", "b"),
            ("b", "a", "c"),
            ("b", "c", "a"),
            ("c", "a", "b"),
            ("c", "b", "a"),
        )
        self.assertEqual(ordered_subsets(("a", "b", "c")), expected)


def _small_market() -> Market:
    return Market(
        students=("s1", "s2", "s3"),
        schools=("c1", "c2"),
        capacities={"c1": 1, "c2": 1},
        priority_classes={
            "c1": (("s1",), ("s2",), ("s3",)),
            "c2": (("s1",), ("s2",), ("s3",)),
        },
    )


class MisreportSpaceTestCase(unittest.TestCase):
    def test_excludes_truthful_report(self):
        market = _small_market()
        truthful = ("c1", "c2")
        space = misreport_space(market, "s2", truthful)
        self.assertNotIn(truthful, space)

    def test_includes_reports_with_schools_absent_from_truthful_report(self):
        market = _small_market()
        truthful = ("c1",)  # s2 truthfully only ranks c1
        space = misreport_space(market, "s2", truthful)
        # ("c2",) mentions a school (c2) absent from the truthful report.
        self.assertIn(("c2",), space)
        self.assertIn(("c2", "c1"), space)

    def test_raises_when_max_space_exceeded(self):
        market = Market(
            students=("s1",),
            schools=("c1", "c2", "c3", "c4", "c5", "c6", "c7", "c8", "c9"),
            capacities={c: 1 for c in ("c1", "c2", "c3", "c4", "c5", "c6", "c7", "c8", "c9")},
            priority_classes={
                c: (("s1",),) for c in ("c1", "c2", "c3", "c4", "c5", "c6", "c7", "c8", "c9")
            },
        )
        with self.assertRaises(ValueError):
            misreport_space(market, "s1", (), max_space=200_000)


class NegativeControlTestCase(unittest.TestCase):
    """Sweep every instance of {2,3} students x 2 schools, capacities 1, every
    strict priority permutation per school, every possible report per student,
    under plain `student_proposing_da`. Deferred Acceptance is strategy-proof
    for students (Dubins & Freedman 1981 / Roth 1982), so this MUST find zero
    manipulations. If it finds any, that is a real finding about `witness.da`
    or `witness.search`, not something to paper over.
    """

    def _reports_for(self, schools):
        return ordered_subsets(schools)

    def _sweep(self, n: int):
        students = tuple(f"s{i}" for i in range(1, n + 1))
        schools = ("c1", "c2")
        reports = self._reports_for(schools)
        config = DAConfig(tiebreak=RejectTies())

        instances_swept = 0
        found: list[tuple] = []

        for order_c1 in itertools.permutations(students):
            for order_c2 in itertools.permutations(students):
                market = Market(
                    students=students,
                    schools=schools,
                    capacities={"c1": 1, "c2": 1},
                    priority_classes={
                        "c1": tuple((s,) for s in order_c1),
                        "c2": tuple((s,) for s in order_c2),
                    },
                )
                for combo in itertools.product(reports, repeat=n):
                    profile = Profile({s: combo[i] for i, s in enumerate(students)})
                    instances_swept += 1
                    witnesses = search_all_students(
                        market, profile, "student_proposing_da", config
                    )
                    if witnesses:
                        found.append((market, profile, witnesses))
        return instances_swept, found

    def test_zero_manipulations_under_plain_da(self):
        total_swept = 0
        all_found: list[tuple] = []
        expected_by_n = {}
        for n in (2, 3):
            swept, found = self._sweep(n)
            # Independently computed expected instance count: (n!)^2 strict
            # priority-permutation pairs, times 5^n report combinations (5 =
            # the number of ordered subsets of 2 schools).
            n_reports = len(ordered_subsets(("c1", "c2")))
            expected = (math.factorial(n) ** 2) * (n_reports ** n)
            expected_by_n[n] = expected
            self.assertEqual(
                swept, expected, f"n={n}: swept {swept}, expected {expected}"
            )
            total_swept += swept
            all_found.extend(found)

        print(
            f"negative control: swept {total_swept} instances "
            f"({expected_by_n}), found {len(all_found)} manipulations"
        )
        self.assertEqual(total_swept, 4600)

        if all_found:
            lines = ["NEGATIVE CONTROL FAILURE: plain student_proposing_da is manipulable:"]
            for market, profile, witnesses in all_found:
                lines.append(f"market={market.to_dict()!r}")
                lines.append(f"profile={profile.to_dict()!r}")
                for w in witnesses:
                    lines.append(
                        f"  target={w.target!r} truthful_report={w.truthful_report!r} "
                        f"false_report={w.false_report!r} "
                        f"truthful_assignment={w.truthful_assignment!r} "
                        f"false_assignment={w.false_assignment!r}"
                    )
            self.fail("\n".join(lines))


class PositiveControlCanaryTestCase(unittest.TestCase):
    """The VERIFIED CONTROL INSTANCE: students ("s1","s2","s3"), schools
    ("c1","c2"), capacities 1 each, identical strict priorities s1>s2>s3 at both
    schools, truthful profile s1:(c1,c2) s2:(c1,c2) s3:(c2,c1)."""

    def _market(self) -> Market:
        return Market(
            students=("s1", "s2", "s3"),
            schools=("c1", "c2"),
            capacities={"c1": 1, "c2": 1},
            priority_classes={
                "c1": (("s1",), ("s2",), ("s3",)),
                "c2": (("s1",), ("s2",), ("s3",)),
            },
        )

    def _profile(self) -> Profile:
        return Profile(
            {"s1": ("c1", "c2"), "s2": ("c1", "c2"), "s3": ("c2", "c1")}
        )

    def _config(self) -> DAConfig:
        return DAConfig(tiebreak=RejectTies(), mechanism="first_choice_bonus_da")

    def test_hand_verified_truthful_priorities_and_assignment(self):
        market, profile, config = self._market(), self._profile(), self._config()
        priorities = first_choice_bonus_priorities(market, profile, config)
        self.assertEqual(priorities.orders["c1"], ("s1", "s2", "s3"))
        self.assertEqual(priorities.orders["c2"], ("s3", "s1", "s2"))

        assignment = run_first_choice_bonus_da(market, profile, config)
        self.assertEqual(
            assignment.student_to_school, {"s1": "c1", "s2": None, "s3": "c2"}
        )

    def test_hand_verified_full_permutation_misreport_priorities_and_assignment(self):
        market, profile, config = self._market(), self._profile(), self._config()
        misreport_profile = profile.with_report("s2", ("c2", "c1"))

        priorities = first_choice_bonus_priorities(market, misreport_profile, config)
        self.assertEqual(priorities.orders["c1"], ("s1", "s2", "s3"))
        self.assertEqual(priorities.orders["c2"], ("s2", "s3", "s1"))

        assignment = run_first_choice_bonus_da(market, misreport_profile, config)
        self.assertEqual(
            assignment.student_to_school, {"s1": "c1", "s2": "c2", "s3": None}
        )

    def test_canary_hand_verified_full_permutation_misreport_is_present(self):
        """`("c2","c1")` -- the misreport hand-verified in the task spec -- is
        present among ALL of s2's profitable manipulations, with the stated
        truthful/false outcomes."""
        market, profile, config = self._market(), self._profile(), self._config()
        all_witnesses = find_all_manipulations(
            market, profile, "s2", "first_choice_bonus_da", config
        )
        matches = [w for w in all_witnesses if w.false_report == ("c2", "c1")]
        self.assertEqual(len(matches), 1, all_witnesses)
        w = matches[0]
        self.assertIsNone(w.truthful_outcome)
        self.assertEqual(w.false_outcome, "c2")

    def test_canary_find_manipulation_finds_the_canonically_first_manipulation(self):
        """The exhaustive, non-pruning search finds the FIRST profitable
        misreport in canonical (length-ascending) order, which is the shorter
        truncated report `("c2",)` -- also verified directly here, independent
        of the search, to actually win c2 for s2."""
        market, profile, config = self._market(), self._profile(), self._config()

        # Independent, direct confirmation that ("c2",) truly is profitable,
        # not relying on the search's own logic.
        truncated_profile = profile.with_report("s2", ("c2",))
        truncated_assignment = run_first_choice_bonus_da(market, truncated_profile, config)
        self.assertEqual(truncated_assignment.student_to_school["s2"], "c2")

        w = find_manipulation(market, profile, "s2", "first_choice_bonus_da", config)
        self.assertIsNotNone(w)
        self.assertEqual(w.false_report, ("c2",))
        self.assertIsNone(w.truthful_outcome)
        self.assertEqual(w.false_outcome, "c2")

    def test_canary_cross_check_plain_da_not_manipulable_here(self):
        """Cross-check: under PLAIN student_proposing_da on this same instance,
        s2 gets c2 truthfully and gains nothing by lying."""
        market, profile = self._market(), self._profile()
        # Deliberately NOT self._config(): that config's mechanism field is
        # "first_choice_bonus_da" (see below), and this test searches
        # "student_proposing_da" instead -- so it needs its own config whose
        # mechanism field agrees, or witness.search's mechanism/config guard
        # would (correctly) refuse to search.
        config = DAConfig(tiebreak=RejectTies(), mechanism="student_proposing_da")

        truthful = deferred_acceptance(market, profile, config)
        self.assertEqual(truthful.assignment.of("s2"), "c2")

        w = find_manipulation(market, profile, "s2", "student_proposing_da", config)
        self.assertIsNone(w)


class DeterminismTestCase(unittest.TestCase):
    def _instance(self):
        market = Market(
            students=("s1", "s2", "s3"),
            schools=("c1", "c2"),
            capacities={"c1": 1, "c2": 1},
            priority_classes={
                "c1": (("s1",), ("s2",), ("s3",)),
                "c2": (("s1",), ("s2",), ("s3",)),
            },
        )
        profile = Profile({"s1": ("c1", "c2"), "s2": ("c1", "c2"), "s3": ("c2", "c1")})
        config = DAConfig(tiebreak=RejectTies(), mechanism="first_choice_bonus_da")
        return market, profile, config

    def test_repeated_calls_return_equal_witness(self):
        market, profile, config = self._instance()
        w1 = find_manipulation(market, profile, "s2", "first_choice_bonus_da", config)
        w2 = find_manipulation(market, profile, "s2", "first_choice_bonus_da", config)
        self.assertIsNotNone(w1)
        self.assertEqual(w1.to_dict(), w2.to_dict())
        self.assertEqual(w1.witness_id, w2.witness_id)

    def test_witness_id_is_content_hash_of_dict_without_itself(self):
        market, profile, config = self._instance()
        w = find_manipulation(market, profile, "s2", "first_choice_bonus_da", config)
        d = w.to_dict()
        without_id = {k: v for k, v in d.items() if k != "witness_id"}
        self.assertEqual(w.witness_id, content_hash(without_id))

    def test_witness_id_reproduced_in_fresh_subprocess(self):
        market, profile, config = self._instance()
        w = find_manipulation(market, profile, "s2", "first_choice_bonus_da", config)
        self.assertIsNotNone(w)

        market_json = canonical_json(market.to_dict())
        profile_json = canonical_json(profile.to_dict())
        config_json = canonical_json(config.to_dict())

        script = f"""
import json
from witness.core import Market, Profile
from witness.da import DAConfig
from witness.search import find_manipulation

market = Market.from_dict(json.loads({market_json!r}))
profile = Profile.from_dict(json.loads({profile_json!r}))
config = DAConfig.from_dict(json.loads({config_json!r}))

w = find_manipulation(market, profile, "s2", "first_choice_bonus_da", config)
print(w.witness_id)
"""
        proc = subprocess.run(
            [sys.executable, "-c", script],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertEqual(proc.stdout.strip(), w.witness_id)


class WitnessSchemaTestCase(unittest.TestCase):
    def _witness(self) -> Witness:
        market = Market(
            students=("s1", "s2", "s3"),
            schools=("c1", "c2"),
            capacities={"c1": 1, "c2": 1},
            priority_classes={
                "c1": (("s1",), ("s2",), ("s3",)),
                "c2": (("s1",), ("s2",), ("s3",)),
            },
        )
        profile = Profile({"s1": ("c1", "c2"), "s2": ("c1", "c2"), "s3": ("c2", "c1")})
        config = DAConfig(tiebreak=RejectTies(), mechanism="first_choice_bonus_da")
        w = find_manipulation(market, profile, "s2", "first_choice_bonus_da", config)
        assert w is not None
        return w

    def test_all_schema_keys_present(self):
        d = self._witness().to_dict()
        for key in WITNESS_SCHEMA_KEYS:
            self.assertIn(key, d)
        self.assertEqual(set(d), set(WITNESS_SCHEMA_KEYS))

    def test_round_trip_to_dict_from_dict_to_dict(self):
        w = self._witness()
        d1 = w.to_dict()
        w2 = Witness.from_dict(d1)
        d2 = w2.to_dict()
        self.assertEqual(d1, d2)

    def test_config_dict_is_json_able(self):
        d = self._witness().to_dict()
        # Round trips through canonical_json without raising.
        canonical_json(d)


class NoMutationTestCase(unittest.TestCase):
    def test_search_does_not_mutate_input_profile(self):
        market = Market(
            students=("s1", "s2", "s3"),
            schools=("c1", "c2"),
            capacities={"c1": 1, "c2": 1},
            priority_classes={
                "c1": (("s1",), ("s2",), ("s3",)),
                "c2": (("s1",), ("s2",), ("s3",)),
            },
        )
        profile = Profile({"s1": ("c1", "c2"), "s2": ("c1", "c2"), "s3": ("c2", "c1")})
        config = DAConfig(tiebreak=RejectTies(), mechanism="first_choice_bonus_da")

        before = dict(profile.rankings)
        search_all_students(market, profile, "first_choice_bonus_da", config)
        after = dict(profile.rankings)

        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
