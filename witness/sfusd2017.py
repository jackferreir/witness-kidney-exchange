"""Adapter for REAL, deployed administrative data: SFUSD's 2017-18
Kindergarten Main Round.

    Source: San Francisco Unified School District kindergarten
    application/assignment records, obtained by KQED journalist Lisa
    Pickoff-White via a California Public Records Act request, hosted at
    https://github.com/pickoffwhite/San-Francisco-Kindergarten-Lottery
    Raw file: data/external/sfusd_2017_kindergarten/
    Academic analysis of this same dataset: Robertson, Nguyen & Salehi,
    "Modeling Assumptions Clash with the Real World," CHI 2021,
    arXiv:2101.10367.

This is the project's second real dataset and its first that is NOT a lab
experiment: `witness.stephenson` replayed 432 recruited subjects who knew
they were in a study; this file replays roughly 4,600 real five-year-olds'
families making a real, consequential choice about where their child goes to
school. That difference matters for what this module can and cannot claim --
see "REPORTED VS TRUE PREFERENCES" and "WHY THIS COULD NOT BE RECOVERED THE
WAY STEPHENSON'S WAS" below, both load-bearing for how any result here may be
described.

WHAT THE REAL 2017-18 MECHANISM ACTUALLY WAS (established from primary
sources, not assumed)
The task that produced this module started from the premise that SFUSD used
student-proposing deferred acceptance in 2017. That premise is WRONG for this
dataset's year, and this is the module's most important finding. Per the
policy paper "Designing School Choice for Diversity in the San Francisco
Unified School District" (Allman, Ashlagi, Lo, Love, Mentzer, O'Connell &
Ruiz-Setz), quoted verbatim:

    "Between the years 2010-2018, the assignment algorithm was based on a
    modification of the Top Trading Cycles algorithm, which allows families
    to trade priorities in trading cycles for admission to preferred
    schools [Abdulkadiroglu and Sonmez, 2003]. We noted that the implemented
    algorithm was neither strategyproof nor envy-free, and families reported
    confusion regarding the algorithm and its properties. Since 2019, in
    line with our recommendation, the algorithm has been based on the
    Deferred Acceptance algorithm."

Leshno & Lo, "The Cutoff Structure of Top Trading Cycles in School Choice"
(2017 working paper; published as Leshno & Lo 2021, Review of Economic
Studies) independently corroborates this: "the only instances of
implementation of TTC in school choice systems are in the San Francisco
school district ... and previously in the New Orleans Recovery School
District." The CHI 2021 paper analyzing this exact dataset says the same in
a footnote: "SFUSD uses a variant of the Top Trading Cycles algorithm."

So the 2017-18 mechanism is TTC-FAMILY, not DA -- and explicitly NOT plain
TTC either ("a modification ... neither strategyproof nor envy-free"; plain
TTC is always strategy-proof, so whatever SFUSD actually ran provably
differs from `witness.ttc.top_trading_cycles` in some particular this
project does not have a primary source pinning down). `witness/` has no
implementation of that specific modification and this task is explicitly
out of scope for writing new mechanism logic, so this module runs the THREE
existing candidates that bracket the possibilities -- plain TTC (the
best-documented family), plain student-proposing DA (what SFUSD runs today,
included as a natural comparison point), and Boston immediate acceptance
(included because, as the empirical results below show, it is NOT safe to
assume the historically-correct mechanism family wins the match-rate
comparison) -- and reports which one comes closest, honestly, rather than
picking TTC because it is the documented one and stopping there.

THE PRIORITY STRUCTURE (established from primary sources)
The same policy paper states the priority order used to feed the algorithm,
independent of which algorithm consumed it:

    "Highest priority is given to students with a sibling at the program,
    followed by students living in the 20% of census tracts with the lowest
    test scores in the 2010 census (CTIP1), and finally students from the
    school's attendance area. A random lottery, drawn independently at each
    program, breaks remaining ties, in a process known in the literature as
    multiple tie-breaking."

So the real hierarchy is: sibling > CTIP1 > attendance area > per-program
random lottery (MTB, not a single shared lottery).

WHY THIS COULD NOT BE RECOVERED THE WAY STEPHENSON'S WAS
`witness.stephenson` recovered an unknown priority ordering by exhaustive
search, because the Zenodo dataset recorded every input the priority order
was a function of (`type`, `lotto`) even though it did not record the
ordering itself -- so a finite search (6^3 = 216 candidates) against 5,184
ground-truth outcomes could falsify all but two.

This dataset is different in kind, not just in scale: the raw file records
NONE of the following, at all:

  * whether a student has a sibling already at a program (no column exists);
  * which attendance area a student's address falls in (only a ZIP code is
    given, which is coarser than SFUSD's 58 attendance-area boundaries and
    does not map onto them without external GIS data this project does not
    have and did not fetch);
  * the per-program lottery number that broke ties among equal-priority
    students (no column exists -- contrast Stephenson's `lotto` column,
    which recorded exactly this).

Only ONE of the four real priority inputs is present: `Does Student Live In
CTIP1 Zone? (y/n)`. This is not a search that happens to be hard -- it is
not a search at all. A per-program random lottery over hundreds of
similarly-situated applicants has no finite candidate space to falsify
against a single realized draw, the way Stephenson's 216 structural orderings
did against 5,184 outcomes. So this module does NOT claim to have recovered
SFUSD's real priority order. It builds the one priority signal the data
actually contains (CTIP1) into the correct position the primary source
states (top tier, ahead of an unmodelled sibling/attendance-area/lottery
residue), and uses a clearly-named STAND-IN tiebreak (`STAND_IN_SEED` below)
for everything the data cannot supply. The stand-in is fixed once, named as
what it is, and never tuned against the outcome column -- tuning it would be
fitting a proxy to a target number, exactly what REVIEWER.md's "test the
property, not a proxy" rule forbids.

SIBLING PRIORITY: CONFIRMED UNRECOVERABLE (re-checked, not just assumed)
A later pass over this module re-examined whether sibling priority
specifically -- the primary source's TOP tier, ahead of even CTIP1 -- could
be reconstructed some other way, e.g. from a shared household/family
identifier or a shared address. It cannot. The raw file's own header (all
98 columns, not just the subset `RAW_FIELDS` reads) was checked directly --
see tests/test_sfusd2017_replay.py's
`test_no_sibling_household_or_address_column_exists_in_the_raw_file` -- and
contains no column whose name contains "sibling", "household", "family",
"address", or "street", and the only geographic field at any granularity is
`Student's Residential Zip Code`. There is no address to match siblings by
shared residence, and no family/household ID to match them by directly.
Ethnicity, ZIP code, and every other retained column are all things a
sibling pair could easily NOT share (siblings can differ in ethnicity as
recorded, and a family that moved between a sibling's enrollment and this
child's application would show different ZIP codes) or could coincidentally
share with a complete stranger, so none of them is evidence of sibling
status and none is used as a stand-in for it. This is a hard, named gap:
sibling priority is not modeled anywhere in this file, for anyone, ever --
not attempted-and-approximated the way attendance area was (see below), but
genuinely absent from what this dataset can support.

ATTENDANCE AREA: INVESTIGATED AND NOT MODELED, WITH THE INVESTIGATION SHOWN
A later pass over this module specifically asked whether attendance-area
priority -- the primary source's THIRD tier, below CTIP1 -- could be added
as a second modeled priority class, since (unlike sibling) the raw file at
least contains a geographic field (ZIP code) that is *related* to
attendance area, even though it is not attendance area itself. Real SFUSD
attendance-area boundary data was fetched and used to test this directly,
rather than assumed impossible by analogy to sibling. See
data/external/sfusd_2017_kindergarten/attendance_area_geography/SOURCE.txt
for full provenance and tests/test_sfusd2017_attendance_area_geography.py
for the exact, re-runnable computation. Two problems were found, and either
alone would be disqualifying:

  1. YEAR MISMATCH. The only usable published SFUSD attendance-area
     boundary data (DataSF, extracted from SFUSD's own GIS system) is
     dated 2023 and labeled for the 2024-2025 school year -- seven years
     after this dataset's 2017-18 Main Round. No earlier-dated version was
     found on DataSF, and a candidate lead the task specifically named,
     archive.sfusd.edu's `final-elementary-attendance-areas-map.pdf`, could
     not even be reached: the host did not respond to a direct connection
     attempt (TCP-level timeout, not a 404), so its year could not be
     checked at all. Attendance areas as a POLICY were in continuous use
     from roughly 2010-11 through the 2025-26 zone-based redesign per
     SFUSD's own FAQ, which is circumstantial evidence the boundary LINES
     might also have been stable across that span, but no primary source
     found in this investigation confirms the 2024-2025 lines are
     geometrically identical to the 2017-18 lines. This is reported as an
     open, unresolved discrepancy, exactly as this module already does for
     the CHI 2021 paper's 4,594-vs-4,611 applicant count.
  2. GRANULARITY MISMATCH -- QUANTIFIED, NOT ASSUMED, AND DISPOSITIVE ON ITS
     OWN even if problem 1 were somehow resolved. SFUSD's 58 elementary
     attendance areas do not align with San Francisco's ~27 ZIP codes:
     computed directly from the real attendance-area polygons and 2010
     Census ZCTA boundaries (shapely polygon intersection, not eyeballed),
     24 of 27 SF ZIP codes meaningfully overlap MORE than one attendance
     area, the single best-covering ("plurality") attendance area inside a
     ZIP covers a MEDIAN of only 43.0% of that ZIP's own area, and --
     weighting by this dataset's own 4,594 SF-resident applicants rather
     than just by ZIP count -- 84.3% of them live in a ZIP where no single
     attendance area covers even half the ZIP's area. A "guess each
     applicant's attendance area from their ZIP's plurality attendance
     area" join would therefore be WRONG for the large majority of real
     applicants, which is a fundamentally different and worse situation
     than CTIP1 (a field the raw file states directly, requiring no
     geographic join or inference of any kind).

  DECISION: attendance-area priority is NOT added to `build_market` or any
  mechanism config in this module. Per this project's standing instruction
  to say plainly when something cannot be reconstructed rather than force a
  noisy join and call it progress: forcing this join would not have
  recovered attendance-area priority, it would have manufactured a third,
  ZIP-shaped, mostly-wrong signal and mixed it into the market under a name
  that promised more than it delivered. The CTIP1-only match rates in
  EMPIRICAL RESULT below are therefore UNCHANGED by this investigation --
  this is reported as the honest finding of the investigation, not as a
  gap still waiting to be closed.

MARKET GRANULARITY
One market = the entire 2017-18 Kindergarten Main Round: every applicant
against every program, run once. This is not a simplification -- it is what
"one market is one school/grade" collapses to here, because this file
covers exactly one grade (Kindergarten; the filename is "K Placement
2017-2018" and there is no grade column, confirming it is K-only) and SFUSD's
Main Round is itself a single centralized computation over all K programs at
once, not 72 independent per-school runs. Unlike Stephenson's 216 small
24-participant periods, this is one large (~4,600 student, 72 school)
instance.

SCHOOL VS. PROGRAM GRANULARITY -- A REAL LIMITATION, NOT SMOOTHED OVER
The raw file's rank columns hold a bare numeric SCHOOL code, not a
(school, pathway) pair, even though SFUSD's real Main Round matches students
to PROGRAMS (a school can host several: General Education, a language
pathway, special-day-class programs -- the current public success-rate
sheets show a "Pathway" column with values like GE/SA/CA/BA that this
1487-column-narrower 2017 file does not have). Direct evidence this
collapsing happened: 1,647 of 4,611 applicants (about 36%) list the SAME
school code more than once across their own 92 rank columns -- which can
only mean they ranked two different programs at the same school (e.g.
General Education and a Spanish immersion pathway), both recorded under one
undifferentiated code. `_ranked_schools` below keeps a student's FIRST
(best) mention of a school and drops later repeats, because
`witness.core.Profile` requires a strict ranking and a repeated school is not
one. This discards real preference information the file cannot supply
(which specific program), and this project cannot recover it. It also means
this adapter's per-"school" capacity is really an aggregate over one or more
real programs -- see CAPACITY INFERENCE.

CAPACITY INFERENCE
No capacity column exists. `capacity[c]` is set to the number of applicants
whose recorded `Round 1 Assignment` equals `c`. This is a deliberate,
declared choice, not a guess dressed up as one: DA/TTC/Boston's choice rule
only ever rejects an applicant for a school BECAUSE the school is full, so
for any school that was actually oversubscribed the realized fill count IS
the binding capacity -- any replay using this value reproduces the same
rejections a larger true capacity would. For a school that was NOT
oversubscribed, any true capacity at or above the realized count gives an
identical replay, so the exact true number cannot be recovered from
assignment counts alone but also cannot change the outcome. The one way this
inference can be WRONG in a way that matters: a program with real,
unmodelled eligibility screening (a language-immersion program requiring a
native/non-native placement test, a special-day class requiring an IEP) could
have left an eligible seat empty for a reason this adapter cannot see, in
which case the true capacity exceeds the realized count and this adapter
would under-count it. One school code (`476`) was ranked exactly once (by a
single applicant, at rank position 14) and never appears as anyone's Round 1
Assignment or enrolled school; capacity 0 is used for it, which is almost
certainly correct (nobody attended it in this data) but the code's presence
at all looks like a data artifact (a stale or mistyped program code) rather
than a real, currently-offered program, and is flagged rather than silently
dropped.

REPORTED VS TRUE PREFERENCES -- see witness.stephenson's Zenodo data for a
case where this project actually had both. Here it does not: only one column
per applicant records anything about preference (`1`..`92`), and it is
necessarily the family's REPORTED ranked list -- there is no companion
"true preference" column the way Stephenson's `truth` field provided. Any
manipulation search run against this profile answers "could this family have
done better with a different report, given everyone else's actual reports"
-- NOT "did the real mechanism make this family worse off than their true
preference," because their true preference is not observed and never will
be from this file. Per REVIEWER.md's disclosure section, nothing produced
from this dataset clears the bar for a public manipulability claim about a
real deployed system: the mechanism itself is not exactly implemented here
(see above), the priority structure is only partially recovered, and no
manipulation search at scale has been run. Any illustrative search result
from this module must carry this paragraph's caveat, prominently, every time
it is quoted.

EMPIRICAL RESULT, STATED HONESTLY
Unlike Stephenson (0 mismatches out of 5,184), replaying this dataset does
NOT reproduce the recorded Round 1 Assignment exactly, and is not expected
to given the missing sibling/attendance-area/lottery inputs above. Measured
results, under `STAND_IN_SEED`, exactly as computed by
tests/test_sfusd2017_replay.py (4,611 applicants; matched/total, rounded to
one decimal):

    top_trading_cycles:          2,586 / 4,611 = 56.1%
    student_proposing_da:        2,108 / 4,611 = 45.7%
    boston_immediate_acceptance: 2,800 / 4,611 = 60.7%

Boston immediate acceptance is the closest of the three under the stand-in
tiebreak -- NOT plain TTC, the historically-documented family, which is
itself a finding worth stating rather than papering over. Re-running with an
entirely unrelated stand-in seed (`STAND_IN_SEED_ALTERNATE`) moves all three
rates by only 1-2 points (54.2% / 45.4% / 61.2%), so the ranking and rough
magnitude are not an artifact of the one stand-in draw.

The gap is concentrated in non-CTIP1 students (the group whose
sibling/attendance-area priorities this adapter cannot see):

    CTIP1 students     (705 of 4,611): 677/705 = 96.0%, IDENTICALLY for all
                                        three mechanisms
    non-CTIP1 students (3,906 of 4,611): TTC 1,909/3,906 = 48.9%,
                                        DA 1,431/3,906 = 36.6%,
                                        Boston 2,123/3,906 = 54.4%

The CTIP1 identity across all three mechanisms is not a coincidence and is
fully mechanical, not just numerically observed: because CTIP1 is this
adapter's top (and only-modelled) priority class at every school, all three
mechanisms give every CTIP1 student their own reported FIRST choice, 100% of
the time (capacity, inferred as the realized fill count, is never scarce
enough among a same-priority-class population this small and this short-
listed to bind above the top tier -- see `witness.ttc.distinct_priority_orders`
on why a shared top class collapses TTC/DA/Boston to the same serial
dictatorship there). So a CTIP1 student's replayed assignment matches the
recorded one if and only if their RECORDED assignment was already their own
first choice -- and it independently turns out that this recorded-outcome
question ("did SFUSD's real 2017 process give this CTIP1 student their own
first choice") is true for exactly 677 of 705 CTIP1 applicants in the raw
file, 96.0%, which is what the CHI 2021 paper independently reports ("96% of
families eligible for CTIP1 priority were assigned their first choice") --
verified against the raw file directly in this module's tests, not merely
copied from the paper. The other three of the CHI 2021 paper's headline
sanity-check numbers were independently reproduced from this same raw file to
within rounding: mean ranked schools 5.5 (CTIP1) / 11.6 (non-CTIP1) / 16.5
(White applicants) in the paper vs. 5.59 / 11.60 / 16.59 measured here on the
raw (non-deduplicated) rank columns, and 58% (not 96%) of non-CTIP1 students
received their own first choice, vs. 58.1% measured here.

Non-CTIP1 match rates range from 36.6% to 54.4% across the three mechanisms,
which is the part of the outcome this adapter's model genuinely cannot see
(sibling, attendance area, the real per-program lottery).

DOES CTIP1 BEHAVE LIKE A RESERVE OR A PLAIN PRIORITY TIER HERE?
`full_ctip1_reserve_config` builds a `reserve_da` config giving CTIP1
students a SOFT reserve on every seat at every school, on top of the same
base order `build_market` already uses. Its replayed assignment is IDENTICAL
to plain `student_proposing_da` under the same tiebreak (0 of 4,611 students
differ; pinned in tests/test_sfusd2017_replay.py). This is expected, not a
coincidence: a reserve only has bite when its eligible group would NOT
already be seated first under the base priority order, and here CTIP1
already IS the base order's top tier. So for this dataset, under this
adapter's model, CTIP1 functions as a plain priority tier -- exactly what
the primary source's own language ("priority is given to...") already says
-- and modelling it as a reserve instead would have changed nothing.
"""

