# Reducing drawdown without timing — the combination route

**Run 21 September 2026.** Successor to [CRUDE_OIL_DRAWDOWN.md](CRUDE_OIL_DRAWDOWN.md), which
rejected eleven timing overlays on a single crude book and closed with an untested inference:

> "The real drawdown lever is diversification, not timing. […] it does not require the edge to
> be real in any one of them."

This tests that inference. **The first half is right and the second half is wrong**, and both
halves matter for how the book gets built.

*Reproduce:* `book_grid.py` → `portfolio_dd.py` → `portfolio_stress.py` → `portfolio_crude.py`,
then `capacity_floor.py` → `capacity.py [min_dv]` for §7. All in `backtesting/hyperliquid/hip3/`.

---

## Verdict

**Combining the two uncorrelated crypto books is the only thing in this project that improves
Sharpe and drawdown at the same time.** Held at natural size, the pair runs Sharpe **1.34**
with a **−11.6%** drawdown, against 0.91 / −12.9% and 0.89 / −14.6% for the legs alone. It
survives a 40bp/side cost hurdle against a 9.5bp assumption — the first idea here not killed by
the fee line. It does **not** clear the project's DSR bar (0.58 against 0.95), and the honest
drawdown planning number is **−27.5%**, not the −11.6% that happened.

Three things had to be corrected to get there, and each one lowered the answer.

---

## 0. The two rules, inherited

Unchanged from `CRUDE_OIL_DRAWDOWN.md` §0, because they are what caught that file's own bug.

**Rule 1 — equal risk.** Any allocator lowers drawdown by holding less, and holding less is
free. Every variant is rescaled by a constant to a common 15% full-sample realised vol before
drawdowns are compared. A constant rescale leaves Sharpe untouched, so this compares *shape*,
not size.

**Rule 2 — one common window.** Allocators warm up at different speeds. Every number is scored
on the single window where all variants have a valid weight.

Rule 2 is now also applied *inside* each leg: the ensemble averages only over dates where every
grid cell has a value, because `resid_win=90` cells start 30 days after `resid_win=60` ones.

---

## 1. Both published legs are the best cell of their own grid

`SURVIVORS_RECHECK.md` predicted this for the residual leg and flagged the substitution as
"not been run and should be". It has now been run, and it turns out to apply to **both** legs.

| Stored file | Reproduces? | At which cell |
|---|---|---|
| `overlap_daily.csv` | **yes, to 1e-17** | lookback 5, hold 20 — **best of 24** |
| `factor_residual_daily.csv` | no, max abs err **6.1e-02** | not the script's defaults |
| `resid_momentum_daily.csv` | no, max abs err **1.1e-01** | 10 factors — **best of 30** |

The residual script's own defaults (`n_factors=5, entry=1.5`) produce Sharpe **0.45**. The
stored file is **1.045**. It was saved from `n_factors=10` and the script was never updated.

### The parameter surfaces, net of 9.5bp/side

| Family | Cells | Median | IQR | Range | Positive |
|---|---:|---:|---|---|---:|
| Momentum (lookback × hold) | 24 | **0.63** | 0.41–0.88 | −0.12 … **1.07** | 23/24 |
| Factor-residual (factors × entry × window) | 30 | **0.57** | 0.37–0.84 | −0.08 … **1.04** | 29/30 |

Both published legs sit at the very top of a distribution whose middle is around 0.6. That is
selection you could not have performed in advance, and it is the same error
`FAST_BOOK_TEST.md` documented for the fast book — where the best config ran 1.09 and the
portfolio you could actually hold ran 0.11.

**So every leg below is the equal-weight average of its whole grid**, which is the book you
could have held without knowing the winner. The best-cell version is kept only to price the
premium.

---

## 2. The combination — the result

Honest legs, common window **2023-09-27 → 2026-08-30, n = 1,069**, net of 9.5bp/side.

