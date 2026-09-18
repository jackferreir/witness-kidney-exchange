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
results here say nothing about how that designed mechanism behaves. Testing
an individually-rational-for-hospitals variant is the obvious next step and
is not yet done.

## What we found

On the *same* real compatibility graphs (Pansart et al. 2022 benchmark,
MIT-licensed, included under `data/external/pansart2022_kep/`), changing
only the maximum cycle length the central clearing may use:

| Pool size | 2-cycles only | 3-cycles allowed |
|---|---|---|
| 50 patients | 2.7% | 3.3% |
| 100 patients | 1.0% | 2.0% |
| 250 patients | 1.3% | **8.7%** |
| 500 patients | 0.9% | **24.4%** |

Pooled at P >= 250: 1.2% (5/405) vs 12.3% (24/195) — a difference of +11.1
percentage points.

**On the statistics, stated carefully.** A naive Fisher exact test on those
counts returns p ~= 1.6e-8, and an earlier version of this README reported
that figure. It is overstated, because it treats every hospital-check as an
independent observation. They are not: there are only ~15 distinct REAL
compatibility graphs per pool size (see `witness/kidney_real_data.py`), and
the large check counts come from re-partitioning those same graphs into
hospitals many times over. Hospitals drawn from one graph share its
compatibility structure, so the observations are CLUSTERED, and clustering
inflates naive significance. Re-analysed clustering on the source graph
(`scripts/clustered_inference.py`):

- cluster bootstrap over graphs, 95% CI on the difference: **[+4.8, +18.5]
  percentage points** — excludes zero
- one-sided bootstrap p (that 3-cycles are NOT higher): **p ~= 1e-4**
- exact sign test, graph as the unit of analysis: **14 of 17 graphs** show
  the 3-cycle rate higher, **p = 0.013**

The finding survives; the certainty does not. Note also a hard ceiling: with
~15 graphs per pool size, a sign test cannot return a p-value below about
6e-5 even if every graph agrees, so no amount of additional re-partitioning
can push these numbers lower. The effective sample size is the number of
graphs, not the number of hospital-checks.

At P = 50-100 the two cycle lengths are statistically indistinguishable
under either analysis.

Raw counts: 2-cycles from `results/kidney_real_data_sweep_v2/summary.json`
(4/300 at P=250, 1/105 at P=500); 3-cycles from
`results/kidney_k3_real_sweep_v2/summary.json` (13/150 at P=250) plus
`results/kidney_k3_real_p500_supplement/summary.json` (11/45 at P=500, run
separately due to per-instance solve time at that size).

A follow-up full census (every hospital checked per market rather than one
sampled hospital per market, closing an undercounting gap found partway
through the project — `results/kidney_census_p250/summary.json`) gives
15.2% at 250 patients under 3-cycles.

### Important caveat: tiebreak dependence is unresolved at the sizes that matter

When several clearings tie for maximum cardinality, the mechanism selects
one deterministically (declared, seeded rule). The rates above are
therefore properties of *that* rule. We tested separately whether each
confirmed manipulation still pays under **every** tied maximum-cardinality
clearing (`scripts/kidney_tiebreak_robustness.py`, validated in
`tests/test_kidney_tiebreak_robustness.py` against an independent
brute-force enumeration on 120 random markets):

| K | Pool | robust under all tiebreaks | profitable under some only | undetermined |
|---|---|---|---|---|
| 2 | 50-750 | 0 | 18 | 0 |
| 3 | 50 | 3 | 7 | 0 |
| 3 | 100 | 1 | 5 | 0 |
| 3 | 250 | 0 | 9 | 4 |
| 3 | 500 | 0 | 0 | 11 |

**At P >= 250 — the sizes carrying the headline result — no manipulation
has been shown robust to arbitrary tiebreaking.** They are profitable under
some maximum-cardinality clearings and not others, and every P=500 case is
undetermined because the feasibility solve exceeded the 60s cap (undetermined
means unmeasured, never counted either way). The measured rates stand as
statements about this deterministic rule; they are **not** established as
invariant to which optimal clearing is selected. Raw per-witness output:
`results/kidney_tiebreak_robustness/per_witness.jsonl`.

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
