"""Adapter for a REAL published human-subject dataset: Stephenson (2022).

    "Assignment feedback in school choice mechanisms", Experimental
    Economics 25(5), doi:10.1007/s10683-022-09767-6.
    Data: Zenodo record 6791431, CC-BY-4.0.
    Raw file: data/external/zenodo_6791431_stephenson_school_choice/

This is the first non-synthetic input this project runs. It matters because
it is the only source available here that carries BOTH real reports submitted
by real people under time pressure AND the mechanism's own recorded outcome
for those reports -- so the mechanisms in `witness/` can be checked against
something nobody in this project produced.

WHAT THE EXPERIMENT IS
432 subjects, in 18 sessions of 24, played 12 one-minute periods. Each period
is ONE market: 24 participants, 3 options (a, b, c), capacity 8 each, so every
participant is always assigned something. A participant submits one of the 6
possible strict rankings of {a,b,c}. Six sessions were run under each of three
mechanisms -- immediate acceptance ("boston"), student-proposing deferred
acceptance ("defAccept"), and top trading cycles ("topTrading") -- crossed
with two feedback conditions that this adapter ignores, since feedback changes
what subjects REPORTED, not how reports were processed.

Each option's priority ranking is built from the participant's `type` (1-3)
and a per-period lottery number `lotto` (1-24, distinct within a period). The
published instructions (Program.zip/SchoolChoiceInstructions.pdf, quoted here
because the article itself is paywalled) state: "Each option may be assigned a
different priority ranking, so you may have a different level of priority for
each of the three options." That is what makes the dataset usable for TTC at
all -- see `witness.ttc.distinct_priority_orders` for why a single shared
priority order would have made TTC and DA indistinguishable.

HOW THE PRIORITY STRUCTURE BELOW WAS RECOVERED, AND WHY IT IS NOT A GUESS
The dataset records each participant's `type` and `lotto` but NOT the priority
ranking each option was actually given, and the paper stating it is paywalled.
So the ordering of the three type-blocks per option was recovered by
exhaustive search over all 6^3 = 216 possible assignments of a strict type
order to each option, keeping only those that reproduce the recorded
`assignment` column EXACTLY for every participant in every period under all
three mechanisms -- 5,184 recorded assignments, none of them produced by this
project. Exactly two survive, and they differ only in how option c orders
types 1 and 3 beneath type 2, a distinction that provably never binds in any
of the 216 markets. `TYPE_PRIORITY` below is one of the two;
`EQUIVALENT_C_ORDER` is the other, and a test pins that both still reproduce
everything, so that nobody later "resolves" the ambiguity by preference and
believes it was measured.

The lottery direction (ascending: lottery number 1 is best) is uniquely pinned
by the same search.

WHY THIS IS A REAL CHECK AND NOT A TAUTOLOGY
The three mechanisms disagree with each other about where individual
participants end up on 35.9% (Boston vs TTC), 39.8% (DA vs TTC) and 47.6% (DA
vs Boston) of the 5,184 real outcomes, and 40.6% of participants did not
receive their own reported first choice. Scarcity genuinely binds here, the
mechanisms genuinely differ here, and each one still has to match its own
recorded column exactly. See `tests/test_stephenson_replay.py`.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from itertools import permutations
from typing import Iterable, Mapping, Sequence

from witness.boston import BostonConfig
from witness.core import Market, Profile
from witness.da import DAConfig
from witness.errors import ModelError
from witness.tiebreak import ExplicitTiebreak
from witness.ttc import TTCConfig

#: The three options, in the dataset's own `assignment` coding (1, 2, 3).
SCHOOLS = ("a", "b", "c")
OPTION_BY_CODE = {"1": "a", "2": "b", "3": "c"}

#: Every option seats exactly 8 of the 24 participants.
CAPACITY = 8
PARTICIPANTS_PER_PERIOD = 24

#: `report` is an index 1-6 into the six strict rankings of {a,b,c} in
#: lexicographic order. Confirmed, not assumed: any other assignment of
#: indices to rankings fails to reproduce the recorded assignments.
REPORT_BY_CODE = {
    str(i + 1): tuple(p) for i, p in enumerate(permutations(SCHOOLS))
}

#: Recovered per-option priority over participant types, best type first.
#: See the module docstring for how this was determined.
TYPE_PRIORITY: Mapping[str, tuple[str, ...]] = {
    "a": ("1", "3", "2"),
    "b": ("2", "1", "3"),
    "c": ("2", "1", "3"),
}

#: The only other type ordering that reproduces the data equally well: option
#: c may rank type 3 above type 1 beneath type 2. The difference never binds.
EQUIVALENT_C_ORDER = ("2", "3", "1")

#: Dataset mechanism code -> this project's registered mechanism name.
MECHANISM_BY_CODE = {
    "defAccept": "student_proposing_da",
    "boston": "boston_immediate_acceptance",
    "topTrading": "top_trading_cycles",
}

#: Columns kept in the compact snapshot cache.
SNAPSHOT_FIELDS = (
    "session", "period", "subject", "mechanism", "feedback",
    "type", "lotto", "truth", "report", "assignment",
)


@dataclass(frozen=True)
class Period:
    """One market: the 24 participants of one (session, period)."""

    session: str
    period: str
    mechanism: str
    feedback: str
    rows: tuple[Mapping[str, str], ...]

    @property
    def key(self) -> tuple[str, str]:
        return (self.session, self.period)


def final_snapshots(csv_path: str) -> list[dict]:
    """The LAST observation of each (session, period, subject) in the raw file.

    The raw CSV is a ~1.56M-row event log sampled roughly every 0.2 simulated
    seconds, because the experiment recorded how subjects revised their report
    during the period. Only the final state of a period is the report the
    mechanism actually ran on, so everything else is dropped here. This is the
    one modelling decision in the adapter that discards data, and it is stated
    rather than buried: the discarded rows are the within-period revision path,
    which is the paper's own subject, not this project's.
    """
    latest: dict[tuple[str, str, str], tuple[float, dict]] = {}
    with open(csv_path, newline="") as f:
        for row in csv.DictReader(f):
            key = (row["session"], row["period"], row["subject"])
            second = float(row["second"])
            if key not in latest or second > latest[key][0]:
                latest[key] = (second, {k: row[k] for k in SNAPSHOT_FIELDS})
    return [row for _, row in sorted(latest.values(), key=lambda p: _sort_key(p[1]))]


def _sort_key(row: Mapping[str, str]) -> tuple:
    return (int(row["session"]), int(row["period"]), int(row["subject"]))


def write_snapshot_cache(rows: Iterable[Mapping[str, str]], path: str) -> int:
    """Write the compact one-row-per-participant-period file. Returns the count."""
    rows = list(rows)
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(SNAPSHOT_FIELDS))
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row[k] for k in SNAPSHOT_FIELDS})
    return len(rows)


def read_snapshot_cache(path: str) -> list[dict]:
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def periods(rows: Sequence[Mapping[str, str]]) -> list[Period]:
    """Group snapshot rows into markets, in declared (session, period) order."""
    grouped: dict[tuple[str, str], list[Mapping[str, str]]] = {}
    for row in rows:
        grouped.setdefault((row["session"], row["period"]), []).append(row)
    out = []
    for key in sorted(grouped, key=lambda k: (int(k[0]), int(k[1]))):
        members = sorted(grouped[key], key=lambda r: int(r["subject"]))
        mechanisms = {r["mechanism"] for r in members}
        feedbacks = {r["feedback"] for r in members}
        if len(mechanisms) != 1 or len(feedbacks) != 1:
            raise ModelError(
                f"period {key} mixes mechanisms {mechanisms!r} / feedback "
                f"{feedbacks!r}; each period is supposed to be one market "
                f"under one mechanism"
            )
        out.append(
            Period(
                session=key[0],
                period=key[1],
                mechanism=members[0]["mechanism"],
                feedback=members[0]["feedback"],
                rows=tuple(members),
            )
        )
    return out


def student_id(row: Mapping[str, str]) -> str:
    return f"p{row['subject']}"


def build_market(
    period: Period, *, type_priority: Mapping[str, Sequence[str]] = None
) -> "tuple[Market, ExplicitTiebreak]":
    """The `Market` for one period, plus the lottery tiebreak it runs under.

    Priority CLASSES are the participant types, in the recovered per-option
    order; the lottery is an `ExplicitTiebreak` over the recorded `lotto`
    numbers, ascending. Modelling it this way rather than pre-flattening to
    singleton classes keeps the market's real structure visible -- the type
    blocks are the priority classes the experiment actually gave the options,
    and the lottery is a genuine within-class tiebreak, exactly as
    `witness.core.resolve_priorities` expects.
    """
    order = dict(TYPE_PRIORITY if type_priority is None else type_priority)
    students = tuple(student_id(r) for r in period.rows)
    if len(students) != PARTICIPANTS_PER_PERIOD:
        raise ModelError(
            f"period {period.key} has {len(students)} participants, expected "
            f"{PARTICIPANTS_PER_PERIOD}"
        )
    by_id = {student_id(r): r for r in period.rows}

    by_lottery = tuple(
        sorted(students, key=lambda s: int(by_id[s]["lotto"]))
    )
    tiebreak = ExplicitTiebreak({"*": by_lottery})

    priority_classes: dict[str, tuple[tuple[str, ...], ...]] = {}
    for school in SCHOOLS:
        blocks = []
        for t in order[school]:
            block = tuple(s for s in students if by_id[s]["type"] == t)
            if block:
                blocks.append(block)
        priority_classes[school] = tuple(blocks)

    market = Market(
        students=students,
        schools=SCHOOLS,
        capacities={c: CAPACITY for c in SCHOOLS},
        priority_classes=priority_classes,
    )
    return market, tiebreak


def build_profile(period: Period, *, truthful: bool = False) -> Profile:
    """What the participants SUBMITTED (`report`), or what they actually
    preferred (`truth`) when `truthful=True`.

    Both are present in this dataset, which is unusual and valuable: the
    manipulation search needs a truthful profile to measure gains against,
    and here it does not have to be assumed."""
    field = "truth" if truthful else "report"
    return Profile(
        {student_id(r): REPORT_BY_CODE[r[field]] for r in period.rows}
    )


def recorded_assignment(period: Period) -> dict[str, str]:
    """The outcome the experiment itself recorded, which is what a replay of
    this period has to reproduce."""
    return {student_id(r): OPTION_BY_CODE[r["assignment"]] for r in period.rows}


def config_for(period: Period, tiebreak: ExplicitTiebreak):
    """The mechanism config this period ran under."""
    name = MECHANISM_BY_CODE.get(period.mechanism)
    if name is None:
        raise ModelError(
            f"unknown dataset mechanism {period.mechanism!r}; known: "
            f"{sorted(MECHANISM_BY_CODE)!r}"
        )
    if name == "student_proposing_da":
        return DAConfig(tiebreak=tiebreak)
    if name == "boston_immediate_acceptance":
        return BostonConfig(tiebreak=tiebreak)
    return TTCConfig(tiebreak=tiebreak)
