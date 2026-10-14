# Insider clusters & point-in-time FAST reactors — backtest

**2026-10-14.** Two new tests on the existing insider data, plus a momentum-ETF
benchmark. Code: `cluster_and_fast.py`. Raw output: `data/cluster_fast/results.json`,
plot: `data/cluster_fast/oos_vs_momentum_etf.png`. **Research only; not investment
advice.**

## 0. Kill numbers (read first)

- **#1 clusters — NOT promoted.** Primary cell (≥2 distinct insiders within 30d,
  each ≥₹10L, hold 20d): net **+2.74%**/trade but **fails FDR** (placebo p=0.048 vs
  BH threshold 0.0438); random-entry Sharpe p=0.396. The wider-window variant (90d)
  is stronger (jitter p=0.008) but is a second look at the same idea.
- **#2 FAST reactors — best insider result so far, still not tradeable.** Net
  **+1.07%**/3-day trade, beats **both** controls (random p=0.000; date-jitter
  p=0.000, p(Sharpe)=0.004), OOS +1.75% (n=134). **But at the small-account cost
  (75 bp) the edge falls to +0.59%**, and the book is only **0.8% invested** on
  average → ~0.5%/yr on capital, far below simply holding Nifty.
- **vs momentum ETFs:** neither strategy is a substitute for buy-and-hold. Over
  2022-08→2026-10 the cluster book made **+3.5% total vs +40.8% for the ABSL
  Nifty200 Momentum 30 ETF**; over 2010→2026 **+12% vs +330% for Nifty** — because
  the strategies sit in cash ~98% of the time. Their Sharpe (0.56–0.60) is
  comparable to the ETF/Nifty (0.53/0.62) but that is a cash-dilution artifact.

## 1. Method (what this tests and how)