from __future__ import annotations

import csv
import collections
from dataclasses import dataclass
from typing import Iterable, Mapping, Optional, Sequence

from witness.boston import BostonConfig
from witness.core import Market, Profile
from witness.da import DAConfig
from witness.errors import ModelError
from witness.reserves import (
    PRECEDENCE_RESERVE_FIRST,
    RESERVE_SOFT,
    ReserveConfig,
    SchoolReserve,
)
from witness.tiebreak import MultipleLotteryTiebreak
from witness.ttc import TTCConfig

#: Rank-position columns in the raw file: "1" (first choice) .. "92".
RANK_COLUMNS = tuple(str(i) for i in range(1, 93))

#: Every column this adapter reads out of the raw CSV.
RAW_FIELDS = (
    "StudentNo",
    *RANK_COLUMNS,
    "Round 1 Assignment",
    "School Enrolled In As Of 11/03/2017",
    "Student's Ethnicity",
    "Does Student Live In CTIP1 Zone? (y/n)",
    "Student's Residential Zip Code",
)

#: A CLEARLY-NAMED STAND-IN for the real, unrecorded per-program lottery. See
#: the module docstring's "WHY THIS COULD NOT BE RECOVERED" section: this is
#: NOT SFUSD's real 2017 lottery, and no such thing can be recovered from
#: this file. Fixed once; never tuned against the recorded outcome column.
STAND_IN_SEED = "sfusd2017-standin-v1"

