# Crude oil on Hyperliquid — full performance statistics

**Run 21 September 2026.** Source: Hyperliquid `POST /info` — `candleSnapshot` (daily) and
paginated `fundingHistory`, `xyz:CL` (WTI) and `xyz:BRENTOIL`.
CL: 258 closed daily bars, 2026-01-06 → 2026-09-20. BRENT: 201 bars, 2026-03-04 → 2026-09-20.
The still-forming current bar is dropped. Funding convention: positive rate = longs pay shorts,
so carry to a long is `-rate`, summed hourly into UTC days.

*Reproduce:* `.venv/bin/python backtesting/hyperliquid/hip3/oil_stats.py`
(data snapshot cached in `hip3/.cache/px_*.csv`, `fund_*.csv`).

**Verdict: every Sharpe here is indistinguishable from zero at this sample size, and the one
number with a real t-stat — the carry — is 40% of the days and reverses sign between halves.**

---

## 1. Headline table

| Strategy | Days | Total | Ann. | Vol | **Sharpe** | Sortino | **Max DD** | DD len | Calmar | Hit |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| CL long — price only | 257 | +68.5% | +109.8% | 66.9% | 1.45 | 1.85 | **−40.1%** | 168d | 2.74 | 54.5% |
| **CL long — price + carry** | 257 | +91.3% | +151.2% | 66.1% | **1.73** | 2.23 | **−33.9%** | 133d | 4.46 | 55.3% |
| CL long — carry only | 258 | +12.9% | +18.8% | 4.5% | 3.86 | 12.54 | −4.0% | 91d | 4.76 | 39.5% |
| BRENT long — price only | 200 | +20.3% | +40.1% | 66.3% | 0.84 | 1.05 | −37.5% | 139d | 1.07 | 55.5% |
| BRENT long — price + carry | 200 | +36.4% | +76.2% | 65.4% | 1.20 | 1.49 | −36.0% | 128d | 2.12 | 56.0% |
| BRENT long — carry only | 201 | +12.9% | +24.7% | 4.5% | 4.97 | 13.66 | −1.4% | 56d | 17.90 | 41.3% |
| CL/BRENT 1:1 — price only | 200 | +6.6% | +12.3% | 17.2% | 0.76 | 1.18 | −10.2% | 171d | 1.21 | 52.0% |
| **CL/BRENT 1:1 — price + carry** | 200 | +10.4% | +19.7% | 17.3% | **1.13** | 1.84 | **−8.4%** | 167d | 2.36 | 49.0% |
| CL/BRENT 1:1 — carry only | 200 | +3.6% | +6.6% | 1.7% | 3.84 | 6.13 | −1.9% | 53d | 3.42 | 58.0% |
| CL/BRENT β=1.07 — price + carry | 200 | +7.0% | +13.2% | 16.6% | 0.83 | 1.30 | −9.6% | 162d | 1.37 | 49.5% |

Annualised at 365 days — these perps trade continuously; the bar count equals the calendar span.
Fees are **not** in this table; they are isolated in §4. β=1.07 is fitted on the same 200 days
it is scored on, which is look-ahead — it is shown only to prove the fitted hedge is *worse*
than the naive 1:1.

### Tail statistics

| Strategy | Worst day | Best day | Skew | Ex. kurt | VaR₉₅ | CVaR₉₅ |
|---|---:|---:|---:|---:|---:|---:|
| CL long — price + carry | **−18.3%** | +13.5% | −0.34 | 5.78 | −4.63% | −7.95% |
| BRENT long — price + carry | −15.4% | +12.5% | −0.55 | 3.89 | −5.25% | −8.33% |
| CL/BRENT 1:1 — price + carry | −2.96% | +5.54% | +1.76 | 11.92 | −1.20% | −1.85% |

Both outrights are left-tailed with fat kurtosis: a −18% day on a 66% vol asset. The hedged
book flips the skew positive but keeps kurtosis 12 — the hedge fails in bursts, not smoothly.

---

## 2. Every Sharpe fails its own t-test

