# REVIEWER.md

This file is not documentation of the code. It is the **role that has been
reviewing this work**, written down so it can be performed from inside the
project rather than from outside it.

Read it at the start of every session. Apply it to your own output before
reporting anything as done.

---

## PURPOSE OF THE PROJECT

Witness searches for strategic manipulations in real, deployed matching
mechanisms — school choice and residency matching. A finding is an existence
claim, not a behavioral one: it asserts that a profitable misreport EXISTS under
these exact rules, not that anyone actually cheats. That is why it must be
provable by replay rather than argued.

The realistic outcome distribution, which should keep expectations calibrated:
~50% the controls pass and nothing new is found (still a real result — a
validated public audit tool); ~25% precise empirical characterization of known-
manipulable mechanisms; ~15-20% a genuine finding in a deployed variant; a few
percent something significant in NRMP couples. Build as if the 50% case is what
you're getting.

Target mechanisms, in order of value: NRMP residency match (couples is the
documented soft spot), school choice systems still running weaker rules,
university course allocation, kidney exchange (different structure — the
strategic actor is a hospital withholding easy pairs, not a patient lying).

## THE STANDING RULES

**Hand-work before coding.** Every mechanism gets paper traces first, derived by
hand, never by a scratch implementation — code must not define its own expected
answers. If you cannot hand-trace it, you cannot implement it. This has caught
three errors that would otherwise have been baked into test fixtures.

**Any outcome-affecting choice is declared configuration.** Tiebreaks, placement
student order, placement school order, proposal policy, precedence order. Never
dict/set iteration order. If a trace's result depends on an order, the order must
be named in the trace.

**Test the property, not a proxy.** All three green-by-coincidence bugs so far
shared this shape: non-empty file instead of file-replays; sorted() succeeding
instead of order correct; prefix semantics instead of sublist. When a test can
assert the real property by actually doing the thing — shelling out to the replay
CLI, running the full pipeline — do that, even when it is slower.

**Make the permissive path explicit at each call site.** `allow_unranked=False`
by default, `True` passed only where intended. Named spaces, not boolean flags.

**Mutation-test every new mechanism's distinctive properties.** A property that
no test bites on is not verified.

**Every finding replays from its saved witness alone, in a fresh subprocess.**
Not the same interpreter. If it doesn't replay, it isn't a finding.

**No number goes public unless it is registered in `claims.json` and
`python3 scripts/verify_claims.py` passes.** "Public" means README.md,
MODEL.md, or an email to anyone outside the project. This rule exists
because the prose rules above did not work: "re-derive, don't inherit" has
been in this file since early on, and every error this project has shipped
still went out under it. A norm is checked only by the person who already
believes they are following it. The registry is the executable version —
see "WHY MECHANICAL CHECKS" below.

## THE REVIEW HEURISTICS — apply these to your own results

**Perfect numbers are artifact-shaped.** 100% coverage, a median of 1, a rate
that lands exactly on a round figure — treat these as suspicious until tested
where the space is sparse enough that the result could have failed. The singleton
result was only credible after m=8, where singletons are 0.007% of report space.

**A surprising rate is a distributional question before it is a bug.** The 75%
Boston manipulation rate was arithmetically correct and deeply misleading: the
generator was over-subscribed by one seat, so a student was unmatched in every
instance, and 241 of 258 gains came from truthfully-unmatched targets. Before
accepting any headline rate: examine five hits by hand, then check the rate
against published figures for comparable setups.

**Benchmarks measured at the smallest configuration always flatter.** The sizing
estimate was wrong by 35x for exactly this reason. Quote cost at the widest shape
you intend to run.

**When a process "hangs," measure cost per unit at two sizes before theorizing.**
Linear scaling rules out deadlocks and payload bugs in one step. Three wrong
diagnoses were spent skipping this.

**Never claim novelty without a literature check.** If you cannot verify a primary
source cleanly, do not attribute a numbered result — say the instrument
rediscovered a standard result and name where to look. A wrong citation costs more
credibility than no citation.

**Convert measurements into invariants where a proof exists.** A measured 100%
can quietly regress; an assertion cannot. Scope it in one place (proved regime =
assert, unproved = record, elsewhere = observe) so the distinction can't drift.
And every invariant needs a deliberate violating fixture, or it may be passing
vacuously.

**Never inherit a theorem across mechanisms.** Singleton sufficiency is proved
for immediate acceptance. It survived placement (prediction wrong) and holds for
`first_choice_bonus_da`, which releases seats (framing wrong). Measure per
mechanism; treat apparent survival where the premise is broken as a signal
something is wrong with the implementation, not as good news.

