# Formal model

Written down so the empirical claims in `README.md` refer to defined
objects rather than to code. Notation follows Roth, Sönmez & Ünver (2005)
and Ashlagi & Roth (2014) where possible.

Sections 1–6 define the mechanism and the measured quantities. **Section 7
states and proves a theorem for `k = 2`**: no withholding deviation yields
more than a center could have obtained by reporting truthfully under the
most favourable tie-break. Two corollaries follow — determinate centers
have no profitable deviation, and no `k = 2` deviation is robust to
tie-breaking. Section 7.5 shows precisely where the argument fails for
`k >= 3`, and §8 gives the counterexamples that falsify the conclusion
there.

## 1. Primitives

A **market** is a tuple `(I, T, o, E, k)`:

- `I` — finite set of incompatible patient-donor **pairs**.
- `T` — finite set of **transplant centers** (hospitals).
- `o : I -> T` — ownership. Each pair registers at exactly one center.
  `I_t = o^{-1}(t)` is center `t`'s set of pairs.
- `E subset I x I` — the **compatibility digraph**. `(i, j) in E` means
  pair `i`'s patient can receive from pair `j`'s donor.
- `k in {2, 3}` — the maximum **exchange length**.

A **cycle** of length `l <= k` is a sequence `(i_1, ..., i_l)` of distinct
pairs with `(i_m, i_{m+1}) in E` for all `m`, indices mod `l`. Every pair
in a cycle receives a transplant. A **selection** is a set of pairwise
disjoint cycles; `|S|` denotes the number of pairs it matches.

For `J subset I`, write `M_k(J)` for the maximum of `|S|` over selections
`S` using only pairs in `J`. `M_k` is the max-cardinality cycle-packing
value; it is computable in polynomial time for `k = 2` (matching) and is
NP-hard for `k >= 3`.

## 2. Reports and the mechanism

Each center `t` submits a **report** `R_t subset I_t` — the pairs it
enrolls centrally. It may withhold any subset. It cannot report pairs it
does not own, nor fabricate edges: `E` is a property of the market, not of
a report. A **profile** is `R = (R_t)_{t in T}`; truthful reporting is
`R_t = I_t` for all `t`.

The **two-stage max-cardinality mechanism** `phi` is:

1. **Central stage.** Let `P(R) = union_t R_t` be the reported pool. Choose
   a selection `S_c` over `P(R)` with `|S_c| = M_k(P(R))`.
2. **Residual local stage.** For each center `t`, let
   `L_t = I_t \ matched(S_c)` — its own pairs, *including any it withheld*,
   not matched centrally. Choose a selection `S_t` over `L_t` with
   `|S_t| = M_k(L_t)`.

Center `t`'s **utility** is the number of its own pairs matched:

```
u_t(R) = |{ i in I_t : i in matched(S_c) or i in matched(S_t) }|
```

Note the residual stage is what makes withholding potentially profitable:
a withheld pair is not lost, it is matched internally if possible.

## 3. Tie-breaking

Stage 1 is underdetermined. Write

```
Opt_k(R) = { S : S a selection over P(R), |S| = M_k(P(R)) }
```

for the set of **optimal central clearings**. When `|Opt_k(R)| > 1` the
mechanism must choose, and `phi` is only fully specified once a
**tie-breaking rule** `tau : R -> Opt_k(R)` is fixed. Write `phi^tau` for
the resulting mechanism.

Two derived quantities, both relative to a center `t` and profile `R`:

```
u_t^max(R) = max over S in Opt_k(R) of t's utility given central clearing S
u_t^min(R) = min over S in Opt_k(R) of t's utility given central clearing S
```

