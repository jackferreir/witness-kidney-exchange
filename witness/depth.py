"""How far a profitable misreport sits from the truthful report.

Exhaustive search over the report space is the only way we currently TRUST a
manipulation finding, but it does not scale: 16 reports at 3 schools, ~326 at
5, ~110k at 8, ~10M at 10. Realistic markets (dozens of schools) are hopeless
for exhaustive search, so Step 4 will need a RESTRICTED, theoretically
motivated report space.

For every manipulation `witness.search` finds, this module records HOW FAR
the profitable misreport sits from the truthful report, in terms that map
directly onto candidate restrictions:

  * is_prefix_truncation / n_dropped -- would "truncate the truthful list"
                                         (drop a SUFFIX) reach it?
  * is_sublist                       -- would dropping any SUBSET of schools,
                                         while keeping the rest in their
                                         truthful relative order, reach it?
  * kendall_tau                      -- how much reordering, among schools
                                         ranked in both reports, would "local
                                         swaps" need to cover?
  * adjacent_swap_distance           -- is it literally k disjoint adjacent
                                         swaps of the truthful report?
  * is_singleton / promotes_school   -- other cheap, interpretable summaries
                                         of the Boston-specific manipulations
                                         actually seen in practice.

A DEFECT THIS MODULE ONCE HAD, FIXED HERE (read before touching this file
again): `is_truncation` meant "false_report is a PREFIX of truthful_report",
and `in_restricted_space(allow_truncation=True)` used that prefix notion as
its entire "drop schools" branch. But the operation manipulable Boston
students actually use is an ORDER-PRESERVING SUBLIST (a subsequence) of the
truthful report, not a prefix -- dropping schools out of the *middle* is what
does the work. Measured over 719 manipulable Boston cases: 100% had a
profitable sublist misreport, 0% had a profitable prefix truncation. Example:
truthful ("c1","c4","c3","c2"), profitable ("c2",) -- a sublist, not a
prefix. Because the old `in_restricted_space` conflated the two, "truncations
only" scored 0.0% while every single case had a kendall_tau=0 misreport
available. The *concept* was wrong, not the data -- hence `is_prefix_truncation`
(unambiguous name, no alias) and the new `is_sublist` field, computed
independently (not derived from the other fields) so a test can cross-check
that the two notions actually agree where they should.

`in_restricted_space` is the function Step 4's design decision will be scored
against: given a named report space, it asks whether a restricted search
over that space would have been ABLE to submit this exact misreport. Spaces
are explicit, named constants (`SPACE_*`) rather than bare boolean kwargs --
an ambiguous boolean flag (`allow_truncation`) is exactly what let the wrong
concept hide undetected, so this module does not offer another one.

Depth is recorded, never used to steer the search (see `witness.search`): the
search remains exhaustive and its enumeration order is untouched by anything
in this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Optional, Sequence

from witness.errors import ModelError

#: Two reports are the "same set of schools, reordered" (`is_permutation`),
#: or share some sub-multiset of schools in common (`kendall_tau`,
#: `n_dropped`, `n_added`). Every report is assumed to list a given school at
#: most once, matching `witness.core.Profile`'s own contract (enforced there
#: by `_as_id_tuple`) -- this module does not re-validate that, since it is
#: always called on reports that already passed through `Profile`.

#: Named restricted-report-space constants for `in_restricted_space`. Bare
#: booleans are deliberately not offered here -- see the module docstring.
SPACE_PREFIX_TRUNCATIONS = "prefix_truncations"
SPACE_SUBLISTS = "sublists"
SPACE_SINGLETONS = "singletons"
SPACE_LOCAL_SWAPS = "local_swaps"
SPACE_SUBLISTS_PLUS_SWAPS = "sublists_plus_swaps"

_KNOWN_SPACES = (
    SPACE_PREFIX_TRUNCATIONS,
    SPACE_SUBLISTS,
    SPACE_SINGLETONS,
    SPACE_LOCAL_SWAPS,
    SPACE_SUBLISTS_PLUS_SWAPS,
)


@dataclass(frozen=True)
class ReportDepth:
    """How far `false_report` sits from `truthful_report`.

    All fields are computed purely from the two report tuples -- no market,
    profile, or outcome is needed. See `report_depth` for the exact
    definitions and `in_restricted_space` for how these fields compose into a
    single "would a restricted search have found this?" verdict.
    """

    length_truthful: int
    length_false: int
    is_prefix_truncation: bool
    is_sublist: bool
    is_singleton: bool
    promotes_school: Optional[str]
    is_permutation: bool
    n_dropped: int
    n_added: int
    first_choice_changed: bool
    kendall_tau: int
    adjacent_swap_distance: Optional[int]

    def to_dict(self) -> dict:
        return {
            "length_truthful": self.length_truthful,
            "length_false": self.length_false,
            "is_prefix_truncation": self.is_prefix_truncation,
            "is_sublist": self.is_sublist,
            "is_singleton": self.is_singleton,
            "promotes_school": self.promotes_school,
            "is_permutation": self.is_permutation,
            "n_dropped": self.n_dropped,
            "n_added": self.n_added,
            "first_choice_changed": self.first_choice_changed,
            "kendall_tau": self.kendall_tau,
            "adjacent_swap_distance": self.adjacent_swap_distance,
        }

    @staticmethod
    def from_dict(d: Mapping) -> "ReportDepth":
        return ReportDepth(
            length_truthful=d["length_truthful"],
            length_false=d["length_false"],
            is_prefix_truncation=d["is_prefix_truncation"],
            is_sublist=d["is_sublist"],
            is_singleton=d["is_singleton"],
            promotes_school=d["promotes_school"],
            is_permutation=d["is_permutation"],
            n_dropped=d["n_dropped"],
            n_added=d["n_added"],
            first_choice_changed=d["first_choice_changed"],
            kendall_tau=d["kendall_tau"],
            adjacent_swap_distance=d["adjacent_swap_distance"],
        )


def _first_choice_changed(truthful: tuple[str, ...], false: tuple[str, ...]) -> bool:
    """`false[0] != truthful[0]`, defined carefully at the boundary.

    Convention (documented, not incidental):
      * both empty -> False. Neither report names a first choice, so there is
        nothing that changed.
      * exactly one empty -> True. A first choice either appeared or
        disappeared, which is itself a change of first choice.
      * both non-empty -> plain positional comparison of index 0.
    """
    if not truthful and not false:
        return False
    if bool(truthful) != bool(false):
        return True
    return truthful[0] != false[0]


def _kendall_tau(truthful: tuple[str, ...], false: tuple[str, ...]) -> int:
    """Adjacent-transposition distance to reorder the COMMON schools of
    `truthful` into their `false` order.

    Computed only over schools present in BOTH reports, in each list's own
    relative order -- schools dropped or added play no part in this number
    (they are covered by `n_dropped` / `n_added` instead). With 0 or 1 common
    schools there is no relative order to disagree on, so this is 0 by
    definition; that includes two entirely DISJOINT reports (kendall_tau 0),
    which is a statement that there is no measurable reordering between them,
    not a claim that they are similar.

    Plain O(n^2) inversion count over the common elements, mapped through
    their rank in `false`'s order -- correct and obvious beats fast, per this
    package's house style.
    """
    false_set = set(false)
    truthful_set = set(truthful)
    common_in_truthful_order = [s for s in truthful if s in false_set]
    common_in_false_order = [s for s in false if s in truthful_set]
    rank_in_false = {s: i for i, s in enumerate(common_in_false_order)}
    sequence = [rank_in_false[s] for s in common_in_truthful_order]

    n = len(sequence)
    inversions = 0
    for i in range(n):
        for j in range(i + 1, n):
            if sequence[i] > sequence[j]:
                inversions += 1
    return inversions


def _adjacent_swap_distance(
    truthful: tuple[str, ...], false: tuple[str, ...]
) -> Optional[int]:
    """If `false` is exactly `truthful` with k DISJOINT ADJACENT pairs
    swapped, that k; else `None`.

    Requires equal length and the identical multiset of schools (a
    truncation, an addition, or any non-adjacent rearrangement returns `None`
    here -- those are captured by `is_prefix_truncation`/`n_dropped`/
    `n_added`/`kendall_tau` instead). Scans left to right: at the first
    position where the two reports disagree, the ONLY way this can still be
    "disjoint adjacent swaps" is if positions i and i+1 are each other's
    values, in which case that is counted as one swap and the scan resumes at
    i+2 (so a later swap can never overlap an earlier one, by construction).
    Any other kind of disagreement -- including a mismatch with no valid
    partner at i+1, or a single unpaired mismatch at the last index -- means
    `false` is not reachable this way, and this returns `None`.
    """
    n = len(truthful)
    if len(false) != n:
        return None
    if sorted(truthful) != sorted(false):
        return None

    swaps = 0
    i = 0
    while i < n:
        if truthful[i] == false[i]:
            i += 1
            continue
        if i + 1 < n and truthful[i + 1] == false[i] and truthful[i] == false[i + 1]:
            swaps += 1
            i += 2
            continue
        return None
    return swaps


def _is_sublist(truthful: tuple[str, ...], false: tuple[str, ...]) -> bool:
    """Is `false` an order-preserving SUBSEQUENCE of `truthful`?

    Every school in `false` must appear in `truthful`, and the relative order
    of `false`'s schools must match their relative order in `truthful` --
    schools of `truthful` that are absent from `false` may be skipped over
    freely (that is what makes this a *sublist*, not a *prefix*).

    Computed DIRECTLY from the two sequences via the standard shared-iterator
    subsequence check, independent of `n_added`/`kendall_tau`, so that
    `report_depth` can cross-check `is_sublist == (n_added == 0 and
    kendall_tau == 0)` as an assertion about two independently-derived
    notions agreeing, not a tautology. Correct because reports never repeat a
    school (see the module-level note above): the greedy left-to-right match
    below cannot be fooled by a duplicate standing in for the "wrong" one.
    """
    it = iter(truthful)
    return all(any(s == t for t in it) for s in false)


def _promotes_school(truthful: tuple[str, ...], false: tuple[str, ...]) -> Optional[str]:
    """The school `false` tries to promote to first choice, or `None`.

    This is the primitive most Boston-mechanism manipulations actually use:
    take some school ranked below first place in the truthful report and
    submit it FIRST instead. Defined as: `false` is non-empty, `false[0]`
    appears in `truthful`, and its index there is > 0 (i.e. it was not
    already the truthful first choice). `None` when `false` is empty, or
    `false[0]` is truthfully unacceptable (absent from `truthful`), or
    `false[0]` already was the truthful first choice.
    """
    if not false:
        return None
    first = false[0]
    if first in truthful and truthful.index(first) > 0:
        return first
    return None


def report_depth(
    truthful_report: Sequence[str], false_report: Sequence[str]
) -> ReportDepth:
    """Compute every `ReportDepth` field for `false_report` against
    `truthful_report`.

    Edge cases (all deliberate, all exercised in `tests/test_depth.py`):

      * empty truthful report: `is_prefix_truncation` is True for ANY
        false_report that is itself empty (the only prefix of `()` is `()`),
        and False otherwise (a non-empty list can never be a prefix of an
        empty one). `n_added` is `len(false_report)`.
      * empty false report: this IS a prefix truncation of any truthful
        report (the empty list is a prefix of every list) -- "submit
        nothing" is the most extreme truncation, and trivially a sublist too.
        `n_dropped` is `len(truthful_report)`.
      * disjoint reports (no common schools): `kendall_tau` is 0 (see
        `_kendall_tau`'s docstring for why), `n_dropped` and `n_added` are
        both the full length of the respective report, `is_permutation` is
        False (unless both are empty), `is_sublist` is False unless
        `false_report` is itself empty.
      * false_report longer than truthful_report: `is_prefix_truncation` is
        False (a strictly longer list cannot be a prefix of a shorter one),
        and `adjacent_swap_distance` is `None` (lengths differ).
    """
    truthful = tuple(truthful_report)
    false = tuple(false_report)
    truthful_set = set(truthful)
    false_set = set(false)

    length_truthful = len(truthful)
    length_false = len(false)

    is_prefix_truncation = (
        length_false <= length_truthful and false == truthful[:length_false]
    )
    is_sublist = _is_sublist(truthful, false)
    is_singleton = length_false == 1
    promotes_school = _promotes_school(truthful, false)
    is_permutation = truthful_set == false_set
    n_dropped = len(truthful_set - false_set)
    n_added = len(false_set - truthful_set)
    first_choice_changed = _first_choice_changed(truthful, false)
    kendall_tau = _kendall_tau(truthful, false)
    adjacent_swap_distance = _adjacent_swap_distance(truthful, false)

    return ReportDepth(
        length_truthful=length_truthful,
        length_false=length_false,
        is_prefix_truncation=is_prefix_truncation,
        is_sublist=is_sublist,
        is_singleton=is_singleton,
        promotes_school=promotes_school,
        is_permutation=is_permutation,
        n_dropped=n_dropped,
        n_added=n_added,
        first_choice_changed=first_choice_changed,
        kendall_tau=kendall_tau,
        adjacent_swap_distance=adjacent_swap_distance,
    )


def in_restricted_space(
    depth: ReportDepth,
    space: str,
    *,
    max_kendall_tau: int = 1,
    allow_additions: bool = False,
) -> bool:
    """Would a restricted search over the named `space`, with these
    parameters, have been able to submit this exact misreport?

    `space` must be one of the `SPACE_*` module constants:

      * `SPACE_PREFIX_TRUNCATIONS` -- contains exactly the misreports that
        are a literal prefix of the truthful report (`depth.is_prefix_truncation`).
      * `SPACE_SUBLISTS` -- contains exactly the misreports that are an
        order-preserving subsequence of the truthful report
        (`depth.is_sublist`); every prefix truncation is a sublist, so this
        space is a strict superset of `SPACE_PREFIX_TRUNCATIONS`.
      * `SPACE_SINGLETONS` -- contains exactly the misreports that name a
        single school (`depth.is_singleton`), whether or not that school is
        truthfully acceptable or was truthfully ranked first.
      * `SPACE_LOCAL_SWAPS` -- contains misreports that drop no school
        (`depth.n_dropped == 0`) and reorder the common schools by at most
        `max_kendall_tau` adjacent transpositions (`depth.kendall_tau <=
        max_kendall_tau`).
      * `SPACE_SUBLISTS_PLUS_SWAPS` -- the union of `SPACE_SUBLISTS` and
        `SPACE_LOCAL_SWAPS`: misreports reachable either by dropping some
        subset of schools while preserving the relative order of the rest,
        or by locally reordering without dropping anything.

    Raises `ModelError` if `space` is not one of the constants above.

    `allow_additions` is a single global gate applied BEFORE any
    space-specific check: when False (the default), any `depth` with
    `n_added > 0` (the false report names a truthfully-unacceptable school)
    is outside EVERY space, regardless of which `space` was asked about. When
    True, that gate is skipped and each space's own criteria decide (note
    that `SPACE_PREFIX_TRUNCATIONS` and `SPACE_SUBLISTS` never have
    `n_added > 0` in the first place, since neither can introduce a school
    absent from the truthful report).
    """
    if space not in _KNOWN_SPACES:
        raise ModelError(
            f"in_restricted_space: unknown space {space!r}; known spaces are "
            f"{_KNOWN_SPACES!r}"
        )

    if depth.n_added > 0 and not allow_additions:
        return False

    if space == SPACE_PREFIX_TRUNCATIONS:
        return depth.is_prefix_truncation
    if space == SPACE_SUBLISTS:
        return depth.is_sublist
    if space == SPACE_SINGLETONS:
        return depth.is_singleton
    if space == SPACE_LOCAL_SWAPS:
        return depth.n_dropped == 0 and depth.kendall_tau <= max_kendall_tau
    if space == SPACE_SUBLISTS_PLUS_SWAPS:
        return depth.is_sublist or (
            depth.n_dropped == 0 and depth.kendall_tau <= max_kendall_tau
        )
    raise AssertionError(f"unreachable: {space!r} passed membership check")  # pragma: no cover