Lo (2002) iid standard error, `SE = sqrt((1 + SR²/2)/n)`:

| Strategy | Sharpe | ±SE | t | 95% CI |
|---|---:|---:|---:|---|
| CL long — price + carry | 1.73 | 1.19 | 1.45 | [−0.61, 4.07] |
| CL long — price only | 1.45 | 1.19 | 1.21 | [−0.89, 3.78] |
| BRENT long — price + carry | 1.20 | 1.35 | 0.88 | [−1.45, 3.85] |
| CL/BRENT 1:1 — price + carry | 1.13 | 1.35 | 0.83 | [−1.52, 3.78] |
| CL/BRENT β=1.07 — price + carry | 0.83 | 1.35 | 0.61 | [−1.82, 3.48] |
| CL long — carry only | 3.86 | 1.20 | **3.22** | [1.51, 6.22] |
| CL/BRENT 1:1 — carry only | 3.84 | 1.36 | **2.81** | [1.16, 6.51] |

**Not one price-bearing strategy clears t=2.** Eight to nine months at 66% vol cannot resolve a
Sharpe of 1.7 from a Sharpe of 0. The only t-stats above 2 are the carry-only lines, and a
carry-only Sharpe is not a tradable Sharpe — it is the Sharpe of an accrual you cannot hold
without also holding the price risk in the rows above it.

---

## 3. Split-half stability — where it breaks

| Strategy | Full | H1 | H2 |
|---|---:|---:|---:|
| CL long — price + carry | 1.73 | 2.62 | **0.47** |
| CL long — price only | 1.45 | 2.35 | **0.13** |
| BRENT long — price + carry | 1.20 | 0.84 | 1.89 |
| CL/BRENT 1:1 — price + carry | 1.13 | 1.99 | **−0.78** |
| CL/BRENT 1:1 — carry only | 3.84 | 9.66 | **−5.76** |
| CL long — carry only | 3.86 | 3.19 | 5.45 |

The hedged book's carry — the one line the crude thesis rests on — goes **+9.66 → −5.76**.
The entire hedged edge was earned in the first hundred days.

---

## 4. The hedged book, decomposed

200 overlapping days, long `xyz:CL` / short `xyz:BRENTOIL`, 1:1 notional:

| Component | 6.5 months |
|---|---:|
| **Price** (WTI–Brent spread moved our way) | **+7.16%** |
| **Carry** (what the strategy claims to harvest) | +3.52% |
| Fees, held throughout (1 round trip × 2 HIP-3 legs @ 9bp) | −0.36% |
| **Net** | **+10.31%** |

**69% of the return is a directional bet on the WTI–Brent spread**, not carry.

Turnover decides the outcome, not the signal:

| Rebalance | Fees | Net |
|---|---:|---:|
| Hold throughout | 0.36% | **+10.31%** |
| Monthly | 2.40% | +8.27% |
| **Weekly** | **10.29%** | **+0.39%** |
| Daily | 72.00% | −61.33% |

Weekly rebalancing consumes the whole edge. Same wall every other item in this log hit.

### Hedge diagnostics

| | |
|---|---:|
| corr(CL, BRENT) daily returns | **0.9741** |
| CL daily vol | 3.82% (73.1% ann) |
| BRENT daily vol | 3.47% (66.3% ann) |
| 1:1 spread vol | 0.90% (17.2% ann) — **76.4% vol cut** |
| β-fitted spread vol (β=1.07) | 0.87% (16.5% ann) |
| Carry to long CL | **+0.0787%/day (28.7%/yr)** |
| Carry to long BRENT | +0.0612%/day (22.3%/yr) |
| Carry, long CL / short BRENT | **+0.0176%/day (6.4%/yr)** |
| Price risk ÷ daily carry, unhedged | **48.6×** |
| Price risk ÷ daily carry, hedged | **51.3×** |

The hedge cuts vol by 76% but cuts carry by 78%, so the risk-per-unit-of-carry is
*unchanged* — marginally worse. That is the single most important line in this document.
Hedging crude on this venue buys smaller numbers, not a better ratio.

