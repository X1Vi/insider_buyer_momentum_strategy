# The fast book, tested out of sample

**16 September 2026.** Built to answer one question: is Mahan's requirement 4
(*"enough trades a day"*) reachable on Hyperliquid, or does the fee schedule
forbid it?

Panel: 4h bars, 147 coins, **45 of them venue-flagged delisted (31%)** — so
survivorship-free. 4,561 bars, Aug 2024 → Aug 2026. Train to 2025-10-31, test
after (10 months, 1,824 bars). Code: `research/fast_vec.py`,
`research/fast_oos_map.py`, `research/fast_top_detail.py`.

**Answer: no — but it is much closer than the earlier work suggested, and it
fails for a different reason than expected.**

---

## The headline

Six best reversal configurations, **test window only**, net Sharpe by execution cost:

| sig / hold | turn/day | gross | @1.5bp | @3.0bp | @4.5bp | DSR@80 |
|---|---:|---:|---:|---:|---:|---:|
| 8h / 4h | 6.58 | **4.30** | 2.69 | **1.09** | −0.52 | 0.072 |
| 8h / 8h | 4.60 | 3.79 | 2.43 | **1.07** | −0.28 | 0.070 |
| 12h / 4h | 5.42 | 3.47 | 2.16 | **0.85** | −0.47 | 0.046 |
| 4h / 8h | 4.58 | 3.01 | 1.43 | −0.16 | −1.74 | 0.005 |
| 4h / 12h | 3.03 | 2.50 | 1.23 | −0.04 | −1.31 | 0.006 |
| 4h / 4h | 9.16 | 2.32 | 0.05 | −2.22 | −4.50 | 0.000 |

1.5bp = maker fee alone. 3.0bp = maker + 1.5bp slippage. 4.5bp = taker.

**Three things to read off this:**

1. **The gross signal is strong and it held out of sample** — 2.3 to 4.3, on
   data the configuration was not chosen on. This is not a weak effect.
2. **The entire P&L lives inside the 0–4.5bp band.** Each 1.5bp of cost removes
   roughly 1.6 of Sharpe. At taker fees every configuration loses.
3. **The deflated Sharpe is 0.000–0.072 against a bar of 0.95.** Ten months at
   Sharpe 1.09 is t ≈ 0.99. After 80 trials that is indistinguishable from the
   luckiest draw.

## The result that settles it

Equal-weighting all six top configurations at 3bp — what you would actually hold
if you could not pick the winner in advance:

| | |
|---|---:|
| Sharpe | **0.11** |
| Annual | +0.5% |
| Max drawdown | −14.9% |
| DSR@80 | 0.009 |
| Mean correlation between the six legs | **0.73** |

The legs are near-duplicates, so combining them buys no diversification — it
just averages in the weak ones. **Individual configurations reach Sharpe 1.09 at
3bp; the portfolio you could actually construct reaches 0.11.** The gap between
those two numbers is selection you cannot perform in advance.

---

## Two corrections to earlier work

### 1. My own first pass was wrong, and the error is instructive

I first ranked configurations by "breakeven bp" = mean gross ÷ mean turnover,
reasoning that cost tolerance matters more than raw Sharpe. **That ratio diverges
as turnover approaches zero.** It selected 48h/48h reversal — breakeven 3.43bp,
but only because turnover was 0.76/day, on a gross Sharpe of 0.43. It returned
**−1.17** out of sample and I briefly reported the fast book as dead before costs.

It is not. Ranking by gross Sharpe, the top configurations returned **+2.3 to
+4.3** out of sample. The correct reading is the table above.

### 2. `MASTER.md`'s breakeven is slightly optimistic

It states breakeven at **1.80 bp/side** against a 1.5bp maker fee — *"inside it
by a hair."* Measured on train for the same 4h/4h reversal config: gross Sharpe
1.74 (close to their 1.93) but breakeven **1.49bp** — *outside* the maker fee by
a hair. Out of sample that config nets **+0.05** at 1.5bp, i.e. exactly zero.

The sign of that comparison is the entire argument for pursuing maker execution,
and it flips. The longer-signal configs (8h, 12h) are the ones with real headroom
— breakevens of 3.97–4.19bp — not the fastest one.

---

## What is real and what is not

**Real:** the gross reversal signal at 4–12 hour horizons. It survived a
train/test split it was not fitted on, on a survivorship-free panel.

**Not established:** that it can be traded. Three separate reasons, any one of
which is sufficient:

- **DSR ≤ 0.072.** Ten months of test data cannot distinguish this from the best
  of 80 attempts, and ~30 strategies plus this 44-cell grid is roughly 80.
- **Config selection does not transfer well enough.** Rank correlation between
  train and test is **+0.438** within one direction (the raw +0.619 across all 44
  is inflated — the grid is *exactly* mirror-symmetric, so every `rev` config has
  a `mom` twin that is its negative and the pairs sit on a line through the
  origin). On 22 configurations the standard error on that is ~0.22.
- **The test window flattered reversal.** Reversal mean train +0.29 → mean test
  **+1.34**, with **17 of 22** configurations improving. Nearly the whole family
  got better regardless of rank. That is a regime, not selection skill.

**Requirement 4 verdict:** unreachable as things stand. Not because the fast
signal is absent — it is the strongest signal in the project — but because it
only pays between 0 and ~4bp of cost, and nobody has established that fills are
obtainable in that band.

## The one measurement that would change this

Everything above collapses to: **can we get filled as a maker, and at what
effective cost including adverse selection?**

- At **1.5bp** (perfect maker, no slippage): 14 of 22 reversal configs are
  net-positive out of sample, best 2.69.
- At **3.0bp**: 3 of 6 top configs positive, best 1.09.
- At **4.5bp**: nothing works.

`MASTER.md` already notes the trap — *"you get filled preferentially when you are
wrong"* — so the honest expectation sits between 1.5 and 3.0, exactly where the
result is decided. The single live datapoint is one day at **0.00bp median
slippage** on a small order.

That is the measurement to make, and it requires posting orders and watching, not
more backtesting. It is now the third independent thread to terminate here:
crude carry (weekly rebalancing took +9.09% to +0.19%), the momentum book, and
this.