#: A second, unrelated seed used only to demonstrate that the match rate
#: below is not an artifact of this particular stand-in (see
#: tests/test_sfusd2017_replay.py).
STAND_IN_SEED_ALTERNATE = "sfusd2017-standin-v2-unrelated"

#: One school code that was ranked by exactly one applicant and never
#: assigned to, or enrolled by, anyone -- see the module docstring.
DEAD_SCHOOL_CODE = "476"

#: The three mechanisms already implemented in `witness/` that bracket what
#: SFUSD's real, undocumented TTC modification might have behaved like. See
#: the module docstring for why none of these IS the real mechanism.
CANDIDATE_MECHANISMS = (
    "top_trading_cycles",
    "student_proposing_da",
    "boston_immediate_acceptance",
)


@dataclass(frozen=True)
class StudentRecord:
    """One applicant, as needed to build a `Market`/`Profile` and to check a
    replay against the recorded outcome. `ranked_schools` is already
    deduplicated -- see `_dedupe_ranked_schools`. `raw_rank_count` is the
    number of non-empty rank columns BEFORE dedup (i.e. counting a
    same-school-different-program repeat as its own list entry); this is
    what the CHI 2021 paper's own "mean schools ranked" figures count (see
    `mean_raw_rank_count` and the module docstring's cross-check against
    that paper), so it is kept alongside the deduplicated list rather than
    only derivable from it."""

    student_id: str
    ranked_schools: tuple[str, ...]
    raw_rank_count: int
    ctip1: bool
    round1_assignment: Optional[str]
    enrolled_school: Optional[str]
    ethnicity: str
    zip_code: str

    def n_duplicate_school_mentions(self, raw_rank_values: Sequence[str]) -> int:
        """How many of the raw (non-deduplicated) rank entries were repeats.
        Exposed for the dataset-shape test that pins the 1,647-applicant
        duplication finding described in the module docstring."""
        seen: set[str] = set()
        dupes = 0
        for v in raw_rank_values:
            if not v:
                continue
            if v in seen:
                dupes += 1
            else:
                seen.add(v)
        return dupes


