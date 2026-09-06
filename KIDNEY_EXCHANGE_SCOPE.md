# Kidney exchange: scoped next target

## Decision

Kidney exchange is the right next mechanism family for Witness, provided the
first result is described accurately:

> A reproducible analysis of *possible* hospital pair-withholding in a
> transparent two-way kidney-exchange clearing model, run on downloadable
> compatibility-graph benchmarks with explicitly synthetic hospital ownership.

It is **not** initially an audit of the OPTN/UNOS implementation or evidence
that an actual hospital withheld a pair.  That distinction is load-bearing.

The setting is a genuine deployed matching domain: the OPTN operates a
national KPD program, and public KPD material says that its computer program
maximizes matched pairs while giving additional consideration to populations
such as children and highly sensitized recipients.  But the operational
optimizer, medical compatibility information, ownership of pairs by hospital,
match-run inputs, and offers/outcomes are not present together in a public
download.  The public UNOS request process offers de-identified STAR data on
request; that is not the same as a downloadable KPD compatibility graph with
hospital provenance.

This is still a high-value extension: unlike every current registered
mechanism, the strategic actor owns a *bundle* of vertices and can withhold a
subset.  It exercises Witness's main promise (exact action, deterministic
outcome, independent replay) without pretending that an individual patient
is filing a false preference list.

## What the first model is

This is a deliberately narrow, static, two-way model.  Starting narrower is
not a claim that real KPD is restricted to two-way exchanges; it is the
published strategic setting for the initial hospital-withholding literature
and makes exhaustive, independently checkable search possible.

### Ground truth

`KidneyMarket` is a new domain type, separate from `witness.core.Market`.
It contains:

* ordered `pairs`, each with exactly one `hospital` owner;
* a directed compatibility graph, where `u -> v` means the donor associated
  with pair `u` can donate to the recipient associated with pair `v`;
* an explicit, ordered list of hospitals; and
* no rankings, capacities, school priorities, or inferred iteration order.

In the first model every selected exchange is a vertex-disjoint directed
2-cycle `(u, v)`: both `u -> v` and `v -> u` must be true.  A selected pair
means its recipient receives a transplant.  The central clearing objective is
maximum cardinality (number of selected pairs), with a declared canonical
tiebreak over the complete, ground-truth pair IDs.  The tiebreak is part of
the configuration and is never a property of Python collection order.

The model deliberately excludes altruistic donors and chains, 3+-cycles,
multiple donors for one recipient, weights/priority points, crossmatch
failure, bridge donors, time, scheduling, and post-offer decline.  Those are
real and important; each changes either feasible exchanges, the objective, or
the strategy space, so none may be smuggled in as a default.

### Strategic action and utility

A hospital's report is a subset of *its own* pairs.  All reported pairs keep
their true incident edges; reporting a false compatibility or another
hospital's pair is illegal.  The central clearing only sees reported pairs.

After that clearing, each hospital deterministically clears the residual
pairs it owns using the same two-way rule on its true internal graph.  Thus a
hospital may benefit by keeping easy pairs for a local exchange.  Its utility
is the number of its recipients transplanted in either stage.  Every pair may
appear in at most one central or local cycle.

The scope makes residual local clearing explicit because it is otherwise easy
to accidentally test the weaker and different question “does hiding change
the central solution?” rather than the strategic question “does hiding make
this hospital better off?”

The report space for hospital `h` with `k` pairs is its `2^k` subsets,
excluding full revelation.  Enumeration is canonical: fewer withheld pairs
first, then ground-truth pair order.  A hard `max_report_space` guard must
raise before enumeration when `2^k` is too large.  The initial exhaustive
regime is small hospitals only; larger cases are a future search-design
problem, not a reason to call a heuristic exhaustive.

## Data plan and evidence boundary

| Role | Candidate | What it supplies | What it does *not* supply |
| --- | --- | --- | --- |
| Primary graph benchmark | Petris et al., `Instances_KEP.zip`, DOI `10.57745/IHQAPY` | Public compatibility instances; 437.1 MB ZIP; Etalab Open Licence 2.0; a documented file format | Hospital ownership or real match-run history |
| Small, easy-to-version fixture source | INFORMSJoC `2024.0664` repository | A MIT-licensed subset of the Pansart et al. instances | The same missing hospital provenance |
| Calibration/context only | Sönmez, Ünver & Yenmez AER replication package, openICPSR 116925 | Public US aggregate calibration tables and code | Pair-level compatibility graphs and pair-to-hospital ownership |
| Actual empirical audit, later only | An approved OPTN/UNOS or program-specific data release | Potentially de-identified patient-level data on request | It is not a public download and requires a separately approved data plan |

The implementation may partition a public graph into hospitals only by a
declared deterministic or seeded synthetic rule.  Such a partition is useful
for stress-testing the game and must be stored in every witness, but it is
not observed hospital behavior.  Results using it must say “benchmark graph
with synthetic ownership,” never “real hospitals.”

Before any download enters `data/external/`, follow the existing external-data
discipline: preserve raw bytes, add `SOURCE.txt` with URL/date/license/size/
SHA-256, add a standalone structural parser, and add an independent raw-file
shape test.  Do **not** infer mechanism logic from a parser.

