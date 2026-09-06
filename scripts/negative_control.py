"""CLI: the negative control, run DEEP rather than wide.

WHAT THIS IS FOR:

    Plain student-proposing deferred acceptance is strategy-proof for the
    proposing side (Dubins & Freedman 1981; Roth 1982): no student can ever
    benefit from misreporting their preferences, in ANY market, no matter how
    the schools' priorities or capacities are shaped. That theorem is
    unconditional -- it does not have exceptions for over-subscription, short
    lists, unlisted students, coarse priority classes, or independent lottery
    families. So when this script runs `witness.search.search_all_students`
    under `"student_proposing_da"` (the default `--mechanism`) over any
    number of randomly generated instances, the ONLY correct outcome is ZERO
    manipulations, always. This is not a hoped-for result to tune toward: it
    is a mathematical certainty about the mechanism being tested. A single
    manipulation found here is not "interesting" or "a discovery" -- it is
    proof of a bug, either in `witness.da`, in `witness.search`, or in this
    generator/coverage plumbing, and the correct response is to stop and
    debug it, never to adjust the sweep so it goes away.

    Before this script existed, the negative control covered 11,520 instances
    spread across 288 configurations -- about 40 instances per configuration.
    That is broad (many market *shapes*) but shallow (each shape sampled only
    ~40 times, which is a spot check, not a search). "3C" -- this script's
    name for itself in the project's own numbering -- converts that breadth
    into DEPTH without collapsing back down to a single instance shape: it
    still sweeps `witness.generate.GeneratorConfig`'s full parameter space
    (subscription level, list length, school-listing fraction, priority-class
    count, capacity heterogeneity, tiebreak family, unlisted-student policy),
    but WEIGHTS that sweep toward the highest-contention regions (see the
    weight constants below) and then runs many thousands of instances per
    configuration rather than a few dozen, so "no manipulation found" means
    something close to "exhaustively checked this shape," not "sampled it a
    little."

RESUMABILITY AND DETERMINISM:

    Every configuration is a pure function of (`--seed`, config_index) --
    see `draw_configuration` -- and every instance of a configuration is a
    pure function of (that configuration's own derived seed, instance_index)
    -- see `witness.generate.generate_instance`. Neither depends on how many
    workers ran, in what order, or on anything left over from a previous
    invocation. That is what makes `--resume` safe: the checkpoint file only
    ever records WHICH configurations are already fully processed, never
    what to draw or generate, so resuming (or re-running from scratch)
    reproduces bit-for-bit the same instances a single uninterrupted pass
    would have.

    Output order is likewise independent of `--workers`: results for a batch
    of pending configurations are always collected into memory, sorted by
    `config_index`, and only then appended to the journal -- see `run_sweep`.

REPORTING / SIZING:

    `<out>/negative_control_summary.json` always carries `wall_seconds`,
    `instances_per_second`, and `mean_seconds_per_instance` for the
    invocation that just ran (never omitted, never left to be inferred from
    a stopwatch) -- these are the numbers sizing decisions get made from,
    and this project has already been burned once by quoting a
    per-instance cost measured at the smallest market shape in the sweep
    and extrapolating it to the whole thing. Per-configuration cost is
    NOT uniform: it is dominated by `mechanism_runs_per_instance` (see that
    function) -- `n_students * (the number of ordered subsets of
    n_schools)` -- which every `<out>/negative_control.jsonl` record and
    the summary's own `total_mechanism_runs` both carry, so a reader can
    see directly why one configuration (e.g. 6 students x 5 schools, 1,956
    mechanism runs per instance) is orders of magnitude slower than another
    (e.g. 3 students x 3 schools, 48 mechanism runs per instance) even at
    the same instance count. Every per-configuration record also carries
    `instances_run`, the actual (never null) number of instances that
    configuration ran.

ON A HIT:

    The moment ANY instance yields a manipulation, this script re-verifies
    it with `witness.replay.verify_in_subprocess` (a genuinely fresh
    process -- see that module's docstring), records it to
    `<out>/negative_control_hits.jsonl`, prints the full market / profile /
    mechanism config / witness so it can be inspected without re-running
    anything, and ABORTS with a non-zero exit code. It does not keep
    sweeping past a hit: a mechanism that fails its negative control has
    nothing further to teach us until the bug is found, and continuing
    would only produce more instances of the same bug.

--expect: ZERO vs MANIPULATIONS.

    Everything above describes `--expect zero`: manipulations are a BUG, so
    the first one aborts the run. That is correct for a strategy-proof
    mechanism (`student_proposing_da`), but wrong for a mechanism that is
    manipulable BY DESIGN (`boston_immediate_acceptance`) -- there, a
    manipulation is the EXPECTED, calibration-relevant outcome, and aborting
    on the first one means the singleton-sufficiency invariant
    (`witness.invariants`) is barely ever exercised through this runner.

    `--expect manipulations` is the other mode: manipulations are counted
    and recorded (`manipulable_cases`, `instances_with_manipulation`, per
    configuration and in the summary), never aborted on. A sample of them
    (`--verify-hits N` per configuration, default 1) is still independently
    re-verified in a fresh subprocess -- verification is not skipped just
    because hits are expected, only made affordable by sampling
    (`hits_verified` / `hits_unverified` record exactly how much of the
    total was actually checked). Every recorded witness is appended to
    `<out>/witnesses.jsonl` (capped by `--max-witnesses`, default 1000, with
    the omitted count recorded).

    `<out>/witnesses.jsonl` IS THE ARTIFACT OF RECORD: each line is a BARE
    witness dict, in EXACTLY the schema `witness.replay` consumes (the same
    schema `witness.search.search_all_students` produces via `.to_dict()`)
    -- nothing else is ever nested inside it, and nothing of this script's
    own bookkeeping (`config_index`, `instance_index`) is added to it. That
    is what makes the file directly replayable with
    `python3 -m witness.replay --jsonl <out>/witnesses.jsonl` in a fresh
    process, which is this project's actual definition of a finding: a
    witness file the replay CLI cannot consume is not a record of anything.
    The `config_index` / `instance_index` provenance for each recorded
    witness is genuinely useful, so it is not discarded -- it is written
    instead to a SEPARATE sidecar file, `<out>/witness_index.jsonl`, one line
    per recorded witness, as `{"witness_id": ..., "config_index": ...,
    "instance_index": ...}`, keyed by the witness's own `witness_id` so the
    two files can be joined without ever polluting the witness object
    itself. The singleton-sufficiency check
    (`witness.invariants.is_proved_regime` decides assert-vs-record, exactly
    as elsewhere) now runs across EVERY instance in this mode, not just
    those before an abort -- a violation still aborts unconditionally, and a
    FAILED sampled verification still aborts unconditionally too (written to
    `<out>/verification_failures.jsonl`): both are real defects, regardless
    of which `--expect` mode is running.

    Each mechanism has a sensible default (`student_proposing_da` ->
    `zero`, `boston_immediate_acceptance` -> `manipulations`), but an
    explicit `--expect` on the command line always wins. Passing
    `--expect zero` against a manipulable mechanism is honoured (it is a
    legitimate thing to test -- e.g. "does Boston still abort here") but
    prints a one-line notice that the run is expected to abort. The
    resolved value is always recorded, in every per-configuration record and
    in the summary, under the key `"expect"`.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import multiprocessing
import os
import sys
import tempfile
import time
from typing import Mapping, Optional, Sequence

# Make `witness` importable when this file is run directly as
# `python3 scripts/negative_control.py ...`, mirroring
# `scripts/search_power.py`'s own sys.path setup.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from witness.boston import boston_immediate_acceptance
from witness.core import UNLISTED_LOWEST_CLASS, UNLISTED_UNACCEPTABLE
from witness.coverage import BRANCH_NAMES, CoverageReport, aggregate, instance_coverage, unreached_branches
from witness.da import deferred_acceptance
from witness.errors import MechanismError, ModelError
from witness.generate import (
    CAPACITY_HETEROGENEOUS,
    CAPACITY_UNIFORM,
    LIST_COMPLETE,
    LIST_FIXED,
    LIST_SHORT,
    LIST_UNIFORM,
    MECHANISM_BOSTON_IMMEDIATE_ACCEPTANCE,
    MECHANISM_RESERVE_DA,
    MECHANISM_STUDENT_PROPOSING_DA,
    MECHANISM_TOP_TRADING_CYCLES,
    RESERVE_MODE_ALL,
    RESERVE_MODE_HALF,
    RESERVE_MODE_NONE,
    RESERVE_MODE_RANDOM,
    SUBSCRIPTION_EXACT,
    SUBSCRIPTION_OVER,
    SUBSCRIPTION_UNDER,
    TIEBREAK_MTB,
    TIEBREAK_STB,
    GeneratorConfig,
    derive_seed,
    generate_config,
    generate_instance,
)
from witness.invariants import (
    DEFAULT_MAX_SPACE as SINGLETON_MAX_SPACE,
    assert_singleton_sufficiency,
    check_instance,
    is_proved_regime,
)
from witness.journal import Journal
from witness.replay import verify_in_subprocess
from witness.ttc import distinct_priority_orders, top_trading_cycles
from witness.reserves import (
    PRECEDENCE_OPEN_FIRST,
    PRECEDENCE_RESERVE_FIRST,
    RESERVE_HARD,
    RESERVE_SOFT,
    reserve_da,
)
from witness.search import search_all_students

#: Mechanisms this script knows how to build a `GeneratorConfig`-derived
#: config for and run directly (for coverage) -- mirrors
#: `witness.generate`'s own supported set exactly, deliberately not the
#: larger `witness.mechanisms` registry (e.g. "first_choice_bonus_da" isn't
#: reachable from a `GeneratorConfig` at all -- see `generate_config`).
SUPPORTED_MECHANISMS = (
    MECHANISM_STUDENT_PROPOSING_DA,
    MECHANISM_BOSTON_IMMEDIATE_ACCEPTANCE,
    MECHANISM_RESERVE_DA,
    MECHANISM_TOP_TRADING_CYCLES,
)

#: `--reserve-mode` / `--reserve-type` / `--precedence` choices, mirroring
#: `witness.generate` / `witness.reserves`'s own named constants exactly --
#: never a bare string literal on the CLI surface.
_RESERVE_MODE_CHOICES = (RESERVE_MODE_NONE, RESERVE_MODE_HALF, RESERVE_MODE_ALL, RESERVE_MODE_RANDOM)
_RESERVE_TYPE_CHOICES = (RESERVE_SOFT, RESERVE_HARD)
_PRECEDENCE_CHOICES = (PRECEDENCE_RESERVE_FIRST, PRECEDENCE_OPEN_FIRST)

#: The three subscription levels, in the fixed order used for reporting.
_SUBSCRIPTIONS = (SUBSCRIPTION_OVER, SUBSCRIPTION_EXACT, SUBSCRIPTION_UNDER)

# =============================================================================
# --expect: zero (the negative control) vs manipulations (the positive /
# calibration mode). See the module docstring's "--expect: ZERO vs
# MANIPULATIONS" section for the full contract.
# =============================================================================

#: Manipulations are a BUG here: abort on the first one. The negative control.
EXPECT_ZERO = "zero"

#: Manipulations are EXPECTED here: count them, record them, never abort.
EXPECT_MANIPULATIONS = "manipulations"

VALID_EXPECTATIONS = (EXPECT_ZERO, EXPECT_MANIPULATIONS)

#: Per-mechanism default `--expect`, used whenever the flag is not given
#: explicitly on the command line. `student_proposing_da` is strategy-proof
#: (any hit is a bug); `boston_immediate_acceptance` is manipulable by
#: design (manipulations are the expected, calibration-relevant outcome).
#: `reserve_da` (student-proposing DA under the DKPS slot choice rule) is
#: ALSO strategy-proof for the proposing side -- substituting a different
#: (still substitutable) school choice rule into the same DA loop preserves
#: strategy-proofness (Dur, Kominers, Pathak & Sonmez 2018, footnote 19 and
#: section 5) -- so it defaults to `EXPECT_ZERO` exactly like plain DA: any
#: hit here is a bug, never a discovery.
DEFAULT_EXPECT_BY_MECHANISM = {
    MECHANISM_STUDENT_PROPOSING_DA: EXPECT_ZERO,
    MECHANISM_BOSTON_IMMEDIATE_ACCEPTANCE: EXPECT_MANIPULATIONS,
    MECHANISM_RESERVE_DA: EXPECT_ZERO,
    MECHANISM_TOP_TRADING_CYCLES: EXPECT_ZERO,
}


def resolve_expect(mechanism: str, explicit: "Optional[str]") -> str:
    """The `--expect` value actually in force: `explicit` if given (an
    explicit command-line `--expect` always wins), else `mechanism`'s own
    default from `DEFAULT_EXPECT_BY_MECHANISM`.
    """
    if explicit is not None:
        return explicit
    return DEFAULT_EXPECT_BY_MECHANISM[mechanism]

# =============================================================================
# Weighted configuration draw.
#
# Every weight below is an explicit, named, commented module constant, and
# the whole draw (see `draw_configuration`) is a pure function of (seed,
# config_index) -- nothing here is "tuned" by feel or drawn from the stdlib
# `random` module; every random-looking decision reduces to `hashlib.sha256`
# over (seed, config_index, purpose), the same non-negotiable construction
# `witness.generate` and `witness.tiebreak` use, for the same reason (see
# `witness.generate`'s own module docstring): reproducible across processes,
# machines, and Python versions.
# =============================================================================

#: subscription weights. OVER (fewer seats than students -- some student is
#: structurally guaranteed to be unmatched) gets HALF the draws: it is the
#: regime `witness.generate`'s own docstring measured at a 20-28%
#: manipulation rate for a mechanism that IS manipulable (Boston), i.e. the
#: single highest-contention regime available. EXACT gets just over a third
#: (still real contention: capacity binds exactly). UNDER (more seats than
#: students -- the least contention, and the regime where the fewest
#: interesting rejections happen) gets the remaining, deliberately smallest,
#: share -- kept well above zero only so that branch is still exercised.
SUBSCRIPTION_WEIGHTS: "tuple[tuple[str, float], ...]" = (
    (SUBSCRIPTION_OVER, 0.50),
    (SUBSCRIPTION_EXACT, 0.35),
    (SUBSCRIPTION_UNDER, 0.15),
)

#: `subscription_ratio` ranges to draw within, once a level is chosen --
#: kept strictly inside the bounds `GeneratorConfig.__post_init__` enforces
#: for that level (OVER < 1.0, UNDER > 1.0), with a small margin on each end
#: so floor/ceil rounding in `witness.generate._target_total_seats` can never
#: accidentally land exactly on `n` for small `n_students`.
OVER_SUBSCRIPTION_RATIO_RANGE = (0.50, 0.95)
UNDER_SUBSCRIPTION_RATIO_RANGE = (1.05, 2.00)

#: list_length_mode weights. SHORT and UNIFORM (both truncated, variable-
#: length reports -- exactly the shapes that make `had_incomplete_list` and
#: `had_very_short_list` bite) together take 70% of the draws; COMPLETE (no
#: truncation at all -- the least interesting shape for a strategy-proofness
#: check, since a complete ranking has no room to omit anything) is held to
#: the same, smallest, 15% share as FIXED.
LIST_LENGTH_WEIGHTS: "tuple[tuple[str, float], ...]" = (
    (LIST_SHORT, 0.35),
    (LIST_UNIFORM, 0.35),
    (LIST_FIXED, 0.15),
    (LIST_COMPLETE, 0.15),
)

#: Probability a configuration lists EVERY student at every school
#: (`school_lists_fraction == 1.0`). The complement (the majority of
#: configurations, per the task's explicit requirement) draws a fraction
#: uniformly from `SCHOOL_LISTS_FRACTION_RANGE`, so the unlisted-student
#: branch -- and `UNLISTED_LOWEST_CLASS` in particular -- actually fires most
#: of the time, not just occasionally.
SCHOOL_LISTS_FULL_PROBABILITY = 0.30
SCHOOL_LISTS_FRACTION_RANGE = (0.30, 0.95)

#: capacity_mode / tiebreak_family / unlisted_student_policy: the task gives
#: no directive to skew any of these, so each is an explicit, even coin
#: flip -- named and commented rather than left as an implicit default, per
#: this module's own "every weight is a named constant" rule.
CAPACITY_MODE_WEIGHTS: "tuple[tuple[str, float], ...]" = (
    (CAPACITY_UNIFORM, 0.5),
    (CAPACITY_HETEROGENEOUS, 0.5),
)
TIEBREAK_FAMILY_WEIGHTS: "tuple[tuple[str, float], ...]" = (
    (TIEBREAK_STB, 0.5),
    (TIEBREAK_MTB, 0.5),
)
UNLISTED_POLICY_WEIGHTS: "tuple[tuple[str, float], ...]" = (
    (UNLISTED_UNACCEPTABLE, 0.5),
    (UNLISTED_LOWEST_CLASS, 0.5),
)

#: n_priority_classes: a small uniform choice; the exact partition of listed
#: students into this many classes is itself deterministic per school and
#: instance inside `witness.generate._derive_priority_classes`.
N_PRIORITY_CLASSES_CHOICES = (1, 2, 3)

#: n_students / n_schools: kept deliberately SMALL and evenly weighted. This
#: is the one place this sweep trades width for depth on purpose --
#: `witness.search.misreport_space` enumerates every ordered subset of
#: `n_schools` schools (sum_{k=0}^{n} P(n, k), e.g. 326 for n_schools=5), and
#: every one of those is a full mechanism run, for every student, for every
#: instance. Running that enumeration to exhaustion (which a TRUE negative
#: control must do -- strategy-proofness gives no shortcut to "no
#: manipulation exists" the way finding one gives a shortcut to "one does")
#: at LARGE n across tens of thousands of instances is not the way to spend
#: the time budget; running it at small n, very many times, over a heavily
#: reweighted shape distribution, is.
N_STUDENTS_CHOICES = (3, 4, 5, 6)
N_SCHOOLS_CHOICES = (3, 4, 5)

#: These defaults give a mean capacity per school of about 1, and that is
#: FINE for the mechanisms they were chosen for -- plain DA and Boston both
#: exercise their whole choice rule at capacity 1.
#:
#: It is NOT fine for a mechanism whose choice rule has internal structure. A
#: school with one seat has one slot, so a reserve/open PRECEDENCE order over
#: its slots cannot possibly matter: measured over the 160 instances of the
#: first `--mechanism reserve_da` sweep, flipping `precedence` changed the
#: matching in 2 of them. A sweep like that reports a truthful zero while
#: testing almost nothing that distinguishes reserve_da from plain DA.
#:
#: Measured rate at which flipping precedence changes the matching, by shape
#: (reserve_mode=half, eligible_fraction=0.5, complete lists):
#:
#:      5 x 5  (mean capacity 1.0)    0%      <- the old default region
#:      6 x 4  (mean capacity 1.5)    9%
#:      8 x 3  (mean capacity 2.7)   21%   over-subscribed: 44%
#:     12 x 3  (mean capacity 4.0)   35%   over-subscribed: 68%
#:
#: So shape is a parameter of the sweep now, not a constant. The defaults are
#: unchanged, so every existing artifact remains reproducible; a caller
#: sweeping a slot-structured mechanism must widen them deliberately and the
#: summary records what was used.
SHAPE_NOTE_MIN_CAPACITY_FOR_SLOTS = 2

#: Floor on the fraction of instances in which flipping `precedence` must
#: change the matching before a reserve_da sweep counts as having exercised
#: the reserve structure. This is a declared JUDGEMENT, not a theorem: there
#: is no principled value, and it is set where it is because the first
#: reserve_da sweep sat at 1.7% while a shape-widened one reached 11.7%, so a
#: floor anywhere between those separates "tested reserves" from "re-tested
#: plain DA". Crossing it is necessary, not sufficient.
MIN_PRECEDENCE_SENSITIVITY = 0.05

#: Domain-separation suffix for this module's own config-draw hashing, mixed
#: in via `derive_seed`'s own `purpose` argument (never bare, never shared
#: with any purpose string `witness.generate` itself uses for a DIFFERENT
#: seed root -- see `draw_configuration`).
_DRAW_PURPOSE_PREFIX = "negative-control/draw"


def _unit_from_seed(seed_str: str) -> float:
    """A deterministic float in [0.0, 1.0), derived by sha256 over
    `seed_str` alone -- same construction as `witness.tiebreak.lottery_key`,
    minus the (scope, student) fields this module doesn't need. Uses the
    top 52 bits of the digest (a double's mantissa width) for a value with no
    detectable bias at this module's sample sizes.
    """
    digest = hashlib.sha256(seed_str.encode("utf-8")).hexdigest()
    return int(digest[:13], 16) / float(1 << 52)


def _weighted_choice(seed_str: str, weights: Sequence["tuple[str, float]"]) -> str:
    """Pick one name from `weights` (a sequence of (name, weight) pairs, in
    a fixed caller-declared order -- never a dict), with probability
    proportional to its weight, using `_unit_from_seed(seed_str)` as the
    single source of randomness.
    """
    total = sum(w for _, w in weights)
    r = _unit_from_seed(seed_str) * total
    cumulative = 0.0
    for name, w in weights:
        cumulative += w
        if r < cumulative:
            return name
    return weights[-1][0]  # pragma: no cover - only reachable by float rounding at the boundary


def _uniform(seed_str: str, lo: float, hi: float) -> float:
    """A deterministic float uniformly in `[lo, hi)`."""
    return lo + _unit_from_seed(seed_str) * (hi - lo)


def _choice_uniform(seed_str: str, options: Sequence):
    """Pick one element of `options` (an ordered sequence) uniformly."""
    digest = hashlib.sha256(seed_str.encode("utf-8")).hexdigest()
    idx = int(digest, 16) % len(options)
    return options[idx]


def ordered_subset_count(m: int) -> int:
    """The number of ordered subsets ("sequences without repetition") of an
    `m`-element set, summed over every subset size `r = 0..m`:
    `sum_{r=0}^{m} m! / (m - r)!`. This is exactly how many distinct
    misreported school rankings `witness.search.misreport_space` enumerates
    for a market with `m` schools -- a length-`r` ranking is one
    permutation of `r` of the `m` schools, for every `r` from the empty
    list (the one length-0 "report nothing" misreport) up to a length-`m`
    complete ranking. E.g. 326 for `m=5` (1 + 5 + 20 + 60 + 120 + 120).
    """
    if m < 0:
        raise ValueError(f"ordered_subset_count: m must be >= 0, got {m}")
    total = 0
    permutations_of_size_r = 1  # r=0: m! / (m-0)! = 1 (the empty subset)
    total += permutations_of_size_r
    for r in range(1, m + 1):
        permutations_of_size_r *= m - r + 1
        total += permutations_of_size_r
    return total


def mechanism_runs_per_instance(n_students: int, n_schools: int) -> int:
    """How many full mechanism runs `witness.search.search_all_students`
    performs for ONE instance with `n_students` students and `n_schools`
    schools: one run per (student, ordered-subset-of-schools misreport)
    pair, i.e. `n_students * ordered_subset_count(n_schools)`. Recorded per
    configuration (see `process_configuration`) and totalled across the
    sweep (see `_write_summary`) so a reader can see directly WHY one
    configuration is orders of magnitude slower than another -- this
    figure, not instance count alone, is what dominates wall-clock time.
    """
    return n_students * ordered_subset_count(n_schools)


def draw_configuration(
    seed: str,
    config_index: int,
    *,
    reserve_overrides: "Optional[Mapping]" = None,
    n_students_choices: "Optional[tuple]" = None,
    n_schools_choices: "Optional[tuple]" = None,
    school_lists_full_probability: "Optional[float]" = None,
    unacceptable_policy_fraction: "Optional[float]" = None,
) -> dict:
    """The full, plain-JSON-able parameter set of configuration
    `config_index`, drawn deterministically from `seed` alone via the
    weight constants above.

    A pure function: calling this twice with the same (seed, config_index)
    always returns an identical dict, in this process, in a fresh process, on
    a different machine -- everything reduces to `hashlib.sha256`. Every
    field it returns is exactly one `GeneratorConfig` constructor argument
    (plus `config_index`, stripped by `generator_config_from_params` before
    construction), so the returned dict IS the record of "how was this
    configuration built."

    `reserve_overrides` (`--reserve-mode` / `--eligible-fraction` /
    `--reserve-type` / `--precedence`, see `parse_args`) is NOT drawn from
    `seed` -- unlike every field above, this sweep does not vary the reserve
    policy across configurations, it applies one caller-chosen policy to
    every one of them (that is what `--mechanism reserve_da` needs: a fixed,
    reported lever, not a hidden random one). When `None` (the default,
    and every existing caller's behaviour, unchanged), the returned dict
    carries no reserve keys at all and `GeneratorConfig` falls back to its
    own defaults (`RESERVE_MODE_NONE` etc.).

    `school_lists_full_probability` / `unacceptable_policy_fraction`
    (`--school-lists-full-probability` / `--unacceptable-policy-fraction`,
    see `parse_args`) override `SCHOOL_LISTS_FULL_PROBABILITY` /
    `UNLISTED_POLICY_WEIGHTS`'s implied 50/50 split for exactly this one
    configuration, the same caller-overridable-but-default-preserving shape
    as `n_students_choices` / `n_schools_choices`: `None` (the default, and
    every existing caller's behaviour, unchanged) means "use the module
    constant." Together these two constants set the probability that a
    configuration can exercise `had_school_unacceptable_rejection` at all --
    it requires BOTH `school_lists_fraction < 1.0` (so some school leaves a
    student unlisted) AND `unlisted_student_policy == UNLISTED_UNACCEPTABLE`
    (so being unlisted actually makes that student unacceptable there rather
    than merely low-priority) -- at the module defaults that is
    `0.70 * 0.50 = 35%` of configurations, which is a real, nonzero, but not
    GUARANTEED-per-handful-of-configs probability (see
    `tests.test_negative_control_runner`'s own
    `test_coverage_report_has_nonzero_fractions_for_hit_branches`, which
    already documents that this branch is "not guaranteed at this tiny a
    sample"). A caller who specifically wants this branch reliably
    exercised within a SMALL number of configurations -- rather than relying
    on enough configurations for the 35% baseline to average out -- raises
    `unacceptable_policy_fraction` toward 1.0 and/or lowers
    `school_lists_full_probability` toward 0.0, exactly the way a caller
    widens `n_students_choices` for `reserve_da`'s precedence structure.
    """

    def s(purpose: str) -> str:
        return derive_seed(seed, config_index, f"{_DRAW_PURPOSE_PREFIX}/{purpose}")

    subscription = _weighted_choice(s("subscription"), SUBSCRIPTION_WEIGHTS)
    if subscription == SUBSCRIPTION_OVER:
        subscription_ratio = _uniform(s("subscription-ratio"), *OVER_SUBSCRIPTION_RATIO_RANGE)
    elif subscription == SUBSCRIPTION_UNDER:
        subscription_ratio = _uniform(s("subscription-ratio"), *UNDER_SUBSCRIPTION_RATIO_RANGE)
    else:
        subscription_ratio = 1.0

    n_schools = _choice_uniform(s("n-schools"), n_schools_choices or N_SCHOOLS_CHOICES)
    n_students = _choice_uniform(s("n-students"), n_students_choices or N_STUDENTS_CHOICES)

    list_length_mode = _weighted_choice(s("list-length-mode"), LIST_LENGTH_WEIGHTS)
    list_length = 0
    if list_length_mode == LIST_FIXED:
        list_length = _choice_uniform(s("list-length"), tuple(range(0, n_schools + 1)))

    full_probability = (
        SCHOOL_LISTS_FULL_PROBABILITY
        if school_lists_full_probability is None
        else school_lists_full_probability
    )
    if _unit_from_seed(s("school-lists-full")) < full_probability:
        school_lists_fraction = 1.0
    else:
        school_lists_fraction = _uniform(s("school-lists-fraction"), *SCHOOL_LISTS_FRACTION_RANGE)

    n_priority_classes = _choice_uniform(s("n-priority-classes"), N_PRIORITY_CLASSES_CHOICES)
    capacity_mode = _weighted_choice(s("capacity-mode"), CAPACITY_MODE_WEIGHTS)
    tiebreak_family = _weighted_choice(s("tiebreak-family"), TIEBREAK_FAMILY_WEIGHTS)
    unlisted_policy_weights = (
        UNLISTED_POLICY_WEIGHTS
        if unacceptable_policy_fraction is None
        else (
            (UNLISTED_UNACCEPTABLE, unacceptable_policy_fraction),
            (UNLISTED_LOWEST_CLASS, 1.0 - unacceptable_policy_fraction),
        )
    )
    unlisted_student_policy = _weighted_choice(s("unlisted-policy"), unlisted_policy_weights)

    gc_seed = derive_seed(seed, config_index, f"{_DRAW_PURPOSE_PREFIX}/gc-seed")

    params = {
        "config_index": config_index,
        "seed": gc_seed,
        "n_students": n_students,
        "n_schools": n_schools,
        "subscription": subscription,
        "subscription_ratio": subscription_ratio,
        "capacity_mode": capacity_mode,
        "list_length_mode": list_length_mode,
        "list_length": list_length,
        "school_lists_fraction": school_lists_fraction,
        "n_priority_classes": n_priority_classes,
        "unlisted_student_policy": unlisted_student_policy,
        "tiebreak_family": tiebreak_family,
    }
    if reserve_overrides is not None:
        params.update(reserve_overrides)
    return params


def draw_configurations(
    seed: str,
    k: int,
    *,
    reserve_overrides: "Optional[Mapping]" = None,
    n_students_choices: "Optional[tuple]" = None,
    n_schools_choices: "Optional[tuple]" = None,
    school_lists_full_probability: "Optional[float]" = None,
    unacceptable_policy_fraction: "Optional[float]" = None,
) -> "tuple[dict, ...]":
    """The first `k` configurations drawn from `seed`, in `config_index`
    order 0..k-1. Reproducible from `seed` alone: a different `seed`
    produces a different sequence, but the same `seed` always produces this
    same sequence, regardless of how many of them a caller asks for -- the
    first `j < k` entries of `draw_configurations(seed, k)` are always
    exactly `draw_configurations(seed, j)`.

    `reserve_overrides`, `school_lists_full_probability` and
    `unacceptable_policy_fraction` are passed through verbatim to every
    `draw_configuration` call -- see that function's docstring.
    """
    return tuple(
        draw_configuration(
            seed,
            i,
            reserve_overrides=reserve_overrides,
            n_students_choices=n_students_choices,
            n_schools_choices=n_schools_choices,
            school_lists_full_probability=school_lists_full_probability,
            unacceptable_policy_fraction=unacceptable_policy_fraction,
        )
        for i in range(k)
    )


def generator_config_from_params(params: Mapping) -> GeneratorConfig:
    """Build the `GeneratorConfig` a configuration's `params` dict
    (`draw_configuration`'s return value) describes."""
    kwargs = {k: v for k, v in params.items() if k != "config_index"}
    return GeneratorConfig(**kwargs)


#: Which raw-result function to call per mechanism, so `process_configuration`
#: can compute `witness.coverage.instance_coverage` from the mechanism's own
#: trace -- `witness.search.search_all_students` only ever hands back
#: `Assignment`s (via the `witness.mechanisms` registry's simplified `run`),
#: not the full `DAResult` / `BostonResult` coverage needs.
_RUN_FOR_COVERAGE = {
    MECHANISM_STUDENT_PROPOSING_DA: deferred_acceptance,
    MECHANISM_BOSTON_IMMEDIATE_ACCEPTANCE: boston_immediate_acceptance,
    MECHANISM_RESERVE_DA: reserve_da,
    MECHANISM_TOP_TRADING_CYCLES: top_trading_cycles,
}


def _branch_hit_counts(coverages: Sequence) -> dict:
    """Raw per-branch hit counts (not fractions) over `coverages`, in
    `BRANCH_NAMES` order -- kept alongside the fractional
    `witness.coverage.CoverageReport` in every journal record so a later
    combination across many configurations (`_combine_coverage`) is exact
    integer arithmetic, never a re-derivation from already-rounded floats.
    """
    return {name: sum(1 for cov in coverages if getattr(cov, name)) for name in BRANCH_NAMES}


def process_configuration(
    params: Mapping,
    instances_per_config: int,
    mechanism: str,
    expect: str,
    verify_hits: int = 1,
) -> dict:
    """Run `instances_per_config` instances of the configuration described by
    `params`.

    Under `expect == EXPECT_ZERO` (the negative control): stop the INSTANT
    any instance yields a manipulation -- unchanged from this function's
    original behaviour. Under `expect == EXPECT_MANIPULATIONS` (the
    positive / calibration mode): never stop on a manipulation, instead
    count and record every one -- see the module docstring's "--expect:
    ZERO vs MANIPULATIONS" section for the full contract.

    Returns a plain dict, always containing "config_index", "params",
    "expect", "hit" (bool -- can only be True under `EXPECT_ZERO`),
    "n_instances" (however many instances actually ran -- always
    `instances_per_config` under `EXPECT_MANIPULATIONS`, unless a violation
    or a failed sampled verification cut the configuration short), "coverage"
    (a `CoverageReport.to_dict()` over exactly those instances),
    "branch_hit_counts", "elapsed_seconds", "mechanism_runs_per_instance"
    (see `mechanism_runs_per_instance`, constant for this configuration since
    it depends only on `n_students` / `n_schools`), the `witness.invariants`
    singleton-sufficiency aggregates "singleton_cases", "singleton_holds",
    and "singleton_checks_skipped" (see the per-instance wiring below), and
    the manipulations-mode aggregates "manipulable_cases" (count of
    (instance, student) pairs with at least one profitable misreport),
    "instances_with_manipulation", "hits_verified", "hits_unverified", and
    "witnesses" (a list of `{"instance_index": ..., "witness": <dict>}`,
    always empty under `EXPECT_ZERO`).

    On a hit under `EXPECT_ZERO`, the dict additionally carries everything
    needed to report and re-verify it: "instance_index", "witness",
    "verified_ok", "verify_reasons", "market", "profile", "mechanism_config".
    "singleton_violation" is `None` unless the proved-regime assertion below
    actually failed, in which case it carries the full failing case for
    `run_sweep` to report and abort on, exactly like a hit, in EITHER
    `expect` mode. "verification_failure" is `None` unless a sampled
    verification under `EXPECT_MANIPULATIONS` actually failed, in which case
    it carries the full failing case for `run_sweep` to report and abort on
    -- a real defect regardless of `expect`.
    """
    gc = generator_config_from_params(params)
    runner = _RUN_FOR_COVERAGE[mechanism]
    config_index = params["config_index"]
    runs_per_instance = mechanism_runs_per_instance(gc.n_students, gc.n_schools)

    # witness.invariants wiring: whether the exhaustive singleton-sufficiency
    # check is even feasible for this configuration's `n_schools` depends
    # only on `n_schools` (see `witness.invariants.check_singleton_sufficiency`
    # -> `witness.search.misreport_space`), so it is decided once per
    # configuration rather than re-derived every instance.
    singleton_space_ok = ordered_subset_count(gc.n_schools) <= SINGLETON_MAX_SPACE
    singleton_cases = 0
    singleton_holds = 0
    singleton_checks_skipped = 0

    # Reserve-structure exercise rate. A negative control that never varies
    # the thing under test reports a truthful zero while proving nothing: at
    # ONE seat per school a reserve/open precedence order has nothing to
    # order, so `reserve_da` degenerates to plain DA and the sweep silently
    # re-tests a mechanism that is already controlled. The first reserve_da
    # sweep did exactly that -- flipping `precedence` changed the matching in
    # 2 of its 160 instances -- and nothing in the artifact said so.
    #
    # So the runner measures it: for every instance, re-run with the
    # precedence order flipped and count the instances whose matching moves.
    # That is ONE extra mechanism run per instance against the hundreds the
    # exhaustive search already does, and it turns "was this sweep
    # meaningful?" from a question someone has to think to ask into a number
    # that comes out of the run.
    precedence_flipped_runs = 0
    precedence_changed_matching = 0

    # The TTC analogue of the precedence measurement above, and it exists for
    # the identical reason. TTC only behaves like TTC when schools disagree
    # about who they want: if every school shares one priority order, TTC and
    # student-proposing DA both collapse into serial dictatorship over that
    # order, and a sweep reporting "0 manipulations under top_trading_cycles"
    # is really reporting "serial dictatorship is strategy-proof" -- true,
    # published since 1979, and nothing to do with TTC.
    #
    # This is not hypothetical either: the generator's OWN DEFAULTS
    # (tiebreak_family="stb", n_priority_classes=1) produce exactly one
    # common order, because a single lottery applied to a single class is the
    # same permutation everywhere. So the runner counts it, per instance,
    # rather than leaving "was this sweep meaningful?" to whoever thinks to
    # ask. See `witness.ttc.distinct_priority_orders`.
    ttc_instances_measured = 0
    ttc_common_order_instances = 0

    # Manipulations-mode aggregates (stay at 0 / empty under EXPECT_ZERO,
    # since that mode aborts before any of this could accumulate).
    manipulable_cases = 0
    instances_with_manipulation = 0
    hits_verified = 0
    hits_unverified = 0
    recorded_witnesses: list = []

    def _base_fields(n_instances: int, elapsed: float) -> dict:
        return {
            "config_index": config_index,
            "params": dict(params),
            "expect": expect,
            "n_instances": n_instances,
            "coverage": aggregate(coverages).to_dict(),
            "branch_hit_counts": _branch_hit_counts(coverages),
            "elapsed_seconds": elapsed,
            "mechanism_runs_per_instance": runs_per_instance,
            "singleton_cases": singleton_cases,
            "singleton_holds": singleton_holds,
            "singleton_checks_skipped": singleton_checks_skipped,
            "precedence_flipped_runs": precedence_flipped_runs,
            "precedence_changed_matching": precedence_changed_matching,
            "ttc_instances_measured": ttc_instances_measured,
            "ttc_common_order_instances": ttc_common_order_instances,
            "manipulable_cases": manipulable_cases,
            "instances_with_manipulation": instances_with_manipulation,
            "hits_verified": hits_verified,
            "hits_unverified": hits_unverified,
            "witnesses": recorded_witnesses,
        }

    t0 = time.perf_counter()
    coverages = []
    for i in range(instances_per_config):
        market, profile = generate_instance(gc, i)
        mech_config = generate_config(gc, i, mechanism, market=market)

        result = runner(market, profile, mech_config)
        coverages.append(instance_coverage(market, profile, mech_config, result))

        if mechanism == MECHANISM_TOP_TRADING_CYCLES:
            ttc_instances_measured += 1
            if distinct_priority_orders(market, result.priorities) == 1:
                ttc_common_order_instances += 1

        if mechanism == MECHANISM_RESERVE_DA:
            flipped = dataclasses.replace(
                mech_config,
                precedence=(
                    PRECEDENCE_OPEN_FIRST
                    if mech_config.precedence == PRECEDENCE_RESERVE_FIRST
                    else PRECEDENCE_RESERVE_FIRST
                ),
            )
            precedence_flipped_runs += 1
            if (
                runner(market, profile, flipped).assignment.to_dict()
                != result.assignment.to_dict()
            ):
                precedence_changed_matching += 1

        witnesses = search_all_students(market, profile, mechanism, mech_config)

        # witness.invariants wiring (additive; see that module's docstring
        # for the proved-vs-recorded scope distinction). In the PROVED
        # regime (Boston, placement off) a violation is a hard bug -- treated
        # exactly like a negative-control hit by `run_sweep`, in EITHER
        # `expect` mode. Everywhere else the property is only OBSERVED, so
        # violations are merely counted, never raised. Under
        # EXPECT_MANIPULATIONS this now runs for every instance actually
        # processed (the loop no longer stops early on a manipulation), so
        # the check is exercised far more than under EXPECT_ZERO.
        if not singleton_space_ok:
            singleton_checks_skipped += 1
        else:
            # `check_instance` is run for EVERY instance regardless of
            # regime, so "singleton_cases" / "singleton_holds" are always
            # populated (never silently inert just because this happens to
            # be the PROVED regime) -- see the module docstring. In the
            # PROVED regime (Boston, placement off) a manipulable case that
            # does not hold is additionally a hard bug: `violation_check`
            # captures the first such case, and `assert_singleton_sufficiency`
            # is then called SOLELY to raise with its own (single source of
            # truth) message text -- it necessarily raises on the very same
            # case, since it runs the identical `check_instance` computation.
            checks = check_instance(
                market, profile, mechanism, mech_config, max_space=SINGLETON_MAX_SPACE
            )
            proved = is_proved_regime(mechanism, mech_config)
            violation_check = None
            for check in checks:
                if check.manipulable:
                    singleton_cases += 1
                    if check.holds:
                        singleton_holds += 1
                    elif proved and violation_check is None:
                        violation_check = check
            if violation_check is not None:
                try:
                    assert_singleton_sufficiency(
                        market, profile, mechanism, mech_config, max_space=SINGLETON_MAX_SPACE
                    )
                except MechanismError as e:
                    elapsed = time.perf_counter() - t0
                    out = _base_fields(i + 1, elapsed)
                    out["hit"] = False
                    out["verification_failure"] = None
                    out["singleton_violation"] = {
                        "instance_index": i,
                        "message": str(e),
                        "market": market.to_dict(),
                        "profile": profile.to_dict(),
                        "mechanism_config": mech_config.to_dict(),
                    }
                    return out

        if witnesses and expect == EXPECT_ZERO:
            w = witnesses[0]
            ok, reasons = verify_in_subprocess(w.to_dict())
            elapsed = time.perf_counter() - t0
            out = _base_fields(i + 1, elapsed)
            out["hit"] = True
            out["instance_index"] = i
            out["witness"] = w.to_dict()
            out["verified_ok"] = ok
            out["verify_reasons"] = list(reasons)
            out["market"] = market.to_dict()
            out["profile"] = profile.to_dict()
            out["mechanism_config"] = mech_config.to_dict()
            out["singleton_violation"] = None
            out["verification_failure"] = None
            return out

        if witnesses and expect == EXPECT_MANIPULATIONS:
            # count and record every
            # manipulation found for this instance, verify only the first
            # `verify_hits` PER CONFIGURATION (across all its instances),
            # and never abort on a hit -- only a FAILED sampled verification
            # aborts (a real defect, not an expected outcome).
            manipulable_cases += len(witnesses)
            instances_with_manipulation += 1
            for w in witnesses:
                wd = w.to_dict()
                if hits_verified + hits_unverified < verify_hits:
                    ok, reasons = verify_in_subprocess(wd)
                    if ok:
                        hits_verified += 1
                    else:
                        elapsed = time.perf_counter() - t0
                        out = _base_fields(i + 1, elapsed)
                        out["hit"] = False
                        out["singleton_violation"] = None
                        out["verification_failure"] = {
                            "instance_index": i,
                            "witness": wd,
                            "verify_reasons": list(reasons),
                            "market": market.to_dict(),
                            "profile": profile.to_dict(),
                            "mechanism_config": mech_config.to_dict(),
                        }
                        return out
                else:
                    hits_unverified += 1
                recorded_witnesses.append({"instance_index": i, "witness": wd})

    elapsed = time.perf_counter() - t0
    out = _base_fields(instances_per_config, elapsed)
    out["hit"] = False
    out["singleton_violation"] = None
    out["verification_failure"] = None
    return out


def _worker(task: Mapping) -> dict:
    """`multiprocessing.Pool` entry point: unpack one task dict and run it.

    Module-level (not a closure) and taking one plain-dict argument
    specifically so it stays picklable under both the "fork" and "spawn"
    start methods -- macOS (this project's target platform) defaults to
    "spawn", which pickles the callable by (module, qualname) and re-imports
    the module in the child, so nothing captured here may depend on
    in-process state from the parent.
    """
    return process_configuration(
        task["params"],
        task["instances_per_config"],
        task["mechanism"],
        task["expect"],
        verify_hits=task["verify_hits"],
    )


# =============================================================================
# Checkpointing.
# =============================================================================


def _checkpoint_path(out_dir: str) -> str:
    return os.path.join(out_dir, "checkpoint.json")


def _load_checkpoint(out_dir: str) -> Optional[dict]:
    path = _checkpoint_path(out_dir)
    if not os.path.exists(path):
        return None
    with open(path, mode="r", encoding="utf-8") as f:
        return json.load(f)


def _write_checkpoint_atomic(out_dir: str, checkpoint: Mapping) -> None:
    """Write `checkpoint` to `<out_dir>/checkpoint.json` atomically: write to
    a temp file IN THE SAME DIRECTORY (so `os.replace` is a same-filesystem
    rename, never a copy) and `os.replace` it into place. An interrupted
    write leaves the temp file orphaned and the real checkpoint untouched --
    it can never observe a half-written checkpoint.
    """
    path = _checkpoint_path(out_dir)
    fd, tmp_path = tempfile.mkstemp(dir=out_dir, prefix=".checkpoint-", suffix=".tmp")
    try:
        with os.fdopen(fd, mode="w", encoding="utf-8") as f:
            json.dump(dict(checkpoint), f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise


# =============================================================================
# Orchestration.
# =============================================================================


def _print_hit_banner(hit: Mapping) -> None:
    bar = "!" * 78
    print()
    print(bar)
    print("!!! NEGATIVE CONTROL FAILED: a manipulation was found. THIS IS A BUG. !!!")
    print(bar)
    print(
        f"config_index={hit['config_index']} instance_index={hit['instance_index']} "
        f"verified_in_fresh_subprocess={hit['verified_ok']}"
    )
    if not hit["verified_ok"]:
        print("WARNING: the witness itself FAILED independent re-verification:")
        for reason in hit["verify_reasons"]:
            print(f"  - {reason}")
    print("--- configuration params ---")
    print(json.dumps(hit["params"], indent=2, sort_keys=True))
    print("--- market ---")
    print(json.dumps(hit["market"], indent=2, sort_keys=True))
    print("--- profile (truthful) ---")
    print(json.dumps(hit["profile"], indent=2, sort_keys=True))
    print("--- mechanism config ---")
    print(json.dumps(hit["mechanism_config"], indent=2, sort_keys=True))
    print("--- witness ---")
    print(json.dumps(hit["witness"], indent=2, sort_keys=True))
    print(bar)
    print()


def _print_singleton_violation_banner(violation_result: Mapping) -> None:
    """Mirrors `_print_hit_banner`, for a `witness.invariants` singleton-
    sufficiency violation instead of a manipulation hit -- see
    `witness.invariants`' module docstring for what this means and why it is
    only ever raised in the PROVED regime (Boston, placement off)."""
    v = violation_result["singleton_violation"]
    bar = "!" * 78
    print()
    print(bar)
    print(
        "!!! NEGATIVE CONTROL FAILED: a singleton-sufficiency violation was "
        "found (witness.invariants). THIS IS A BUG. !!!"
    )
    print(bar)
    print(
        f"config_index={violation_result['config_index']} "
        f"instance_index={v['instance_index']}"
    )
    print(v["message"])
    print("--- configuration params ---")
    print(json.dumps(violation_result["params"], indent=2, sort_keys=True))
    print("--- market ---")
    print(json.dumps(v["market"], indent=2, sort_keys=True))
    print("--- profile (truthful) ---")
    print(json.dumps(v["profile"], indent=2, sort_keys=True))
    print("--- mechanism config ---")
    print(json.dumps(v["mechanism_config"], indent=2, sort_keys=True))
    print(bar)
    print()


def _print_verification_failure_banner(failure_result: Mapping) -> None:
    """Mirrors `_print_hit_banner`, for a FAILED sampled re-verification
    under `--expect manipulations` -- see the module docstring's "--expect:
    ZERO vs MANIPULATIONS" section. A witness that the search itself
    considered a manipulation but that does not survive independent
    re-derivation in a fresh subprocess is a real defect (in the mechanism,
    the search, or `witness.replay` itself), never an expected outcome --
    this aborts the run regardless of `--expect`.
    """
    v = failure_result["verification_failure"]
    bar = "!" * 78
    print()
    print(bar)
    print(
        "!!! NEGATIVE CONTROL FAILED: a sampled witness FAILED independent "
        "re-verification. THIS IS A BUG. !!!"
    )
    print(bar)
    print(
        f"config_index={failure_result['config_index']} "
        f"instance_index={v['instance_index']}"
    )
    for reason in v["verify_reasons"]:
        print(f"  - {reason}")
    print("--- configuration params ---")
    print(json.dumps(failure_result["params"], indent=2, sort_keys=True))
    print("--- market ---")
    print(json.dumps(v["market"], indent=2, sort_keys=True))
    print("--- profile (truthful) ---")
    print(json.dumps(v["profile"], indent=2, sort_keys=True))
    print("--- mechanism config ---")
    print(json.dumps(v["mechanism_config"], indent=2, sort_keys=True))
    print("--- witness ---")
    print(json.dumps(v["witness"], indent=2, sort_keys=True))
    print(bar)
    print()


def _combine_coverage(records: Sequence[Mapping]) -> CoverageReport:
    """Fold every per-configuration journal `record`'s `branch_hit_counts` /
    `coverage.subscription_counts` / `n_instances` into one overall
    `CoverageReport`, using the raw integer `branch_hit_counts` (never the
    already-rounded `coverage.fractions`) so the combination is exact.
    """
    total_n = sum(r["n_instances"] for r in records)
    if total_n == 0:
        raise ModelError("_combine_coverage: no instances recorded yet")

    combined_counts = {name: 0 for name in BRANCH_NAMES}
    for r in records:
        for name in BRANCH_NAMES:
            combined_counts[name] += r["branch_hit_counts"][name]
    fractions = {name: combined_counts[name] / total_n for name in BRANCH_NAMES}

    subscription_counts = {k: 0 for k in _SUBSCRIPTIONS}
    for r in records:
        for k, v in r["coverage"]["subscription_counts"].items():
            subscription_counts[k] = subscription_counts.get(k, 0) + v

    return CoverageReport(n_instances=total_n, fractions=fractions, subscription_counts=subscription_counts)


def _write_summary(
    *,
    out_dir: str,
    journal: Journal,
    seed: str,
    mechanism: str,
    expect: str,
    verify_hits: int,
    max_witnesses: int,
    requested_configs: int,
    wall_seconds_this_invocation: float,
    instances_this_invocation: int,
    configs_this_invocation: int,
    witnesses_recorded: int,
    witnesses_omitted: int,
    reserve_mode: str,
    eligible_fraction: float,
    reserve_type: str,
    precedence: str,
    n_students_choices: "Optional[tuple]" = None,
    n_schools_choices: "Optional[tuple]" = None,
    school_lists_full_probability: "Optional[float]" = None,
    unacceptable_policy_fraction: "Optional[float]" = None,
) -> dict:
    records = journal.read_all()
    total_instances = sum(r["n_instances"] for r in records)
    manipulations_found = sum(r.get("manipulations_found", 0) for r in records)
    manipulable_cases = sum(r.get("manipulable_cases", 0) for r in records)
    instances_with_manipulation = sum(r.get("instances_with_manipulation", 0) for r in records)
    hits_verified = sum(r.get("hits_verified", 0) for r in records)
    hits_unverified = sum(r.get("hits_unverified", 0) for r in records)
    combined = _combine_coverage(records)
    unreached = unreached_branches(combined)

    # `.get(..., 0)` / `.get("instances_run", r.get("n_instances", 0))`
    # below is defensive against a journal produced by an older version of
    # this script (e.g. resuming a pre-existing --out directory) that
    # predates the "instances_run" / "mechanism_runs_per_instance" fields
    # -- never a KeyError just because part of a resumed run is older.
    total_mechanism_runs = sum(
        r.get("mechanism_runs_per_instance", 0) * r.get("instances_run", r.get("n_instances", 0))
        for r in records
    )

    # These three are sizing numbers, not decoration: quoting a
    # per-instance cost measured at the smallest market shape (or omitting
    # it entirely) is exactly the mistake that previously got this project
    # burned on capacity planning -- see the module docstring.
    wall_seconds = wall_seconds_this_invocation
    instances_per_second = (
        instances_this_invocation / wall_seconds if wall_seconds > 0 else None
    )
    mean_seconds_per_instance = (
        wall_seconds / instances_this_invocation if instances_this_invocation > 0 else None
    )

    if expect == EXPECT_ZERO:
        manipulations_found_expectation = (
            "--expect zero: manipulations are a BUG here. Plain student-proposing DA "
            "(and any mechanism run under --mechanism with --expect zero) is expected "
            "to yield EXACTLY ZERO manipulations: student_proposing_da is "
            "strategy-proof for the proposing side in every market, unconditionally. "
            "A nonzero count is a bug in the mechanism, the search, or this generator "
            "-- not a discovery."
        )
    else:
        manipulations_found_expectation = (
            "--expect manipulations: manipulations are EXPECTED here (this mechanism "
            "is manipulable by design). They are counted and recorded, never treated "
            "as a bug -- see 'manipulable_cases' / 'instances_with_manipulation'. A "
            "sample of them (--verify-hits per configuration) is independently "
            "re-verified in a fresh subprocess; a FAILED sampled verification is a "
            "real defect and aborts the run regardless of this --expect value -- see "
            "'hits_verified' / 'hits_unverified' and verification_failures.jsonl."
        )

    summary = {
        "seed": seed,
        "mechanism": mechanism,
        "expect": expect,
        "verify_hits": verify_hits,
        "max_witnesses": max_witnesses,
        # The reserve-policy levers `--mechanism reserve_da` runs under (see
        # `run_sweep`'s docstring): applied uniformly to every configuration
        # in this sweep, and inert (but still recorded here) for every other
        # mechanism, so the artifact always says what reserve policy -- if
        # any -- was actually in force.
        "reserve_mode": reserve_mode,
        "eligible_fraction": eligible_fraction,
        "reserve_type": reserve_type,
        "precedence": precedence,
        "requested_configs": requested_configs,
        "total_configurations": len(records),
        "total_instances": total_instances,
        "total_mechanism_runs": total_mechanism_runs,
        # The shapes ACTUALLY drawn, read back off the records rather than
        # from the requested choices, so the artifact cannot claim a width it
        # did not sweep. Shape is not cosmetic for a slot-structured
        # mechanism: at one seat per school a reserve/open precedence order
        # has nothing to order, so a sweep confined to capacity-1 schools
        # reports a truthful zero while never exercising the reserve rule.
        # Reserve-structure exercise rate, summed over configurations. Reads
        # 0/0 for every mechanism without a precedence order.
        "ttc_instances_measured": sum(
            r.get("ttc_instances_measured", 0) for r in records
        ),
        "ttc_common_order_instances": sum(
            r.get("ttc_common_order_instances", 0) for r in records
        ),
        "precedence_flipped_runs": sum(
            r.get("precedence_flipped_runs", 0) for r in records
        ),
        "precedence_changed_matching": sum(
            r.get("precedence_changed_matching", 0) for r in records
        ),
        # The shape CHOICES this sweep drew from, so a later reader can
        # reproduce the draw exactly instead of guessing whether the defaults
        # were in force.
        "n_students_choices": list(n_students_choices or N_STUDENTS_CHOICES),
        "n_schools_choices": list(n_schools_choices or N_SCHOOLS_CHOICES),
        # The two levers that widen how often a configuration is even
        # ELIGIBLE to exercise `had_school_unacceptable_rejection` -- see
        # `draw_configuration`'s docstring. Recorded the same way the shape
        # choices above are, so a reader never has to guess whether the
        # default 35%-of-configurations baseline was in force.
        "school_lists_full_probability": (
            SCHOOL_LISTS_FULL_PROBABILITY
            if school_lists_full_probability is None
            else school_lists_full_probability
        ),
        "unacceptable_policy_fraction": (
            UNLISTED_POLICY_WEIGHTS[0][1]
            if unacceptable_policy_fraction is None
            else unacceptable_policy_fraction
        ),
        "shapes_swept": sorted(
            {
                f"{r['params']['n_students']}x{r['params']['n_schools']}"
                for r in records
                if "params" in r
            }
        ),
        "manipulations_found": manipulations_found,
        "manipulations_found_expectation": manipulations_found_expectation,
        # Manipulations-mode aggregates (always 0 under --expect zero, since
        # that mode aborts before any of this could accumulate). See
        # process_configuration's docstring for exact definitions.
        "manipulable_cases": manipulable_cases,
        "instances_with_manipulation": instances_with_manipulation,
        "hits_verified": hits_verified,
        "hits_unverified": hits_unverified,
        "witnesses_recorded": witnesses_recorded,
        "witnesses_omitted": witnesses_omitted,
        "wall_seconds": wall_seconds,
        "instances_per_second": instances_per_second,
        "mean_seconds_per_instance": mean_seconds_per_instance,
        "configs_processed_this_invocation": configs_this_invocation,
        "instances_processed_this_invocation": instances_this_invocation,
        "coverage": combined.to_dict(),
        "unreached_branches": list(unreached),
        # witness.invariants singleton-sufficiency aggregates, summed from
        # each record's own "singleton_cases" / "singleton_holds" /
        # "singleton_checks_skipped" (see process_configuration / run_sweep;
        # `.get(..., 0)` is defensive against an older journal that predates
        # these fields). "singleton_cases" is the number of manipulable
        # (instance, student) cases checked; "singleton_holds" is how many
        # of those had a singleton misreport achieve the best available
        # gain; "singleton_checks_skipped" is how many instances the check
        # was skipped for (misreport space too large -- see
        # witness.invariants.DEFAULT_MAX_SPACE), so a reader can see the
        # check was not silently inert.
        "singleton_cases": sum(r.get("singleton_cases", 0) for r in records),
        "singleton_holds": sum(r.get("singleton_holds", 0) for r in records),
        "singleton_checks_skipped": sum(r.get("singleton_checks_skipped", 0) for r in records),
    }

    summary_path = os.path.join(out_dir, "negative_control_summary.json")
    with open(summary_path, mode="w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, sort_keys=True)

    print()
    print("=== negative_control summary ===")
    print(
        f"seed={seed!r} mechanism={mechanism!r} requested_configs={requested_configs} "
        f"total_configurations={len(records)} total_instances={total_instances} "
        f"total_mechanism_runs={total_mechanism_runs}"
    )
    print(f"expect={expect!r} verify_hits={verify_hits} max_witnesses={max_witnesses}")
    print(
        f"reserve policy: reserve_mode={reserve_mode!r} "
        f"eligible_fraction={eligible_fraction!r} reserve_type={reserve_type!r} "
        f"precedence={precedence!r}"
    )
    _ttc_measured = sum(r.get("ttc_instances_measured", 0) for r in records)
    _ttc_common = sum(r.get("ttc_common_order_instances", 0) for r in records)
    if _ttc_measured:
        _pct = 100.0 * _ttc_common / _ttc_measured
        print(
            f"  TTC schools sharing ONE priority order: "
            f"{_ttc_common}/{_ttc_measured} instances ({_pct:.1f}%)"
        )
        if _ttc_common:
            print(
                "  WARNING: in those instances TTC degenerates to serial "
                "dictatorship and is identical to plain DA, so they carry no "
                "evidence about TTC (see witness.ttc.distinct_priority_orders); "
                "use --tiebreak-family mtb or --n-priority-classes > 1"
            )

    _flipped = sum(r.get("precedence_flipped_runs", 0) for r in records)
    _moved = sum(r.get("precedence_changed_matching", 0) for r in records)
    if _flipped:
        pct = 100.0 * _moved / _flipped
        print(
            f"reserve structure exercised: flipping precedence changed the "
            f"matching in {_moved}/{_flipped} instances ({pct:.1f}%)"
        )
        if pct < 100.0 * MIN_PRECEDENCE_SENSITIVITY:
            print(
                f"  WARNING: below the {MIN_PRECEDENCE_SENSITIVITY:.0%} floor -- "
                f"this sweep barely exercised the reserve structure, so its "
                f"result is mostly a re-test of plain DA. Widen "
                f"--n-students-choices so schools have more than one seat."
            )
    if expect == EXPECT_ZERO:
        print(f"manipulations found: {manipulations_found} (expected 0)")
    else:
        print(
            f"manipulations found: {manipulations_found} (expected, this mechanism is "
            "manipulable by design) -- "
            f"manipulable_cases={manipulable_cases} "
            f"instances_with_manipulation={instances_with_manipulation}"
        )
        print(
            f"sampled verification: hits_verified={hits_verified} "
            f"hits_unverified={hits_unverified}"
        )
        print(
            f"witnesses: recorded={witnesses_recorded} omitted={witnesses_omitted} "
            f"(cap={max_witnesses})"
        )
    print(
        f"this invocation: configs={configs_this_invocation} "
        f"instances={instances_this_invocation} wall_seconds={wall_seconds:.3f} "
        + (
            f"instances/sec={instances_per_second:.1f} "
            f"mean_seconds_per_instance={mean_seconds_per_instance:.6f}"
            if instances_per_second is not None
            else "instances/sec=n/a mean_seconds_per_instance=n/a"
        )
    )
    print(combined.format_report())
    for name in unreached:
        print(f"WARNING: branch {name!r} was reached 0.0% of the time -- NO EVIDENCE about it")
    print(
        f"singleton sufficiency (witness.invariants): "
        f"{summary['singleton_holds']}/{summary['singleton_cases']} manipulable cases held"
        + (
            f", {summary['singleton_checks_skipped']} instances skipped (misreport "
            "space too large)"
            if summary["singleton_checks_skipped"]
            else ""
        )
    )
    print(f"summary written to {summary_path}")

    return summary


def run_sweep(
    *,
    seed: str,
    configs: int,
    instances_per_config: int,
    mechanism: str,
    out_dir: str,
    resume: bool,
    workers: int,
    expect: str,
    verify_hits: int = 1,
    max_witnesses: int = 1000,
    reserve_mode: str = RESERVE_MODE_NONE,
    eligible_fraction: float = 0.5,
    reserve_type: str = RESERVE_SOFT,
    precedence: str = PRECEDENCE_RESERVE_FIRST,
    n_students_choices: "Optional[tuple]" = None,
    n_schools_choices: "Optional[tuple]" = None,
    school_lists_full_probability: "Optional[float]" = None,
    unacceptable_policy_fraction: "Optional[float]" = None,
) -> int:
    """Run (or resume) the sweep. Returns the process exit code: 0 if the
    full requested sweep completed cleanly (zero manipulations under
    `expect == EXPECT_ZERO`; any number under `expect == EXPECT_MANIPULATIONS`,
    as long as nothing sampled failed re-verification and no singleton-
    sufficiency violation was found), 1 if any of the three abort
    conditions fired (a hit under `EXPECT_ZERO`, a singleton-sufficiency
    violation in either mode, or a failed sampled verification under
    `EXPECT_MANIPULATIONS`) and the run was aborted.

    `reserve_mode` / `eligible_fraction` / `reserve_type` / `precedence`
    (`--reserve-mode` / `--eligible-fraction` / `--reserve-type` /
    `--precedence` on the CLI) are the reserve-policy levers `--mechanism
    reserve_da` needs (see `witness.generate.generate_reserves` /
    `witness.reserves.ReserveConfig`): unlike every other `GeneratorConfig`
    field, this sweep does not vary them across configurations -- one
    caller-chosen policy is applied, uniformly, to every configuration drawn,
    and recorded verbatim (via `draw_configuration`'s `reserve_overrides`) in
    every configuration's own `params`, so the journal and summary say
    exactly what reserve policy was actually run. Inert (but still recorded)
    for every mechanism other than `reserve_da`.

    `school_lists_full_probability` / `unacceptable_policy_fraction`
    (`--school-lists-full-probability` / `--unacceptable-policy-fraction`)
    widen (or narrow) how often a configuration is even ELIGIBLE to exercise
    `had_school_unacceptable_rejection` -- see `draw_configuration`'s
    docstring for the exact mechanics and the 35%-at-defaults baseline.
    `None` (the default) means "use the module constants,"
    byte-for-byte the pre-existing draw.
    """
    os.makedirs(out_dir, exist_ok=True)

    checkpoint = _load_checkpoint(out_dir)
    if checkpoint is not None:
        if not resume:
            raise RuntimeError(
                f"{_checkpoint_path(out_dir)!r} already exists (a previous run wrote it); "
                "pass --resume to continue that run, or use a fresh --out directory"
            )
        for field, value in (
            ("seed", seed),
            ("instances_per_config", instances_per_config),
            ("mechanism", mechanism),
            ("expect", expect),
            ("reserve_mode", reserve_mode),
            ("eligible_fraction", eligible_fraction),
            ("reserve_type", reserve_type),
            ("precedence", precedence),
        ):
            if checkpoint.get(field) != value:
                raise RuntimeError(
                    f"cannot --resume: checkpoint has {field}={checkpoint.get(field)!r}, "
                    f"but this invocation asked for {field}={value!r} -- these must match "
                    "exactly for resuming to be meaningful (--configs is the one field that "
                    "may safely grow across a resume)"
                )
        completed = set(checkpoint["completed_config_indices"])
    else:
        checkpoint = {
            "seed": seed,
            "instances_per_config": instances_per_config,
            "mechanism": mechanism,
            "expect": expect,
            "reserve_mode": reserve_mode,
            "eligible_fraction": eligible_fraction,
            "reserve_type": reserve_type,
            "precedence": precedence,
            "n_students_choices": list(n_students_choices or N_STUDENTS_CHOICES),
            "n_schools_choices": list(n_schools_choices or N_SCHOOLS_CHOICES),
            "school_lists_full_probability": (
                SCHOOL_LISTS_FULL_PROBABILITY
                if school_lists_full_probability is None
                else school_lists_full_probability
            ),
            "unacceptable_policy_fraction": (
                UNLISTED_POLICY_WEIGHTS[0][1]
                if unacceptable_policy_fraction is None
                else unacceptable_policy_fraction
            ),
            "completed_config_indices": [],
            "witnesses_omitted_total": 0,
        }
        completed = set()

    reserve_overrides = {
        "reserve_mode": reserve_mode,
        "eligible_fraction": eligible_fraction,
        "reserve_type": reserve_type,
        "precedence": precedence,
    }
    all_params = draw_configurations(
        seed,
        configs,
        reserve_overrides=reserve_overrides,
        n_students_choices=n_students_choices,
        n_schools_choices=n_schools_choices,
        school_lists_full_probability=school_lists_full_probability,
        unacceptable_policy_fraction=unacceptable_policy_fraction,
    )
    pending = [p for p in all_params if p["config_index"] not in completed]

    journal = Journal(os.path.join(out_dir, "negative_control.jsonl"))
    hits_journal = Journal(os.path.join(out_dir, "negative_control_hits.jsonl"))
    # Always touched into existence (even under --expect zero, and even when
    # nothing is ever appended to them), the same way `hits_journal` always
    # exists whether or not a hit occurs -- a reader should never have to
    # infer "nothing happened" from a missing file.
    #
    # `witnesses_journal` holds BARE witness dicts -- see the module
    # docstring's "IS THE ARTIFACT OF RECORD" section -- exactly the schema
    # `witness.replay` consumes; `witness_index_journal` is the sidecar that
    # carries this script's own provenance (config_index / instance_index)
    # for each recorded witness, keyed by that witness's own "witness_id",
    # so the two files can be joined without nesting anything inside the
    # witness object itself.
    witnesses_journal = Journal(os.path.join(out_dir, "witnesses.jsonl"))
    witness_index_journal = Journal(os.path.join(out_dir, "witness_index.jsonl"))
    verification_failures_journal = Journal(
        os.path.join(out_dir, "verification_failures.jsonl")
    )

    results: list = []
    wall_t0 = time.perf_counter()
    if not pending:
        pass
    elif workers <= 1:
        for p in pending:
            r = process_configuration(p, instances_per_config, mechanism, expect, verify_hits=verify_hits)
            print(
                f"config {r['config_index']}: n_instances={r['n_instances']} "
                f"hit={r['hit']} manipulable_cases={r.get('manipulable_cases', 0)} "
                f"elapsed={r['elapsed_seconds']:.3f}s"
            )
            results.append(r)
            if r["hit"] or r.get("singleton_violation") or r.get("verification_failure"):
                break
    else:
        tasks = [
            {
                "params": p,
                "instances_per_config": instances_per_config,
                "mechanism": mechanism,
                "expect": expect,
                "verify_hits": verify_hits,
            }
            for p in pending
        ]
        with multiprocessing.Pool(processes=workers) as pool:
            abort_seen = False
            for r in pool.imap_unordered(_worker, tasks):
                print(
                    f"config {r['config_index']}: n_instances={r['n_instances']} "
                    f"hit={r['hit']} manipulable_cases={r.get('manipulable_cases', 0)} "
                    f"elapsed={r['elapsed_seconds']:.3f}s"
                )
                results.append(r)
                if (
                    r["hit"] or r.get("singleton_violation") or r.get("verification_failure")
                ) and not abort_seen:
                    abort_seen = True
                    pool.terminate()
                    break
    wall_seconds_this_invocation = time.perf_counter() - wall_t0

    hit_results = [r for r in results if r["hit"]]
    # Additive: a singleton-sufficiency violation (`witness.invariants`, the
    # PROVED regime only -- see that module's docstring) and a FAILED sampled
    # re-verification (`--expect manipulations` only) are each their own
    # abort condition, distinct from a manipulation "hit" and from each
    # other -- all three are real defects, in EITHER `--expect` mode.
    # Excluded here from `normal_results` the same way a hit's own config is:
    # a config that hit any of these is not a clean, fully-processed one.
    singleton_violation_results = [r for r in results if r.get("singleton_violation")]
    verification_failure_results = [r for r in results if r.get("verification_failure")]

    abort_candidates: "list[tuple[str, dict]]" = []
    if hit_results:
        abort_candidates.append(("hit", min(hit_results, key=lambda r: r["config_index"])))
    if singleton_violation_results:
        abort_candidates.append(
            ("singleton_violation", min(singleton_violation_results, key=lambda r: r["config_index"]))
        )
    if verification_failure_results:
        abort_candidates.append(
            ("verification_failure", min(verification_failure_results, key=lambda r: r["config_index"]))
        )

    if abort_candidates:
        abort_kind, first_abort = min(abort_candidates, key=lambda kv: kv[1]["config_index"])
        first_abort_index = first_abort["config_index"]
        normal_results = [
            r
            for r in results
            if not r["hit"]
            and not r.get("singleton_violation")
            and not r.get("verification_failure")
            and r["config_index"] < first_abort_index
        ]
    else:
        abort_kind, first_abort = None, None
        normal_results = [
            r
            for r in results
            if not r["hit"] and not r.get("singleton_violation") and not r.get("verification_failure")
        ]
    # Requirement: output order is deterministic regardless of --workers or
    # scheduling -- collect (already done above) then sort by config_index
    # before writing anything.
    normal_results.sort(key=lambda r: r["config_index"])

    instances_this_invocation = 0
    witnesses_recorded_total = len(witnesses_journal)  # carries over across --resume
    witnesses_omitted_this_invocation = 0
    for r in normal_results:
        record = {
            "config_index": r["config_index"],
            "params": r["params"],
            "mechanism": mechanism,
            "expect": r.get("expect", expect),
            "n_instances": r["n_instances"],
            # Same value as "n_instances", under the name the reporting
            # contract requires: the actual number of instances run for
            # this configuration, always the real int (never null) --
            # `instances_per_config` if no hit, else the 1-based count
            # through the hit (see `process_configuration`).
            "instances_run": r["n_instances"],
            "mechanism_runs_per_instance": r["mechanism_runs_per_instance"],
            # Under --expect zero this is always 0 (that mode aborts before
            # a normal result could ever carry a manipulation). Under
            # --expect manipulations it equals "manipulable_cases" below --
            # kept as its own field for continuity with the pre-existing
            # summary key of the same name.
            "manipulations_found": r.get("manipulable_cases", 0),
            # Manipulations-mode aggregates (additive; see
            # process_configuration's docstring for exact definitions).
            "manipulable_cases": r.get("manipulable_cases", 0),
            "instances_with_manipulation": r.get("instances_with_manipulation", 0),
            "hits_verified": r.get("hits_verified", 0),
            "hits_unverified": r.get("hits_unverified", 0),
            # witness.invariants singleton-sufficiency aggregates (additive;
            # see process_configuration and witness.invariants' module
            # docstring for the proved-vs-recorded scope distinction).
            "singleton_cases": r.get("singleton_cases", 0),
            "singleton_holds": r.get("singleton_holds", 0),
            "singleton_checks_skipped": r.get("singleton_checks_skipped", 0),
            # Reserve-structure exercise rate (additive; 0/0 for every
            # mechanism without a precedence order). Journalled per
            # configuration, not just summed in the summary, so a sweep whose
            # shapes were too narrow can be identified after the fact from
            # the artifact alone rather than by re-running it.
            "ttc_instances_measured": r.get("ttc_instances_measured", 0),
            "ttc_common_order_instances": r.get("ttc_common_order_instances", 0),
            "precedence_flipped_runs": r.get("precedence_flipped_runs", 0),
            "precedence_changed_matching": r.get("precedence_changed_matching", 0),
            "coverage": r["coverage"],
            "branch_hit_counts": r["branch_hit_counts"],
            "elapsed_seconds": r["elapsed_seconds"],
        }
        journal.append(record)
        instances_this_invocation += r["n_instances"]

        # Every recorded witness (only ever non-empty under
        # --expect manipulations), capped at `max_witnesses` TOTAL (not per
        # configuration) so the file cannot grow without bound; the cap
        # persists correctly across --resume via the checkpoint's own
        # "witnesses_omitted_total" and by starting this invocation's count
        # from the journal's existing length.
        for entry in r.get("witnesses", ()):
            if witnesses_recorded_total < max_witnesses:
                wd = entry["witness"]
                # BARE witness dict, unwrapped -- see the module docstring's
                # "IS THE ARTIFACT OF RECORD" section. This is exactly what
                # `witness.search.search_all_students(...)[i].to_dict()`
                # produced; nothing of this script's own bookkeeping is
                # nested inside it.
                witnesses_journal.append(wd)
                # Provenance lives beside the witness, never inside it,
                # joined back by the witness's own "witness_id".
                witness_index_journal.append(
                    {
                        "witness_id": wd["witness_id"],
                        "config_index": r["config_index"],
                        "instance_index": entry["instance_index"],
                    }
                )
                witnesses_recorded_total += 1
            else:
                witnesses_omitted_this_invocation += 1

        completed.add(r["config_index"])
        checkpoint["completed_config_indices"] = sorted(completed)
        checkpoint["witnesses_omitted_total"] = (
            checkpoint.get("witnesses_omitted_total", 0) + witnesses_omitted_this_invocation
        )
        _write_checkpoint_atomic(out_dir, checkpoint)
        # Only THIS configuration's omissions must be added to the running
        # checkpoint total once; reset so the next configuration's loop
        # iteration doesn't double-count it on the next checkpoint write.
        witnesses_omitted_this_invocation = 0

    if abort_kind == "hit":
        _print_hit_banner(first_abort)
        hits_journal.append(
            {
                "config_index": first_abort["config_index"],
                "params": first_abort["params"],
                "mechanism": mechanism,
                "expect": expect,
                "instance_index": first_abort["instance_index"],
                "witness": first_abort["witness"],
                "verified_in_fresh_subprocess": first_abort["verified_ok"],
                "verify_reasons": first_abort["verify_reasons"],
                "market": first_abort["market"],
                "profile": first_abort["profile"],
                "mechanism_config": first_abort["mechanism_config"],
            }
        )
        print(
            f"ABORTING: manipulation found at config_index={first_abort['config_index']} "
            f"instance_index={first_abort['instance_index']}. See "
            f"{os.path.join(out_dir, 'negative_control_hits.jsonl')} for the full record. "
            "The sweep was stopped; nothing past this point was run."
        )
        return 1

    if abort_kind == "singleton_violation":
        v = first_abort["singleton_violation"]
        _print_singleton_violation_banner(first_abort)
        singleton_violations_journal = Journal(
            os.path.join(out_dir, "singleton_violations.jsonl")
        )
        singleton_violations_journal.append(
            {
                "config_index": first_abort["config_index"],
                "params": first_abort["params"],
                "mechanism": mechanism,
                "expect": expect,
                "instance_index": v["instance_index"],
                "message": v["message"],
                "market": v["market"],
                "profile": v["profile"],
                "mechanism_config": v["mechanism_config"],
            }
        )
        print(
            f"ABORTING: singleton-sufficiency violation found at "
            f"config_index={first_abort['config_index']} instance_index="
            f"{v['instance_index']}. See "
            f"{os.path.join(out_dir, 'singleton_violations.jsonl')} for the full record. "
            "The sweep was stopped; nothing past this point was run."
        )
        return 1

    if abort_kind == "verification_failure":
        v = first_abort["verification_failure"]
        _print_verification_failure_banner(first_abort)
        verification_failures_journal.append(
            {
                "config_index": first_abort["config_index"],
                "params": first_abort["params"],
                "mechanism": mechanism,
                "expect": expect,
                "instance_index": v["instance_index"],
                "witness": v["witness"],
                "verify_reasons": v["verify_reasons"],
                "market": v["market"],
                "profile": v["profile"],
                "mechanism_config": v["mechanism_config"],
            }
        )
        print(
            f"ABORTING: a sampled witness FAILED independent re-verification at "
            f"config_index={first_abort['config_index']} instance_index="
            f"{v['instance_index']}. See "
            f"{os.path.join(out_dir, 'verification_failures.jsonl')} for the full record. "
            "This is a real defect, regardless of --expect. The sweep was stopped; "
            "nothing past this point was run."
        )
        return 1

    _write_summary(
        out_dir=out_dir,
        journal=journal,
        seed=seed,
        mechanism=mechanism,
        expect=expect,
        verify_hits=verify_hits,
        max_witnesses=max_witnesses,
        requested_configs=configs,
        wall_seconds_this_invocation=wall_seconds_this_invocation,
        instances_this_invocation=instances_this_invocation,
        configs_this_invocation=len(normal_results),
        witnesses_recorded=len(witnesses_journal),
        witnesses_omitted=checkpoint.get("witnesses_omitted_total", 0),
        reserve_mode=reserve_mode,
        eligible_fraction=eligible_fraction,
        reserve_type=reserve_type,
        precedence=precedence,
        n_students_choices=n_students_choices,
        n_schools_choices=n_schools_choices,
        school_lists_full_probability=school_lists_full_probability,
        unacceptable_policy_fraction=unacceptable_policy_fraction,
    )
    return 0


def parse_args(argv: "list[str] | None" = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python3 scripts/negative_control.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--seed", default="negative-control", help="root seed for the whole sweep")
    parser.add_argument(
        "--instances-per-config", type=int, default=40, help="instances to run per configuration"
    )
    parser.add_argument("--configs", type=int, default=288, help="number of configurations to sweep")
    parser.add_argument(
        "--out", default="results/negative_control", help="output directory for all four result files"
    )
    parser.add_argument(
        "--resume", action="store_true", help="continue a previous run found in --out via its checkpoint"
    )
    parser.add_argument("--workers", type=int, default=1, help="parallel worker processes (>=1)")
    parser.add_argument(
        "--n-students-choices",
        default=None,
        help=(
            "comma-separated student counts to draw shapes from (default "
            f"{','.join(map(str, N_STUDENTS_CHOICES))}). Widen this for a "
            "mechanism whose choice rule has internal structure: at one seat "
            "per school, reserve_da's precedence order has nothing to order."
        ),
    )
    parser.add_argument(
        "--n-schools-choices",
        default=None,
        help=(
            "comma-separated school counts to draw shapes from (default "
            f"{','.join(map(str, N_SCHOOLS_CHOICES))}). NOTE the exhaustive "
            "report space grows superexponentially in this, so raise "
            "--n-students-choices instead when you want bigger schools."
        ),
    )
    parser.add_argument(
        "--school-lists-full-probability",
        type=float,
        default=None,
        help=(
            "override SCHOOL_LISTS_FULL_PROBABILITY (default "
            f"{SCHOOL_LISTS_FULL_PROBABILITY}): the probability a configuration "
            "draws school_lists_fraction == 1.0 (every school lists every "
            "student). Lower this toward 0.0 to make school_lists_fraction < 1.0 "
            "-- a PREREQUISITE for had_school_unacceptable_rejection -- draw "
            "more often; combine with --unacceptable-policy-fraction to widen "
            "that branch reliably rather than relying on enough configurations "
            "for the baseline rate to average out. Must be in [0.0, 1.0]."
        ),
    )
    parser.add_argument(
        "--unacceptable-policy-fraction",
        type=float,
        default=None,
        help=(
            "override the probability a configuration draws "
            "unlisted_student_policy=UNLISTED_UNACCEPTABLE rather than "
            "UNLISTED_LOWEST_CLASS (default 0.5, an even coin flip). Raise "
            "this toward 1.0 -- together with --school-lists-full-probability "
            "toward 0.0 -- to reliably exercise had_school_unacceptable_rejection "
            "within a small number of configurations rather than relying on the "
            "default ~35%% per-configuration baseline. Must be in [0.0, 1.0]."
        ),
    )
    parser.add_argument(
        "--mechanism",
        default=MECHANISM_STUDENT_PROPOSING_DA,
        choices=SUPPORTED_MECHANISMS,
        help="mechanism to search for manipulations under (default: student_proposing_da, "
        "which is strategy-proof -- any hit is a bug)",
    )
    parser.add_argument(
        "--expect",
        default=None,
        choices=VALID_EXPECTATIONS,
        help=(
            "'zero': manipulations are a BUG, abort on the first one (the negative "
            "control). 'manipulations': manipulations are EXPECTED, count and record "
            "them, never abort (the positive/calibration mode). Defaults per "
            "--mechanism when omitted (student_proposing_da -> zero, "
            "boston_immediate_acceptance -> manipulations); an explicit --expect "
            "always overrides that default."
        ),
    )
    parser.add_argument(
        "--verify-hits",
        type=int,
        default=1,
        help=(
            "under --expect manipulations only: independently re-verify the first N "
            "manipulations found PER CONFIGURATION in a fresh subprocess (default 1); "
            "the rest are counted but not re-verified (see hits_verified / "
            "hits_unverified in the output). A failed sampled verification always "
            "aborts the run, regardless of --expect."
        ),
    )
    parser.add_argument(
        "--max-witnesses",
        type=int,
        default=1000,
        help=(
            "under --expect manipulations only: cap on the total number of witnesses "
            "appended to <out>/witnesses.jsonl (bare witness dicts, replay-ready) "
            "across the whole run (default 1000), with matching provenance rows in "
            "<out>/witness_index.jsonl; the count omitted by the cap is recorded in "
            "the summary"
        ),
    )
    parser.add_argument(
        "--reserve-mode",
        default=RESERVE_MODE_NONE,
        choices=_RESERVE_MODE_CHOICES,
        help=(
            "--mechanism reserve_da only (inert, but still recorded, for every other "
            "mechanism): how many seats each school reserves. 'none' (default): 0. "
            "'half': ceil(capacity/2) -- Boston's 50/50 walk-zone split, the DKPS "
            "(2018) case. 'all': every seat. 'random': a count drawn uniformly, "
            "deterministically, from 0..capacity. Applied uniformly to every "
            "configuration in the sweep (see witness.generate.GeneratorConfig.reserve_mode)."
        ),
    )
    parser.add_argument(
        "--eligible-fraction",
        type=float,
        default=0.5,
        help=(
            "--mechanism reserve_da only: for each (school, student) pair "
            "independently, the probability that student is reserve-eligible at "
            "that school (eligibility is per-school -- a walk zone -- never a global "
            "student attribute). Must be in [0.0, 1.0]. Default 0.5."
        ),
    )
    parser.add_argument(
        "--reserve-type",
        default=RESERVE_SOFT,
        choices=_RESERVE_TYPE_CHOICES,
        help=(
            "--mechanism reserve_da only: 'soft_reserve' (default) -- a reserve seat "
            "is a FLOOR, an ineligible student may take it if unclaimed. 'hard_quota' "
            "-- a reserve seat is EXCLUSIVE, it goes empty rather than seat an "
            "ineligible student."
        ),
    )
    parser.add_argument(
        "--precedence",
        default=PRECEDENCE_RESERVE_FIRST,
        choices=_PRECEDENCE_CHOICES,
        help=(
            "--mechanism reserve_da only: 'reserve_first' (default) -- reserve slots "
            "filled before open slots (what Boston did). 'open_first' -- open slots "
            "filled first."
        ),
    )
    return parser.parse_args(argv)



def _parse_choices(raw, flag):
    """Parse a comma-separated positive-int list, or None to keep the default.

    Raises rather than silently ignoring a malformed value: a shape flag that
    quietly fell back to the default would make the sweep report a width it
    never swept, which is the exact failure this flag exists to prevent.
    """
    if raw is None:
        return None
    try:
        values = tuple(int(x) for x in str(raw).split(",") if x.strip() != "")
    except ValueError:
        raise SystemExit(f"{flag}: expected comma-separated integers, got {raw!r}")
    if not values or any(v < 1 for v in values):
        raise SystemExit(f"{flag}: need at least one positive integer, got {raw!r}")
    return values


def main(argv: "list[str] | None" = None) -> int:
    args = parse_args(argv)
    if args.workers < 1:
        raise ValueError(f"--workers must be >= 1, got {args.workers}")
    if args.configs < 1:
        raise ValueError(f"--configs must be >= 1, got {args.configs}")
    if args.instances_per_config < 1:
        raise ValueError(f"--instances-per-config must be >= 1, got {args.instances_per_config}")
    if args.verify_hits < 0:
        raise ValueError(f"--verify-hits must be >= 0, got {args.verify_hits}")
    if args.max_witnesses < 0:
        raise ValueError(f"--max-witnesses must be >= 0, got {args.max_witnesses}")
    if not (0.0 <= args.eligible_fraction <= 1.0):
        raise ValueError(f"--eligible-fraction must be in [0.0, 1.0], got {args.eligible_fraction}")
    if args.school_lists_full_probability is not None and not (
        0.0 <= args.school_lists_full_probability <= 1.0
    ):
        raise ValueError(
            "--school-lists-full-probability must be in [0.0, 1.0], got "
            f"{args.school_lists_full_probability}"
        )
    if args.unacceptable_policy_fraction is not None and not (
        0.0 <= args.unacceptable_policy_fraction <= 1.0
    ):
        raise ValueError(
            "--unacceptable-policy-fraction must be in [0.0, 1.0], got "
            f"{args.unacceptable_policy_fraction}"
        )

    expect = resolve_expect(args.mechanism, args.expect)
    if args.expect == EXPECT_ZERO and DEFAULT_EXPECT_BY_MECHANISM.get(args.mechanism) != EXPECT_ZERO:
        print(
            f"NOTE: --expect zero was explicitly requested for mechanism "
            f"{args.mechanism!r}, whose default is 'manipulations' (it is manipulable "
            "by design) -- this run is expected to ABORT as soon as a manipulation "
            "is found."
        )

    return run_sweep(
        seed=args.seed,
        configs=args.configs,
        instances_per_config=args.instances_per_config,
        mechanism=args.mechanism,
        out_dir=args.out,
        resume=args.resume,
        workers=args.workers,
        expect=expect,
        verify_hits=args.verify_hits,
        max_witnesses=args.max_witnesses,
        reserve_mode=args.reserve_mode,
        eligible_fraction=args.eligible_fraction,
        reserve_type=args.reserve_type,
        precedence=args.precedence,
        n_students_choices=_parse_choices(args.n_students_choices, "--n-students-choices"),
        n_schools_choices=_parse_choices(args.n_schools_choices, "--n-schools-choices"),
        school_lists_full_probability=args.school_lists_full_probability,
        unacceptable_policy_fraction=args.unacceptable_policy_fraction,
    )


if __name__ == "__main__":
    raise SystemExit(main())
