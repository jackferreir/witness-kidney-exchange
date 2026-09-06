"""A CONTROL mechanism whose only job is to prove the manipulation search has teeth.

THIS IS NOT A DEPLOYED MECHANISM. It is a permanent canary: `first_choice_bonus_da` has
a known, hand-verified manipulation (see the module-level docstring of
`tests/test_search.py` and the VERIFIED CONTROL INSTANCE below). If `witness.search`
ever stops finding it, the search itself has regressed -- that is the entire reason
this mechanism exists and must never be "fixed" to remove the manipulation.

`first_choice_bonus_da` models the first-choice-priority bump used by real
immediate-acceptance ("Boston mechanism"-style) systems: each school promotes every
student who ranked it FIRST in their *submitted report* above every student who did
not, preserving the base resolved order within each of the two groups. Standard
student-proposing DA is then run against those modified priorities.

Because the bonus is computed from the submitted reports, and DA's own priority
resolution is deliberately profile-free (see `witness.core`'s module docstring), the
combination here is exactly what makes first-choice-bonus manipulable in the way DA
itself is not: what a student reports changes their own priority standing.

VERIFIED CONTROL INSTANCE (computed and confirmed by hand -- do NOT change these
values; if this implementation disagrees with them, that is a real finding, report it
and stop):

    students ("s1","s2","s3"); schools ("c1","c2"); capacities c1=1, c2=1
    priority_classes: c1: (("s1",),("s2",),("s3",))   c2: (("s1",),("s2",),("s3",))
    config: DAConfig(tiebreak=RejectTies(), mechanism="first_choice_bonus_da")
            [unlisted_student_policy="unacceptable", proposal_policy="all_free_simultaneous"]
            -- mechanism must be passed explicitly: DAConfig is shared with plain DA and
            its default mechanism name is "student_proposing_da" (see witness.da.DAConfig).

    truthful profile: s1:(c1,c2)  s2:(c1,c2)  s3:(c2,c1)
      -> resolved priorities: c1 = ("s1","s2","s3"),  c2 = ("s3","s1","s2")
      -> assignment: s1->c1, s2->None, s3->c2

    s2 misreports ("c2","c1"):
      -> resolved priorities: c1 = ("s1","s2","s3"),  c2 = ("s2","s3","s1")
      -> assignment: s1->c1, s2->c2, s3->None

    s2's truthful report is ("c1","c2"), so c2 is at rank 1 and unmatched is WORST:
       s2 STRICTLY PREFERS the misreport outcome. That is the canary manipulation.

    Cross-check: under PLAIN student_proposing_da on this same instance, s2 gets c2
    truthfully and gains nothing by lying.
"""

from __future__ import annotations

from witness.core import Market, Profile, ResolvedPriorities, resolve_priorities
from witness.da import Assignment, DAConfig, deferred_acceptance


def first_choice_bonus_priorities(
    market: Market, profile: Profile, config: DAConfig
) -> ResolvedPriorities:
    """The base resolved priority order at each school, with every student who
    ranked that school FIRST in `profile` promoted above every student who did
    not -- the relative order *within* each of the two groups is preserved
    from the base order.

    Iterates `market.schools` explicitly, and within each school's base order
    (itself already a deterministic, caller-declared tuple -- see
    `witness.core.resolve_priorities`), never a dict or set.
    """
    base = resolve_priorities(market, config)
    orders: dict[str, tuple[str, ...]] = {}
    for c in market.schools:
        base_order = base.orders[c]
        first_choosers = tuple(
            s for s in base_order if profile.report(s) and profile.report(s)[0] == c
        )
        first_chooser_set = set(first_choosers)
        others = tuple(s for s in base_order if s not in first_chooser_set)
        orders[c] = first_choosers + others
    return ResolvedPriorities(orders)


def run_first_choice_bonus_da(market: Market, profile: Profile, config: DAConfig) -> Assignment:
    """Resolve first-choice-bonus priorities FROM `profile` (i.e. from whatever
    was actually submitted) and run standard student-proposing DA against them.

    Deliberately recomputes `first_choice_bonus_priorities` every call rather
    than accepting a pre-resolved `priorities=` argument: see the interface
    note in `witness.mechanisms`.
    """
    priorities = first_choice_bonus_priorities(market, profile, config)
    return deferred_acceptance(market, profile, config, priorities=priorities).assignment
