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
(`witness/kidney_ir.py`) — see "Does individual rationality fix it?" below.

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
   the ILP. That is not innocuous, because tie-breaking is not incidental
   here: across the census below (n = 6,908), **50.7% of hospitals have an
   outcome that varies depending on which tied optimal clearing is
   returned**, and the two solvers resolve those ties differently. An
   earlier draft of this README cited a sharper figure (0/135 manipulable
   under the ILP rule vs 4/135 under Blossom on identical markets); that
   run's raw data is not in `results/`, so the claim is withdrawn here in
   favour of the census figure, which is reproducible. Note also that
   "zero overlap" was a vacuous way to describe 0-vs-4: one of those sets
   is empty.
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

### The sharpest result: at 2-cycles, lying never beats honest-plus-lucky

For every outcome-blind hospital the census records the full range of its
outcome across ALL maximum-cardinality clearings (`u_true_min` /
`u_true_max`) alongside its best achievable misreport gain from exhaustive
search. That permits a question sharper than "can a hospital gain?":
**when it gains, where does the gain come from?**

Write `U_true_max` for a hospital's best outcome under truthful reporting
over every maximum-cardinality clearing — its luckiest honest tie-break.
Comparing each confirmed manipulation's payoff against it:

| cycle length | verified manipulations | payoff exceeds `U_true_max` |
|---|---|---|
| **K = 2** | **26,584** | **0 (0.00%)** |
| **K = 3** | 1,362 | **188 (13.8%)** |

At two-way exchange, across 26,584 verified manipulations, **not one beat
what honest reporting could have achieved under a favorable tie-break** —
and 87% landed exactly on it. The 95% upper bound on the true rate is
0.011%. At three-way that fails: 188 hospitals end with strictly more than
any honest clearing could ever have given them.

Stated as the conjecture (call it **Claim A**):

> At k=2, a hospital's payoff from withholding never exceeds `U_true_max`.

The interpretation is structural, not quantitative. At 2-cycles the whole
withholding incentive lives **inside tie-breaking indeterminacy** — a
hospital can only recover what a luckier tie-break would have handed it
anyway, never manufacture value. At 3-cycles withholding becomes
*creative*: it produces outcomes no truthful clearing could. The difference
between k=2 and k=3 is one of **kind**, not of magnitude.

#### Determinacy is a corollary, not a separate finding

Call a hospital **determinate** if its matched count is identical under
every maximum-cardinality clearing (`tiebreak_spread == 0`). Claim A
implies determinate hospitals cannot gain, in two lines: determinacy means
`u_min = u_max = u`, the realized honest payoff is therefore exactly `u`,
and Claim A caps any misreport at `U_true_max = u`, so the gain is ≤ 0.

The data agrees. Excluding hospitals already matching all their own pairs
(which cannot gain for trivial reasons):

| | determinate hospitals with room to gain | manipulable |
|---|---|---|
| real benchmark (K=2) | 7,550 | **0** |
| synthetic, four parameter settings (K=2) | 187,573 | **0** |
| **total** | **195,123** | **0** |

95% upper bound, clustered on graph: ~0.003%. And all 165 determinate K=3
manipulations fall inside the "exceeds `U_true_max`" class, exactly as the
logic requires.

The controlled version holds the graphs fixed and varies only cycle
length — identical markets, identical hospitals, identical solver:

| | determinate with room to gain | manipulable |
|---|---|---|
| K = 2 | 1,003 | **0** |
| K = 3 | 367 | **17 (4.6%)** |

All 17 pass independent subprocess replay.

#### Nearly every manipulation is tie-break-dependent

Running the exact joint-ILP check (`scripts/kidney_tiebreak_exact.py`) over
119 unique K=3 witnesses asks whether a manipulation survives an
*adversarial* tie-break on both sides (`U_false_min > U_true_max`) — i.e.
whether **no** selection rule over maximum-cardinality clearings could
deter it:

| pool size | resolved | survives any tie-break | tie-break-dependent |
|---|---|---|---|
| P = 50 | 22 | 7 | 15 |
| P = 100 | 20 | 3 | 17 |
| **P = 250** | 67 | **0** | 67 |
| P = 500 | 0 | — | — (all 9 timed out) |

The ten flagged rows are **6 distinct underlying cases** (four were
independently rediscovered by two separate collection pipelines, with
identical numbers — a cross-validation, not extra evidence). Each was
re-verified by a from-scratch CP-SAT reimplementation sharing no code with
the checker; all six agreed exactly. Each withholds exactly one pair.

**These exist only in small pools.** Zero survive at P=250 out of 67
resolved, and P=500 is uninformative (every case exceeded the solve
budget). The hospitals involved own 6–7 of 50 pairs — roughly 13% of the
entire market, versus ~2.4% at P=250 — so this plausibly reflects hospitals
being large relative to the exchange, which is not the regime national
programs operate in. Reported as a small-market observation, not a general
one.

#### Claim A is proved at k=2, and the proof explains the boundary