def _dedupe_ranked_schools(raw_rank_values: Sequence[str]) -> tuple[str, ...]:
    """First-occurrence dedup of a raw rank row. See the module docstring's
    "SCHOOL VS. PROGRAM GRANULARITY" section for why duplicates occur at all
    and why keeping the first (best) mention is the only sound choice."""
    out: list[str] = []
    seen: set[str] = set()
    for v in raw_rank_values:
        if v and v not in seen:
            out.append(v)
            seen.add(v)
    return tuple(out)


def load_raw_rows(csv_path: str) -> list[dict]:
    with open(csv_path, newline="") as f:
        return [
            {k: row[k] for k in RAW_FIELDS} for row in csv.DictReader(f)
        ]


def build_records(rows: Iterable[Mapping[str, str]]) -> tuple[StudentRecord, ...]:
    """Turn raw CSV rows into `StudentRecord`s, in the file's own row order."""
    out = []
    for row in rows:
        raw_ranks = tuple(row[c] for c in RANK_COLUMNS)
        out.append(
            StudentRecord(
                student_id=f"student{row['StudentNo']}",
                ranked_schools=_dedupe_ranked_schools(raw_ranks),
                raw_rank_count=sum(1 for v in raw_ranks if v),
                ctip1=row["Does Student Live In CTIP1 Zone? (y/n)"] == "Y",
                round1_assignment=row["Round 1 Assignment"] or None,
                enrolled_school=row["School Enrolled In As Of 11/03/2017"] or None,
                ethnicity=row["Student's Ethnicity"],
                zip_code=row["Student's Residential Zip Code"],
            )
        )
    return tuple(out)