- **Universe:** 215 current-ticker NSE stocks with cached adjusted OHLC
  (`data/bt_prices/`). 7,819 major market-purchase events have prices.
  **Survivorship bias is unresolved** (only today's tickers).
- **Events:** promoter / promoter-group / director / KMP, `Market Purchase`, equity,
  **point-in-time disclosure date** (`disclose_ts`), never the trade date.
- **Execution:** buy next session's **open** after the signal; exit at **close H
  sessions later** (no intrabar stop, so no stop-fill trap). Cost **27 bp** round
  trip (repo delivery reference); **75 bp** shown as the small-account reality.
- **Controls (decisive):**
  1. *Random-entry placebo* — same count of entries per stock, random dates.
  2. *Date-jitter placebo* — same stock, timing shifted ±20 sessions. This removes
     "the stock/period was simply good" and isolates the insider **date**.
  3. **BH-FDR** over the 8 configurations tested.
- **Split:** 2023-07-05 (70/30). Portfolio Sharpe from equal-weight daily sleeves
  (overlapping trades allowed); non-overlapping trade count also reported.

## 2. #1 Insiders clustering

Signal = a disclosure that completes ≥K **distinct** insiders buying the same stock
within W calendar days (singletons excluded). Deduplicated so a cluster yields one
signal.

| config (hold 20d) | n | net/trade | median | win | Sharpe | OOS n / mean | random p (mean/Sh) | jitter p (mean/Sh) |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| W30, K2, ≥₹10L (**primary**) | 508 | **+2.74%** | +0.94% | 0.54 | 0.56 | 122 / +2.55% | 0.048 / 0.396 | 0.044 / 0.092 |
| W30, K2, ≥₹0 | 695 | +3.01% | +0.97% | 0.54 | 0.65 | 175 / +1.80% | 0.012 / 0.228 | 0.008 / 0.008 |
| W90, K2, ≥₹10L | 520 | +3.08% | +1.17% | 0.54 | 0.64 | 119 / +2.64% | 0.004 / 0.208 | 0.008 / 0.024 |
| W30, K3, ≥₹10L | 206 | +2.43% | +0.82% | 0.54 | 0.34 | 54 / +1.99% | 0.180 / 0.528 | 0.044 / 0.124 |

- The effect is **positive and roughly consistent**, but the **primary cell fails
  FDR**. Requiring *more* insiders (K3) makes it *weaker* — the opposite of the
  literature's cluster prediction, which is a warning sign.
- Exposure 1.7–2.5% of the book. At 75 bp the primary mean is +2.26% (still > cost),
  so the per-trade edge clears the toll; the problem is significance and frequency,
  not cost.

## 3. #2 Point-in-time FAST reactors

A stock is armed only if its **own prior** qualifying purchases (whose 5-session
outcome was already public before the current disclosure) reacted fast (≥+3% excess
in 5 sessions) at least `fast_frac` of the time over ≥`min_history` events. Then any
qualifying purchase → next open → exit at close 3 sessions later. **No look-ahead**
(the classifier's outcome window must close before the next signal).

| config (hold 3d) | n | net/trade | median | win | Sharpe | OOS n / mean | random p (mean/Sh) | jitter p (mean/Sh) |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| frac≥0.5, n≥3 | 375 | +0.78% | +0.63% | 0.54 | 0.38 | 68 / +1.21% | 0.004 / 0.024 | 0.008 / 0.016 |
| frac≥0.5, n≥2 | 641 | **+1.07%** | +0.76% | 0.56 | 0.60 | 134 / +1.75% | 0.000 / 0.000 | 0.000 / 0.004 |
| frac≥0.34, n≥2 | 1574 | +0.79% | +0.23% | 0.52 | 0.62 | 294 / +1.76% | 0.000 / 0.000 | 0.000 / 0.000 |

- This is the **most robust insider result in the repo so far**: it beats the
  random-date control *and* the ±20-session jitter control, and holds in the
  untouched 2023-07→2026-10 period (n=134, +1.75%).
- **Kill caveats:** per-trade edge is small (+1.07%); at 75 bp it is **+0.59%**;
  historical **spread is unmeasured** (thin small caps could erase it); survivorship
  remains; and the classifier may be selecting **momentum/volatility**, not insider
  information (the jitter control uses the *same* stocks, so it tests *timing* only,
  not whether the stock-selection is information).

## 4. Momentum-ETF comparison

Momentum ETFs benchmarked (buy-and-hold, close-to-close): `MOM30_ABSL`
(2022-08+), `MOM30_HDFC` (2023-10+), `MOM30_MO` (2025-03+), `MOM50_MO` (2024-09+),
plus `NIFTY`. **Data repair:** `HDFCMOMENT` had a bad listing print (₹233 → ₹23 on
2023-10-20, a −90% one-day jump); the un-repaired series gave a fake **−87%** total.
`repair_level_shift()` rescales the level break; corrected total is −4.6%
(AGENTS.md split/print trap).

| window | cluster book | fast book | BEST ETF / Nifty |
|---|---|---|---|
| 2022-08→2026-10 | +3.5% (Sharpe 0.81) | +3.7% (Sharpe 0.88) | MOM30_ABSL +40.8% (Sharpe 0.53) |
| 2010/2022→2026-10 | +12.3% | +8.5% | NIFTY +330% (Sharpe 0.62) |

The strategies have a decent **Sharpe** but a **guaranteed low absolute return**
because they are ~cash (1% vol). They are **overlays, not alternatives** to a
momentum ETF.

## 5. Verdict

- **FAST reactors:** keep as the single most promising insider lead; next step is a
  **survivorship-free bhavcopy** price set + **measured historical spread**, and a
  test of whether the edge survives when the FAST classifier is replaced by a plain
  momentum/volatility filter (to prove the insider dates add anything).
- **Clusters:** not promoted (primary cell fails FDR; more insiders did not help).
  Record as a weak/negative result.
- Neither beats simply holding a Nifty200 Momentum 30 ETF or Nifty on rupees; both
  are near-cash. This is consistent with the repo's standing finding: the insider
  signal, if anything, carries a small amount of information at best.

## 6. Reproduce

```bash
cd strategy_categories/could_work/india_insider_drift
/…/volume_indicator_studies/.venv/bin/python cluster_and_fast.py
# -> data/cluster_fast/results.json, data/cluster_fast/oos_vs_momentum_etf.png
```

*Research only; not investment advice.*
