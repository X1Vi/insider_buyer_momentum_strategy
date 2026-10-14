# EVERYTHING — India insider-buying strategy (read me first)

**2026-10-13.** One file that contains the whole journey: what we tried, what broke,
what the numbers are, and which files to open. Written in plain language but in full
detail. **Bottom line: no tradeable edge was found.** Research only; not investment
advice.

If you only read one thing, read §0 and §8.

---

## 0. The bottom line (short version)

- **The idea:** when a "big party" (promoter / director / top manager) buys a lot of
  their own company's shares, and the stock is "cheap" (low RSI = in a dip), buy it
  and hold for a few weeks.
- **What we found:** it does **not** make money. After costs, the strategy's Sharpe is
  about **0**, and buying on **random days** in the same stocks does just as well (or
  better). The stocks drift up over the years, so *any* long position earns that
  drift — the insider signal adds nothing on top.
- **Why it looks good on the charts but isn't:** the "dips" the insiders buy are often
  **crashes** (2016-Jan, 2020-COVID). The stock kept falling for the next few weeks, so
  a 20-day hold lost money. On a long chart the price later recovered, which makes the
  markers look clever — but the trade was already closed at a loss.
- **The one thing that helped:** requiring the stock to be **above its 200-day moving
  average** (i.e., buy dips only inside an uptrend). That lifted Sharpe from −0.04 to
  +0.24 and cut the drawdown from −15% to −4%. But that is just **momentum** (buy
  stocks that are already trending up) — it is not the insider signal working, and it
  still didn't beat random entries.

---

## 1. The idea, in plain words

Company insiders (owners/promoters, directors, senior managers) must tell the stock
exchange when they buy or sell their own shares. The theory: insiders know their
company best, so when they buy, the price should rise afterwards — and small stocks
are slow to react, so there is time to profit.

We tested the specific, "de-noised" version:
- Only **major people** (promoter, promoter-group, director, key manager) — not
  employees.
- Only **big trades** (≥ ₹1 crore, sometimes ≥ ₹25 lakh).
- Only when the stock is **in a dip** (RSI below a level, e.g. 35–40).
- **Buy the next day's open**, hold a fixed number of days (5 / 20 / 60), then sell.
- Long-only, cash, no leverage. Costs charged on both buy and sell.

---

## 2. Where the data came from

**Insider disclosures — NSE PIT API (free, no login).**

```
GET https://www.nseindia.com/api/corporates-pit
    ?index=equities&from_date=DD-MM-YYYY&to_date=DD-MM-YYYY&symbol=
```

- The NSE **homepage returns 403** to a script, but the API itself returns **200**
  without any login. No key, no cost.
- Each record has: symbol, company, who bought, their role, buy/sell, quantity, value,
  the **trade date**, the **intimation date**, and the **NSE publication date**.
- **Rate limits we measured (2026-10-13):** 8 requests back-to-back → all fine, about
  1.5 seconds each, no blocking. One request per year works (2025 = 13,545 rows). No
  hidden cap seen. Still, we kept ~2 seconds between calls to be polite.

**Prices — yfinance** (`*.NS` tickers), adjusted for splits, downloaded from 2010.
The Nifty Auto ETF (`AUTOBEES`) or the Nifty index (`^NSEI`) used as the market
benchmark.

Full source notes: `data/2026-10-13/DATA_SOURCES.md`.

---

## 3. How much data, and how we cleaned it

- Scraped **2015–2026**, one file per year → `data/raw/pit_YYYY.json` (about 258 MB).
- **341,514 raw rows → 331,244 cleaned rows**, across **2,414 symbols**.
- Of those, **42,553 are "market purchases"** (real buys, not ESOP/pledges) across
  **1,601 symbols**.

Cleaning steps (`insider_drift.py --clean`):
1. Turn date strings into real dates; turn quantities/values into numbers.
2. Keep only **equity** rows.
3. Mark a real buy as `side == "Buy"` AND `mode == "Market Purchase"`.
4. Remove exact duplicates.
5. **Fix a data bug:** 8 rows had century typos — the trade date said `22-Jul-1922`
   when it meant 2022. Where the trade date is impossible, we use the publication date.

---

## 4. The de-noised plots

