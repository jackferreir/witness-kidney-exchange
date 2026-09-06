"""Tests for `witness.generate`'s reserve-structure generation
(`GeneratorConfig.reserve_mode` / `eligible_fraction` / `reserve_type` /
`precedence`, and `generate_reserves`), and for `generate_config`'s
`reserve_da` support.

Per REVIEWER.md's "test the property, not a proxy": determinism is checked by
actually shelling out to a fresh interpreter and comparing byte-identical
canonical JSON (not by calling the function twice in one process, which would
only prove the function is a pure function of its Python-level arguments, not
that it survives a real process boundary); the eligibility-fraction and
per-school-eligibility properties are checked with an explicit NON-VACUITY
assertion, so a generator that silently ignored `eligible_fraction` or that
drew eligibility globally instead of per-school would fail these tests rather
than pass them vacuously.
"""

from __future__ import annotations

import math
import subprocess
import sys
import unittest
from pathlib import Path

from witness.core import canonical_json
from witness.errors import ModelError
from witness.generate import (
    MECHANISM_RESERVE_DA,
    RESERVE_MODE_ALL,
    RESERVE_MODE_HALF,
    RESERVE_MODE_NONE,
    RESERVE_MODE_RANDOM,
    GeneratorConfig,
    generate_config,
    generate_instance,
    generate_reserves,
)
from witness.mechanisms import get_mechanism
from witness.reserves import ReserveConfig

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _reserves_to_plain_dict(reserves) -> dict:
    return {school: reserve.to_dict() for school, reserve in reserves.items()}


class TestCrossProcessDeterminism(unittest.TestCase):
    """(a) Determinism ACROSS PROCESSES, not just across two in-process calls."""

    def test_generate_reserves_is_byte_identical_in_a_fresh_subprocess(self):
        seed = "cross-process-reserve-seed"
        n_students, n_schools, index = 6, 4, 3

        gc = GeneratorConfig(
            n_students=n_students,
            n_schools=n_schools,
            seed=seed,
            reserve_mode=RESERVE_MODE_RANDOM,
            eligible_fraction=0.4,
        )
        market, _ = generate_instance(gc, index)
        in_process_reserves = generate_reserves(gc, index, market)
        in_process_json = canonical_json(_reserves_to_plain_dict(in_process_reserves))

        script = f"""
import sys
sys.path.insert(0, {str(PROJECT_ROOT)!r})
from witness.core import canonical_json
from witness.generate import GeneratorConfig, generate_instance, generate_reserves

gc = GeneratorConfig(
    n_students={n_students},
    n_schools={n_schools},
    seed={seed!r},
    reserve_mode="random",
    eligible_fraction=0.4,
)
market, _ = generate_instance(gc, {index})
reserves = generate_reserves(gc, {index}, market)
out = {{school: reserve.to_dict() for school, reserve in reserves.items()}}
print(canonical_json(out))
""".strip()

        proc = subprocess.run(
            [sys.executable, "-c", script],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, msg=f"subprocess failed: {proc.stderr}")
        subprocess_json = proc.stdout.strip()
        self.assertEqual(
            in_process_json,
            subprocess_json,
            "generate_reserves must produce byte-identical output in a fresh "
            "subprocess, not just across two calls in this same interpreter",
        )
        # Sanity: the digest actually contains something (a genuinely empty
        # comparison would pass vacuously).
        self.assertTrue(subprocess_json)


