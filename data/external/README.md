# External research datasets

This directory holds raw, unmodified third-party research datasets pulled in
as **data plumbing only**. Nothing here is wired into `witness/`. No
mechanism logic was written or inferred to produce these files — see
`REVIEWER.md`'s "Hand-work before coding" rule, which is exactly why this
stops at verified raw data plus a sanity-check parser and does not attempt a
`witness` `Market`/`PreferenceProfile` conversion.

Each dataset subdirectory contains:
- the raw downloaded file(s), byte-for-byte as fetched, plus the original
  README from the source (renamed to avoid colliding with this repo's own
  files)
- `SOURCE.txt` — exact download URL(s), file sizes, and sha256 checksums
- `parsed.py` — a standalone summary/sanity-check script (also exercised by
  `tests/test_external_data.py`)

Explicitly out of scope, per instructions, and not touched by this work:
openICPSR / Harvard Business School course-allocation dataset (project
112547) — unresolved data-use-agreement/AI-restriction question that needs a
human to check first.

---

## Dataset 1: Assignment Feedback in School Choice Mechanisms (Zenodo 6791431)

- **Source URL:** https://zenodo.org/records/6791431
- **DOI:** 10.5281/zenodo.6791431
- **Accessed:** 2026-09-04
- **License, exact quote:** Zenodo's own record metadata
  (`https://zenodo.org/api/records/6791431`) reports
  `"license": {"id": "cc-by-4.0"}` and `"access_right": "open"`.
  This is **CC-BY-4.0**, a permissive license — proceeded with download.
- **Paper it comes from:** Stephenson, Daniel (with Alexander L. Brown and
  Rodrigo A. Velez credited for the underlying experimental research team),
  "Assignment feedback in school choice mechanisms," *Experimental
  Economics*, Vol. 25, Issue 5 (December 2022), DOI
  10.1007/s10683-022-09767-6. **This paper is paywalled** — confirmed via
  the Unpaywall API (`oa_status: "closed"`, `is_oa: false`, no OA locations
  found for that DOI). The abstract (openly available via IDEAS/RePEc) reads,
  verbatim:

  > "This paper experimentally investigates the provision of real-time
  > feedback about school assignments during the preference reporting period
  > in three widely employed mechanisms: deferred acceptance, top trading
  > cycles, and the Boston mechanism. [...] real-time assignment feedback
  > consistently increased equilibrium assignments but did not increase
  > truthful reporting."

- **What mechanism is actually used on real students:** None — **this is a
  lab experiment**, not a deployed system. Recruited human subjects played
  the role of students under each of three mechanisms (Deferred Acceptance,
  Top Trading Cycles, Boston) inside a controlled experimental market with
  fake "schools," under two feedback conditions (real-time vs. discrete).
  No real school-choice deployment is involved. This matters for how the
  data can be used later: it is preference-elicitation *behavior* data
  (what real people report, and how mechanism/feedback conditions change
  that), not administrative/deployed-mechanism outcome data.
- **Restrictions on use noticed:** None beyond CC-BY-4.0 attribution.
  The record also contains `Analysis.zip` (R/Python analysis scripts) and
  `Program.zip` (Windows `.exe`/`.dll` client-server software for running
  the experiment) under the same license; both were left undownloaded (see
  `SOURCE.txt`) as out of scope for a data sanity-check — they are software,
  not data.

### What's in the raw file

`SchoolChoiceData.csv` is a **fine-grained event log**, not a one-row-per-
subject summary: every subject's screen state is recorded roughly every 0.2
simulated seconds throughout each period (columns: `session`, `feedback`,
`mechanism`, `period`, `subject`, `type`, `truth`, `lotto`, `second`,
`assignment`, `report`, `pay1..pay6`). 1,560,384 data rows in total.

### Verification against the paper's own reported numbers

The paper's full text (subject counts, session counts, etc.) is behind
Cambridge/Springer's paywall and could not be accessed directly, so we could
not check the raw CSV against numbers pulled from the primary source itself.
Per `REVIEWER.md`'s literature-check rule ("if you cannot verify a primary
source cleanly, do not attribute a numbered result... name where to look"),
here is exactly what could and could not be independently confirmed:

