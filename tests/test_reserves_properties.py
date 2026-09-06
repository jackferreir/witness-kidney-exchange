"""Properties of witness.reserves that the hand-worked traces cannot check.

Four things are verified here, each by DOING the thing rather than by
checking a proxy for it:

  1. RES-D's zero is not a dead search. The same market and the same search
     entry point DO find manipulations when pointed at a manipulable
     mechanism, so "zero" is a fact about reserve_da.
  2. The `choice_rule` hook added to `witness.da` did not change plain DA.
     Checked against an INDEPENDENT reimplementation of the pre-hook inner
     block, over generated instances, comparing the full trace -- not by
     observing that the existing suite stayed green, which is the proxy.
  3. reserve_da with no reserved seats anywhere is plain DA, trace for trace.
  4. A reserve configuration survives a round trip through JSON and a FRESH
     SUBPROCESS and reproduces the identical assignment.
"""

from __future__ import annotations

import json
import subprocess
import sys
import unittest

from witness.core import Market, Profile, canonical_json, resolve_priorities
from witness.da import DAConfig, deferred_acceptance
from witness.generate import GeneratorConfig, generate_instance
from witness.mechanisms import get_mechanism
from witness.reserves import (
    PRECEDENCE_OPEN_FIRST,
    PRECEDENCE_RESERVE_FIRST,
    RESERVE_HARD,
    RESERVE_SOFT,
    ReserveConfig,
    SchoolReserve,
    reserve_da,
)
from witness.search import find_all_manipulations


def singles(order):
    return tuple((s,) for s in order)


def res_d_market():
    """The exact market RES-D searches, so the vacuity check runs on it."""
    order = ("r1", "m1", "r2", "m2")
    market = Market(
        students=order,
        schools=("c1", "c2"),
        capacities={"c1": 2, "c2": 1},
        priority_classes={"c1": singles(order), "c2": singles(order)},
    )
    profile = Profile({s: ("c1", "c2") for s in order})
    return market, profile


class NegativeControlIsNotVacuous(unittest.TestCase):
    """An invariant nothing has ever been observed to violate is
    indistinguishable from one that cannot be violated. RES-D reports zero
    manipulations for reserve_da; this shows the same market, searched the
    same way, is one where manipulations ARE findable."""

    def test_boston_finds_manipulations_on_the_same_market(self):
        from witness.boston import BostonConfig

        market, profile = res_d_market()
        cfg = BostonConfig(mechanism="boston_immediate_acceptance")
        total = sum(
            len(find_all_manipulations(market, profile, s, "boston_immediate_acceptance", cfg))
            for s in market.students
        )
        self.assertGreater(
            total, 0,
            "the RES-D market yields no manipulations even under Boston, so "
            "RES-D's zero says nothing about reserve_da",
        )

    def test_first_choice_bonus_canary_also_fires_here(self):
        market, profile = res_d_market()
        cfg = DAConfig(mechanism="first_choice_bonus_da")
        total = sum(
            len(find_all_manipulations(market, profile, s, "first_choice_bonus_da", cfg))
            for s in market.students
        )
        self.assertGreater(total, 0)


def _pre_hook_da_rosters(market, profile, config):
    """An independent reimplementation of the DA inner block AS IT WAS before
    the `choice_rule` hook: sort the pool by rank, keep the first q_c, drop
    the rest. Deliberately written out here rather than imported, so that a
    change to `witness.da` cannot silently change what it is compared against.
    """
    priorities = resolve_priorities(market, config)
    report = {s: profile.report(s) for s in market.students}
    nxt = {s: 0 for s in market.students}
    holder = {s: None for s in market.students}
    held = {c: () for c in market.schools}
    trace = []
    while True:
        free = tuple(
            s for s in market.students
            if holder[s] is None and nxt[s] < len(report[s])
        )
        if not free:
            break
        proposals = []
        for s in free:
            c = report[s][nxt[s]]
            nxt[s] += 1
            proposals.append((s, c))
        rejected = []
        for c in market.schools:
            applicants = tuple(s for s, t in proposals if t == c)
            acceptable = [s for s in applicants if priorities.rank(c, s) is not None]
            if not acceptable:
                continue
            pool = held[c] + tuple(acceptable)
            ranked = sorted(pool, key=lambda s: priorities.rank(c, s))
            keep = tuple(ranked[: market.capacity(c)])
            drop = tuple(ranked[market.capacity(c):])
            held[c] = keep
            for s in keep:
                holder[s] = c
            for s in drop:
                holder[s] = None
                rejected.append((s, c))
        trace.append((tuple(proposals), tuple(rejected),
                      tuple((c, held[c]) for c in market.schools if held[c])))
    return dict(holder), trace