class TestReserveModeHalf(unittest.TestCase):
    """(b) reserve_mode='half' gives exactly ceil(capacity/2) everywhere."""

    def test_half_mode_reserves_ceil_capacity_over_two(self):
        gc = GeneratorConfig(
            n_students=11,
            n_schools=5,
            seed="half-mode-seed",
            capacity_mode="heterogeneous",
            reserve_mode=RESERVE_MODE_HALF,
        )
        checked_nonuniform_capacity = False
        for index in range(10):
            market, _ = generate_instance(gc, index)
            reserves = generate_reserves(gc, index, market)
            capacities = {c: market.capacity(c) for c in market.schools}
            if len(set(capacities.values())) > 1:
                checked_nonuniform_capacity = True
            for c in market.schools:
                expected = math.ceil(capacities[c] / 2)
                self.assertEqual(
                    reserves[c].reserved_seats,
                    expected,
                    f"school {c!r} at instance {index}: capacity={capacities[c]}",
                )
        # Not a proxy: make sure this was actually exercised against more
        # than one capacity value across the swept instances.
        self.assertTrue(checked_nonuniform_capacity)


class TestReserveModeNone(unittest.TestCase):
    """(c) reserve_mode='none' -> zero everywhere, including through
    generate_config for reserve_da."""

    def test_none_mode_reserves_zero_everywhere(self):
        # reserve_mode=NONE governs reserved_seats only -- eligible_fraction
        # is an orthogonal setting (a school with 0 reserved seats has no
        # reserve slot for eligibility to matter at, but generate_reserves
        # still records who WOULD be eligible, independently).
        gc = GeneratorConfig(
            n_students=8, n_schools=4, seed="none-mode-seed", reserve_mode=RESERVE_MODE_NONE
        )
        for index in range(5):
            market, _ = generate_instance(gc, index)
            reserves = generate_reserves(gc, index, market)
            for c in market.schools:
                self.assertEqual(reserves[c].reserved_seats, 0)

    def test_none_mode_generate_config_produces_all_zero_reserve_config(self):
        # eligible_fraction=0.0 here isolates the property under test: with
        # reserve_mode=NONE *and* nobody eligible, the resulting ReserveConfig
        # really is all-zero/all-open in every sense, not just seat count.
        gc = GeneratorConfig(
            n_students=8,
            n_schools=4,
            seed="none-mode-config-seed",
            reserve_mode=RESERVE_MODE_NONE,
            eligible_fraction=0.0,
        )
        index = 0
        market, _ = generate_instance(gc, index)
        cfg = generate_config(gc, index, MECHANISM_RESERVE_DA, market=market)
        self.assertIsInstance(cfg, ReserveConfig)
        self.assertEqual(cfg.mechanism, MECHANISM_RESERVE_DA)
        for c in market.schools:
            spec = cfg.reserve_for(c)
            self.assertEqual(spec.reserved_seats, 0)
            self.assertEqual(spec.eligible, ())


class TestEligibleFraction(unittest.TestCase):
    """(d) eligible_fraction extremes, plus a NON-VACUITY check at 0.5."""

    def test_zero_fraction_means_nobody_eligible_anywhere(self):
        gc = GeneratorConfig(
            n_students=7, n_schools=4, seed="elig-zero-seed", eligible_fraction=0.0
        )
        for index in range(25):
            market, _ = generate_instance(gc, index)
            reserves = generate_reserves(gc, index, market)
            for c in market.schools:
                self.assertEqual(reserves[c].eligible, ())

    def test_one_fraction_means_everybody_eligible_everywhere(self):
        gc = GeneratorConfig(
            n_students=7, n_schools=4, seed="elig-one-seed", eligible_fraction=1.0
        )
        for index in range(25):
            market, _ = generate_instance(gc, index)
            reserves = generate_reserves(gc, index, market)
            for c in market.schools:
                self.assertEqual(set(reserves[c].eligible), set(market.students))

    def test_half_fraction_is_not_vacuous_share_between_0_35_and_0_65(self):
        gc = GeneratorConfig(
            n_students=6, n_schools=4, seed="elig-half-seed", eligible_fraction=0.5
        )
        total_pairs = 0
        eligible_pairs = 0
        for index in range(200):
            market, _ = generate_instance(gc, index)
            reserves = generate_reserves(gc, index, market)
            for c in market.schools:
                spec = reserves[c]
                for s in market.students:
                    total_pairs += 1
                    if spec.is_eligible(s):
                        eligible_pairs += 1
        self.assertGreater(total_pairs, 0)
        share = eligible_pairs / total_pairs
        # A generator that ignored eligible_fraction (e.g. always 0, always 1,
        # or some unrelated fixed constant) fails this range check.
        self.assertGreater(share, 0.35, f"observed eligible share {share} too low")
        self.assertLess(share, 0.65, f"observed eligible share {share} too high")