- **Independently confirmed, via a different, non-paywalled paper that cites
  this one:** a 2026 working paper on experimental school choice
  (arXiv 2603.24615) includes a literature-comparison table whose entry for
  `Stephenson (2022)` reads: **"DA, TTC, BOS — 432 students."** This is an
  independent secondary source, not this repo's own re-derivation, and not
  the primary paper's text.
- **What we measured directly from the downloaded file, run via
  `parsed.py`:**
  - Mechanisms present: exactly `{boston, defAccept, topTrading}` — 3
    mechanisms, matching "DA, TTC, BOS."
  - Distinct `(session, subject)` pairs (= total experimental participants,
    since Zenodo does not reuse subject IDs across sessions): **432** —
    matches the "432 students" figure above exactly.
  - 18 sessions x 24 subjects/session = 432 (clean, confirmed by direct
    count, not assumed).
  - 2 feedback conditions (`discrete`, `realTime`), 6 distinct
    `(mechanism, feedback)` treatment cells, 3 sessions replicating each
    cell (18 / 6 = 3) — consistent with a balanced 3x2 design run in
    triplicate, matching the paper's stated real-time-vs-discrete feedback
    comparison across all three mechanisms.

**Bottom line for this dataset:** the one independently-sourced number we
could find (432 subjects, 3 mechanisms) matches the raw data exactly. We
could not verify additional finer-grained claims (e.g. exact subjects-per-
session breakdown, number of schools/seats in the experimental market)
against the primary paper because it is paywalled; a human with journal
access should re-run this check against the full text before this dataset's
provenance is treated as fully audited.

---

## Dataset 2: UMass Amherst CS course-allocation survey data (Fall 2024)

- **Source URLs:**
  - Data: https://github.com/Fair-and-Explainable-Decision-Making/course-allocation-data
  - Companion code (reference only, not downloaded, not run):
    https://github.com/Fair-and-Explainable-Decision-Making/yankee-swap-allocation-framework
- **Pinned commit:** `2c1143e1b737aafeebb751f6e2f9bf3815998beb` (repo's HEAD
  at access time)
- **Accessed:** 2026-09-04
- **License, exact quote:** There is **no `LICENSE` file** in either repo —
  confirmed via GitHub's API (`GET /repos/.../license` returns 404, and the
  repo metadata's `license` field is `null`). However, the data repo's own
  `README.md` states, in a dedicated "License" section, verbatim:

  > "This project is open-source and available under the MIT License."

  This is corroborated by `pyproject.toml`, which declares the classifier
  `"License :: OSI Approved :: MIT License"`. We treated this as sufficient
  confirmation of an **MIT** license (one of the task's named acceptable
  licenses) and proceeded with download. Flagging explicitly: this is a
  license *claim in prose*, not a formal `LICENSE` file — a human should
  confirm this is what the authors intend before any redistribution beyond
  this research use.
- **Paper it comes from:** "Deploying Fair and Efficient Course Allocation
  Mechanisms," arXiv:2502.10592 (Bissias, Navarrete Diaz, et al.,
  University of Massachusetts Amherst). Openly available on arXiv (no
  paywall issue for this one).
- **What mechanism is actually used on real students:** Confirmed directly
  in the paper's own text (quoted verbatim from the arXiv HTML source):
  UMass Amherst's real, deployed system is described in the paper as a
  seniority-ordered **Serial Dictatorship**: PhD students enter first,
  followed by MS, then undergraduates in decreasing order of seniority.
  **Serial Dictatorship is provably strategy-proof** (truthful reporting is
  a dominant strategy for every agent, regardless of everyone else's
  reports). This means: **this dataset is a clean-result / validation
  dataset for Witness's negative-control machinery, not a manipulation-
  hunting target, under the mechanism actually deployed on these students.**
  It only becomes manipulation-hunting material if a *different*,
  non-deployed mechanism (e.g. one of the paper's own comparison points —
  Round Robin, an ILP, or Yankee Swap) is later tested against these same
  real preferences — and per this task's scope, no such mechanism exists in
  `witness/` yet and none was implemented here.
- **Restrictions on use noticed:** None found beyond the MIT-license caveat
  above. The survey data is described by the authors as anonymized (course
  identities in `anonymized_courses.xlsx` are scrubbed, e.g. instructor
  names and exact catalog numbers).