class ChoiceRuleHookPreservesPlainDA(unittest.TestCase):
    def test_matches_pre_hook_implementation_over_generated_instances(self):
        checked = 0
        for n_schools in (2, 3):
            for seed in ("hook-a", "hook-b"):
                gc = GeneratorConfig(
                    n_students=5, n_schools=n_schools, seed=seed,
                    list_length_mode="uniform", tiebreak_family="stb",
                )
                for i in range(150):
                    market, profile = generate_instance(gc, i)
                    cfg = DAConfig(
                        tiebreak=__import__(
                            "witness.tiebreak", fromlist=["SingleLotteryTiebreak"]
                        ).SingleLotteryTiebreak(seed=f"{seed}-{i}"),
                        unlisted_student_policy="lowest_priority_class",
                    )
                    got = deferred_acceptance(market, profile, cfg)
                    want_holder, want_trace = _pre_hook_da_rosters(market, profile, cfg)
                    self.assertEqual(
                        dict(got.assignment.student_to_school), want_holder
                    )
                    self.assertEqual(len(got.steps), len(want_trace))
                    for step, (props, rej, holds) in zip(got.steps, want_trace):
                        self.assertEqual(step.proposals, props)
                        self.assertEqual(step.rejected_by_competition, rej)
                        self.assertEqual(step.holds_after, holds)
                    checked += 1
        self.assertEqual(checked, 600)


class ZeroReservesIsPlainDA(unittest.TestCase):
    def test_trace_identical_with_no_reserved_seats(self):
        from witness.tiebreak import SingleLotteryTiebreak

        checked = 0
        for i in range(200):
            gc = GeneratorConfig(
                n_students=6, n_schools=3, seed="zero-reserve",
                list_length_mode="uniform", tiebreak_family="stb",
            )
            market, profile = generate_instance(gc, i)
            tb = SingleLotteryTiebreak(seed=f"zr-{i}")
            plain = deferred_acceptance(
                market, profile,
                DAConfig(tiebreak=tb, unlisted_student_policy="lowest_priority_class"),
            )
            for prec in (PRECEDENCE_RESERVE_FIRST, PRECEDENCE_OPEN_FIRST):
                for rtype in (RESERVE_SOFT, RESERVE_HARD):
                    got = reserve_da(
                        market, profile,
                        ReserveConfig(
                            tiebreak=tb,
                            unlisted_student_policy="lowest_priority_class",
                            reserves={}, precedence=prec, reserve_type=rtype,
                        ),
                    )
                    self.assertEqual(
                        got.assignment.to_dict(), plain.assignment.to_dict()
                    )
                    self.assertEqual(
                        [s.to_dict() for s in got.steps],
                        [s.to_dict() for s in plain.steps],
                    )
                    checked += 1
        self.assertEqual(checked, 800)


REPLAY_SNIPPET = """
import json, sys
from witness.core import Market, Profile
from witness.mechanisms import get_mechanism
payload = json.load(sys.stdin)
market = Market.from_dict(payload["market"])
profile = Profile.from_dict(payload["profile"])
spec = get_mechanism(payload["mechanism"])
config = spec.config_from_dict(payload["config"])
print(json.dumps(spec.run(market, profile, config).to_dict(), sort_keys=True))
"""


class ReserveConfigReplaysInAFreshProcess(unittest.TestCase):
    """The operational definition of a replayable result: rebuild from saved
    state alone, in a process that never saw the original objects."""

    def test_round_trip_through_subprocess(self):
        order = ("r1", "m1", "r2", "m2")
        market = Market(
            students=order, schools=("c1", "c2"),
            capacities={"c1": 2, "c2": 1},
            priority_classes={"c1": singles(order), "c2": singles(order)},
        )
        profile = Profile({s: ("c1", "c2") for s in order})
        for prec in (PRECEDENCE_RESERVE_FIRST, PRECEDENCE_OPEN_FIRST):
            for rtype in (RESERVE_SOFT, RESERVE_HARD):
                with self.subTest(precedence=prec, reserve_type=rtype):
                    cfg = ReserveConfig(
                        reserves={"c1": SchoolReserve(1, ("r1", "r2"))},
                        precedence=prec, reserve_type=rtype,
                    )
                    here = reserve_da(market, profile, cfg).assignment
                    payload = {
                        "market": market.to_dict(),
                        "profile": profile.to_dict(),
                        "mechanism": "reserve_da",
                        "config": cfg.to_dict(),
                    }
                    out = subprocess.run(
                        [sys.executable, "-c", REPLAY_SNIPPET],
                        input=canonical_json(payload), text=True,
                        capture_output=True, check=True,
                    )
                    self.assertEqual(
                        json.loads(out.stdout),
                        json.loads(json.dumps(here.to_dict(), sort_keys=True)),
                    )

    def test_config_survives_registry_round_trip(self):
        cfg = ReserveConfig(
            reserves={"c1": SchoolReserve(2, ("a", "b")), "c2": SchoolReserve(0, ())},
            precedence=PRECEDENCE_OPEN_FIRST, reserve_type=RESERVE_HARD,
        )
        rebuilt = get_mechanism("reserve_da").config_from_dict(cfg.to_dict())
        self.assertEqual(rebuilt.to_dict(), cfg.to_dict())


if __name__ == "__main__":
    unittest.main()