class TestEligibilityIsPerSchool(unittest.TestCase):
    """(e) Eligibility must be drawn per (school, student) pair, not per
    student globally -- at least one student must come out eligible at one
    school and ineligible at another, over enough instances."""

    def test_some_student_is_eligible_at_one_school_and_not_another(self):
        gc = GeneratorConfig(
            n_students=6, n_schools=4, seed="elig-per-school-seed", eligible_fraction=0.5
        )
        found_example = None
        for index in range(200):
            market, _ = generate_instance(gc, index)
            reserves = generate_reserves(gc, index, market)
            for s in market.students:
                elig_at = [c for c in market.schools if reserves[c].is_eligible(s)]
                if 0 < len(elig_at) < len(market.schools):
                    found_example = (index, s, elig_at, list(market.schools))
                    break
            if found_example is not None:
                break
        self.assertIsNotNone(
            found_example,
            "expected at least one (instance, student) where eligibility differs "
            "across schools within 200 instances -- if this never happens, "
            "eligible_fraction is being applied as a single global draw per "
            "student instead of independently per school",
        )


class TestGenerateConfigRequiresMarketForReserveDA(unittest.TestCase):
    """(f) generate_config(mechanism='reserve_da', market=None) must raise,
    never silently build an empty (i.e. misleadingly RESERVE_MODE_NONE-shaped)
    reserve structure."""

    def test_reserve_da_without_market_raises_model_error(self):
        gc = GeneratorConfig(n_students=4, n_schools=3)
        with self.assertRaises(ModelError):
            generate_config(gc, 0, MECHANISM_RESERVE_DA)

    def test_other_mechanisms_do_not_need_a_market(self):
        gc = GeneratorConfig(n_students=4, n_schools=3)
        # Must not raise: market is only required for reserve_da.
        generate_config(gc, 0, "student_proposing_da")
        generate_config(gc, 0, "boston_immediate_acceptance")


class TestReserveConfigRoundTrip(unittest.TestCase):
    """(g) A generated ReserveConfig round-trips through the mechanism
    registry's own to_dict/config_from_dict machinery unchanged."""

    def test_round_trip_via_mechanism_registry(self):
        gc = GeneratorConfig(
            n_students=6,
            n_schools=4,
            seed="round-trip-seed",
            reserve_mode=RESERVE_MODE_RANDOM,
            eligible_fraction=0.4,
        )
        index = 2
        market, _ = generate_instance(gc, index)
        cfg = generate_config(gc, index, MECHANISM_RESERVE_DA, market=market)
        self.assertIsInstance(cfg, ReserveConfig)

        first = cfg.to_dict()
        spec = get_mechanism(MECHANISM_RESERVE_DA)
        rebuilt = spec.config_from_dict(first)
        second = rebuilt.to_dict()
        self.assertEqual(first, second)

    def test_round_trip_with_all_reserve_mode_too(self):
        gc = GeneratorConfig(
            n_students=5,
            n_schools=3,
            seed="round-trip-all-seed",
            reserve_mode=RESERVE_MODE_ALL,
            eligible_fraction=1.0,
        )
        index = 0
        market, _ = generate_instance(gc, index)
        cfg = generate_config(gc, index, MECHANISM_RESERVE_DA, market=market)
        first = cfg.to_dict()
        spec = get_mechanism(MECHANISM_RESERVE_DA)
        second = spec.config_from_dict(first).to_dict()
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