def all_schools(records: Sequence[StudentRecord]) -> tuple[str, ...]:
    """Every school code seen anywhere (ranked or assigned), sorted for a
    stable, declared enumeration order -- never a set's incidental order."""
    seen: set[str] = set()
    for r in records:
        seen.update(r.ranked_schools)
        if r.round1_assignment:
            seen.add(r.round1_assignment)
    return tuple(sorted(seen))


def infer_capacities(
    records: Sequence[StudentRecord], schools: Sequence[str]
) -> dict[str, int]:
    """Capacity per school: the number of recorded Round 1 assignments to it.
    See the module docstring's "CAPACITY INFERENCE" section for why this is a
    safe, declared choice rather than a guess, and its one real failure mode
    (unmodelled eligibility screening leaving a seat idle)."""
    counts = collections.Counter(
        r.round1_assignment for r in records if r.round1_assignment
    )
    return {c: counts.get(c, 0) for c in schools}


def build_profile(records: Sequence[StudentRecord]) -> Profile:
    """What each family actually reported. See the module docstring's
    "REPORTED VS TRUE PREFERENCES" section -- there is no companion "true
    preference" column in this dataset, unlike Stephenson's."""
    return Profile({r.student_id: r.ranked_schools for r in records})


def recorded_assignment(records: Sequence[StudentRecord]) -> dict[str, Optional[str]]:
    """The outcome SFUSD's Round 1 actually produced -- what a replay is
    checked against. `None` means the applicant was not assigned in Round 1
    (141 of 4,611 in this dataset; confirmed separately that this is never
    because their recorded assignment sits outside their own reported list --
    see tests/test_sfusd2017_replay.py)."""
    return {r.student_id: r.round1_assignment for r in records}