where in each case the residual stage is still *maximizing* for `t` (the
mechanism never clears a center's residual adversarially). The
**tie-break spread** for `t` at `R` is `u_t^max(R) - u_t^min(R)`.

## 4. Deviations

Center `t` has a **profitable withholding deviation** at profile `R` under
`phi^tau` if there exists `R_t' subsetneq R_t` with

```
u_t(R_t', R_{-t}) > u_t(R_t, R_{-t})
```

its **gain** being the difference. Two robustness notions:

- The deviation is **tie-break robust** if it is profitable under *every*
  tie-breaking rule, i.e. `u_t^min(R_t', R_{-t}) > u_t^max(R_t, R_{-t})`.
- It is **tie-break contingent** if it is profitable under some optimal
  central clearings and not others.

The **deviation rate** at a market is the fraction of centers possessing
at least one profitable withholding deviation, each verified by exhaustive
search over `2^{|I_t|}` reports.

## 5. Individual rationality

`standalone(t) = M_k(I_t)` is what `t` achieves by never participating.
A mechanism is **individually rational for centers** if `u_t >= standalone(t)`
for every `t` at the truthful profile. The **IR-constrained mechanism**
`phi_IR` maximizes `|S_c|` subject to the constraint that every center's
central-plus-residual total is at least its standalone value. Its
**efficiency cost** at a market is
`M_k(P(R)) - |S_c^{IR}|`, the transplants forgone to satisfy IR.

Proposition 1 of Roth, Sönmez & Ünver (2005) shows an IR mechanism exists;
their Proposition 2 shows no Pareto-efficient mechanism makes full
participation a dominant strategy (their example uses `k = 2`).

## 6. What is measured here

For each `(pool size, k)` on published compatibility graphs:

- the deviation rate under `phi^tau` for a fixed declared `tau`;
- for each confirmed deviation, its gain, and whether it is tie-break
  robust or tie-break contingent;
- the tie-break spread `u_t^max - u_t^min` at the truthful profile;
- the deviation rate and efficiency cost under `phi_IR`.

## 7. A theorem for `k = 2`

### 7.1 The pairwise specialization

Fix `k = 2`. Define the undirected graph `G = (I, Ê)` by

```
{i, j} in Ê   iff   (i, j) in E and (j, i) in E
```

A 2-cycle is exactly an edge of `G`, so a selection over `J subset I` is
exactly a matching of `G[J]`, and `M_2(J)` is the number of *vertices* such
a matching covers when it is maximum. Call `X subset V` **matchable in a
graph `H`** if some matching of `H` covers every vertex of `X`.

### 7.2 Statement

Fix a center `t` and the other centers' reports `R_{-t}`, with
`P_{-t} = union_{s != t} R_s`. Write

```
P^T = I_t  u  P_{-t}      (pool when t reports truthfully)
P'  = R_t' u  P_{-t}      (pool when t reports R_t' subset I_t)
```

Note `P' subset P^T`. The quantity `u_t^max(I_t, R_{-t})` is as in §3: the
best utility `t` attains over `Opt_2(I_t, R_{-t})`, the optimal central
clearings at the profile where `t` is truthful.

> **Theorem.** Let `k = 2`. For every market, every center `t`, every
> `R_{-t}`, every report `R_t' subset I_t`, and every optimal central
> clearing the mechanism may return at `(R_t', R_{-t})`,
>
> ```
> u_t(R_t', R_{-t})  <=  u_t^max(I_t, R_{-t})
> ```
>
> That is: no withholding deviation yields more than `t` could have
> obtained by reporting truthfully under the most favourable tie-break.

Nothing is assumed about `R_{-t}`; other centers may themselves be
withholding. The bound holds for every tie-breaking rule `tau`, since it
bounds the deviation payoff by a quantity defined over all of
`Opt_2(I_t, R_{-t})`.

### 7.3 Proof

Let `S_c` be any maximum matching of `G[P']` (an optimal central clearing
under the deviation) and `S_t` the residual local selection, a maximum
matching of `G[I_t \ matched(S_c)]`. Put

```
A = matched(S_c) n I_t        B = matched(S_t)
```

`A` and `B` are disjoint by construction and `u_t(R_t', R_{-t}) = |A| + |B|`.

**Step 1: `S_c u S_t` is a matching of `G[P^T]`.** `S_c` is a matching of
`G[P'] subset G[P^T]`. `S_t` is a matching on `I_t \ matched(S_c)`, and
`I_t subset P^T`, so `S_t` is a matching of `G[P^T]` too. They are
vertex-disjoint, since `S_t` is built on vertices `S_c` does not cover.
Hence `N := S_c u S_t` is a matching of `G[P^T]`, and
`matched(N) n I_t = A u B`.

**Step 2: `A u B` is matchable in `G[P^T]`.** Immediate from Step 1: the
matching `N` covers it.

**Step 3: extend to a maximum matching.** The matchable subsets of the
vertex set of a graph are the independent sets of a matroid on that vertex
set — the **matching matroid** (Edmonds & Fulkerson 1965). Its bases are
exactly the vertex sets covered by *maximum* matchings. Applying this to
`G[P^T]`: `A u B` is independent, so by matroid augmentation it extends to
a basis. That is, there exists a maximum matching `S*` of `G[P^T]` with

```
matched(S*)  ⊇  A u B
```

and `S*` is an optimal central clearing at the truthful profile,
`S* in Opt_2(I_t, R_{-t})`.

**Step 4: conclude.** Since `A u B subset I_t`,

```
|matched(S*) n I_t|  >=  |A u B|  =  u_t(R_t', R_{-t})
```

and `u_t^max(I_t, R_{-t}) >= |matched(S*) n I_t|`, because under central
clearing `S*` center `t` already receives `|matched(S*) n I_t|` pairs
before its residual stage, which can only add. Chaining the two
inequalities gives the theorem. ∎

### 7.4 Corollary: determinacy implies no profitable deviation

> **Corollary.** Let `k = 2` and suppose `t` is **determinate** at the
> truthful profile, i.e. `u_t^max(I_t, R_{-t}) = u_t^min(I_t, R_{-t})`.
> Then `t` has no profitable withholding deviation, under any tie-breaking
> rule.

*Proof.* The mechanism returns some `S in Opt_2(I_t, R_{-t})`, so `t`'s
realized truthful utility lies in `[u_t^min, u_t^max]`, which is the single
point `u_t^max`. By the Theorem every deviation yields at most `u_t^max`.
Hence no deviation is strictly profitable. ∎

This is why determinacy is not an independent empirical regularity: it is a
consequence of the Theorem.

### 7.4b Corollary: no `k = 2` deviation is tie-break robust

Recall from §4 that a deviation is **tie-break robust** if it pays off under
*every* tie-breaking rule, i.e. `u_t^min(R_t', R_{-t}) > u_t^max(I_t, R_{-t})`.

> **Corollary.** Let `k = 2`. No withholding deviation is tie-break robust.

*Proof.* The Theorem bounds `u_t(R_t', R_{-t})` by `u_t^max(I_t, R_{-t})`
for *every* optimal central clearing at `(R_t', R_{-t})` — in particular
for one attaining `u_t^min(R_t', R_{-t})`. So
`u_t^min(R_t', R_{-t}) <= u_t^max(I_t, R_{-t})`, contradicting the strict
inequality the definition requires. ∎

In words: at `k = 2` every profitable deviation is tie-break *contingent*.
A center that gains by withholding does so only because the mechanism
happened to resolve a tie against it; some optimal clearing of the truthful
pool would have served it at least as well. This is consistent with the
exact joint-ILP check, which found **0 tie-break robust deviations at
`k = 2`**, and it is *not* vacuous at `k = 3`, where 6 distinct tie-break
robust deviations were confirmed (all in small pools, `P = 50` and
`P = 100`; none among 67 resolved cases at `P = 250`).

### 7.5 Why the argument fails for `k >= 3`

Step 3 is the only step that uses `k = 2`, and it is exactly where the
argument breaks. For `k >= 3` the sets coverable by a packing of cycles of
length at most `k` do **not** form a matroid, so an analogue of `A u B`
need not extend to a maximum packing, and no substitute for `S*` is
available.

The failure of a proof is not a disproof. The Theorem's conclusion is
*separately* falsified at `k = 3` by explicit counterexamples: 188 of 1,362
verified deviations satisfy `u_t(R_t', R_{-t}) > u_t^max(I_t, R_{-t})`
(§8). So the `k = 2` / `k >= 3` boundary is real, not an artifact of the
proof technique.

This is the same boundary at which the matroid structure is invoked
elsewhere in the literature: Ashlagi & Roth (2014) use it for `k = 2` to
identify `k`-efficiency with `k`-maximality, and their worst-case cost of
individual rationality is free at `k = 2` and `1/(k-1)` at `k >= 3`.

### 7.6 Computational verification

The Theorem was checked against the implementation, not merely asserted:

- **The matroid-augmentation step alone** (Step 3), by brute force over all
  matchings of random graphs: for 20,000 random `(graph, vertex-set)` pairs,
  the best `S`-coverage over maximum matchings was never less than the best
  over arbitrary matchings. Zero violations.
- **The full statement**, end-to-end against the mechanism: on 3,000 random
  instances, enumerating *every* report `R_t' subset I_t` against *every*
  optimal central clearing, no deviation exceeded `u_t^max`. Zero
  violations. The stronger intermediate bound of Step 4,
  `u_t(R_t', R_{-t}) <= max_{S in Opt} |matched(S) n I_t|`, also held
  everywhere.
- **On the benchmark data**, 0 of 26,584 verified `k = 2` deviations exceed
  `u_t^max`, and 87% attain it exactly.

## 8. Empirical status of the Theorem's boundary

| | verified deviations | exceeding `u_t^max` |
|---|---|---|
| `k = 2` | 26,584 | **0** (Theorem) |
| `k = 3` | 1,362 | **188 (13.8%)** |

Reading: at `k = 2` a withholding deviation can only recover tie-breaking
slack the center might have received anyway; it cannot manufacture a payoff
no optimal truthful clearing could deliver. At `k = 3` it can. The
difference between the two regimes is one of kind, not of degree.

By the Corollary, the same split appears for determinacy: 0 of 195,123
determinate `k = 2` centers with room to gain have a profitable deviation,
while determinate `k = 3` centers do.

## 9. Retracted

An earlier version of §7 conjectured that at `k = 3`, tie-break spread
could exceed the maximum deviation gain by an arbitrary factor, on the
premise that *every* confirmed deviation gains exactly 1. **That premise is
false**: the census records 11 deviations of gain 2 and one of gain 3, all
independently replay-verified. The conjecture rested on an artifact of an
earlier *first-hit* deviation search, which stops at the first profitable
report rather than the best one. It is withdrawn, and no claim in this
document depends on a bound of 1 on deviation gains.
