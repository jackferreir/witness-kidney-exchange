"""Tests for witness/oracles.py.

The point of this file is part A: an exhaustive cross-check of
`deferred_acceptance` against `student_optimal_stable_matching`, a brute-force
oracle built directly from the definitions in Gale & Shapley (1962) rather
than from the DA algorithm. Agreement across the *entire* swept instance
space is the evidence that DA is implemented correctly; a disagreement
anywhere is a genuine finding about witness/da.py, not a test bug.

Run with:
    python3 -m unittest discover -s tests -t . -v
from the repository root. stdlib unittest only — no pytest.
"""

from __future__ import annotations

import itertools
import time
import unittest

from witness.core import (
    Market,
    MechanismConfig,
    Profile,
    UNLISTED_UNACCEPTABLE,
    resolve_priorities,
)
from witness.da import (
    ALL_FREE_SIMULTANEOUS,
    ONE_AT_A_TIME_DECLARED_ORDER,
    Assignment,
    DAConfig,
    deferred_acceptance,
)
from witness.errors import ModelError
from witness.oracles import (
    all_matchings,
    all_stable_matchings,
    blocking_pairs,
    is_individually_rational,
    is_stable,
    student_optimal_stable_matching,
)
from witness.tiebreak import RejectTies


def all_reports(schools: tuple[str, ...]) -> tuple[tuple[str, ...], ...]:
    """Every ordered subset of `schools`: the empty report, every single
    school, every pair in either order, etc. up to the full permutation.
    This is "every possible report" a student could submit over this exact
    school list, truncations included."""
    out: list[tuple[str, ...]] = []
    for r in range(0, len(schools) + 1):
        out.extend(itertools.permutations(schools, r))
    return tuple(out)


def build_market(
    students: tuple[str, ...], schools: tuple[str, ...], priority_orders: tuple[tuple[str, ...], ...]
) -> Market:
    """`priority_orders[i]` is a full strict order of `students` for
    `schools[i]`, expressed (per the task spec) as a tuple of singleton
    priority classes so RejectTies never has anything to break."""
    capacities = {c: 1 for c in schools}
    priority_classes = {
        c: tuple((s,) for s in priority_orders[i]) for i, c in enumerate(schools)
    }
    return Market(
        students=students,
        schools=schools,
        capacities=capacities,
        priority_classes=priority_classes,
    )


def sweep_instances(students: tuple[str, ...], schools: tuple[str, ...]):
    """Yield (market, profile) for every combination of:
      - a strict priority order (permutation of `students`) at each school
        independently, and
      - a report (every ordered subset of `schools`, empty and truncated
        included) for each student independently.
    All capacities are 1. Deterministic order (nested itertools.product over
    the declared students/schools tuples).
    """
    priority_order_choices = tuple(itertools.permutations(students))
    report_choices = all_reports(schools)

    for priority_orders in itertools.product(priority_order_choices, repeat=len(schools)):
        market = build_market(students, schools, priority_orders)
        for reports in itertools.product(report_choices, repeat=len(students)):
            rankings = {s: reports[i] for i, s in enumerate(students)}
            profile = Profile(rankings)
            yield market, profile


def expected_sweep_count(n_students: int, n_schools: int) -> int:
    n_priority_orders = 1
    for _ in range(n_schools):
        n_priority_orders *= _factorial(n_students)
    n_reports_per_student = sum(
        _permutations_count(n_schools, r) for r in range(0, n_schools + 1)
    )
    n_profiles = n_reports_per_student ** n_students
    return n_priority_orders * n_profiles


def _factorial(n: int) -> int:
    out = 1
    for i in range(2, n + 1):
        out *= i
    return out


def _permutations_count(n: int, r: int) -> int:
    out = 1
    for i in range(n, n - r, -1):
        out *= i
    return out


CONFIG = DAConfig(tiebreak=RejectTies(), unlisted_student_policy=UNLISTED_UNACCEPTABLE)
CONFIG_ONE_AT_A_TIME = DAConfig(
    tiebreak=RejectTies(),
    unlisted_student_policy=UNLISTED_UNACCEPTABLE,
    proposal_policy=ONE_AT_A_TIME_DECLARED_ORDER,
)

# The three shapes named in the task spec. Kept as a module-level constant so
# part A, B and C all sweep over exactly the same instances (computed once)
# instead of three independent, three-times-slower sweeps.
SHAPES = (
    ("2x2", ("s1", "s2"), ("c1", "c2")),
    ("3x2", ("s1", "s2", "s3"), ("c1", "c2")),
    ("2x3", ("s1", "s2"), ("c1", "c2", "c3")),
)