---

## 5. The carry is episodic, and it has a regime

Long `xyz:CL`, 258 days, total carry **+12.25%**:

| | |
|---|---:|
| best 1 day | +1.42% (12% of total) |
| best 5 days | +5.66% (**46% of total**) |
| best 10 days | +9.44% (**77% of total**) |
| best 20 days | +14.86% (**121% of total** — the other 238 days are net negative) |
| days paying a long at all | **102 of 258 (40%)** |

Monthly (%):

| Month | CL px+carry | CL carry | CL/BR px+carry | CL/BR carry |
|---|---:|---:|---:|---:|
| 2026-01 | +12.43 | **−1.87** | — | — |
| 2026-02 | +7.21 | **−1.43** | — | — |
| 2026-03 | +43.08 | **−0.25** | +8.07 | +0.76 |
| 2026-04 | +11.56 | +6.72 | −0.06 | +2.48 |
| 2026-05 | −12.30 | +3.47 | +2.27 | +1.03 |
| 2026-06 | −20.65 | +1.14 | +0.52 | +1.01 |
| 2026-07 | +24.03 | −0.41 | +0.77 | +0.06 |
| 2026-08 | −0.07 | +1.00 | −2.37 | −1.31 |
| 2026-09 | +15.25 | +4.20 | +1.04 | −0.47 |

**New finding versus `CRUDE_CARRY_RECHECK.md`:** that recheck started 20 March and therefore
never saw January–March, when carry to a long CL was **negative in all three months**. The
positive carry regime begins in April. What looks like a yield is one five-month episode,
and the 21 days of it before April point the other way.

---

## 6. Consistency with the 16 September recheck

| | 16 Sep recheck (181d from 20 Mar) | This run (258d from 6 Jan) |
|---|---:|---:|
| Carry to long CL | 0.0898%/day | 0.0787%/day |
| Carry, hedged CL/BRENT | 0.0170%/day | 0.0176%/day |
| corr(CL, BRENT) | 0.976 | 0.974 |
| 1:1 spread ann vol | 14% | 17% |
| Hedged 6-month net | +9.09% | +10.31% |

The recheck replicates. The 0.6%/day claim in `MASTER_V3.md` remains wrong by ~7×.

---

## 7. What these numbers say

1. **Nothing here is statistically established.** Every price-bearing Sharpe has a 95% CI
   straddling zero. A +151%/yr annualised figure on 257 days at 66% vol is a sample artifact
   presented in annual clothing; do not quote it.
2. **Unhedged crude is not investable on these numbers.** 28.7%/yr of carry against 73%/yr of
   price vol, a −40% drawdown that took 168 days to clear, and a −18.3% single day.
3. **The hedge does not improve the ratio.** 76% less vol, 78% less carry, 48.6× → 51.3×
   price-risk-to-carry. It reduces position size, not risk-adjusted return.
4. **Two thirds of the hedged P&L is directional.** +7.16% of +10.31% net is the WTI–Brent
   spread moving favourably. It could as easily have gone the other way.
5. **The honest carry number is ~6.4%/yr gross, ~6.0% after one round trip**, on a spread with
   17% annualised vol of its own — and it came from one half of the sample.
6. **The fitted hedge is worse than the naive one** (Sharpe 0.83 vs 1.13), in-sample. Nothing
   is gained by estimating β.

**Unchanged recommendation from the recheck:** the measurement worth making is
**discount persistence** — whether `xyz:CL` trades at a structural discount to its oracle
because HIP-3 markets are hard to arbitrage — not the funding level. Six to nine months
cannot separate a durable discount from one that closes.

> **Note (21 Sep 2026):** the hedged book's +10.37%/Sharpe 1.13 below is concentrated in
> 5–31 March (+8.07%) and 1–3 April (+4.26%); from 4 April to 20 September it is **−2.04%**
> over 170 days. See `CRUDE_OIL_DRAWDOWN.md` §2. The figures in this file are correct as stated
> for the windows named; the concentration is what the split-half table in §3 was signalling.