## Build sequence

1. **Hand-specification gate.** Write four paper traces before code:
   full revelation; one profitable withholding example; a central-clearing
   tiebreak example with multiple optima; and a no-cross-hospital-edge
   isolation example where withholding cannot help.  State every vertex,
   directed edge, owner, central cycle, residual local cycle, and utility.

2. **Mechanism only.** Add `witness/kidney.py` with validated immutable
   types, cycle feasibility, deterministic maximum-cardinality central
   clearing, residual local clearing, and a trace containing both stages.
   Add a brute-force *independent* small-market oracle which checks feasible
   disjoint 2-cycles and objective optimality.  Do not put this through the
   current `MechanismSpec` registry: its `Market`/`Profile` interface asserts
   precisely the one-agent/one-ranking shape that kidney exchange lacks.

3. **Strategic search and artifact.** Add a separate `KidneyWitness` and
   `kidney_search.py`.  Its saved artifact must contain complete ground truth,
   the target hospital, all-revealed and deviating reports, both full-stage
   outcomes, per-hospital utilities, preference/utility proof, configuration,
   and a content hash.  A new replay CLI must rebuild solely from that
   artifact and verify in a fresh subprocess.  It must assert that other
   hospitals' reports and all true compatibility edges were byte-identical.

4. **Data adapter and experiment.** Only after the hand fixtures, oracle,
   positive control, and replay are green, add a raw-data adapter.  It should
   report graph sizes/densities and ownership-generation parameters, fail
   closed on an unsupported input, and journal every scanned graph/partition.
   Separate data-validation output from strategy-search output.

## Required tests and controls

* Every 2-cycle has both directed edges; no pair is used twice across the
  central and residual stages; the central result is cardinality-optimal;
  canonical tiebreaks are cross-process deterministic.
* The planted, hand-derived withholding case is found and replays exactly in
  a fresh subprocess.  The saved outcome must prove the hospital's *total*
  recipient count improves, not merely that its reported-set outcome changes.
* In an isolated hospital with no cross-hospital compatible edges, every
  legal withholding report has utility no greater than full revelation.  This
  is a genuine negative control for the scoped game.
* Mutation tests must kill: reversing an edge, accepting a one-way edge as a
  cycle, reusing a pair, maximizing number of cycles rather than recipients,
  omitting residual local clearing from utility, and allowing a hospital to
  change another owner's pair or invent an edge.
* An exhaustive run is labeled with the exact hospital-size/report-space
  bound.  Any later sampled or heuristic run is labeled sampled/heuristic and
  cannot support an existence claim by itself.

## Definition of done for the first increment

The increment is done when it can produce a self-contained, fresh-process
replayable `KidneyWitness` for the hand positive control; prove the isolation
negative control over its entire legal report space; import one downloadable
compatibility-graph benchmark with verified provenance; and issue a short
result that cleanly separates (a) the real KPD domain, (b) the transparent
two-way model, and (c) synthetic hospital ownership.

The next expansion after that is 3-cycles, then altruist-started chains.  A
claim about actual hospital strategic behavior remains gated on a dataset
with observed ownership and match-run provenance, plus an independent review
of the deployed rule and appropriate data authorization.

## Sources checked on 2026-09-05

* OPTN/HRSA, [Kidney Paired Donation for Patients](https://www.hrsa.gov/optn/patients/kidney-paired-donation-for-patients), and [KPD informed-consent matching requirements](https://optn.transplant.hrsa.gov/media/1205/kpd_informed_consent.pdf).
* Ashlagi & Roth, [New Challenges in Multihospital Kidney Exchange](https://www.aeaweb.org/articles?id=10.1257/aer.102.3.354), which states the withholding problem directly.
* Ashlagi et al., [Mix and Match: A Strategyproof Mechanism for Multi-Hospital Kidney Exchange](https://eprints.gla.ac.uk/131324/), for the two-way hospital-strategy setting.
* Petris et al., [public full testbed](https://entrepot.recherche.data.gouv.fr/dataset.xhtml;jsessionid=dd5ec92b36b4490f66d999232935?fileAccess=Public&fileSortField=name&fileSortOrder=desc&fileTypeGroupFacet=%22Archive%22&folderPresort=true&persistentId=doi%3A10.57745%2FIHQAPY&q=&tagPresort=true&version=) and [MIT repository subset](https://github.com/INFORMSJoC/2024.0664).
* Sönmez, Ünver & Yenmez, [Incentivized Kidney Exchange replication package](https://www.openicpsr.org/openicpsr/project/116925/version/V1/view?flag=follow&pageSelected=0&pageSize=10&path=%2Fopenicpsr%2F116925%2Ffcr%3Aversions%2FV1%2FIKE-data-calibration-simulation-files&sortAsc=true&sortOrder=%28%3Ftitle%29), as a useful but insufficient calibration-only source.
* Barkel et al., [2026 operational-research survey](https://eprints.gla.ac.uk/363937/2/363937.pdf), for the public benchmark/generator landscape and the limitation of synthetic instances.
