# Witness: measuring hospital withholding incentives in kidney exchange

A computational audit of how often a hospital can gain by withholding
patient-donor pairs from a central kidney-paired-donation (KPD) clearing
run, built on **exhaustive, independently-verified manipulation search**
(not simulation sampling, not heuristics) against a real, published
compatibility-graph benchmark.

## What this measures (and what it does not)

The hospital-withholding problem is **known and long-studied** — see
"Prior work" below; it was modeled by Roth, Sönmez and Ünver in 2005, and
Ashlagi and Roth (2014) give both worst-case and large-market results for
it. This project does not claim to discover the problem or to refute those
results.

What it measures is an empirical quantity we could not find reported
anywhere: **the fraction of hospitals holding a strictly profitable
withholding deviation, on published reproducible compatibility graphs, as
a function of pool size, under a maximum-cardinality clearing rule, with
the maximum cycle length varied between 2 and 3.**

The mechanism audited here is deliberately a **plain two-stage
max-cardinality rule** — central clearing over reported pairs, then
residual local clearing per hospital — which is close to what deployed
programs run. It is explicitly **not** the individually-rational or
incentive-aligned mechanism that Ashlagi and Roth (2014) construct, and
results here say nothing about how that designed mechanism behaves. An
individually-rational-for-hospitals variant HAS since been built and tested
(`witness/kidney_ir.py`): imposing IR costs 0.031% of transplants across
2,751 instances and is never infeasible on truthful profiles, but whether it
reduces the withholding rate is NOT established — the graph-level sign test
is null (6/12 graphs at P=250), so the point estimates should not be read as
a demonstrated effect.

## What we found

### Headline: with the solver held fixed, 3-cycles raise the withholding rate

The cleanest comparison in this repo holds the clearing *solver* constant
and varies only the maximum cycle length. Both arms use the exact-ILP
policy, the same ownership seed, the same experimental design; only K
differs (`scripts/kidney_tiebreak_census.py` hardcodes the ILP policy for
both cycle lengths, which is what makes the comparison solver-clean):

| | rate at P = 250 |
|---|---|
| 2-cycles (ILP) | 2.17% (26 / 1200) |
| 3-cycles (ILP) | 8.73% (80 / 916) |
| **difference** | **+6.57 pp** |

Clustered on the source graph — the only honest unit, since there are only
~15 distinct real compatibility graphs per pool size and the large row
counts come from re-partitioning those same graphs:

- cluster bootstrap 95% CI: **[+2.96, +11.63] pp** — excludes zero
- exact sign test, graph as unit: **13 of 15 graphs**, p = **0.0074**

The same census finds **no effect at P = 50 (−0.25 pp) or P = 100 (+0.08
pp)**. The divergence is a large-market phenomenon, which is the direction
that matters and the opposite of what a small-sample artifact would produce.

### A superseded earlier headline, and why it was retired

An earlier version of this README reported **1.2% vs 12.3%** pooled at
P >= 250, with a naive Fisher exact p ≈ 1.6e-8. That comparison is retired.
Three defects, all found by adversarial review of this repo's own data:

1. **It mixed solvers.** The 2-cycle arm ran Blossom, the 3-cycle arm ran
   the ILP. Separately in this project, swapping tiebreak policy on
   identical markets changed which hospitals could manipulate (0/135 vs
   4/135, *zero overlap*), so a solver difference is not innocuous.
2. **It mixed ownership seeds** across its three constituent runs.
3. **Its significance leaned on a 45-check run** seeded `smoke-cap-test`.
   Dropping P=500, the sign test falls to 6/8, p = 0.29.

The naive p-value was also overstated on its own terms: it treated every
hospital-check as independent when the checks come from ~15 graphs.
Clustered, that comparison gives CI [+4.8, +18.5] pp and p ≈ 1e-4 — still
real, but four orders of magnitude less certain than first claimed. It is
superseded here by the solver-clean comparison above rather than repaired.

There is a hard ceiling worth stating: with ~15 graphs per pool size, an
exact sign test cannot return a p-value below about 6e-5 no matter how
large the effect. The effective sample size is the number of graphs, not
the number of hospital-checks.

### Retracted: "manipulation gain is always exactly 1"

Earlier drafts claimed every confirmed manipulation gained exactly one
transplant. That is false. Across all census data (`strategic_gain` field):

| gain | count |
|---|---|
| 0 | 6,700 |
| 1 | 181 |
| 2 | 11 |
| 3 | 1 |

