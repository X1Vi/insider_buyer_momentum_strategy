# CONTEXT FOR CODEX — India "insider + momentum" strategy

**Date:** 2026-10-13 · **Status:** hand-off. The code exists but does **not** yet
satisfy the trade-frequency requirement. Read this whole file before writing code.

---

## 1. What we are trying to do (plain words)

An insider (promoter / director / senior manager) buys a chunk of their own
company's shares. That is a **bullish hint**, not a buy order by itself. We want to
use it to **catch momentum**: after the insider buys, we wait until the price
**confirms an uptrend** (it breaks to a new high while the moving averages are
below it), then we buy, hold while it keeps rising, and sell when it starts to
drop. Long-only, cash, small account (₹5,000–₹8,000), NSE stocks.

---

## 2. The rules, exactly (this is the criteria to implement)

**Signal / watchlist trigger**
- A **major insider** — promoter, promoter group, director, or key managerial
  personnel (NOT employees / ESOP) — makes a **market purchase** worth ≥ ₹25 lakh
  (₹2,500,000).

**Entry (momentum confirmation)** — after the insider buy:
- Place the order when the price **beats its highest high** (a breakout to a new
  high; "or is near / approaching it" is acceptable) **AND**
- **EMA(50) and EMA(200) are both BELOW the price** (`close > EMA50 > EMA200`) —
  i.e. it is in an uptrend, not a falling knife.
- Buy at the **open of the next trading day** after the breakout.

**Stop-loss**
- A hard stop below entry (exact % to be decided — currently 10–20%). This is the
  drawdown protection.