### What's in the raw files

- `survey_data.csv` — one row per Qualtrics survey response: academic
  status, planned course load, time-slot preferences, and per-course
  interest rankings (1-7, or 8 for "required course").
- `anonymized_courses.xlsx` — one row per course *section* offered in Fall
  2024 CICS, with anonymized catalog/instructor identifiers, enrollment
  capacity, meeting time, and credits.
- `random_survey.csv` — a small synthetic instance with the same column
  structure (not real student data; kept only because it ships alongside
  the real file and future work may want it as a schema reference).
- `survey_column_mapping.csv` — maps the raw Qualtrics question codes
  (e.g. `"1"`, `"7_12"`) to their human-readable question text.

### Verification against the paper's own reported numbers

Unlike dataset 1, arXiv:2502.10592 is fully open, so we fetched and grepped
its actual HTML text (not a summary) for the numbers below.

| Quantity | Paper's own text (verbatim) | What `parsed.py` found in the raw file | Match? |
|---|---|---|---|
| Course sections, Fall 2024 CICS | "The Fall 2024 course schedule for the Computer Science department includes **96 distinct course sections**." | `anonymized_courses.xlsx`: **96** data rows, 96 distinct `(Catalog, Section)` pairs | **Exact match** |
| Students invited (population) | Table 2, "Total" row: **2308** invited | Not present in the downloaded files (population size, not response data) | not checkable from this data |
| Total survey responses | Table 2, "Total" row: **1065** responses (46.14% raw response rate) | `survey_data.csv`: **1061** data rows | **Mismatch: 4 fewer rows than the paper reports** |
| Responses with academic status specified | Table 2 column sum: 156+134+143+135+190+51 = **809** | `parsed.py`: **809** rows with non-blank status (question `"1"`) | **Exact match** |
| "Unspecified" status responses | Table 2: **256** | `parsed.py`: **252** (1061 - 809) | Mismatch of 4 — same 4 rows missing as above, all in the "unspecified" bucket |
| "Effective" responses (status + non-empty preferences) | Paper's text: "We utilized **700** effective responses with both academic status and non-empty preferences" | `parsed.py`'s best-effort reproduction of that filter (status specified AND >=1 non-empty entry among the 108 course-ranking columns): **730** | **Mismatch (+30)** — see caveat below |

**The task description's own count ("1,061 UMass Amherst CS students")
matches the raw file exactly** (1,061 rows), not the paper's Table 2 (1,065)
and not the GitHub repo's own `README.md`, which states in prose: *"This
file contains **1,063 student responses**."* So we have **three different
numbers for the same nominal quantity** — 1,061 (this file, and the task
brief), 1,063 (the dataset repo's own README), 1,065 (the published paper's
Table 2) — none of which we manufactured; all three are independently
sourced (file byte-count, GitHub-hosted prose, paywall-free published PDF
text). The most parsimonious explanation is that a handful of rows
(plausibly ones with no usable content at all) were trimmed from the public
CSV release after the paper's Table 2 was computed, and the README's "1,063"
is itself slightly stale/approximate — but we did not confirm this
explanation and are reporting the discrepancy rather than the explanation.

On the "effective responses = 700" figure: our from-scratch attempt to
reconstruct the paper's exact filter (has status + has at least one
non-empty course-ranking cell across all 108 ranking-question columns,
which we identified by header name from `survey_column_mapping.csv`) yields
730, not 700. The paper's Table 2 caption says effective responses require
"non-empty preferences," but does not fully specify, in the text we could
access, whether some ranking columns (there appear to be three historical
header spellings for the same underlying question: `"7"`, `"7_N"`, and
`"7 _N"`, likely from a mid-survey Qualtrics edit) should be excluded, or
whether a stricter "coherent/complete" criterion beyond "non-empty" was
applied. We are flagging this gap rather than tuning the filter until it
happens to hit 700 — that would be fitting a proxy to a target number, which
is exactly the failure mode `REVIEWER.md` warns against ("Test the property,
not a proxy").

**Bottom line for this dataset:** the two numbers with unambiguous,
directly-comparable definitions (96 course sections; 809 status-specified
responses) match the paper exactly. The two numbers with softer or
multiply-defined boundaries (total responses; "effective" responses) show
real, moderate-sized discrepancies (4 and 30 respectively) against the
published paper, and a further discrepancy (1,063 vs. 1,061) against the
hosting repo's own prose description of its own file. None of this blocks
using the data — the discrepancies are all small relative to the dataset
size and don't suggest a wrong or truncated download (file sizes and
checksums both confirm byte-for-byte correct downloads, see `SOURCE.txt`)
— but a human should be aware of them before citing "1,061," "1,063," or
"1,065" as an uncontested fact about this dataset.