All twelve gain>1 cases pass independent subprocess replay. The false claim
came from an earlier analysis built on a *first-hit* manipulation search,
which stops at the first profitable report rather than the best one; the
census uses max-gain search. Any argument resting on a gain bound of 1 —
including the conjecture previously stated in `MODEL.md` — is unsupported.

### Tie-breaking indeterminacy is widespread, but the magnitude claim did not survive

When several clearings tie for maximum cardinality, which one the mechanism
returns is not specified by the theory, by policy, or by the software. We
measured, per hospital and outcome-blind, the full range of its outcome
across all tied optimal clearings (`tiebreak_spread`) alongside its best
achievable misreport gain (`strategic_gain`).

**What survives** is a prevalence claim, which does not depend on comparing
magnitudes:

| | tiebreak-sensitive | any strategic option |
|---|---|---|
| pooled (n = 6,908) | **50.7%** | **2.8%** |
| K=2, P=250 | 73.7% | 2.2% |
| K=3, P=250 | 81.9% | 8.8% |

**What did not survive**: an earlier framing claimed the tiebreak effect was
~25x larger than the strategic effect. That ratio was inflated three ways —
it compared a range over *all* mathematically tied clearings against a gain
measured under *one* fixed rule; the realizable set is narrower than the
mathematical one; and the ratio was carried by the ~97% of hospitals with
zero gain. Restricted to hospitals that actually have a strategic option,
the two are comparable (1.69 vs 1.07), not 25x apart.

A direct test also showed the indeterminacy is **not** realized by re-running
one solver: on an instance with 760 candidate cycles and a confirmed spread
of 4, eight different CP-SAT random seeds returned the *identical*
selection. The variation appears across *implementations* (ILP vs Blossom),
not across runs of one implementation.

### The sharpest result: determinacy appears to imply strategyproofness at K=2

For every outcome-blind hospital the census records two things: the full
range of its outcome across ALL maximum-cardinality clearings
(`tiebreak_spread`), and its best achievable misreport gain from exhaustive
search (`strategic_gain`). That permits a conditional we could not find
reported anywhere:

| cycle length | determinate hospitals (spread = 0) | of those, manipulable |
|---|---|---|
| **K = 2** | **2,434** | **0** |
| **K = 3** | 1,557 | 11 (0.71%), every one gaining exactly 1 |

Across 2,434 two-way-exchange hospitals whose outcome was identical under
every optimal clearing, **not one had a profitable misreport**. The 95%
upper bound on the true rate is 0.12%. For contrast, among *indeterminate*
hospitals the manipulation rate is 4.39% (K=2) and 6.13% (K=3) — a risk
ratio of ~19x pooled, clustered over 41 graphs at +4.97 pp,
95% CI [+3.67, +6.48], sign test **38 of 39 graphs**, p at the resolution
floor.

The eleven K=3 exceptions are spread across 9 distinct source graphs (not
one pathological instance), all gain exactly 1, and none occur at hospitals
with zero baseline utility.

**Why this may not be a coincidence.** The K=2 / K=3 boundary is exactly
where the matroid structure of the clearing problem fails — the same
boundary at which Ashlagi & Roth (2014) show the cost of individual
rationality goes from free (k=2, where maximum matchings form a matroid) to
worst-case 1/(k-1) (k>=3). Two separate properties break at the same place.

Stated as the open question rather than a result: **is determinacy
sufficient for strategyproofness in this class of mechanisms — provably so
at k=2, and approximately so at k=3?** If a hospital's outcome is identical
under every maximum-cardinality clearing, can it ever gain by lying? The
data says essentially never at k=2 and rarely-and-minimally at k=3. Whether
that is a theorem is not something measurement can settle.

Reproduce both analyses in this section with
`python3 scripts/samesolver_and_determinacy.py`.

## What is real and what is synthetic

- **Real**: the compatibility graph. Published, peer-reviewed,
  MIT-licensed KEP benchmark instances (Pansart et al. 2022 / Petris et al.
  2025, IJOC).
- **Synthetic**: hospital ownership. The dataset carries no ownership
  metadata; pairs are partitioned into hospitals by a declared, seeded rule
  (`witness/kidney_real_data.py`). Every result is labeled accordingly.
- **Not modeled**: chains, altruistic/non-directed donors, dynamic arrival,
  failure/crossmatch rates, and the priority and weighting rules in
  deployed OPTN/NKR/APD clearing.