def build_market(
    records: Sequence[StudentRecord], *, invert_ctip1: bool = False
) -> Market:
    """The single district-wide Round 1 market.

    Priority classes are `(ctip1_students, everyone_else)` at every school,
    matching the primary-source order "sibling > CTIP1 > attendance area >
    lottery" as far as this dataset's one observable signal (CTIP1) can
    represent it -- sibling and attendance-area status are not recorded (see
    the module docstring) and so cannot be given their own tiers; every
    applicant lacking sibling/attendance-area status is, from this adapter's
    point of view, indistinguishable from every other non-CTIP1 applicant.

    `invert_ctip1=True` swaps the two classes -- used by
    tests/test_sfusd2017_replay.py to confirm the model is actually sensitive
    to CTIP1's position (a deliberately WRONG structure should, and does,
    measurably change the outcome and degrade the match rate).
    """
    schools = all_schools(records)
    capacities = infer_capacities(records, schools)
    ctip1_students = tuple(r.student_id for r in records if r.ctip1)
    other_students = tuple(r.student_id for r in records if not r.ctip1)
    top, bottom = (
        (other_students, ctip1_students)
        if invert_ctip1
        else (ctip1_students, other_students)
    )
    priority_classes = {c: (top, bottom) for c in schools}
    return Market(
        students=tuple(r.student_id for r in records),
        schools=schools,
        capacities=capacities,
        priority_classes=priority_classes,
    )