---

## Dataset 3: SFUSD 2017-18 Kindergarten Main Round (KQED public-records data)

- **Source repo:** https://github.com/pickoffwhite/San-Francisco-Kindergarten-Lottery
- **Raw file:** `20171103_ KQED_KinderAssignmentData_201718 - K Placement
  2017-2018.csv`, obtained by KQED journalist Lisa Pickoff-White via a
  California Public Records Act request to San Francisco Unified School
  District. Repo description (verbatim, via the GitHub API): "KQED News
  analyzed how those parental choices impacted school assignment and
  enrollment, using anonymized data provided by the San Francisco Unified
  School District."
- **Accessed:** 2026-09-04. Full URL, size, and sha256 checksum are in
  `data/external/sfusd_2017_kindergarten/SOURCE.txt`.
- **License:** confirmed via `GET /repos/pickoffwhite/San-Francisco-Kindergarten-Lottery`
  that the API's `license` field is `null`, and there is no `LICENSE` file and
  no `README` at all in the source repo (unlike the UMass dataset above,
  which at least had a prose license claim in its own README). This is the
  **same no-formal-license-file situation** as Dataset 2, but with even less
  to go on. Proceeding on the same basis documented there: research
  replication of a publicly-hosted, already-published, de-identified
  administrative dataset obtained through a public-records request — **not**
  clearance for redistribution or any use beyond that. A human should
  confirm terms with the journalist/outlet or SFUSD directly before any
  broader use.