Directory: `plots/major_dips/`. Each chart has the price on top and RSI(14) below, and
marks only:
- **Green ▲ = LONG** when a **major insider buys ≥ ₹1 crore AND RSI < 35** (a dip).
- **Red ▼ = SHORT** when a major insider **sells** ≥ ₹1 crore AND RSI > 65 (overbought).
- Marker size = size of the trade in ₹.

Names plotted (hand-picked, liquid, with real activity): AXISBANK, JSWSTEEL,
ADANIPORTS, BAJAJHLDNG, BAJAJFINSV, GRASIM, GODREJAGRO, GODREJIND, USHAMART,
APOLLOTYRE, PIDILITIND, HDFCLIFE.

There are also earlier, noisier charts: `plots/*_insider_buys.png` (all buys) and
`plots/overview.png` (counts by year).

---

## 5. Stress test — checking the backtest for traps (`REPORT.md`)

Before trusting any number, we attacked it (10 batteries). The important ones:

| Check | What it showed |
|---|---|
| Raw excess vs Nifty (enter next open) | +2.24% at 20 days, +6.61% at 60 days — looks great |
| **Placebo** (same stocks, random dates) | +0.99% / +3.79% — so **more than half is not the signal**, it's the stocks drifting up |
| **Cluster-robust t** (count symbols, not trades) | t fell from ~13 to **~3.6** — events repeat in the same stock, so the naive significance was fake |
| vs **Nifty Midcap 150** | +1.75% / +4.61% — part of the "edge" is just small-cap vs large-cap |
| Sub-periods | **negative** in 2018, 2019 and 2025 |
| Most-frequently-bought names | **−0.23%** at 20 days — the "hot" names don't work |

Conclusion of the stress test: a real but **small** effect, **unstable** over time, and
**mostly a size/survivorship drift**, not a signal.

---

## 6. The backtest — full numbers (`BACKTEST.md`)

**Basket:** 18 hand-picked names with many signals and recent activity (so the
out-of-sample period is not empty):
DBCORP, STEL, MAHSEAMLES, JINDALSTEL, USHAMART, JSL, SURYAROSNI, NRBBEARING, NCC,
MANINFRA, APLLTD, MANGLMCEM, SHOPERSTOP, GREENPLY, PAISALO, JINDRILL, KRISHANA,
TFCILTD.

**Signal:** major insider buy ≥ ₹25 lakh, RSI < 40. Entry next open. Hold 20 days.
Cost 0.75% round trip (₹8–16k delivery).

### Variants compared (pooled portfolio, equal weight)

| variant | trades | win rate | avg net/trade | Sharpe | max drawdown | Calmar |
|---|--:|--:|--:|--:|--:|--:|
| buy dip, no filter | 237 | 0.53 | +0.99% | **−0.04** | −15.4% | −0.01 |
| buy dip, **wait for RSI recovery** | 235 | 0.48 | −0.52% | −0.12 | −12.0% | −0.02 |
| buy dip, **above 200-day MA** | 49 | 0.51 | +2.18% | **+0.24** | **−4.1%** | +0.08 |
| recovery + 200-day MA | 47 | 0.47 | +2.27% | +0.08 | −5.9% | +0.01 |

### Hold-period sensitivity (no filter)

| hold | trades | win | avg net | Sharpe | maxDD | Calmar |
|--:|--:|--:|--:|--:|--:|--:|
| 5d | 237 | 0.43 | −1.69% | −0.42 | −16.6% | −0.05 |
| 20d | 237 | 0.53 | +0.99% | −0.04 | −15.4% | −0.01 |
| 60d | 237 | 0.52 | +5.38% | +0.13 | −15.8% | +0.03 |

### Out-of-sample (entries from 2024 on)

- No filter, 20d: 111 trades, win 0.59, avg +1.37%.
- **200-day MA, 20d: 15 trades, win 0.80, avg +4.71%, median +6.26%.**

### Monte Carlo + placebo (the decisive tests)

- **200-day MA variant:** bootstrap Sharpe p05 −0.15, p50 +0.24, p95 +0.63;
  P(Sharpe ≤ 0) = 0.16.
- **Random-entry placebo** (same stocks, random dates): mean Sharpe **+0.26** vs our
  **+0.24**; **random beats us 58% of the time.** So even the best variant has **no
  edge over luck**.