def stand_in_tiebreak(seed: str = STAND_IN_SEED) -> MultipleLotteryTiebreak:
    """A per-school (multiple tie-breaking) stand-in lottery. Matches the
    REAL structure's use of MTB ("a random lottery, drawn independently at
    each program") even though it cannot match the real draw -- see the
    module docstring."""
    return MultipleLotteryTiebreak(seed=seed)


def config_for(mechanism: str, tiebreak) -> object:
    """The config object for one of `CANDIDATE_MECHANISMS`, sharing the same
    priority/tiebreak input so the three are genuinely comparable."""
    if mechanism == "top_trading_cycles":
        return TTCConfig(tiebreak=tiebreak)
    if mechanism == "student_proposing_da":
        return DAConfig(tiebreak=tiebreak)
    if mechanism == "boston_immediate_acceptance":
        return BostonConfig(tiebreak=tiebreak)
    raise ModelError(
        f"unknown SFUSD candidate mechanism {mechanism!r}; known: "
        f"{CANDIDATE_MECHANISMS!r}"
    )


def full_ctip1_reserve_config(
    records: Sequence[StudentRecord], market: Market, tiebreak
) -> ReserveConfig:
    """A `reserve_da` config in which CTIP1 holds every seat at every school
    as a SOFT reserve (see `witness.reserves`), for the "does CTIP1 behave
    like a reserve or a plain priority tier" question the task raises.

    This is a PROOF, not a fitted alternative: because CTIP1 already sits at
    the top of the ordinary (base) priority order at every school in
    `build_market`, giving it a reserve on top of that changes nothing --
    the reserve mechanism only has bite when its eligible group is NOT
    already the highest-priority group in the base order (see
    `witness.reserves`'s own module docstring on RESERVE vs QUOTA and on
    DKPS's slot model). `tests/test_sfusd2017_replay.py` pins that this
    config's assignment is IDENTICAL to plain `student_proposing_da` under
    the same tiebreak, which is what settles the question for this dataset:
    the primary source's own language ("priority is given to...") already
    says CTIP1 is a plain priority tier, and this equivalence confirms that
    modelling it as a reserve instead would have made no difference here."""
    reserves = {
        c: SchoolReserve(
            reserved_seats=market.capacity(c),
            eligible=tuple(r.student_id for r in records if r.ctip1),
        )
        for c in market.schools
    }
    return ReserveConfig(
        tiebreak=tiebreak,
        reserves=reserves,
        reserve_type=RESERVE_SOFT,
        precedence=PRECEDENCE_RESERVE_FIRST,
    )