| Book | Sharpe | Vol | **MaxDD** | DD @15% | Calmar @15% |
|---|---:|---:|---:|---:|---:|
| momentum (24-cell ensemble) | 0.906 | 15.6% | −12.90% | −12.46% | 1.066 |
| resid_mom (30-cell ensemble) | 0.892 | 14.0% | −14.61% | −15.61% | 0.835 |
| **50/50 of the two** | **1.335** | **9.95%** | **−11.57%** | −17.03% | **1.221** |

Correlation between the legs on this window: **−0.095** (−0.092 over the full
1,190-day leg history). The 1.34 is close to the arithmetic two uncorrelated
books of this size predict, so the lift is diversification and not a fitted result.

### The two readings of "drawdown", which is where the question actually lives

**At natural size — what you run.** The combination improves *both* axes: drawdown −12.9% →
−11.6%, Sharpe 0.91 → 1.34. This is the answer to "highest Sharpe with lowest drawdown".

**At matched 15% risk — Rule 1.** The combination's drawdown is *deeper*: −12.5% → −17.0%.
Nothing contradictory: the pair's natural vol is 9.95%, so matching 15% levers it 1.5×, and
drawdown scales with size.

The useful way to hold both facts at once: **at matched risk, drawdown and Sharpe are nearly
the same objective.** Size is the drawdown dial and it is free. Diversification is the Sharpe
dial and it is the only one that is not free. So "lowest drawdown for the Sharpe" reduces to
"raise Sharpe, then choose size" — and the timing overlays in the previous study failed
precisely because they moved size while claiming to move shape.

---

## 3. 1/N beats every optimiser

All weights causal: estimated on a trailing 120 days, lagged one day, long-only, shrunk
covariance. Ranked by equal-risk Calmar.

| Books | Allocator | Sharpe | MaxDD | DD @15% | **Calmar @15%** | mean w |
|---|---|---:|---:|---:|---:|---|
| mom+resid | **equal weight (1/N)** | **1.335** | −11.57% | −17.03% | **1.221** | .50/.50 |
| mom+resid | risk parity (ERC) | 1.326 | −11.86% | −17.52% | 1.178 | .47/.53 |
| mom+resid | inverse vol | 1.326 | −11.86% | −17.52% | 1.178 | .47/.53 |
| mom+resid | max diversification | 1.326 | −11.86% | −17.52% | 1.178 | .47/.53 |
| mom+resid | min variance | 1.308 | −12.13% | −17.86% | 1.138 | .45/.56 |
| mom+resid | trailing max-Sharpe | 1.072 | −12.25% | −14.65% | 1.100 | .54/.46 |
| — | *[single] momentum* | 0.906 | −12.90% | −12.46% | 1.066 | — |
| mom+resid+fast | min variance | 1.110 | −9.70% | −17.47% | 0.961 | .41/.39/.20 |
| mom+resid+fast | risk parity (ERC) | 1.004 | −9.98% | −17.91% | 0.835 | .39/.36/.24 |
| mom+resid+fast | inverse vol | 0.967 | −9.84% | −17.52% | 0.817 | .36/.41/.23 |
| mom+resid+fast | trailing max-Sharpe | 0.946 | −17.87% | −21.23% | 0.658 | .39/.38/.23 |
| mom+resid+fast | equal weight (1/N) | 0.669 | −14.42% | −23.42% | 0.398 | ⅓ each |
| — | *[single] fast_rev* | −0.354 | −54.33% | −37.55% | −0.166 | — |

Two readings:

1. **Nothing beats 1/N.** With two books, three years and noisy estimates, every optimiser
   spends its degrees of freedom on estimation error. The three covariance-only rules
   (inverse vol, ERC, max diversification) land on the same .47/.53 and the same 1.178.
   Trailing max-Sharpe — the obvious thing to reach for — is the worst of the two-book set.
2. **Estimating weights is not where the drawdown is.** The spread from best to worst
   allocator *within* the two-book set is 1.221 → 1.100. The spread from one book to two is
   1.066 → 1.221 on Calmar and 0.91 → 1.34 on Sharpe. The book count is the lever; the weight
   rule is a rounding error.

---

## 4. A negatively-correlated book with a negative edge does not pay for itself

`fast_rev` looks like the ideal diversifier — correlation **−0.405** to momentum. It is not.
Every three-book variant scores below every two-book variant on Calmar, and the split halves
are the tell:

| Book set, 1/N | H1 Sharpe | H2 Sharpe |
|---|---:|---:|
| mom+resid | 1.223 | **1.477** |
| mom+resid+fast | 1.612 | **−0.445** |

Adding it buys a shallower raw drawdown (−9.7% vs −11.6% for min variance) purely by cutting
portfolio vol to 8.0%, which Rule 1 exists to see through: at matched risk it is −17.5% against
the pair's −17.0%, on a lower Sharpe.

---

## 5. Crude as a diversifier — and why §7.4 of the previous file is wrong

Crude is genuinely uncorrelated with the crypto book: **+0.035** (unhedged CL) and **+0.036**
(CL/BRENT hedged). By the correlation argument alone it should help.

| Blend (hedged crude) | Sharpe | DD @15% | Calmar @15% |
|---|---:|---:|---:|
| 100/0 | 1.454 | −6.77% | 3.395 |
| 80/20 | 1.743 | −6.92% | 4.107 |
| **70/30** | 1.736 | **−6.64%** | **4.262** |
| 50/50 | 1.524 | −6.74% | 3.606 |

That looks like a confirmation. It is not, for two reasons.

**The window is selected to contain crude's edge.** The hedged overlap starts 5 March 2026, and
`CRUDE_OIL_DRAWDOWN.md` §2 established that the hedged book's entire positive result is March
plus three days of April. Most of the Sharpe gain above is crude's own return over the one
stretch it had one.

**With crude demeaned, the optimal weight is zero.** Setting crude's mean return to zero leaves
only its volatility and its correlation — pure diversification, no edge:

| Blend, crude DEMEANED | Sharpe | DD @15% | Calmar @15% |
|---|---:|---:|---:|
| **100/0** | **1.454** | **−6.77%** | **3.395** |
| 90/10 | 1.402 | −7.07% | 3.118 |
| 80/20 | 1.260 | −7.18% | 2.710 |
| 50/50 | 0.602 | −7.86% | 1.048 |

Every positive weight lowers Sharpe *and* deepens drawdown at matched risk. The unhedged CL
version is worse still (−6.8% → −9.3% at a 10% weight).