**Hold / exit**
- **Keep holding while it keeps rising** (ignore minor dips).
- **Sell when it starts to drop** — the exit indicator is the **EMA(50)**: exit
  when the closing price falls back to / below EMA50 (i.e. EMA50 "stabilises with
  the closing price").
- Also cap the hold (≈6 months) so a dead trade does not sit forever.

**Plotting (required)**
- Price, **EMA(50)**, **EMA(200)**.
- Mark **when the insider bought** (their trade date).
- Mark **our entry** and **our exit**.
- Draw **RSI(14)** in a lower panel.

**Frequency requirement (THE thing that keeps being wrong)**
- **Target: 1–2 trades per year.** Not dozens. Not one trade in 16 years.

---

## 3. The frequency problem — read this twice

This is where every attempt has failed, in both directions:

- Attempt 1: entered on **every** insider buy → **2,293 trades** (way too many),
  because one stock can have 100–275 insider buys.
- Attempt 2: "one trade per episode" → 269 trades (still too many).
- Attempt 3: "one position at a time" → **2.0 trades/year overall**, BUT the
  per-stock plots then show things like **ADANIPORTS = 1 trade in 16 years**,
  which looks empty and wrong.

**The ambiguity that MUST be resolved before coding:**
- **Interpretation A — "1–2 trades per year total"**: a single-position portfolio.
  Simple, but individual stock charts will show almost no trades.
- **Interpretation B — "1–2 trades per year PER STOCK"**: each stock trades 1–2×/yr
  on its own signals (so ~20 stocks → ~20–40 trades/yr total). Stock charts then
  look populated.
- **Interpretation C — "very few, high-conviction trades, roughly 1–2 per year, and
  each must be clearly visible on the chart of the stock it belongs to"**: a
  blend — a small number of strong signals, one position at a time, but the chart
  shows each trade where it happened.

**Do not guess.** Ask which of A / B / C is wanted. The user's phrasing ("1 or 2
trades a year… just one trade in 16 years is wrong") points to a small total but
also expects trades to be visible per stock — likely **C**.

---

## 4. Data (already verified, free)

- **Insider disclosures — NSE PIT API** (no auth):
  `GET https://www.nseindia.com/api/corporates-pit?index=equities&from_date=DD-MM-YYYY&to_date=DD-MM-YYYY&symbol=`
  - Fields include `symbol, acqName, personCategory, tdpTransactionType, acqMode,
    acqfromDt, intimDt, date (dissemination), secAcq, secVal`.
  - Use the **disclosure date** (`date`), never the trade date (point-in-time).
  - Measured rate limits (2026-10-13): 8 back-to-back calls all HTTP 200, ~1.5 s
    each; full-year calls fine. Cache raw JSON per year.
  - Cleaned data: `data/events.csv` (331k rows, 2015–2026).
- **Prices — yfinance** (`<SYM>.NS`), adjusted; stored in `data/bt_prices/*.csv`
  (columns: date, open, close) and `data/panel/*.csv`.
  - **Caveat:** yfinance only has surviving tickers (survivorship bias).
  - **Caveat:** no high/low column — "highest high" is currently approximated by
    the highest *close*. Add true OHLC (bhavcopy) if needed.

---

## 5. Existing code (all in `strategy_categories/could_work/india_insider_drift/`)

| file | what it does |
|---|---|
| `insider_drift.py` | fetch + clean + summary + de-noised plots |
| `backtest_insider.py` | fixed-hold backtest, variants, OOS, Monte Carlo, placebo |
| `stress_insider.py` | 10 stress batteries (look-ahead, placebo, clustering, …) |
| `patterns.py` | reaction-shape taxonomy (SLOW/KNIFE/FAST/FADE/FLAT) |
| `trend_overlay.py`, `trend_variants.py` | insider + Donchian/EMA trend overlays |
| `follow_rules.py` | insider → wait 2d → hold, exit on EMA10 |
| `rules_v2.py` | one-trade-per-episode, EMA50 exit, vectorbt |
| `momentum_entry.py` | **breakout + EMA50>EMA200 entry** (closest to the criteria) |
| `one_position.py` | single position, ~2 trades/year |
| `estimate.py`, `rupee_estimate.py` | ₹8,000 / ₹5,000 account sims |

Data: `data/events.csv`, `data/bt_prices/`, `data/panel/`, `data/patterns.csv`.
Plots: `plots/{major_dips,patterns,backtest,buyer_vs_us,rules,rules_v2,momentum,one_position}/`.

**Retracted earlier result** (`momentum_entry.py`): the previously reported 176
trades / Sharpe 0.54 / maxDD −9.5% used an impossible exit price — a breach seen
at the close was filled at that same day's earlier open. The script is now causal
(close confirmation → next open) and uses a 126-session six-month cap. Do not cite
the old metrics. The honest optimization and matched control are in
`optimize_momentum.py` and `data/momentum_optimized/summary.json`. **Correction:**
that optimizer changed the actual strategy (₹1cr threshold, 30-day watch expiry,
50-day closing high, upper chase cap, trailing exit, and forced portfolio trade
quota), so its failure does not test the rules in section 2. The fixed-rule
`faithful_momentum.py` persistent-watch test produced 30 untouched-test trades;
actual insider dates beat matched-random dates on mean return in 95.2% of 250
trials (empirical p=0.048). This is promising but not conclusive because the
mean-return error bar is wide, spreads are unmeasured, and survivorship remains.

**vectorbt** is available in `volume_indicator_studies/.venv` (has yfinance too).
Use that interpreter.

---

## 6. Mistakes already made (do not repeat)

1. Treated the insider buy as an immediate buy → thousands of trades.
2. Used the trade date instead of the disclosure date (look-ahead).
3. RSI-dip entry bought **falling knives** (AXISBANK −5.7% vs random +1.8%).
4. Wrong benchmark (Nifty Auto for every stock); summed sleeves → −107% drawdown.
5. Monte-Carlo compounded all trades as if simultaneous → absurd totals.
6. Exit too sensitive (EMA20) → median hold 2 days → whipsaw.
7. Forgot to cumprod a return series into equity (bogus −100% CAGR).
8. Per-stock charts showed almost no trades under the single-position model.
9. `momentum_entry.py` originally used the same day's open for an exit triggered
   by that day's close (look-ahead). Corrected to the next open; old Sharpe retracted.

**Fundamental finding to respect:** across every honest test, **random entries
with the same trend rules did as well or better than the insider trigger.** So any
new version MUST include a **random-entry control**; if it does not beat the
control, the insider signal is doing nothing.

---

## 6b. VISUALIZE FIRST — open the plots to see what we are trying to do

**Before writing any code, open and look at the existing plots** (they are PNG
images — read them, don't just list them). They are the clearest statement of
intent. Locations under `plots/`:

| folder | what it shows | what to check |
|---|---|---|
| `one_position/` | the current **1–2 trades/year** version: `equity.png` + one chart per stock | how few trades there are, how long they last, how the ₹8,000 curve rises then gives back |
| `momentum/` | **breakout + EMA50>EMA200 entry** (closest to the rule): price, EMA50, EMA200, insider buys, our entry/exit, RSI | entries only on new highs with EMAs below; exits at EMA50 |
| `buyer_vs_us/` | **when the insider bought vs when WE traded** (blue dots vs green ▲) | the gap between their buy and our entry |
| `rules_v2/` | EMA50 exit + RSI + EMA200 | long holds, stop-loss behaviour |
| `major_dips/` | the raw signal charts (price + RSI + long/short markers) | the original de-noised view |

**How to use them:** open the plots, describe in your own words what the strategy
is doing, and confirm with the user that the *shape* is right (how many trades,
how long held, where entered/exited) **before** coding. The recurring failure in
this project has been building the wrong shape; the plots prevent that.

Also render fresh plots as you go, so the user can visually confirm each change.

---

## 7. What Codex should build

1. **First, ask which frequency interpretation (A / B / C in §3) is wanted.**
2. Implement the rules in §2 **exactly**, with:
   - true point-in-time disclosure dates,
   - the momentum entry (`close > highest high` AND `close > EMA50 > EMA200`),
   - a stop-loss + EMA50 exit + ~6-month cap,
   - the required plot (price, EMA50, EMA200, insider-buy markers, entry, exit, RSI),
   - vectorbt for the backtest.
3. Report: trades/year, win rate, avg net, **Sharpe, max drawdown, Calmar**,
   IS/OOS split, and the **random-entry control**.
4. Estimate a **₹8,000 and ₹5,000** account (whole shares, one position at a time).
5. If it cannot beat the random-entry control, record it as **dead**.

---

## 8. Open questions for the user (ask before coding)

1. Frequency: **1–2 trades per year total** (A) or **per stock** (B) or **few, but
   visible per stock** (C)?
2. Exact **stop-loss %** and whether the exit is EMA50 or a fixed trailing stop.
3. "Highest high" = highest **close** (what we have) or true **intraday high**
   (needs bhavcopy OHLC)?
4. Universe: the hand-picked basket, or all stocks with insider buys?
5. Is the goal **maximum rupee growth** (accept drawdown) or **smooth equity**
   (lower drawdown)?

---

## 9. Where the truth lives

- `EVERYTHING.md` — all findings + mistakes.
- `TREND_OVERLAY_PLAN.md` — the overlay design + variant list.
- `data/2026-10-13/DATA_SOURCES.md` — data sources + measured rate limits.
- `data/2026-10-12/AGENTS.md` — repo rules (costs, point-in-time, FDR, DSR, traps).

*Research only; not investment advice.*