- **Not claimed**: that any real hospital has done this. The claim is that
  under the compatibility structure of a real benchmark, and under a plain
  max-cardinality clearing rule, the measured deviation rate rises sharply
  with pool size when 3-cycles are allowed and does not when they are not.

## Rigor

Every claimed manipulation is:
1. Found by **exhaustive search** over the hospital's full report space
   (every subset of its own pairs it could withhold), not sampling.
2. Checked against an **independent oracle** (`witness/oracles_kidney.py`)
   sharing no code with the mechanism it checks.
3. **Replayed in a fresh subprocess** from the saved witness alone
   (`witness/replay_kidney.py`) before being counted.
4. Cleared, for 3-cycles (NP-hard cycle packing), by exact integer
   programming (OR-Tools CP-SAT, proof of optimality required, never a
   heuristic bound), cross-validated against a brute-force oracle on 350+
   random instances before being trusted at scale
   (`tests/test_kidney3_ilp_matches_oracle.py`).

Hand-derived fixtures (`tests/test_kidney_handworked.py`,
`tests/test_kidney3_handworked.py`) were worked out on paper from the
model's definition before being checked against the implementation, per
`REVIEWER.md`.

## Reproducing

```
pip install -r requirements.txt
python3 -m pytest tests/test_kidney_handworked.py tests/test_kidney3_handworked.py \
  tests/test_kidney_blossom_matches_oracle.py tests/test_kidney3_ilp_matches_oracle.py \
  tests/test_kidney_tiebreak_robustness.py tests/test_external_data.py -q

# Real-data sweep, both cycle-length regimes:
python3 scripts/kidney_real_data_sweep.py --sizes 50 100 250 500 \
  --draws-per-member 20 20 20 7 --tiebreak-policy max_cardinality_blossom \
  --max-cycle-length 2 --out-dir results/repro_k2

python3 scripts/kidney_real_data_sweep.py --sizes 50 100 250 \
  --draws-per-member 20 20 20 --tiebreak-policy max_cardinality_ilp \
  --max-cycle-length 3 --out-dir results/repro_k3

# Tiebreak robustness (resumable; rerun the same command to continue):
python3 scripts/kidney_tiebreak_robustness.py \
  results/kidney_k3_real_sweep_v2/witnesses.jsonl \
  results/kidney_k3_real_p500_supplement/witnesses.jsonl \
  results/kidney_real_data_sweep_v2/witnesses.jsonl \
  --out-dir results/kidney_tiebreak_robustness --max-ilp-seconds 60
```

See `KIDNEY_EXCHANGE_SCOPE.md` for the full model specification and data
provenance, and `results/` for every raw run behind the numbers above.

## Prior work

The withholding problem is established; this project is an empirical
measurement inside it, not a discovery of it.

- **Roth, Sönmez & Ünver (2005), "Transplant Center Incentives in Kidney
  Exchange"** (unpublished note) — first models transplant centers as
  strategic players who may withhold pairs and match them internally, i.e.
  the same two-stage structure audited here. Proposition 2 proves no
  Pareto-efficient mechanism makes full participation a dominant strategy.
  Read in full: its impossibility example uses **pairwise exchanges only**,
  and the note makes no claim about severity varying with cycle length.
- **Ashlagi & Roth (2014), "Free riding and participation in large scale,
  multi-hospital kidney exchange," Theoretical Economics 9(3)** — worst-case
  bound on the cost of individual rationality, and the large-market result
  that this cost becomes low in almost every large pool, **for exchanges of
  size up to 3**, together with a mechanism giving hospitals incentives to
  reveal all pairs. Their asymptotic result is not contradicted by anything
  here: it concerns a designed mechanism, whereas this audit measures a
  plain max-cardinality rule.
- **Agarwal, Ashlagi, Azevedo, Featherstone & Karaduman (2019), "Market
  Failure in Kidney Exchange," AER 109(11)** — quantifies efficiency loss
  from fragmentation on US platform data. Measures platform-level
  production and aggregate welfare loss rather than per-hospital deviation
  rates, on proprietary rather than published graphs.
- **Ashlagi, Fischer, Kash & Procaccia (2015)** — strategyproof mechanism
  design (Mix-and-Match) with guarantees stated for two-way exchange.
- **Toulis & Parkes (2015), xCM** — extends to 3-cycles with an ex-post
  Nash guarantee, explicitly not full strategy-proofness.

If the specific measurement here is already published somewhere, we would
be glad of the citation.