**Keep strong and weak claims strictly separated in every metric.** Some-gain vs
best-gain. Order-robust vs order-dependent. Existence vs behavioral. A restricted
search space that reliably finds small gains while missing large ones looks
excellent under the wrong metric and is worthless in practice.

**Prerequisites before scaling.** Millions of instances from a narrow generator is
the same narrow case repeated, not stronger evidence. Fix generator width first,
then scale. Compute has never been this project's constraint; report-space
explosion is.

**A number that only exists when you run a script by hand is not infrastructure.**
It must come out of the runner.

## SEQUENCING AND OPEN ITEMS

Reserved seats before couples. Reserves preserve determinism and yield both
controls in one mechanism via substitutability of the choice rule. In hand-working
them, make at least one example distinguish RESERVE seats (a floor for the target
group, others may take them if unfilled) from QUOTA seats (hard cap or exclusive)
— they are different mechanisms with different theoretical properties, and citing
theory about one while implementing the other survives a green test suite.

Couples: read Roth-Peranson properly before implementing, not from memory.
Determinism gets constructed, not discovered — processing order and the
restart/stopping rule become explicit config. Note the inversion: for
`proposal_policy` the test asserts the setting CANNOT change the outcome; for
couples it asserts that it DOES, and pins which. The oracle becomes three-valued
because a stable matching may not exist; non-existence frequency is a measurement
in its own right, possibly more interesting than any manipulation found there.
Expect singleton sufficiency to FAIL under couples — a couple's report changes
which seats their partner competes for, so round-1 independence dissolves.

Exhaustive report search cannot be the hunting method at realistic sizes (~10M
reports at 10 schools). Singleton-promotion is the empirically-derived
replacement for Boston. Re-derive, don't inherit, for each new mechanism.

## DISCLOSURE

If a manipulation in a real deployed system is found: verify it is not an
implementation bug, then disclose privately to the mechanism's operators or the
academics who study it before any public claim. That is the norm in this field
and it is how the finding gets taken seriously rather than dismissed.

## THE HONEST LIMITATION OF THIS FILE

The reviewer's value was independence — someone who did not write the code
checking whether it was right, and who caught errors the author's own tests were
structurally blind to. Reviewing your own work does not reproduce that. Compensate
by having a subagent reproduce contested numbers from scratch rather than
inspecting the code that produced them — that method already caught one false
"defect" report. Where you cannot get independence, say so in the report rather
than implying a check was independent when it was not.

## WHY MECHANICAL CHECKS — the three shapes every shipped error took

Every incorrect claim this project has published had one of three shapes.
None was caught by the prose rules above. `claims.json` plus
`scripts/verify_claims.py` turn each shape into a test that fails.

**(A) Incommensurable comparison.** Two numbers compared that differ in more
than the one respect being claimed. The plain-vs-IR comparison differed in
the IR constraint *and* the tie-breaking rule; since manipulability is
provably tie-break contingent at k=2, the two effects were not separable,
so the reported magnitudes meant nothing. The "25x tie-break" claim compared
a range taken over all tied optima against a gain measured under one fixed
rule.

*Check C1:* each arm declares its full config; the verifier diffs them and
requires the differing keys to equal `varies` exactly. An undeclared
difference fails even if the author believes it immaterial.

**(B) Inherited number.** A figure established under method X, reused under
method Y without re-derivation. "Gain is always exactly 1" was true of a
first-hit search and false of the max-gain census that replaced it. Size-
effect p-values were carried across from the tie-break analysis. A README
cited `clustered_inference.py` for a comparison that script never performed.

*Check P0:* every claim names the files it derives from, and they must
exist. Re-deriving from a named source is the only way to register a number.

**(C) Scope overreach.** Evidence covering population P stated as a claim
about superset Q. "The IR constraint never binds" was verified at the
truthful profile only — and the matched-tie-break control later showed the
constraint *does* bite under misreports, which nearly caused a correct
finding to be retracted. A determinacy denominator counted hospitals already
matching all their own pairs, which cannot gain by construction, inflating
195,123 to 490,147.

*Checks C2 and C3:* `eligibility` must state which rows count and which are
excluded and why; `scope` must state the tested population, and a claim
whose text uses a universal quantifier ("never", "every", "no") fails
unless scope is explicit about it.

**The meta-lesson.** All three are the same underlying failure: a claim's
justification lived in the author's head rather than in a form anything
could check. The registry does not make anyone more careful. It makes the
uncheckable claim impossible to file.

**Retracting is also a claim.** A retraction needs the same standard of
evidence as an assertion — twice in this project a correct result was nearly
withdrawn on the strength of a test that did not actually test it. A claim
marked `retracted` must carry a `retraction` field saying what specifically
failed, and the verifier enforces that.