class TestExhaustiveCrossCheck(unittest.TestCase):
    """Part A/B/C: one sweep, three properties checked per instance.

    Ran the full space named in the task spec (2x2, 3x2, 2x3, all
    capacities 1, every strict priority order per school, every truncated
    report per student) — nothing was dropped. Expected instance count is
    computed independently (factorials/permutation counts) and asserted
    against the actual number swept, so this can't silently degenerate to
    checking zero instances.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.expected_counts = {}
        cls.actual_counts = {}
        for name, students, schools in SHAPES:
            cls.expected_counts[name] = expected_sweep_count(len(students), len(schools))

    def test_a_b_c_full_sweep(self) -> None:
        start = time.time()
        total_checked = 0
        priorities_cache: dict[int, object] = {}

        for name, students, schools in SHAPES:
            count_this_shape = 0
            for market, profile in sweep_instances(students, schools):
                count_this_shape += 1
                total_checked += 1

                priorities = resolve_priorities(market, CONFIG)

                # --- Part A: DA output equals the brute-force student-optimal
                # stable matching. ---
                da_result = deferred_acceptance(market, profile, CONFIG, priorities=priorities)
                oracle_result = student_optimal_stable_matching(market, profile, priorities)

                if da_result.assignment != oracle_result:
                    self.fail(
                        "DA disagrees with the brute-force student-optimal stable "
                        "matching oracle.\n"
                        f"market = {market.to_dict()!r}\n"
                        f"profile = {profile.to_dict()!r}\n"
                        f"priorities = {priorities.to_dict()!r}\n"
                        f"DA assignment      = {da_result.assignment.to_dict()!r}\n"
                        f"oracle assignment   = {oracle_result.to_dict()!r}"
                    )

                # --- Part B: the DA output is stable, checked by the
                # independent definitional oracle. ---
                if not is_stable(market, profile, priorities, da_result.assignment):
                    ok, reasons = is_individually_rational(
                        market, profile, priorities, da_result.assignment
                    )
                    self.fail(
                        "DA produced an assignment the definitional oracle says is not "
                        "stable.\n"
                        f"market = {market.to_dict()!r}\n"
                        f"profile = {profile.to_dict()!r}\n"
                        f"priorities = {priorities.to_dict()!r}\n"
                        f"assignment = {da_result.assignment.to_dict()!r}\n"
                        f"individually_rational = {ok}, reasons = {reasons!r}\n"
                        f"blocking_pairs = "
                        f"{blocking_pairs(market, profile, priorities, da_result.assignment)!r}"
                    )

                # --- Part C: proposal-policy invariance. ---
                da_one_at_a_time = deferred_acceptance(
                    market, profile, CONFIG_ONE_AT_A_TIME, priorities=priorities
                )
                if da_one_at_a_time.assignment != da_result.assignment:
                    self.fail(
                        "ALL_FREE_SIMULTANEOUS and ONE_AT_A_TIME_DECLARED_ORDER produced "
                        "different assignments on the same instance.\n"
                        f"market = {market.to_dict()!r}\n"
                        f"profile = {profile.to_dict()!r}\n"
                        f"priorities = {priorities.to_dict()!r}\n"
                        f"ALL_FREE_SIMULTANEOUS assignment    = {da_result.assignment.to_dict()!r}\n"
                        f"ONE_AT_A_TIME_DECLARED_ORDER assignment = "
                        f"{da_one_at_a_time.assignment.to_dict()!r}"
                    )

            self.assertEqual(
                count_this_shape,
                self.expected_counts[name],
                f"shape {name}: swept {count_this_shape} instances, expected "
                f"{self.expected_counts[name]} — the sweep silently degenerated",
            )

        elapsed = time.time() - start
        print(
            f"\n[test_oracles] swept {total_checked} instances across shapes "
            f"{[n for n, _, _ in SHAPES]!r} in {elapsed:.2f}s "
            f"(A: DA == oracle, B: DA output stable, C: proposal-policy invariance)"
        )
        self.assertGreater(total_checked, 0)
        # Fails loudly, with the actual counts, if the sweep space silently
        # changed shape (e.g. a bug in all_reports or sweep_instances).
        self.assertEqual(total_checked, sum(self.expected_counts.values()))


class TestOracleSelfCheck(unittest.TestCase):
    """Part D: prove the oracles themselves are not vacuous — they must
    actually catch violations we construct by hand, not just rubber-stamp
    whatever they're given."""

    def setUp(self) -> None:
        self.market = Market(
            students=("s1", "s2"),
            schools=("c1", "c2"),
            capacities={"c1": 1, "c2": 1},
            priority_classes={"c1": (("s1",), ("s2",)), "c2": (("s1",), ("s2",))},
        )
        self.profile = Profile({"s1": ("c1", "c2"), "s2": ("c1", "c2")})
        self.priorities = resolve_priorities(
            self.market, MechanismConfig(tiebreak=RejectTies())
        )

    def test_blocking_pairs_exact(self) -> None:
        # s1 and s2 both prefer c1, both rank first at c1, but this
        # assignment swaps them onto their second choice: (s1, c1) blocks.
        bad = Assignment(
            student_to_school={"s1": "c2", "s2": "c1"},
            school_to_students={"c1": ("s2",), "c2": ("s1",)},
        )
        self.assertEqual(
            blocking_pairs(self.market, self.profile, self.priorities, bad),
            (("s1", "c1"),),
        )
        self.assertFalse(is_stable(self.market, self.profile, self.priorities, bad))

    def test_ir_catches_school_not_on_report(self) -> None:
        profile = Profile({"s1": ("c1",), "s2": ("c1", "c2")})
        bad = Assignment(
            student_to_school={"s1": "c2", "s2": None},
            school_to_students={"c1": (), "c2": ("s1",)},
        )
        ok, reasons = is_individually_rational(self.market, profile, self.priorities, bad)
        self.assertFalse(ok)
        self.assertTrue(any("absent from their own report" in r for r in reasons))

    def test_ir_catches_over_capacity(self) -> None:
        bad = Assignment(
            student_to_school={"s1": "c1", "s2": "c1"},
            school_to_students={"c1": ("s1", "s2"), "c2": ()},
        )
        ok, reasons = is_individually_rational(self.market, self.profile, self.priorities, bad)
        self.assertFalse(ok)
        self.assertTrue(any("exceeding its capacity" in r for r in reasons))

    def test_ir_catches_unacceptable_hold(self) -> None:
        # c1's priority order lists only s1, s2 — both acceptable in
        # self.market. Build a market where c1 finds s2 unacceptable, then
        # hand it a matching that assigns s2 to c1 anyway.
        market = Market(
            students=("s1", "s2"),
            schools=("c1", "c2"),
            capacities={"c1": 1, "c2": 1},
            priority_classes={"c1": (("s1",),), "c2": (("s1",), ("s2",))},
        )
        priorities = resolve_priorities(market, MechanismConfig(tiebreak=RejectTies()))
        profile = Profile({"s1": ("c2",), "s2": ("c1", "c2")})
        bad = Assignment(
            student_to_school={"s1": None, "s2": "c1"},
            school_to_students={"c1": ("s2",), "c2": ()},
        )
        ok, reasons = is_individually_rational(market, profile, priorities, bad)
        self.assertFalse(ok)
        self.assertTrue(any("unacceptable to it" in r for r in reasons))

    def test_all_stable_matchings_nonempty_and_sometimes_multiple(self) -> None:
        for market, profile in sweep_instances(("s1", "s2"), ("c1", "c2")):
            priorities = resolve_priorities(market, CONFIG)
            stable = all_stable_matchings(market, profile, priorities)
            self.assertGreater(
                len(stable),
                0,
                f"no stable matching found for market={market.to_dict()!r} "
                f"profile={profile.to_dict()!r} — a stable matching always exists",
            )

        # Hardcoded instance with more than one stable matching: the classic
        # 2x2 "opposite preferences, opposite priorities" example. Students
        # disagree with schools about who's best, so both
        # (s1-c1, s2-c2) and (s1-c2, s2-c1) are stable.
        market = Market(
            students=("s1", "s2"),
            schools=("c1", "c2"),
            capacities={"c1": 1, "c2": 1},
            priority_classes={"c1": (("s2",), ("s1",)), "c2": (("s1",), ("s2",))},
        )
        profile = Profile({"s1": ("c1", "c2"), "s2": ("c2", "c1")})
        priorities = resolve_priorities(market, MechanismConfig(tiebreak=RejectTies()))
        stable = all_stable_matchings(market, profile, priorities)
        self.assertGreater(
            len(stable),
            1,
            f"expected multiple stable matchings on the opposite-preferences "
            f"instance, got {[a.to_dict() for a in stable]!r}",
        )
        # And DA (student-optimal) must pick the one both students like best:
        # each gets their own first choice.
        oracle = student_optimal_stable_matching(market, profile, priorities)
        self.assertEqual(oracle.of("s1"), "c1")
        self.assertEqual(oracle.of("s2"), "c2")


class TestAllMatchingsSpaceLimit(unittest.TestCase):
    """Part E: all_matchings must refuse to enumerate an oversized space."""

    def test_raises_when_max_space_exceeded(self) -> None:
        market = Market(
            students=("s1", "s2", "s3"),
            schools=("c1", "c2"),
            capacities={"c1": 1, "c2": 1},
            priority_classes={
                "c1": (("s1",), ("s2",), ("s3",)),
                "c2": (("s1",), ("s2",), ("s3",)),
            },
        )
        profile = Profile(
            {"s1": ("c1", "c2"), "s2": ("c1", "c2"), "s3": ("c1", "c2")}
        )
        priorities = resolve_priorities(market, MechanismConfig(tiebreak=RejectTies()))
        # Each student has 3 options (2 schools + None) -> 3**3 = 27 combos.
        with self.assertRaises(ValueError):
            list(all_matchings(market, profile, priorities, max_space=26))
        # And it does not raise once the limit actually covers the space.
        list(all_matchings(market, profile, priorities, max_space=27))


if __name__ == "__main__":
    unittest.main()