### The single clearest example (why it fails)

AXISBANK's 25 "buy in a dip" signals (RSI 13–33, at the 2016 and 2020 crashes):
- next 20 days: signal **−5.73%** vs random **+1.78%** → the signal **lost** 7.5% vs
  random.
- The dips were the middle of crashes; the stock kept falling for the whole hold.

---

## 7. Mistakes I made (and fixed) — so you don't repeat them

1. **Selected the winners and called it a result.** The first look at the top-6 most
   insider-bought names looked positive; that was **selection bias**. The proper
   random-universe test was flat.
2. **Used the insider's trade date as the signal** in the first forward-return table.
   That is **look-ahead** (the trade is private until disclosed). Fixed to the
   **publication date**.
3. **Wrong benchmark.** Used the Nifty Auto ETF as the market for every stock. Fixed
   to Nifty / Nifty Midcap.
4. **Portfolio math bug.** Added the per-stock returns together, which secretly
   **over-leveraged** the book and produced a **−107% drawdown** (impossible). Fixed to
   average (equal weight).
5. **Monte-Carlo bug.** Multiplied all trades as if they happened at once → absurd
   totals (thousands of %). Replaced with a proper block bootstrap.
6. **Falling-knife entry.** "RSI < 35" buys *during* a crash. The stock keeps falling.
   This was the core design error; it only became obvious after the direct check.
7. **Plot vs backtest used different dates** (plot = trade date, backtest =
   publication date). Minor (median gap 2 days) but sloppy.
8. **Employee/ESOP trades counted as "big party"** at first — huge noise. Excluded.
9. **Empty out-of-sample** at first because the hand-picked names had no 2024+ buys.
   Re-picked names that do.
10. **NSE's own date typo** (1922 for 2022) — caught and corrected.
11. **Close-triggered exit filled at the earlier same-day open** in the first
    momentum script — direct look-ahead. Corrected to next-open execution; the
    earlier 176-trade Sharpe 0.54 result is retracted.

---

## 8. Files to examine

| File | What it is |
|---|---|
| `EVERYTHING.md` | This file. Start here. |
| `PLAN.md` | The original research plan and pre-registered gates. |
| `REPORT.md` | The stress test (10 batteries, with code). |
| `BACKTEST.md` | The backtest write-up (metrics, OOS, Monte Carlo). |
| `insider_drift.py` | Fetch + clean + summary + all plots. |
| `stress_insider.py` | The stress-test batteries. |
| `backtest_insider.py` | The backtester (variants, OOS, Monte Carlo, placebo). |
| `data/events.csv` | Cleaned events (331k rows) — the main table. |
| `data/raw/pit_YYYY.json` | Raw NSE disclosures (2015–2026). |
| `data/bt_prices/*.csv` | Price history used by the backtest. |
| `data/panel/*.csv` | Price history used by the stress test. |
| `data/stress_results.json` | Machine-readable stress output. |
| `data/backtest_results.json` | Machine-readable backtest output. |
| `plots/overview.png` | Disclosures per year, by type. |
| `plots/major_dips/*.png` | The de-noised signal charts. |
| `plots/*_insider_buys.png` | Earlier buys-only charts. |
| `../data/2026-10-13/DATA_SOURCES.md` | All free data sources + rate limits. |
| `../data/2026-10-13/NICHE_INEFFICIENCIES.md` | The three niche ideas this came from. |

---

## 9. How to reproduce

```bash
# 1. Scrape + clean the insider disclosures (free, no login)
python insider_drift.py --fetch
python insider_drift.py --clean --summary

# 2. The de-noised plots
python insider_drift.py --major-top 12

# 3. Stress-test the event study
python stress_insider.py --fetch --n 200 --placebo 100

# 4. Backtest — compare the variants
python backtest_insider.py --symbols "<list>" \
  --min-value 2500000 --rsi-dip 40 --hold 20 --cost 0.0075 --variants

# 4b. Backtest — the best variant, full output
python backtest_insider.py --symbols "<list>" \
  --min-value 2500000 --rsi-dip 40 --hold 20 --cost 0.0075 --entry dip --ma 200
```
(Needs a Python environment with pandas, numpy, matplotlib, yfinance.)

---

## 10. Caveats and what would change the answer