**Claim.** At two-way exchange, no misreport gives a hospital `h` more than
`U_true_max`.

**Proof.** Let `R ⊆ V_h` be any report `h` submits, `M` a maximum matching
the center returns over the reported pool, and `L` the local matching `h`
forms afterward on its own true pairs left unmatched. `M` and `L` are
vertex-disjoint by construction (`L` only ever touches pairs `M` didn't
reach) and every edge in both is a real edge of the truthful compatibility
graph, so `N := M ∪ L` is a matching **in the full truthful graph**, and
`|V(N) ∩ V_h|` is exactly `h`'s realized payoff from misreporting.

`V(N) ∩ V_h` is therefore a *matchable* set. Matchable vertex sets of a
graph are the independent sets of the **matching matroid**, whose bases are
exactly the vertex sets of maximum matchings. By matroid augmentation,
`V(N) ∩ V_h` extends to a basis — i.e. there is a maximum matching `M*` of
the truthful graph with `V(M*) ⊇ V(N) ∩ V_h`. Hence

    h's payoff from R  ≤  |V(M*) ∩ V_h|  ≤  U_true_max.  ∎

This is also exactly why it fails at k≥3: sets packable by cycles of length
up to 3 do **not** form a matroid, so the augmentation step is unavailable.
It is the same matroid fact Ashlagi & Roth (2014) cite for k=2 (their
`k-efficient = k-maximal` equivalence) and the same boundary at which they
show the cost of individual rationality goes from free to worst-case
1/(k−1). Three properties in this repo break at that one k: the withholding
rate jumps, IR's efficiency cost goes from exactly zero to positive, and
this claim stops holding.

**Verified independently of the proof**, by exhaustive search over every
misreport against every tied optimum: 0 of 26,584 verified K=2
manipulations exceed `U_true_max` (87% land exactly on it); 188 of 1,362
K=3 manipulations do. The proof was also checked computationally — the
matroid-augmentation lemma against 20,000 random (graph, vertex-set) pairs,
and the full claim end-to-end (every misreport × every optimal tie-break)
against 3,000 random instances — with zero violations either way.

We checked Ashlagi & Roth (2014) in full (both the 2011 NBER working paper
and the 2013 pre-publication draft) and could not find this statement. Its
Proposition 8.1 — credited to an unpublished 2007 Roth–Sönmez–Ünver note —
uses a two-hospital graph with multiple maximum matchings where the
withholding gain equals what the other tied optimum would have given,
which is the same phenomenon, deployed to prove a different (and
stronger) three-way impossibility; it does not isolate this bound.

Reproduce the cycle-length and determinacy analyses with
`python3 scripts/samesolver_and_determinacy.py`.

### Does individual rationality fix it?

The standard proposed remedy is to require the clearing to give every
hospital at least what it could match internally on its own. That variant
is implemented as a single joint CP-SAT model in `witness/kidney_ir.py` —
the IR constraint is imposed *during* optimization, never as a post-hoc
repair.

**Imposing IR costs almost nothing in transplants**, and the cost splits at
exactly the k=2 / k≥3 boundary:

| | instances | transplants (plain → IR) | loss |
|---|---|---|---|
| K = 2 | 645 | 11,092 → 11,092 | **exactly 0** |
| K = 3 | 2,106 | 124,964 → 124,922 | 42 (**0.034%**) |

IR was **never infeasible** across all 2,751 instances. The exact zero at
k=2 is what matroid structure predicts (Ashlagi & Roth 2014), reproduced
here independently. The k=3 figure is worth contrasting with the
**worst-case** bound of 1/(k−1) = 50%: on real compatibility structure the
typical cost is roughly three orders of magnitude below the worst case.

**But IR does not eliminate the withholding incentive.** A paired design
(`scripts/kidney_ir_paired.py`) runs both mechanisms on the *same* market
and hospital, counting a case only when both arms resolve, which removes
the differential-attrition confound that invalidated an earlier unpaired
comparison at P=500:

| P = 250, K = 3 | rate |
|---|---|
| plain mechanism | 31 / 288 = 10.8% |
| IR mechanism | 11 / 288 = **3.8%** |

IR removes the deviation in 27 discordant cases (McNemar exact
p = 0.0008) — a real and substantial reduction. It does **not** remove it
everywhere: 11 hospitals retain a profitable withholding deviation under
IR, consistent with 41 confirmed IR-mechanism manipulations (1.5% of 2,742
checks) in the separate unpaired sweep.

More pointedly, **7 of the 288 cases can manipulate under IR but could
not under the plain mechanism** — IR does not merely under-deliver, it can
*introduce* withholding opportunities. The structural reason is visible in
the mechanism: the IR floor is computed from what a hospital *reports*, so
withholding lowers a hospital's own floor, and the constraint cannot see
the pairs held back. IR protects a hospital relative to what it discloses,
which is not the same as what it has.

This run is **in progress** (288 of a planned 1,440 paired checks); the
direction and significance are established, the point estimates will move.

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
