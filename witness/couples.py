"""Applicant-proposing deferred acceptance generalized to couples, per Roth &
Peranson (1999), AER 89(4):748-780, "III. Design of the Applicant-Proposing
Algorithm, A. The Conceptual Design", restricted to the CORE couples
mechanism: no supplemental (first-year) lists, no even/odd quota adjustments,
no position reversions. Those are real NRMP engineering details but are
orthogonal to the actual open theoretical question this module targets
(existence of a stable matching, sensitivity to processing order) -- see
Roth (1984) and the paper's own Appendix C formal model restricted to sets
A1 and C (omitting A2, the supplemental-list applicants).

THE MODEL
    Individual applicants ("singles") submit an ordinary strict ROL over
    programs, exactly like `witness.core.Profile`. A COUPLE is an ordered
    pair of two distinct applicants that submits a single joint ROL of
    ORDERED PAIRS of programs -- `Couple.joint_rankings`, a new type this
    codebase has no precedent for (do not conflate it with two individual
    ROLs). Programs have capacities and strict priority orders over
    INDIVIDUAL applicants -- `witness.core.ResolvedPriorities` is reused
    UNCHANGED, because "from the point of view of a potential employer, the
    members of a couple ... are two distinct applicants who seek distinct
    positions ... [while] from the point of view of the couple they are one
    agent with preferences over pairs of positions" (Roth & Peranson 1999,
    Appendix C, "Complex Matches").

THE ALGORITHM (paper's own "Conceptual Design", quoted/paraphrased)
    Applicants (singles and couples) are added to the match one at a time,
    in a declared order (`CouplesConfig.couple_order_policy`). Adding a
    SINGLE applicant runs an ordinary Gale-Shapley proposal chain exactly as
    `witness.da.deferred_acceptance` does. Adding a COUPLE makes BOTH members
    propose to their next-ranked PAIR of programs SIMULTANEOUSLY: the pair is
    accepted only if BOTH programs would take their respective member; if
    EITHER program would reject, the WHOLE pair proposal fails and the couple
    moves to its next-ranked pair. A successful pair proposal may displace
    the previous worst-held applicant at either program. If a displaced
    applicant is herself a member of a couple, BOTH members of that couple
    are withdrawn -- even the one not directly displaced -- and that couple
    re-proposes down its OWN joint ROL starting after its former pair. This
    is the paper's f1/w1/f2/w2 cascade, verified against the PDF directly:
    "At some point in this process, an applicant S(k, n) may be displaced who
    is a member of a couple ... [and] the spouse of S(k, n) is withdrawn from
    his tentative match ... [T]he program whose position is left vacant,
    P(k, n), is added to a 'program stack' ... If S(k, n) is a couple, then
    both couple members ... now propose down their joint ROL of pairs of
    programs."

    A position that becomes vacant this way is added to a PROGRAM STACK: "A
    residency program is then selected from the program stack, and all of
    the applicants in A(k) with whom it might form instabilities [i.e., all
    of the applicants in A(k) who are preferred by the program to its
    least-preferred current tentative match and who prefer this program to
    their current match] are added to the applicant stack ... with applicants
    proposing down their ROLs from the top." THIS PIECE IS LOAD-BEARING, not
    decorative: without it, a vacancy created by a couple's withdrawal can
    sit unexamined and the algorithm terminates having missed a genuine
    blocking pair (verified directly against fixture CPL-B below: dropping
    program-stack reactivation makes the algorithm silently return an
    UNSTABLE matching instead of detecting the loop). The paper's own text
    only names "applicants" as the beneficiaries of a program-stack pull, and
    is not explicit about whether a COUPLE (as opposed to an A1/A2 single)
    can be reactivated this way. THIS MODULE'S DECLARED, NON-INHERITED
    ENGINEERING CHOICE is to generalize reactivation to couples too --
    exactly the extension the paper's own vagueness ("how to proceed ... may
    depend on the nature of the loop") invites, and the one needed for this
    module's own loop-detector to actually fire on fixture CPL-B rather than
    silently returning a wrong answer. It is documented HERE, not buried,
    per REVIEWER.md.

LOOP DETECTION -- REQUIRED, DECLARED, AND HONEST ABOUT WHAT IT PROVES
    The paper states plainly that with couples present the process CAN
    cycle, that "loop-detectors need to be added," and that "how to proceed
    at this point may depend on the nature of the loop" -- i.e. it
    deliberately does NOT specify one universal answer, and neither does
    this module. What IS implemented:

      1. Detection: every time an individual applicant departs a program
         (a couple-cascade withdrawal, or this module's vacancy-driven
         reactivation pulling a single/couple away from where she currently
         sits), the (applicant, program) pair is logged. A REPEAT of an
         already-seen pair is a loop signal (Roth & Peranson's own
         criterion: "If the same pairs appear multiple times, a loop is in
         progress"). Because there are only `|applicants| * |programs|`
         distinct such pairs, a genuine infinite cycle is GUARANTEED to
         produce a repeat within that many distinct departures -- so the
         detector cannot be dodged by a true loop, only by a process that
         actually terminates.

      2. `LOOP_POLICY_BOUNDED_RETRY` (the only implemented policy, and an
         explicit, named `CouplesConfig.loop_policy` field rather than a
         hardcoded default -- REVIEWER.md: any outcome-affecting choice is
         declared configuration): once a repeat is detected, the algorithm
         does not abort immediately -- Roth & Peranson note "certain kinds
         of inessential loops can be rendered harmless" by continuing -- but
         after `CouplesConfig.max_loop_repeats` further repeats (a bare,
         undocumented-in-the-literature threshold; there is no theorem
         backing this number, it is pure engineering judgement, declared as
         such), the algorithm gives up and reports
         `STATUS_LOOP_DETECTED_NO_STABLE_MATCHING` -- a genuine THIRD outcome,
         distinct from `STATUS_STABLE`.

      3. A NAMED, NOT-YET-BUILT ALTERNATIVE: Roth & Peranson cite Roth and
         Vande Vate (1990) for the fact that RANDOMIZING the order in which
         applicants/positions are processed from the stacks can let the
         algorithm escape certain (inessential) loops. This module does NOT
         implement that escape -- `loop_policy` has exactly one real setting.
         A production system wanting to distinguish "this specific
         processing order loops" from "no stable matching exists at all"
         would need it; this pass does not build it, and says so here rather
         than silently only ever reporting the bounded-retry outcome.

      4. HONESTY ABOUT WHAT "LOOP DETECTED" PROVES. `STATUS_LOOP_DETECTED_
         NO_STABLE_MATCHING` means exactly: "this run, under this
         `couple_order_policy` and this bounded-retry heuristic, could not
         resolve a repeating cycle." It is NOT a mathematical proof that no
         stable matching exists for the instance (Roth 1984's actual
         impossibility results are proved by exhaustive case analysis, as
         `tests/test_couples_handworked.py`'s CPL-B fixture does independently
         via `witness.oracles_couples`). A different `couple_order_policy`,
         a different `max_loop_repeats`, or the unimplemented randomized
         restart might resolve some instances this heuristic gives up on.
         Conversely, `STATUS_STABLE` means only "no loop was mechanically
         detected before the stacks emptied" -- it is checked against the
         independent oracle on every hand fixture in this codebase, but is
         NOT itself a formal proof that the returned matching satisfies every
         clause of the Appendix C definition for every possible market this
         module might be run on. Anything load-bearing should be re-checked
         against `witness.oracles_couples.is_stable_couples`.

PROCESSING ORDER -- DECLARED CONFIGURATION, AND NOT PROVEN INVARIANT
    `CouplesConfig.couple_order_policy` picks one of three treatments, named
    after exactly the three the paper itself tested ("couples intermixed
    with singles, couples first, and couples last") in its own sequencing
    experiments (Section III.B.2), which found that "the number of loops
    encountered was fewest when couples were introduced ... after single
    applicants" and that sequencing decisions could, in a small number of
    cases, change who matches where (up to 12 of 22,937 applicants in the
    paper's own data). Unlike `witness.da.DAConfig.proposal_policy` -- whose
    docstring correctly states the two settings PROVABLY cannot change the
    outcome -- this setting is NOT proven order-invariant, and this module's
    docstring makes no such claim. `tests/test_couples_handworked.py` PINS an
    instance (CPL-C) where flipping it changes who matches where, mirroring
    `tests/test_reserves_handworked.py`'s RES-B for `ReserveConfig.precedence`
    (also a provably-CAN-change-the-outcome setting in this codebase).

WHAT IS NOT REGISTERED IN `witness.mechanisms`
    Every entry in that registry's `MechanismSpec.run` takes a flat
    `witness.core.Profile` (one report per student). A couple's joint ROL of
    PAIRS is not representable in that type, and `CouplesProfile` below is a
    genuinely different shape (singles' reports plus a tuple of `Couple`s),
    not a drop-in substitute. Forcing this mechanism through the existing
    registry interface would mean silently pretending a `CouplesProfile` is
    a `Profile`, which conflicts with this project's "no incidental
    interfaces" discipline (see `witness/mechanisms.py`'s own docstring on
    why `mechanism` is an explicit field rather than inferred). So this
    mechanism is deliberately NOT registered there; `couples_deferred_
    acceptance` is called directly instead.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Optional, Sequence

from witness.core import (
    Market,
    MechanismConfig,
    ResolvedPriorities,
    WORST,
    resolve_priorities,
    strictly_prefers,
)
from witness.da import Assignment, build_assignment, default_choice_rule
from witness.errors import MechanismError, ModelError

# --- couple processing order (declared config; NOT proven order-invariant) --

#: Every agent (single or couple) processed in one merged order, by the
#: declared position of its earliest member in `Market.students`.
COUPLE_ORDER_INTERMIXED = "intermixed"

#: All couples processed first (each in their own declared position order),
#: then all singles.
COUPLE_ORDER_COUPLES_FIRST = "couples_first"

#: All singles processed first, then all couples. The paper's own experiments
#: found this minimizes loop frequency -- see the module docstring -- but
#: that is a measured tendency, not a guarantee, and is not assumed here.
COUPLE_ORDER_COUPLES_LAST = "couples_last"

_COUPLE_ORDER_POLICIES = (
    COUPLE_ORDER_INTERMIXED,
    COUPLE_ORDER_COUPLES_FIRST,
    COUPLE_ORDER_COUPLES_LAST,
)

# --- loop-breaking policy (declared config; see module docstring) ----------

#: The only implemented policy: keep going for `max_loop_repeats` further
#: repeated (applicant, program) departures after the first repeat, then give
#: up and report `STATUS_LOOP_DETECTED_NO_STABLE_MATCHING`. A named,
#: NOT-YET-IMPLEMENTED alternative (randomizing stack processing order to
#: escape inessential loops, per Roth & Vande Vate 1990) is documented in the
#: module docstring but has no config value here -- there is nothing to
#: select.
LOOP_POLICY_BOUNDED_RETRY = "bounded_retry"

_LOOP_POLICIES = (LOOP_POLICY_BOUNDED_RETRY,)

# --- outcomes ----------------------------------------------------------------

#: No loop was mechanically detected before both stacks emptied. See the
#: module docstring's HONESTY note: this is NOT a formal proof of stability
#: for arbitrary markets, only "this run's mechanics found no further
#: reactive proposal to make."
STATUS_STABLE = "stable_matching_found"

#: The bounded-retry loop policy gave up. See the module docstring's HONESTY
#: note: this is NOT a proof that no stable matching exists, only that this
#: heuristic, under this processing order, could not resolve a genuine
#: repeating cycle it detected.
STATUS_LOOP_DETECTED = "no_stable_matching_found_loop_detected"

_STATUSES = (STATUS_STABLE, STATUS_LOOP_DETECTED)


@dataclass(frozen=True)
class Couple:
    """A couple's joint report: an ordered pair of applicant ids and a
    single ranked list of ORDERED PAIRS of programs.

    `members = (a1, a2)`; `joint_rankings[k] = (r, r2)` means "our k-th most
    preferred outcome is a1 at r and a2 at r2" -- position within the pair is
    semantic and tied to `members`' own order, exactly as Roth & Peranson's
    Appendix C states it ("an ordered list of elements of R x R whose first
    element is some (ri, rj) which is the couple's first-choice pair of
    positions for ai and aj, respectively").
    """

    members: tuple[str, str]
    joint_rankings: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        members = tuple(self.members)
        if len(members) != 2:
            raise ModelError(f"Couple.members must have exactly 2 applicants, got {members!r}")
        a1, a2 = members
        for a in (a1, a2):
            if not isinstance(a, str) or not a:
                raise ModelError(f"Couple.members must be non-empty strings, got {members!r}")
        if a1 == a2:
            raise ModelError(f"Couple.members must be two DISTINCT applicants, got {members!r}")
        rankings = []
        for pair in self.joint_rankings:
            pair = tuple(pair)
            if len(pair) != 2:
                raise ModelError(f"Couple.joint_rankings entries must be (r, r2) pairs, got {pair!r}")
            r, r2 = pair
            for x in (r, r2):
                if not isinstance(x, str) or not x:
                    raise ModelError(f"Couple.joint_rankings entries must be program-id strings, got {pair!r}")
            rankings.append(pair)
        if len(set(rankings)) != len(rankings):
            raise ModelError(f"Couple.joint_rankings must not repeat a pair, got {rankings!r}")
        object.__setattr__(self, "members", members)
        object.__setattr__(self, "joint_rankings", tuple(rankings))

    def to_dict(self) -> dict:
        return {
            "members": list(self.members),
            "joint_rankings": [list(p) for p in self.joint_rankings],
        }

    @staticmethod
    def from_dict(data: Mapping) -> "Couple":
        return Couple(
            members=tuple(data["members"]),
            joint_rankings=tuple(tuple(p) for p in data["joint_rankings"]),
        )


@dataclass(frozen=True)
class CouplesProfile:
    """What every applicant submitted: singles' ordinary reports plus every
    couple's joint ROL of pairs.

    Deliberately NOT `witness.core.Profile`: a couple's report is not a
    ranking of programs at all, it is a ranking of PAIRS of programs, and
    conflating the two types is exactly what this module's docstring warns
    against.
    """

    singles: Mapping[str, tuple[str, ...]]
    couples: tuple[Couple, ...]

    def __post_init__(self) -> None:
        singles = {s: tuple(r) for s, r in self.singles.items()}
        couples = tuple(self.couples)
        seen: set[str] = set()
        for s in singles:
            if not isinstance(s, str) or not s:
                raise ModelError(f"CouplesProfile: single ids must be non-empty strings, got {s!r}")
            seen.add(s)
        for c in couples:
            for a in c.members:
                if a in seen:
                    raise ModelError(
                        f"applicant {a!r} appears more than once across singles/couples "
                        f"(as a single report and/or in more than one couple)"
                    )
                seen.add(a)
        object.__setattr__(self, "singles", singles)
        object.__setattr__(self, "couples", couples)

    def all_applicants(self) -> tuple[str, ...]:
        out = list(self.singles)
        for c in self.couples:
            out.extend(c.members)
        return tuple(out)

    def couple_of(self, applicant: str) -> Optional[Couple]:
        for c in self.couples:
            if applicant in c.members:
                return c
        return None

    def validate_against(self, market: Market) -> None:
        applicants = set(self.all_applicants())
        if applicants != set(market.students):
            raise ModelError(
                f"CouplesProfile must cover exactly market.students; got {sorted(applicants)}, "
                f"expected {sorted(market.students)}"
            )
        school_set = set(market.schools)
        for s, report in self.singles.items():
            for c in report:
                if c not in school_set:
                    raise ModelError(f"single {s!r}'s report lists unknown school {c!r}")
        for couple in self.couples:
            for r, r2 in couple.joint_rankings:
                if r not in school_set or r2 not in school_set:
                    raise ModelError(
                        f"couple {couple.members!r}'s joint ROL lists unknown program(s) "
                        f"in pair {(r, r2)!r}"
                    )

    def to_dict(self) -> dict:
        return {
            "singles": {s: list(r) for s, r in sorted(self.singles.items())},
            "couples": [c.to_dict() for c in self.couples],
        }

    @staticmethod
    def from_dict(data: Mapping) -> "CouplesProfile":
        return CouplesProfile(
            singles={s: tuple(r) for s, r in data["singles"].items()},
            couples=tuple(Couple.from_dict(c) for c in data["couples"]),
        )


@dataclass(frozen=True)
class CouplesConfig(MechanismConfig):
    """`MechanismConfig` plus the couples-specific declared choices: which
    order applicants are introduced in, and how the loop-breaking heuristic
    is bounded. See the module docstring for why neither has a "provably
    inert" default the way `DAConfig.proposal_policy` does.
    """

    couple_order_policy: str = COUPLE_ORDER_INTERMIXED
    loop_policy: str = LOOP_POLICY_BOUNDED_RETRY
    max_loop_repeats: int = 3
    mechanism: str = "couples_da"

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.couple_order_policy not in _COUPLE_ORDER_POLICIES:
            raise ModelError(
                f"couple_order_policy must be one of {_COUPLE_ORDER_POLICIES}, "
                f"got {self.couple_order_policy!r}"
            )
        if self.loop_policy not in _LOOP_POLICIES:
            raise ModelError(f"loop_policy must be one of {_LOOP_POLICIES}, got {self.loop_policy!r}")
        if (
            isinstance(self.max_loop_repeats, bool)
            or not isinstance(self.max_loop_repeats, int)
            or self.max_loop_repeats < 0
        ):
            raise ModelError(
                f"max_loop_repeats must be a non-negative int, got {self.max_loop_repeats!r}"
            )
        if not isinstance(self.mechanism, str) or not self.mechanism:
            raise ModelError(f"mechanism must be a non-empty string, got {self.mechanism!r}")

    def to_dict(self) -> dict:
        data = super().to_dict()
        data["mechanism"] = self.mechanism
        data["couple_order_policy"] = self.couple_order_policy
        data["loop_policy"] = self.loop_policy
        data["max_loop_repeats"] = self.max_loop_repeats
        return data

    @classmethod
    def from_dict(cls, data: Mapping) -> "CouplesConfig":
        base = MechanismConfig.from_dict(data)
        return cls(
            tiebreak=base.tiebreak,
            unlisted_student_policy=base.unlisted_student_policy,
            couple_order_policy=data.get("couple_order_policy", COUPLE_ORDER_INTERMIXED),
            loop_policy=data.get("loop_policy", LOOP_POLICY_BOUNDED_RETRY),
            max_loop_repeats=data.get("max_loop_repeats", 3),
            mechanism=data.get("mechanism", "couples_da"),
        )


@dataclass(frozen=True)
class CouplesEvent:
    """One atomic event in the run, recorded for inspection.

    A flexible `kind` + `data` shape (rather than one dataclass per event
    type, as `witness.ttc.TTCStep` uses for its per-round shape) because the
    couples algorithm's branching is genuinely event-shaped, not
    round-shaped: a single proposal, a couple pair attempt, a displacement, a
    cascade withdrawal, a vacancy, a reactivation, and a repeat-departure
    signal are all differently-shaped facts that happen at irregular points,
    not fixed fields of a uniform "step." `data` is always a plain,
    JSON-able dict, so `to_dict()` and `format_trace()` are direct.
    """

    kind: str
    data: Mapping[str, object]

    def to_dict(self) -> dict:
        return {"kind": self.kind, "data": dict(self.data)}


@dataclass(frozen=True)
class CouplesResult:
    status: str
    assignment: Assignment
    events: tuple[CouplesEvent, ...]
    priorities: ResolvedPriorities

    def format_trace(self) -> str:
        lines = [f"status: {self.status}"]
        for e in self.events:
            lines.append(f"  {e.kind}: {dict(e.data)}")
        return "\n".join(lines)


class _LoopDetected(Exception):
    """Internal signal: the bounded-retry threshold was exceeded."""


def _agent_order(market: Market, profile: CouplesProfile, config: CouplesConfig):
    """The declared processing order of agents (singles and couples), per
    `config.couple_order_policy`. Each agent is `("single", student)` or
    `("couple", couple_index)` (index into `profile.couples`).

    A single's position is its index in `Market.students`; a couple's
    position is the LOWER of its two members' indices -- mirroring Roth &
    Peranson's own stated baseline convention exactly: "When applicants were
    processed in ascending code order, a couple was selected for processing
    based on the code number of the spouse with the lower applicant code."
    """
    index = {s: i for i, s in enumerate(market.students)}
    singles = sorted(profile.singles, key=lambda s: index[s])
    couples = sorted(
        range(len(profile.couples)),
        key=lambda i: min(index[a] for a in profile.couples[i].members),
    )
    single_agents = [("single", s) for s in singles]
    couple_agents = [("couple", i) for i in couples]

    if config.couple_order_policy == COUPLE_ORDER_COUPLES_FIRST:
        return tuple(couple_agents + single_agents)
    if config.couple_order_policy == COUPLE_ORDER_COUPLES_LAST:
        return tuple(single_agents + couple_agents)
    # COUPLE_ORDER_INTERMIXED: merge by declared position.
    def pos(agent):
        kind, val = agent
        if kind == "single":
            return index[val]
        return min(index[a] for a in profile.couples[val].members)

    return tuple(sorted(single_agents + couple_agents, key=pos))


def couples_deferred_acceptance(
    market: Market,
    profile: CouplesProfile,
    config: Optional[CouplesConfig] = None,
    *,
    priorities: Optional[ResolvedPriorities] = None,
) -> CouplesResult:
    """Run the applicant-proposing algorithm generalized to couples. See the
    module docstring for the algorithm, the loop-detector, and the honesty
    caveats on what `STATUS_STABLE` / `STATUS_LOOP_DETECTED` do and do not
    prove.
    """
    config = config if config is not None else CouplesConfig()
    profile.validate_against(market)
    if priorities is None:
        priorities = resolve_priorities(market, config)

    reports: dict[str, tuple[str, ...]] = dict(profile.singles)
    couple_of: dict[str, int] = {}
    for i, c in enumerate(profile.couples):
        for a in c.members:
            couple_of[a] = i

    held: dict[str, tuple[str, ...]] = {c: () for c in market.schools}
    holder: dict[str, Optional[str]] = {a: None for a in market.students}
    single_next: dict[str, int] = {s: 0 for s in reports}
    couple_progress: dict[int, int] = {i: 0 for i in range(len(profile.couples))}
    couple_current_pair: dict[int, Optional[int]] = {i: None for i in range(len(profile.couples))}

    introduced_singles: set[str] = set()
    introduced_couples: set[int] = set()

    events: list[CouplesEvent] = []
    seen_departures: set[tuple[str, str]] = set()
    loop_repeat_count = 0

    applicant_queue: list[tuple[str, object]] = []
    program_queue: list[str] = []

    max_total_pops = 200 * (len(market.students) * len(market.schools) + 10) * (
        config.max_loop_repeats + 2
    )
    total_pops = 0

    def log(kind: str, **data) -> None:
        events.append(CouplesEvent(kind=kind, data=data))

    def log_departure(applicant: str, program: str) -> None:
        nonlocal loop_repeat_count
        key = (applicant, program)
        if key in seen_departures:
            loop_repeat_count += 1
            log(
                "departure_repeat",
                applicant=applicant,
                program=program,
                loop_repeat_count=loop_repeat_count,
            )
            if loop_repeat_count > config.max_loop_repeats:
                log("loop_detected", applicant=applicant, program=program)
                raise _LoopDetected()
        else:
            seen_departures.add(key)
        log("departure", applicant=applicant, program=program)

    def would_accept(program: str, applicant: str) -> bool:
        if not priorities.acceptable(program, applicant):
            return False
        pool = held[program] + (applicant,)
        chosen = default_choice_rule(market, priorities, program, pool)
        return applicant in chosen

    def preferred_to_current(report: Sequence[str], target: str, current: Optional[str]) -> bool:
        return strictly_prefers(report, target, current)

    def handle_drops(dropped: Sequence[str], filled_program: str) -> None:
        couples_touched: list[int] = []
        for x in dropped:
            ck = couple_of.get(x)
            if ck is None:
                holder[x] = None
                log_departure(x, filled_program)
                applicant_queue.append(("single", x))
            elif ck not in couples_touched:
                couples_touched.append(ck)
        for ck in couples_touched:
            withdraw_couple(ck, trigger_program=filled_program)
            applicant_queue.append(("couple", ck))

    def withdraw_couple(
        ck: int, trigger_program: Optional[str], chase_vacancies: bool = True
    ) -> None:
        idx = couple_current_pair[ck]
        if idx is None:
            return
        r, r2 = profile.couples[ck].joint_rankings[idx]
        a1, a2 = profile.couples[ck].members
        for member, prog in ((a1, r), (a2, r2)):
            if holder.get(member) != prog:
                continue
            held[prog] = tuple(x for x in held[prog] if x != member)
            holder[member] = None
            log_departure(member, prog)
            if prog != trigger_program:
                if chase_vacancies:
                    program_queue.append(prog)
                    log("vacancy", program=prog)
                else:
                    # Same declared scope limit as the single-reactivation
                    # branch: a vacancy created by OUR OWN reactivation
                    # choice (not a direct couple-cascade displacement) is
                    # not chased further -- see that branch's comment.
                    log("vacancy_not_chased", program=prog)
        couple_current_pair[ck] = None

    def process_single(s: str) -> None:
        report = reports[s]
        while True:
            if single_next[s] >= len(report):
                holder[s] = None
                log("single_exhausted", applicant=s)
                return
            p = report[single_next[s]]
            single_next[s] += 1
            if not priorities.acceptable(p, s):
                log("single_skipped_unacceptable", applicant=s, program=p)
                continue
            pool = held[p] + (s,)
            chosen = default_choice_rule(market, priorities, p, pool)
            if s not in chosen:
                log("single_rejected", applicant=s, program=p)
                continue
            old_held = held[p]
            held[p] = tuple(sorted(chosen, key=lambda x: priorities.rank(p, x)))
            dropped = [x for x in old_held if x not in chosen]
            holder[s] = p
            log("single_accepted", applicant=s, program=p, displaced=list(dropped))
            handle_drops(dropped, filled_program=p)
            return

    def process_couple(ck: int) -> None:
        couple = profile.couples[ck]
        a1, a2 = couple.members
        if holder.get(a1) is not None or holder.get(a2) is not None:
            # A STALE, duplicate applicant_queue entry: this couple was
            # queued more than once before either entry was processed (e.g.
            # a cascade withdrawal and a program-stack reactivation both
            # noticed the same couple in the same "drain" pass). The first
            # entry already resolved the couple's state; this second one is
            # a no-op, not a bug -- see the queueing discussion in this
            # module's own test suite / mutation notes.
            log("couple_stale_requeue_skipped", couple=list(couple.members))
            return
        while True:
            idx = couple_progress[ck]
            if idx >= len(couple.joint_rankings):
                couple_current_pair[ck] = None
                log("couple_exhausted", couple=list(couple.members))
                return
            r, r2 = couple.joint_rankings[idx]
            couple_progress[ck] += 1
            if r == r2:
                pool = held[r] + (a1, a2)
                chosen = set(default_choice_rule(market, priorities, r, pool))
                accept = priorities.acceptable(r, a1) and priorities.acceptable(r, a2) and a1 in chosen and a2 in chosen
            else:
                accept = would_accept(r, a1) and would_accept(r2, a2)
            log("couple_proposal", couple=list(couple.members), pair=[r, r2], accepted=accept)
            if not accept:
                continue
            if r == r2:
                old_held = held[r]
                held[r] = tuple(sorted(chosen, key=lambda x: priorities.rank(r, x)))
                dropped = [x for x in old_held if x not in chosen]
                holder[a1] = r
                holder[a2] = r2
                couple_current_pair[ck] = idx
                handle_drops(dropped, filled_program=r)
            else:
                old_r = held[r]
                new_r_pool = old_r + (a1,)
                chosen_r = default_choice_rule(market, priorities, r, new_r_pool)
                held[r] = tuple(sorted(chosen_r, key=lambda x: priorities.rank(r, x)))
                dropped_r = [x for x in old_r if x not in chosen_r]

                old_r2 = held[r2]
                new_r2_pool = old_r2 + (a2,)
                chosen_r2 = default_choice_rule(market, priorities, r2, new_r2_pool)
                held[r2] = tuple(sorted(chosen_r2, key=lambda x: priorities.rank(r2, x)))
                dropped_r2 = [x for x in old_r2 if x not in chosen_r2]

                holder[a1] = r
                holder[a2] = r2
                couple_current_pair[ck] = idx
                handle_drops(dropped_r, filled_program=r)
                handle_drops(dropped_r2, filled_program=r2)
            return

    def wants_reactivation(ck: int, program: str) -> bool:
        idx = couple_current_pair[ck]
        ranks = profile.couples[ck].joint_rankings
        limit = idx if idx is not None else len(ranks)
        for k in range(limit):
            r, r2 = ranks[k]
            if r == program or r2 == program:
                return True
        return False

    def reactivate_for(program: str) -> None:
        for s in market.students:
            if s not in introduced_singles:
                continue
            if couple_of.get(s) is not None:
                continue
            report = reports[s]
            if program not in report:
                continue
            if not priorities.acceptable(program, s):
                continue
            current = holder.get(s)
            if current == program:
                continue
            if not preferred_to_current(report, program, current):
                continue
            if not would_accept(program, s):
                # She prefers `program`, but it would NOT currently take her
                # (a real instability requires BOTH sides -- see Appendix
                # C's "a >_r sigma for some sigma in mu(r)" clause). Without
                # this check, withdrawing her from her current hold merely
                # on preference creates a SPURIOUS vacancy there for a move
                # she was never going to complete -- measured directly: this
                # was the actual cause of a >90% loop-detected rate in an
                # early version of `scripts/couples_sequencing.py`'s sweep,
                # entirely among singles with no couple in the cycle at all.
                continue
            if current is not None:
                held[current] = tuple(x for x in held[current] if x != s)
                holder[s] = None
                log_departure(s, current)
                # DECLARED SCOPE LIMIT: `current` is NOT pushed onto the
                # program stack here. Roth & Peranson's own loop criterion
                # (module docstring) ties a loop-worthy vacancy to a couple
                # (or supplemental) withdrawal specifically; chasing a
                # SECOND-ORDER vacancy created by a voluntary single-to-
                # single reactivation (rather than a couple cascade) is an
                # unbounded transitive search this module does not attempt
                # -- measured directly, doing so produced repeated
                # single-vs-single departures (a loop signal) with no couple
                # anywhere in the cycle, which inflated the loop-detected
                # rate far beyond anything attributable to couples at all.
                # This scope limit is a further declared incompleteness
                # (beyond the ones already named in the module docstring):
                # `current` sitting vacant here MAY still be a genuine
                # blocking opportunity for some other single that this run
                # will not discover.
                log("vacancy_not_chased", program=current)
            single_next[s] = 0
            log("reactivated_single", applicant=s, program=program)
            applicant_queue.append(("single", s))
        for ck in range(len(profile.couples)):
            if ck not in introduced_couples:
                continue
            if not wants_reactivation(ck, program):
                continue
            idx = couple_current_pair[ck]
            if idx is not None:
                # Same fix as the single case above: only disturb a couple
                # that is ALREADY happily matched if the better pair it is
                # being pulled toward would actually accept BOTH members
                # right now -- otherwise withdrawing them creates spurious
                # vacancies at BOTH their current programs for a retry that
                # was never going to succeed.
                a1, a2 = profile.couples[ck].members
                candidate = None
                for k in range(idx):
                    r, r2 = profile.couples[ck].joint_rankings[k]
                    if r == program or r2 == program:
                        candidate = (r, r2)
                        break
                if candidate is None:
                    continue
                r, r2 = candidate
                if r == r2:
                    pool = held[r] + (a1, a2)
                    chosen = set(default_choice_rule(market, priorities, r, pool))
                    ok = a1 in chosen and a2 in chosen
                else:
                    ok = would_accept(r, a1) and would_accept(r2, a2)
                if not ok:
                    continue
                withdraw_couple(ck, trigger_program=None, chase_vacancies=False)
            couple_progress[ck] = 0
            log("reactivated_couple", couple=list(profile.couples[ck].members), program=program)
            applicant_queue.append(("couple", ck))

    def drain_all() -> None:
        nonlocal total_pops
        while applicant_queue or program_queue:
            while applicant_queue:
                total_pops += 1
                if total_pops > max_total_pops:
                    raise MechanismError(
                        f"couples_deferred_acceptance exceeded its safety bound of "
                        f"{max_total_pops} stack pops without the loop-detector firing; "
                        f"this indicates a bug in the loop detector, not a real loop "
                        f"(a genuine loop is guaranteed to produce a repeated departure "
                        f"within |applicants| * |programs| distinct events)"
                    )
                kind, val = applicant_queue.pop(0)
                if kind == "single":
                    process_single(val)
                else:
                    process_couple(val)
            if program_queue:
                p = program_queue.pop(0)
                reactivate_for(p)

    try:
        for kind, val in _agent_order(market, profile, config):
            if kind == "single":
                introduced_singles.add(val)
                log("agent_introduced", agent_kind="single", applicant=val)
                applicant_queue.append(("single", val))
            else:
                introduced_couples.add(val)
                log("agent_introduced", agent_kind="couple", couple=list(profile.couples[val].members))
                applicant_queue.append(("couple", val))
            drain_all()
        status = STATUS_STABLE
    except _LoopDetected:
        status = STATUS_LOOP_DETECTED

    assignment = build_assignment(market, priorities, holder, allow_unranked=False)
    return CouplesResult(
        status=status,
        assignment=assignment,
        events=tuple(events),
        priorities=priorities,
    )