def match_rate(
    assignment_by_student: Mapping[str, Optional[str]],
    records: Sequence[StudentRecord],
    *,
    ctip1: Optional[bool] = None,
) -> tuple[int, int]:
    """(matched, total) comparing `assignment_by_student` to the recorded
    Round 1 outcome, optionally restricted to CTIP1 (`True`) or non-CTIP1
    (`False`) applicants."""
    pool = [r for r in records if ctip1 is None or r.ctip1 == ctip1]
    matched = sum(
        1
        for r in pool
        if assignment_by_student[r.student_id] == r.round1_assignment
    )
    return matched, len(pool)


def recorded_first_choice_rate(
    records: Sequence[StudentRecord], *, ctip1: Optional[bool] = None
) -> tuple[int, int]:
    """(got_own_first_choice, total) using ONLY what SFUSD itself recorded --
    `round1_assignment` compared to `ranked_schools[0]` -- with no replay
    involved at all. This is the module's cross-check against the CHI 2021
    paper's own headline statistics ("96% of families eligible for CTIP1
    priority were assigned their first choice", "compared to only 58% of
    other students"): see the module docstring's EMPIRICAL RESULT section
    and tests/test_sfusd2017_replay.py, which pins both figures against this
    exact function applied to the raw file, not against a number copied from
    the paper."""
    pool = [r for r in records if ctip1 is None or r.ctip1 == ctip1]
    pool = [r for r in pool if r.round1_assignment is not None]
    got = sum(
        1 for r in pool if r.ranked_schools and r.ranked_schools[0] == r.round1_assignment
    )
    return got, len(pool)


def mean_raw_rank_count(
    records: Sequence[StudentRecord], *, ctip1: Optional[bool] = None
) -> float:
    """Mean number of schools ranked, counting pre-dedup raw rank entries
    (see `StudentRecord.raw_rank_count`) -- the definition that matches how
    the CHI 2021 paper describes "schools ranked" (5.5 for CTIP1-eligible
    families, 11.6 for others, 16.5 for White applicants). Used only for the
    module's cross-check against that paper; not used anywhere in building
    the market or profile, which correctly use the deduplicated
    `ranked_schools` instead (see "SCHOOL VS. PROGRAM GRANULARITY")."""
    pool = [r for r in records if ctip1 is None or r.ctip1 == ctip1]
    return sum(r.raw_rank_count for r in pool) / len(pool)
