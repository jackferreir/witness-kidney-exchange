# Witness: does the "large market" safety net hold for real kidney exchange?

A computational audit of hospital withholding incentives in kidney-paired
donation, built on **exhaustive, independently-verified manipulation
search** (not simulation sampling, not heuristics) run against a real,
published compatibility-graph benchmark.

## The question

A well-known result in this literature says a hospital's incentive to
withhold an easy-to-match patient-donor pair (instead of pooling it
nationally) vanishes as the shared pool grows. That result is proven, and
correctly, for two-way exchanges. **We tested whether it holds once
three-way exchanges are allowed — the structure actually used in deployed
kidney-paired-donation programs, not a simplification of it.**

## What we found

On the *same* real compatibility graphs (Petris/Pansart et al. 2022
benchmark, MIT-licensed, included in this repo under
`data/external/pansart2022_kep/`), changing only whether the central
clearing mechanism is allowed to use 3-cycles:

| Pool size | 2-cycles only | 3-cycles allowed |
|---|---|---|
| 50 patients | 2.7% | 3.3% |
| 100 patients | 1.0% | 2.0% |
| 250 patients | 1.3% | **8.7%** |
| 500 patients | 0.9% | **24.4%** |

Figures are the fraction of hospitals with an exhaustively-verified,
strictly-profitable way to withhold a subset of their own pairs. At P >=
250: 1.2% (5/405) vs 12.3% (24/195), one-sided Fisher exact p ~= 1.6e-8.
At P = 50-100 the two are statistically indistinguishable (p = 0.41 and
p = 0.25 respectively) — **the divergence is a large-market phenomenon,
not a small-market artifact.**

Raw counts behind the P >= 250 figures: 2-cycles from
`results/kidney_real_data_sweep_v2/summary.json` (4/300 at P=250, 1/105 at
P=500); 3-cycles from `results/kidney_k3_real_sweep_v2/summary.json`
(13/150 at P=250) plus `results/kidney_k3_real_p500_supplement/summary.json`
(11/45 at P=500, run separately due to per-instance solve time at this
size).

A follow-up full census (every hospital checked per market, not one
sampled hospital per market, closing an undercounting gap found partway
through this project — see `results/kidney_census_p250/summary.json`)
confirms the trend continues: 15.2% at 250 patients when every hospital is
checked exhaustively rather than sampled.

## What this is and is not

- **Real**: the compatibility graph. Published, peer-reviewed, MIT-licensed
  KEP benchmark instances (Pansart et al. 2022 / Petris et al. 2025, IJOC).
- **Synthetic**: hospital ownership. This dataset has no ownership
  metadata; pairs are partitioned into hospitals via a declared, seeded
  rule (see `witness/kidney_real_data.py`). Every result is labeled
  accordingly.
- **Not tested**: real hospital identities, real match-run history, chains,
  altruistic donors, or the actual deployed OPTN/NKR/APD clearing
  algorithms (which include additional priority/weighting rules this
  two-and-three-way-only model does not capture).
- **Not a claim** that any real hospital has exploited this. It is a claim
  that, under the compatibility structure actually observed in a real
  benchmark, the incentive to do so exists and grows with scale once
  3-cycles are the clearing rule — which is what real KPD systems use.

## Rigor

Every claimed manipulation is:
1. Found by **exhaustive search** over a hospital's full report space
   (every subset of its own pairs it could withhold), not sampling.
2. Checked against an **independent oracle** (`witness/oracles_kidney.py`)
   that shares no code with the mechanism it checks.
3. **Replayed in a fresh subprocess** from the saved witness alone
   (`witness/replay_kidney.py`) before being counted.
4. Central clearing for 3-cycles (NP-hard cycle packing) is solved via
   exact integer programming (OR-Tools CP-SAT, proof of optimality
   required, never a heuristic bound) — cross-validated against a brute-
   force oracle on 350+ random instances before being trusted at scale
   (`tests/test_kidney3_ilp_matches_oracle.py`).

Every hand-derived example (`tests/test_kidney_handworked.py`,
`tests/test_kidney3_handworked.py`) was worked out on paper from the
model's definition before being checked against the implementation, per
the project discipline in `REVIEWER.md`.

## Reproducing this

```
pip install -r requirements.txt
python3 -m pytest tests/test_kidney_handworked.py tests/test_kidney3_handworked.py \
  tests/test_kidney_blossom_matches_oracle.py tests/test_kidney3_ilp_matches_oracle.py \
  tests/test_external_data.py -q

# Real-data sweep, both cycle-length regimes:
python3 scripts/kidney_real_data_sweep.py --sizes 50 100 250 500 \
  --draws-per-member 20 20 20 7 --tiebreak-policy max_cardinality_blossom \
  --max-cycle-length 2 --out-dir results/repro_k2

python3 scripts/kidney_real_data_sweep.py --sizes 50 100 250 \
  --draws-per-member 20 20 20 --tiebreak-policy max_cardinality_ilp \
  --max-cycle-length 3 --out-dir results/repro_k3
```

See `KIDNEY_EXCHANGE_SCOPE.md` for the full model specification and data
provenance, and `results/` for every raw run behind the numbers above.

## Prior work

This project confirms and extends a documented soft spot: Ashlagi, Fischer,
Kash & Procaccia (2015) built a mechanism (Mix-and-Match) for exactly this
problem but explicitly note their guarantee is for two-way exchange;
Toulis & Parkes (2015, xCM) extend to 3-cycles but their own stated
guarantee is an ex-post Nash equilibrium, explicitly *not* full
strategy-proofness. We could not find prior work isolating whether the
per-hospital deviation *rate* grows or shrinks with pool size specifically
under 3-cycles — if this is already known, we would very much like the
citation.