- **Costs are modelled, not measured.** Small-cap spreads would make it worse.
- **Survivorship:** yfinance only has stocks that still exist, which flatters returns.
- **Few events:** most names give 1–20 signals in 10 years. That is too few for
  confidence.
- **The `date` field** (publication time) is assumed correct; not independently
  verified.
- To overturn the verdict you would need: a **survivorship-free** price source
  (bhavcopy with delisted names), a **measured spread**, and a **size-matched
  benchmark** — and even then the placebo says random entry is just as good.

## 11. Verdict

**No tradeable edge.** The major-insider RSI-dip long signal does not beat random
entry into the same stocks after cost. The only improvement (200-day MA filter) is
plain momentum, not the insider signal. Recommend recording this as a
**tested-and-dead** result and not extending the approach.

### 2026-10-13 momentum-optimization follow-up

The direct momentum interpretation was also tested honestly in
`optimize_momentum.py`: major public insider purchase → wait for a closing-high
breakout with `close > EMA50 > EMA200` and a rising EMA50 → enter next open →
close-confirmed stop/trailing exit at the next open. The portfolio held one cash
stock at a time and was capped at two entries per calendar year.

- Data: 20-name requested surviving-ticker basket (18 had cached prices), cached
  adjusted yfinance open/close, 2015-11-20–2026-10-13. Train
  2015-11-20–2023-07-04; untouched test
  2023-07-05–2026-10-13.
- Search: 216 predefined configurations, 148 with enough train trades and the
  required frequency. Two raw one-sided p-values were below 0.05 versus 7.4
  expected by chance; **zero survived FDR**.
- Locked rule: insider buy ≥₹1 crore; 30-session confirmation window; 50-session
  highest-close breakout; price already +5% but no more than +30% from the public
  disclosure close; 10% close-trailing exit; 10% close-confirmed hard stop;
  126-session cap.
- Untouched test at 27 bp delivery charges (spread excluded): 6 non-overlapping
  trades, 1.83/year, CAGR 7.14%, Sharpe 0.42, max drawdown −25.36%, median trade
  −3.52%, mean +6.29% with 95% CI −22.90% to +35.48%, DSR 0.025. One KRISHANA
  winner (+62.11% net) supplied the result; four of six trades lost.
- Kill number: 250 matched random-catalyst trials had median test CAGR 11.24%;
  random equalled or beat the insider strategy 56.8% of the time.

Therefore the optimized result remains **dead**. The charts do show genuine price
momentum, but the insider disclosure does not select it better than random dates
under the same trend rules. Historical bid/ask spread, intraday stop fills,
delisted names, true daily highs/lows, and an independent price-source check are
still missing, so the already-negative inference cannot be upgraded to a
net-positive claim. Evidence is in `data/momentum_optimized/` and
`plots/momentum_optimized/`.

*Research only; not investment advice.*

### Correction: faithful persistent-watch implementation (2026-10-13)

The momentum-optimization conclusion above applies only to that altered
short-window variant, not to the strategy requested by the user.
`faithful_momentum.py` restores the fixed ₹25 lakh Market Purchase threshold,
lets the event arm a stock without a 30-day expiry, requires a +10% rise and a
breakout above the prior 252-session true high with `close > EMA50 > EMA200`,
enters next open, and exits next open after an EMA50/10% stop breach (126-session
cap). No annual trade quota is imposed.

Using adjusted Yahoo Finance OHLC for all 20 basket stocks, 27 bp round-trip
delivery charges, and a chronological 70/30 split, the untouched
2023-07-05–2026-10-13 test had 30 trades: mean net +2.67% (SE 3.69%), median
−3.84%, win rate 43.3%, equal-weight-sleeve Sharpe 1.09, CAGR 3.42%, and max
drawdown −4.56%. The low median with a positive mean is the expected positively
skewed momentum shape, not by itself a failure.

Against 250 controls with the same catalyst count per stock and otherwise
identical rules, random dates had median mean trade return +0.87%; only 4.8% of
random trials matched or exceeded the actual insiders' +2.67% test mean. This is
the first result consistent with incremental information in the insider dates,
but it is borderline: the 30-trade mean-return confidence interval crosses zero,
historical spread is unmeasured, and current-ticker survivorship remains.