- **Paper analyzing this same dataset:** Robertson, Nguyen & Salehi,
  "Modeling Assumptions Clash with the Real World: Transparency, Equity, and
  Community Challenges for Student Assignment Algorithms," CHI 2021,
  arXiv:2101.10367 — openly available, no paywall. The paper's own text
  (fetched and grepped directly, not summarized) states it analyzed "4,594
  applicants," while this raw file has **4,611 data rows** — 17 more. Both
  counts are independently sourced (the paper's own prose vs. this file's
  own row count via Python's `csv` module) and this discrepancy is reported
  rather than resolved, per this project's standing rule against silently
  reconciling numbers that do not match. See "Verification" below for why
  this is nonetheless clearly the same dataset.
- **What mechanism was actually used on real students in 2017-18 — the
  single most important finding of this dataset's ingestion:** the task
  that produced this dataset's adapter started from the premise that SFUSD
  ran student-proposing deferred acceptance in 2017. **That premise is
  wrong for this dataset's year.** Per the policy paper "Designing School
  Choice for Diversity in the San Francisco Unified School District"
  (Allman, Ashlagi, Lo, Love, Mentzer, O'Connell & Ruiz-Setz; EAAMO/EC 2022;
  fetched directly from
  https://www.uts.edu.au/globalassets/sites/default/files/2022-06/SFUSD_Policy_Paper_Draft.pdf),
  quoted verbatim:

  > "Between the years 2010-2018, the assignment algorithm was based on a
  > modification of the Top Trading Cycles algorithm, which allows families
  > to trade priorities in trading cycles for admission to preferred
  > schools [Abdulkadiroğlu and Sönmez, 2003]. We noted that the
  > implemented algorithm was neither strategyproof nor envy-free, and
  > families reported confusion regarding the algorithm and its properties.
  > Since 2019, in line with our recommendation, the algorithm has been
  > based on the Deferred Acceptance algorithm."

  Independently corroborated by two more primary sources, fetched and
  grepped directly:
  - The CHI 2021 paper analyzing this exact dataset, footnote 8: "SFUSD
    uses a variant of the Top Trading Cycles algorithm."
  - Leshno & Lo, "The Cutoff Structure of Top Trading Cycles in School
    Choice" (2021, *Review of Economic Studies*; working-paper PDF fetched
    from the author's site): "the only instances of implementation of TTC
    in school choice systems are in the San Francisco school district
    ... and previously in the New Orleans Recovery School District."

  So the 2017-18 mechanism is **TTC-family, not DA** — and explicitly not
  *plain* TTC either ("a modification ... neither strategyproof nor
  envy-free"; plain TTC is always strategy-proof). `witness/` has no
  implementation of that specific undocumented modification, so
  `witness/sfusd2017.py` runs the three existing mechanisms that bracket
  the possibilities (plain TTC, plain DA, Boston immediate acceptance) and
  reports which comes closest — see the STATUS UPDATE below for the
  result, which is **not** the historically-documented TTC family.
- **The priority order, from the same policy paper, verbatim:** "Highest
  priority is given to students with a sibling at the program, followed by
  students living in the 20% of census tracts with the lowest test scores
  in the 2010 census (CTIP1), and finally students from the school's
  attendance area. A random lottery, drawn independently at each program,
  breaks remaining ties, in a process known in the literature as multiple
  tie-breaking." Of these four inputs (sibling, CTIP1, attendance area,
  per-program lottery), the raw file records only **one**: `Does Student
  Live In CTIP1 Zone? (y/n)`. See `witness/sfusd2017.py`'s module docstring,
  "WHY THIS COULD NOT BE RECOVERED THE WAY STEPHENSON'S WAS," for why this
  makes an exhaustive-search recovery (as done for Dataset 1) impossible in
  principle here, not merely harder.

### What's in the raw file

One row per applicant (`StudentNo`), 92 rank-position columns (`1`..`92`,
each holding a bare numeric school code or blank), `Round 1 Assignment`,
`School Enrolled In As Of 11/03/2017`, `Student's Ethnicity`, `Does Student
Live In CTIP1 Zone? (y/n)`, and `Student's Residential Zip Code`. No
capacity column, no sibling column, no attendance-area column, no
per-program lottery-draw column, no grade column (the filename and column
set confirm this is Kindergarten-only), no program/pathway distinction
within a school (see `witness/sfusd2017.py`'s "SCHOOL VS. PROGRAM
GRANULARITY" section: 1,647 of 4,611 applicants list the same school code
more than once across their own rank columns, which can only happen if two
different programs at one school were collapsed into a single code).

### Verification against the paper's own reported numbers

Unlike Dataset 1 (paywalled paper), arXiv:2101.10367 is fully open, so its
PDF was fetched and grepped directly (not summarized) for the numbers
below, and each one was independently reproduced from the raw CSV by this
project's own code (`witness.sfusd2017.mean_raw_rank_count` and
`witness.sfusd2017.recorded_first_choice_rate`; see
`tests/test_sfusd2017_replay.py`'s `CrossCheckAgainstThePublishedPaper`).

| Quantity | Paper's own text (verbatim) | Measured directly from the raw file | Match? |
|---|---|---|---|
| Mean schools ranked, CTIP1-eligible families | "students ranked 5.5 schools in their application (95% CI: 5.0–6.2)" | **5.59** | Match (paper reports one decimal; within its own CI) |
| Mean schools ranked, other families | "families in other areas of the city ranked an average of 11.6 (95% CI: 11.2–12.1)" | **11.60** | Exact match to the paper's stated one-decimal figure |
| Mean schools ranked, White applicants | "White students submitted especially long preference lists (mean = 16.5; 95% CI: 15.6–17.6)" | **16.59** | Match (within CI) |
| CTIP1-eligible families assigned their own first choice | "96% of families eligible for CTIP1 priority were assigned their first choice" | **677/705 = 96.0%** | Exact match |
| Other families assigned their own first choice | "compared to only 58% of other students" | **2,187/3,765 = 58.1%** | Match (within rounding) |
| Total applicants | "4,594 applicants" | 4,611 rows | **Mismatch: 17 more rows than the paper reports** (see above; reported, not resolved) |

**Bottom line for this dataset:** five of six independently-checkable
numbers from the paper's own text match this raw file almost exactly,
including two (96%/58% first-choice rates) that are exact recorded-outcome
statistics with no ambiguity in their definition — strong, independently-
sourced confirmation that this file is the same underlying dataset the
paper analyzes. The one mismatch (4,594 vs. 4,611 applicants) is a genuine,
unresolved discrepancy between two different documents about the same
dataset, reported here rather than picked one way or the other.

---

## STATUS UPDATE: dataset 3 is now wired into the mechanisms, with an honest partial result

`witness/sfusd2017.py` and `tests/test_sfusd2017_replay.py` replay this
dataset against the three existing mechanisms that bracket SFUSD's real,
undocumented 2017-18 TTC modification (plain top trading cycles, plain
student-proposing deferred acceptance, and Boston immediate acceptance).

**Unlike Dataset 1's 0-mismatches-out-of-5,184 result, this replay does NOT
reproduce the recorded `Round 1 Assignment` column exactly, and could not
be expected to:** three of the four real priority inputs the primary
sources establish (sibling status, attendance-area membership, and the
real per-program lottery draw) are simply absent from this public file.
Only CTIP1 is present. Measured match rates against the 4,611 recorded
Round 1 assignments, under a clearly-named stand-in tiebreak for everything
the data cannot supply (`STAND_IN_SEED` — fixed once, never tuned against
the outcome column):

| Mechanism | Overall match | CTIP1 match (705 students) | Non-CTIP1 match (3,906 students) |
|---|---|---|---|
| Top trading cycles (historically documented) | 56.1% | 96.0% | 48.9% |
| Student-proposing deferred acceptance | 45.7% | 96.0% | 36.6% |
| Boston immediate acceptance | **60.7% (closest)** | 96.0% | 54.4% |

Two findings worth stating plainly rather than smoothing over:

1. **The historically-documented mechanism (TTC) is not the closest
   match** — Boston immediate acceptance is, under this model. This is
   exactly the kind of result `REVIEWER.md` warns against papering over:
   the "obviously right" answer from the historical record is not what the
   data best supports once actually measured, most likely because the
   real 2017 modification to TTC and the three missing priority inputs
   both push the outcome away from what plain TTC would predict.
2. **The identical 96.0% CTIP1 match rate across all three mechanisms is
   fully mechanical, not a coincidence:** CTIP1 is this adapter's shared
   top priority tier everywhere, which makes every mechanism give every
   CTIP1 student their own reported first choice 100% of the time in the
   replay. So a CTIP1 student's replayed assignment matches the recorded
   one exactly when the recorded one already *was* their first choice —
   and that is independently true for 96.0% of CTIP1 students in the raw
   file (matching the CHI 2021 paper's own figure; see the verification
   table above). The gap this adapter cannot close is concentrated
   entirely in non-CTIP1 students, exactly where the missing sibling/
   attendance-area/lottery inputs would matter.

Also checked and reported: a `reserve_da` config giving CTIP1 a full soft
reserve on top of the same base priority order produces an assignment
**identical** to plain deferred acceptance (0 of 4,611 students differ) —
for this dataset, under this model, CTIP1 functions as a plain priority
tier, not a reserve, exactly as the primary source's own language
("priority is given to...") already states.

**Reported vs. true preferences:** unlike Dataset 1, this file has no
companion "true preference" column — only the reported ranked list. Any
manipulation search run against this profile would answer "could this
family have done better with a different report, given everyone else's
actual reports," never "did the real mechanism make this family worse off
than what they actually wanted." No manipulation search at scale has been
run against this dataset, and per `REVIEWER.md`'s disclosure section,
nothing here clears the bar for a public manipulability claim about a real
deployed system regardless: the mechanism itself is not exactly
implemented (see above), the priority structure is only one-quarter
recovered, and this task was explicitly scoped to stop well short of that
bar.

### STATUS UPDATE: attendance-area priority investigated, sibling priority re-confirmed unrecoverable — the CTIP1-only match rates above are unchanged

A later pass asked whether the two remaining unmodeled priority tiers
(sibling, attendance area) could be added to close some of the gap above.

**Sibling priority: re-confirmed unrecoverable, against the raw file's own
header, not by assumption.** All 98 columns of the raw file (not just the
subset this project's adapter reads) were checked directly for anything
resembling a sibling flag, household/family ID, or address (address would
allow a shared-residence proxy). None exists — see
`witness/sfusd2017.py`'s module docstring, "SIBLING PRIORITY: CONFIRMED
UNRECOVERABLE," and the pinned test in `tests/test_sfusd2017_replay.py`.

**Attendance-area priority: actually investigated with real geographic
data, and found not usable at acceptable precision — so it was NOT added.**
Two real primary-source geographic datasets were fetched to test this
directly rather than assume it impossible by analogy to sibling:

1. SFUSD's own published attendance-area boundaries (DataSF, extracted
   from SFUSD's GIS system) — but this extract is dated 2023, labeled for
   the **2024-2025** school year, seven years after this dataset's 2017-18
   Main Round. No earlier DataSF version was found, and the task's other
   named lead, `archive.sfusd.edu`'s
   `final-elementary-attendance-areas-map.pdf`, could not even be reached
   (the host did not respond at the TCP level when fetched) — so its year
   could not be checked at all. This year mismatch is reported, not
   resolved.
2. 2010 Census TIGER/Line ZCTA boundaries for San Francisco's ZIP codes —
   the closest-to-2017 ZIP vintage available.

Computing the actual polygon overlap between these two (not eyeballed —
see `tests/test_sfusd2017_attendance_area_geography.py` for the exact,
re-runnable computation, and
`data/external/sfusd_2017_kindergarten/attendance_area_geography/SOURCE.txt`
for full provenance) shows the ZIP-to-attendance-area join is not usable
at acceptable precision, independent of the year-mismatch problem above:

| Measure | Result |
|---|---|
| SF ZIP codes that meaningfully overlap more than one attendance area | 24 of 27 |
| Median area-share of a ZIP covered by its single best ("plurality") attendance area | 43.0% |
| 2017 raw-file SF-resident applicants living in a ZIP with no dominant (≥50%-area) attendance area | 3,873 / 4,594 = **84.3%** |

A "guess each applicant's attendance area from their ZIP's plurality
attendance area" join would be wrong for the large majority of real
applicants — a fundamentally different, and much worse, situation than
CTIP1, which the raw file states directly with no geographic join needed
at all. **Decision: attendance-area priority was NOT added to the market
model.** Forcing the join would not have recovered attendance-area
priority — it would have manufactured a third, mostly-wrong, ZIP-shaped
signal and mixed it into the market under a name that promised more than
it delivered. The CTIP1-only match rates in the table above (56.1% / 45.7%
/ **60.7%**) are therefore unchanged by this investigation. This is
reported as the honest, actual finding — the remaining gap between the
recorded outcomes and any of the three candidate mechanisms is most likely
dominated by the two priority inputs this dataset genuinely cannot supply
(sibling, confirmed above; the real per-program lottery draw), not by
attendance area, which was investigated and found not to be the fixable
part of the gap.

---

## STATUS UPDATE: dataset 1 is now wired into the mechanisms

The Zenodo dataset above is no longer only ingested -- it is REPLAYED. See
`witness/stephenson.py` and `tests/test_stephenson_replay.py`.

All three of the mechanisms this experiment ran (immediate acceptance,
student-proposing deferred acceptance, and top trading cycles) are now
implemented in `witness/`, and each one reproduces the experiment's own
recorded `assignment` column EXACTLY: 5,184 recorded assignments, made to 432
real participants, 0 mismatches.

The per-option priority structure is not recorded in the data and the article
stating it is paywalled, so it was recovered by exhaustive search over all
6^3 = 216 possible type orderings, keeping only those reproducing all 5,184
recorded outcomes under all three mechanisms. Exactly two survive and they
differ only in a way that provably never binds; both are pinned by tests, and
the residual ambiguity is documented rather than silently resolved.

The replay is non-vacuous: on these same markets the three mechanisms disagree
about individual outcomes on 35.9% / 39.8% / 47.6% of participants (pairwise),
and 40.6% of participants did not get their reported first choice.

A derived file `final_snapshots.csv` (5,184 rows, one per participant-period)
is committed next to the raw log so tests run fast; a test re-derives it from
the 90MB raw log and asserts equality, so it cannot silently drift.