**So the claim "it does not require the edge to be real in any one of them" is false.** Adding
book B to book A raises the Sharpe only when `SR_B > SR_A × ρ`. At ρ ≈ 0.035 that hurdle is
near zero — but "near zero" is a hurdle a zero-edge book fails, and crude's higher volatility
(18% hedged against the crypto book's 8.3%) means each unit of weight adds more risk than
correlation removes. Correlation buys the *arithmetic*; it does not supply the numerator.

The mom+resid pair works because both legs have positive expected return **and** are
uncorrelated. Only the conjunction does anything.

---

## 6. Stress battery

Nine tests on the honest 50/50, each able to kill it alone.

### 6.1 The drawdown is a single draw — 4,000 stationary bootstrap paths, mean block 20d

| | Sharpe p5 | Sharpe p50 | Sharpe p95 | P(SR≤0) | DD obs | DD median | **DD worst-5%** | DD worst-1% |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| momentum | 0.16 | 0.92 | 1.69 | 2.4% | −12.5% | −13.7% | −22.7% | −28.7% |
| resid_mom | 0.04 | 0.89 | 1.67 | 4.5% | −15.6% | −14.5% | −25.3% | −31.6% |
| **50/50** | **0.29** | **1.31** | **2.31** | **2.0%** | −17.0% | −16.5% | **−27.5%** | −33.6% |

Resampling the two legs *jointly* at fixed weights — which preserves the cross-correlation
rather than assuming it — gives the same answer: Sharpe p5 0.32 / p50 1.36 / p95 2.34,
drawdown median −16.4%, worst-5% **−26.7%**.

**The −11.6% that happened is not a risk number.** Plan on −27%.

*(Drawdowns are negative, so the bad tail is the LOW percentile. An earlier version of this
table reported the p95 and made a −27% tail read as −9%.)*

### 6.2 Cost — the line that killed 12 of the project's 30 strategies

| bp/side | 0 | 4.5 (taker) | 9.5 (assumed) | 15 | 20 | 30 |
|---|---:|---:|---:|---:|---:|---:|
| Sharpe | 1.743 | 1.549 | **1.335** | 1.099 | 0.884 | 0.455 |
| Ann. | +18.3% | +16.1% | +13.6% | +11.0% | +8.7% | +4.1% |

Turnover is **0.090/day** (momentum) and **0.144/day** (residual). **Breakeven is 40.75 bp per
side** against a 9.5bp assumption, a 4.5bp taker fee and a ~3bp posted fee.

This is the first result in the project with real headroom on cost. Every earlier idea died in
the 0–5bp band; this one survives 4×. It also means the unresolved maker/taker question —
"the highest-value open item" in `README.md` — **does not decide this book**. It moves it from
1.55 to 1.34, not from alive to dead.

*(The portfolio turnover used here is the sum across legs, which ignores positions the two
books hold in opposite directions and net out. True turnover is lower, so this is the
conservative direction.)*

### 6.3 Deflated Sharpe — it does not clear the bar

| | DSR@30 | DSR@60 | DSR@100 | DSR@200 |
|---|---:|---:|---:|---:|
| 50/50 portfolio | **0.580** | 0.472 | 0.399 | 0.312 |
| momentum alone | 0.295 | 0.209 | 0.159 | 0.109 |
| resid_mom alone | 0.291 | 0.206 | 0.157 | 0.107 |

The bar is 0.95. Combination roughly doubles the legs' DSR — the same mechanism
`SURVIVORS_RECHECK.md` measured — but from 0.29 to 0.58, not over the line. Note this is
*lower* than that file's 0.710, because it is computed on honest legs rather than best cells.
At the realistic trial count for this project (38 ideas + 54 cells + 6 allocators, so
100–200), it is **0.31–0.40**.

**This is the binding constraint, and no analysis of the existing panel fixes it. The sample
is the constraint.**

### 6.4 Tail correlation — the diversification is not fair-weather

Conditioned on **external** stress from the price panel, never on the books' own composite.

| Stressor, worst decile | corr, all days | calm | **stressed** |
|---|---:|---:|---:|
| BTC return | −0.095 | −0.086 | **−0.163** |
| panel median \|return\| (vol proxy) | −0.095 | −0.100 | **−0.070** |

Stable, with a mild improvement under BTC stress. The direct check, free of any conditioning
artefact:

| On the worst decile of… | the other book returns | unconditionally |
|---|---:|---:|
| momentum's worst days | resid_mom **+19.1 bp** | +3.4 bp |
| resid_mom's worst days | momentum **+8.4 bp** | +3.9 bp |

Each book earns *more* than its average on the other's worst days. That is what makes this a
drawdown tool rather than an averaging artefact.

*(A first version of this test conditioned on the books' own equal-weight composite and
reported −0.80 against a full-sample −0.10. That is a collider: selecting days where a sum is
extreme mechanically induces negative correlation between its addends. The stressor has to be
exogenous.)*

### 6.5 Weight perturbation — 1,000 Dirichlet draws, concentration 20

Sharpe p5 **1.22** / p50 1.32 · drawdown @15% median −17.0%, worst-5% −17.7% · Calmar p5 1.11.
The result is a property of holding both books, not of holding them 50/50.

### 6.6 Stability

Rolling 252-day Sharpe: min **−0.75**, p25 0.36, median 0.94, p75 1.60, max 2.45.
**11.5% of rolling years are negative.**

| Year | Days | Sharpe | Return | MaxDD |
|---|---:|---:|---:|---:|
| 2023 | 96 | 4.62 | +13.3% | −2.8% |
| 2024 | 366 | **0.50** | +4.8% | −11.6% |
| 2025 | 365 | 1.32 | +13.8% | −8.1% |
| 2026 | 242 | 1.36 | +7.7% | −3.8% |

Split halves **1.22 → 1.48**. Like the published version, it is improving rather than decaying
— still the only thing in this project that does.

### 6.7 Worst contiguous windows, at 15% vol

| 1 month | 3 months | 6 months | 12 months | Longest underwater |
|---:|---:|---:|---:|---:|
| −11.2% | −12.6% | −11.0% | −3.5% | **296 days** |

**Ten months underwater** is the number that decides whether this is holdable, and it is a
harder constraint than the drawdown depth.

### 6.8 Was the realised path lucky?

Observed drawdown @15% −17.0%, against an iid normal null with the same mean and sigma: median
−14.6%, worst-5% −25.4%. The realised path is **deeper than 68% of iid paths** — mildly
unlucky, not flattering. Skew −0.06, excess kurtosis **+0.90**: fat-tailed, so the iid null
understates the true tail and §6.1's bootstrap is the better guide.

---

## 7. Capacity — how much capital, and is it feasible

Percentages do not decide whether this is worth running; a floor and a ceiling do. Both are
measured from the rebuilt ensemble **position** matrices, not from a rule of thumb
(`capacity.py`, `capacity_floor.py`). Venue minimum order value **$10**, confirmed against
Hyperliquid's contract specifications. FX at **GBP/USD 1.3380** (21 Sep 2026).

### 7.1 The liquidity floor is the lever, and it is nearly free

The book's capacity is not set by the book — it is set by a handful of illiquid names. At
$250k eligibility the median participation at $1m AUM is 0.026% while the worst coin on the
worst day is 29%. Raising the eligibility floor trades cross-section for capacity:

| min_dv | Sharpe | Ann. | MaxDD | leg corr | coins held | **1% capacity** | 5% capacity |
|---|---:|---:|---:|---:|---:|---:|---:|
| $250,000 | 1.335 | +13.6% | −11.6% | −0.095 | 90 | $196,815 | $984,073 |
| **$1,000,000** | **1.472** | **+16.2%** | −12.1% | −0.090 | 60 | **$445,301** | $2,226,506 |
| $5,000,000 | 0.754 | +6.6% | −10.1% | **+0.005** | 28 | $2,060,474 | $10,302,368 |

**The capacity gain is arithmetic, not a fitted return** — holding 60 larger coins instead of
90 smaller ones raises the participation ceiling by construction, whether or not the edge is
real. The Sharpe *improvement* is not claimed: 1.335 → 1.472 against a standard error of ~0.80
is noise, and picking $1m out of three floors is the same best-of-grid selection §1 is about.
The defensible statement is **capacity roughly doubles at no measurable Sharpe cost**.

The $5m row fails for a reason worth keeping: with only 28 coins the leg correlation goes
to **+0.005**. There is no longer enough cross-section for the two books to be different
trades, and the diversification that the whole result rests on disappears. **The edge needs
breadth, so capacity cannot be bought indefinitely.**

### 7.2 The band, at min_dv $1m

| | USD | GBP |
|---|---:|---:|
| Floor — median trade clears $10 | $14,106 | £10,543 |
| **Floor — 75% of trades clear $10** | **$37,654** | **£28,143** |
| Floor — 95% of trades clear $10 | $211,200 | £157,853 |
| **Ceiling — 1% of volume** | **$445,301** | **£332,823** |
| Ceiling — 5% of volume | $2,226,506 | £1,664,114 |

**Usable band ≈ $37.7k – $445k (£28k – £333k), a factor of 11.8.** At the $250k floor it was
$55k – $197k, a factor of 3.6.

Second floor, overheads: at 16.2%/yr net, $6k/yr of fixed cost needs $37k of capital to break
even, $12k/yr needs $74k. Note the book holds ~60 coins and trades ~59 of them per day, so
"fixed cost" here is real infrastructure, not a spreadsheet.

### 7.3 What it earns, both currencies

| Capital | Net/yr (central) | Per month | **At the bootstrap-p5 haircut** | Planning DD −27.5% |
|---|---:|---:|---:|---:|
| $50k · £37k | $8,080 · £6,039 | $673 · £503 | $1,745 · £1,304 | −$13,750 · −£10,277 |
| $100k · £75k | $16,160 · £12,078 | $1,347 · £1,007 | $3,491 · £2,609 | −$27,500 · −£20,554 |
| $200k · £149k | $32,320 · £24,156 | $2,693 · £2,013 | $6,981 · £5,218 | −$55,000 · −£41,108 |
| $445k · £333k | $71,912 · £53,748 | $5,993 · £4,479 | $15,533 · £11,610 | −$122,375 · −£91,464 |

The p5 column applies the ratio (0.216) between the bootstrap 5th-percentile Sharpe and the
observed one, measured on the $250k book in §6.1. The $1m variant has **not** been
bootstrapped; that column is a scaling, not a measurement.

### 7.4 Verdict

**Technically feasible.** $37.7k–$445k is ordinary money, and the band is now wide enough to
matter. The constraint is not access to capital.

**Economically marginal, for one reason.** At DSR 0.58 the book cannot be distinguished from
a much weaker one, and the two worlds look completely different in cash: **$16,160 a year on
$100k if the backtest is right, $3,491 if you are at the 5th percentile** — the latter below
the cost of running 59 orders a day. The spread between those two numbers, not the capital
requirement, is what makes this hard to size.

**So the capital question has a clean answer and it is not the binding one.** Around
**$150k–$300k (£112k–£224k)** sits comfortably inside the band and earns $24k–48k (£18k–36k)
a year if the edge is real, against a −£41k to −£62k planning drawdown and up to ten months
underwater. Whether to commit that is a question about DSR 0.58, and DSR 0.58 is only movable
by live data.

---

## 8. What to do

1. **Hold both books at 1/N. Do not optimise the weights.** Two books, equal weight, rebalanced
   on whatever schedule is convenient. Every optimiser tested loses to this, and weight
   perturbation shows the result does not depend on the split.
2. **Quote 1.34, not 1.57 or 1.75.** The published 1.57 is unreproducible; regenerating the
   best cells gives 1.75; the holdable ensemble gives **1.335**. The ~0.4 Sharpe gap between
   the ensemble and the best cells is the selection premium, and it is not yours.
3. **Size to a −27% drawdown, not −11.6%.** And budget for **ten months underwater**.
4. **Stop looking for a drawdown rule.** Between this file and `CRUDE_OIL_DRAWDOWN.md`, the
   following have now been rejected at equal risk: vol targeting, trend filters, carry filters,
   drawdown control, hedge-ratio choice, five portfolio optimisers, and adding an uncorrelated
   zero-edge book. The only thing that worked was holding a second book with its own edge.
5. **A third book must clear `SR > SR_portfolio × ρ` on its own.** With the pair at 1.34, even
   a near-zero correlation candidate needs real standalone expectancy. Correlation alone is not
   a reason to add anything — that is §5's whole finding.
6. **The DSR gap is not closable from this panel.** 0.58 against 0.95 needs roughly t 3.3–3.5,
   about two more years at this rate, or genuine live out-of-sample. Which points at the same
   item everything else points at: **restart the paper harness.** It has run for one day since
   1 September.

---

## 9. What would kill this

- **The legs are two views of one effect.** Both are cross-sectional momentum on the same 157-
  coin panel; one hedges against peers by rank, the other against principal components. The
  −0.09 correlation is measured, not structural, and there is no mechanism guaranteeing it
  stays there. Holding the legs' own means and vols fixed and moving only the correlation:
  ρ = 0 gives 1.27, ρ = +0.2 gives 1.16, **ρ = +0.4 gives 1.07** — most of the case goes with it.
- **2024 was Sharpe 0.50.** One year in four at half the headline, and 11.5% of rolling years
  negative. A repeat of 2024 is inside the distribution, not outside it.
- **The panel is 157 coins over four years, reused for ~38 ideas.** DSR is the honest summary
  and it says 0.31–0.58. This is the best thing in the project and it is still not established.
- **`fast_rev` and `factor_residual_daily.csv` remain unreproduced.** The first is a stored
  series from a 4h engine with no turnover data, so it cannot enter a cost sweep; the second
  does not match its own script at any tested cell. Neither is used in the recommendation, but
  neither should be quoted either until regenerated.
