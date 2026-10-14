# Master Documentation — Spread Reversion & Pairs Trading System

*Everything we know so far, consolidated. Strategies, code, data, findings, capital reality, and the path forward.*

**Date:** 2026-08-29
**Scope:** NSE ETF pair trading (Groww) + crypto perpetual pairs trading (Hyperliquid)
**Author:** Trading research project (user + AI-assisted analysis)

---

## Table of Contents

1. [Mission & Goal](#1-mission--goal)
2. [The Strategy — Statistical Arbitrage (Pole 2007)](#2-the-strategy--statistical-arbitrage-pole-2007)
3. [Venue Comparison: Groww (NSE) vs Hyperliquid (Crypto)](#3-venue-comparison-groww-nse-vs-hyperliquid-crypto)
4. [What We Built — Code Inventory](#4-what-we-built--code-inventory)
5. [Groww API & Fee Facts](#5-groww-api--fee-facts)
6. [Key Findings (Data-Backed)](#6-key-findings-data-backed)
7. [Backtest Results Summary](#7-backtest-results-summary)
8. [Financial Reality & Capital Requirements](#8-financial-reality--capital-requirements)
9. [Hyperliquid Pairs Research (Crypto)](#9-hyperliquid-pairs-research-crypto)
10. [Tax & Legal (India)](#10-tax--legal-india)
11. [Risk Management Rules](#11-risk-management-rules)
12. [Recommendations & Next Steps](#12-recommendations--next-steps)
13. [File Map / Where Everything Lives](#13-file-map--where-everything-lives)
14. [Appendix — Fees & Formulas](#14-appendix--fees--formulas)

---

## 1. Mission & Goal

Primary objective: **earn money with minimal capital (₹10,000–20,000)**.

Secondary objective: build a systematic, research-backed trading stack (paper → live) for statistical arbitrage / pairs trading.

**The core tension (proven repeatedly):** mean-reversion strategies return ~10–16%/yr. To earn **₹10,000/month** (₹1.2L/yr) you need ~₹9.6–10.5L of capital. At ₹10–20k, that target requires a 600–1200%/yr return — **not achievable by any legitimate strategy**. The gap is capital, not cleverness.

---

## 2. The Strategy — Statistical Arbitrage (Pole 2007)

**Concept:** two instruments that normally move together sometimes diverge. Bet the gap snaps back (mean reversion).

- **Spread:** `s = ln(PA) − β·ln(PB)`, with `β = 1.0` (unit-neutral pair: buy 1 A, sell 1 B).
- **Rolling z-score:** `z = (s − mean) / std` over a trailing window.
- **Entry:** `|z| > 2` (gap is unusually wide).
  - `z > +2` → **SHORT** the spread (sell A / buy B) — bet the gap narrows.
  - `z < −2` → **LONG** the spread (buy A / sell B) — bet the gap widens back.
- **Exit:** z crosses 0 (gap returns to its average). Optional stop-loss / take-profit / confidence gate.

**Pairs:**
- Primary: BANKBEES (Nippon Bank Bees) vs SETFNIFBK (SBI Nifty Bank ETF) — both track Nifty Bank.
- Secondary: NIFTYBEES vs SETFNIF50.
- Crypto candidates: see §9.

**Important:** this is *statistical* arbitrage — **probabilistic, not risk-free**. The gap can widen and stay wide. Gross win rate is high (~72–100%) but losses happen, and fees can erase the edge.

---

## 3. Venue Comparison: Groww (NSE) vs Hyperliquid (Crypto)

| Factor | Groww / NSE | Hyperliquid (crypto perps) |
|---|---|---|
| **Fees** | ₹20/order or 0.1% (min **₹5/leg**), + STT/stamp/exchange/SEBI/IPFT/GST | **0.045% taker, 0.015% maker**, no per-order floor |
| **Pair round trip** | ~₹24–133 (4 legs) | ~0.09–0.3% of notional |
| **Shorting** | Intraday only (MIS), square-off EOD | 24/7, symmetric, no borrow |
| **Position size** | Whole ETF units (₹500–600/unit) | Arbitrary, sub-$10 possible |
| **Universe** | ~12 relevant index ETFs | 232 perps |
| **Capital friendliness** | **Poor at small size** (fee floor) | **Good** (tiny fees + leverage) |
| **India tax** | STT/stamp built in; capital gains rules | 30% VDA, no loss set-off (⚠️ see §10) |

**Bottom line:** For ₹10–20k, **Hyperliquid is the only venue where small capital isn't structurally killed by fees.** The NSE/Groww route needs ₹1.2L+ to be net-profitable on pairs.

---

## 4. What We Built — Code Inventory

### Python (deployable to Groww, or runnable locally)

| File | Purpose | Status |
|---|---|---|
| `main.py` | Paper trader — fees modeled, `PAPER_TRADING` toggle, stdout-only (sandbox-safe) | Working |
| `live_trader.py` | Real-money trader — MARKET/MIS orders, margin-sized from API, sanity checks | Working (needs token) |
| `portfolio_trader.py` | Paper trader — ₹ portfolio sizing + stop-loss/take-profit | Working |
| `indicator_groww.py` | Live two-sided indicator, 1–5s refresh, **alert sound**, qty suggestion | Working (needs token) |
| `live_trade.py` | One-sided (LONG) live trader — alerts + **live stop-loss display** | Working (needs token) |
| `get_access_token.py` | Token generator | ⚠️ **Contains credentials — do not commit/upload** |

### Backtests (`backtesting/`)

| File | Data | What it tests |
|---|---|---|
| `backtest.py` | Groww historical | Original Groww-data backtest |
| `backtest_yahoo.py` | Yahoo 5m (60d) | Intraday, qty sweep |
| `backtest_portfolio_yahoo.py` | Yahoo daily 2023–26 | 81-config stress grid |
| `backtest_report_yahoo.py` | Yahoo daily 2023–26 | Full metrics (Sharpe, MDD, …) + MD report |
| `backtest_one_side.py` | Yahoo (any pair, 5m or daily) | **Parameterized** one-sided LONG + stop-loss |
| `backtest_master.py` | Yahoo (intraday or daily) | Two-sided, adjustable ₹ portfolio, full metrics + MD |
| `indicator_live.py` | Yahoo 5m | Live-refresh LONG-only manual indicator |

Generated outputs: `spread_reversion_yahoo.png`, `portfolio_stress_yahoo.png`, `report_equity.png`, `master_equity.png`, `backtest_one_side_*.png`, `report.md`, `master_report.md`, `report_layman.md`, `indicator_live.png`.

### Rust (the original engine + additions)

| File | Purpose |
|---|---|
| `src/main.rs` | Entry point; added `--indicator` mode branch (existing engine untouched) |
| `src/groww.rs` | Groww API client (token + quote) |
| `src/trading.rs` | Paper-trading strategy engine (30s poll, window 60) |
| `src/indicator.rs` | **New** — live two-sided indicator (1–5s, alerts, env-configurable) |
| `src/bin/simulator.rs` | **New** — market-replay simulator: loads stored CSV, replay from any/random start, **confidence score**, confidence-gated trades, **benchmarks optimal universal position %** |
| `src/tui.rs`, `src/state.rs`, `src/logging.rs`, `src/notify.rs`, `src/ledger.rs` | Existing engine support |

Run indicator: `cargo run -- --indicator` · Simulator: `cargo run --bin simulator -- --data file.csv --benchmark`

### Research / studies (external dir)
`/home/null/Documents/studies/trading/` — books, income study guide, ML pairs-trading research, **Hyperliquid screener + backtest** (see §9).

---

## 5. Groww API & Fee Facts

### API rules (from AGENTS.md)
- **Only two endpoints allowed:** token generation (`POST /v1/token/api/access`) and live quote (`GET /v1/live-data/quote`). (SDK also exposes `get_ltp`, margin, order APIs.)
- **Paper trading only / NO real orders** unless using `live_trader.py` deliberately.
- Fetch data only for held tokens (BANKBEES, SETFNIFBK).

### Rate limits
| Type | Per sec | Per min |
|---|---|---|
| Authentication (token) | 5 | 30 |
| Orders | 10 | 250 |
| **Live Data** | **10** | **300** |
| Non-trading (margin, positions) | 20 | 500 |

→ A **1–5s refresh** of `get_ltp` (1 call fetches both symbols) = 12–60 calls/min, **well within limits**.

### Sandbox constraints (Groww deployment)
- **Read-only filesystem** — no file writes (no log/state files). Stdout-only logging.
- Runs the uploaded script as `/tmp/code/main.py`.

### Fee model (intraday MIS, per order)
| Component | Rate | Applied |
|---|---|---|
| Brokerage | ₹20 or 0.1% of value, **min ₹5** | both sides |
| STT | 0.025% | SELL (intraday) |
| Stamp duty | 0.003% | BUY |
| Exchange (NSE) | 0.00297% | both |
| SEBI | 0.0001% | both |
| IPFT | 0.0001% | both |
| GST | 18% on (brokerage + exchange + SEBI + IPFT) | both |

**Round-trip cost (4 legs) at ₹550 ETF:**
| qty | Notional/leg | Fees/round trip |
|---|---|---|
| 2 | ₹1,100 | **₹24** |
| 19 | ₹10,450 | **₹61** |
| 100 | ₹55,000 | **₹133** |

### API gotchas discovered
- `get_order_margin_details` **rejects basket orders for CASH segment** → must call per-leg.
- `place_order` rapid-fire rejection → add ~0.5s between legs.
- `resp.get(key, default)` needed (missing keys), plus price range validation.

---

## 6. Key Findings (Data-Backed)

### 6.1 The fee floor is the #1 problem
The BANKBEES/SETFNIFBK edge is only **~₹1.4/unit** per reversion. Fees are ~₹24+ per round trip no matter how small. **At ₹5–20k (qty 2–17), fees are 4–6× the edge → guaranteed net loss.**

### 6.2 "est_gross" is misleading
Live session showed `est_gross = +₹103.61` but the account **lost money** — est_gross is LTP-based, pre-fees, pre-slippage. Real result: **net loss ≈ −₹90 + fees**. Always report net after fees.

### 6.3 The pair IS high-confidence (the edge is real)
- Gross win rate ~72–100% on the ETF pair (matches AGENTS.md "73.4%").
- Intraday 60d gross: **+₹9,491 at qty 100** — reversion genuinely works.
- **Fees, not reliability, are what fail at small capital.**

### 6.4 Confidence gating helps
On daily data, one-sided LONG: `conf_min=0` → net −₹118; **`conf_min=40` → net +₹96** (fewer, higher-quality trades). The indicator's confidence score is doing real work.

### 6.5 Wider pairs fail the reliability test
HDFCBANK/KOTAKBANK (bigger dislocations) lost **intraday**: 74 trades, gross **−₹1,053**, 53% win. The daily "+₹1,524" was a 7-trade small-sample artifact. **Bigger dislocations ≠ reliable reversion.**

### 6.6 Stop-loss is inert on daily data
On daily bars the spread reverts before the ₹50–100 stop is ever hit (all exits are z-cross). Stop-loss matters intraday / at larger size.

### 6.7 The Rust simulator validated the confidence concept
Gating on confidence flipped one-sided daily from net-negative to net-positive, and the benchmark sweep (position % 5→95) reports the optimal universal size.

---

## 7. Backtest Results Summary

### Intraday (Yahoo 5m, ~60 days, 109 trades, two-sided)
| qty | Gross ₹ | Fees ₹ | Net ₹ | Net win% |
|---:|---:|---:|---:|---:|
| 2 (₹5k) | +190 | 2,664 | **−2,474** | 0% |
| 100 | +9,491 | 14,863 | −5,372 | 8% |
| 200 | +18,982 | 19,436 | −454 | 40% |
| 300 | +28,473 | 24,010 | **+4,463** | 57% |
| 500 | +47,455 | 33,156 | **+14,299** | 72% |

→ Net positive needs **qty ≥ ~250–300** (₹3–6L intraday notional).

### Daily (2023–2026, 3.6 years, ~36 trades)
| Config | Net ₹ (₹5k) | Final ₹ |
|---|---|---|
| Base (w60,z2,SL100) | −732 | 4,268 |
| Best (w120,z3) | −151 | 4,849 |
| Worst (w20,z2) | −1,118 | 3,882 |

All 81 grid configs net-negative at ₹5k. **At qty=100 daily: net +₹3,848** (positive!). Sharpe base −3.04, MaxDD −14.7%.

### One-sided LONG (₹20k, 5m, 60d) — with stop-loss
40 trades, 0 stops hit, gross +₹560, fees ₹2,031, net −₹1,471. Same fee story.

---

## 8. Financial Reality & Capital Requirements

**To earn ₹10,000/month (₹1.2L/yr):**
| Source / Strategy | Annual Return | Capital needed |
|---|---|---|
| Value investing (Graham) | ~12% | ₹10L |
| Pairs trading (Pole) | ~12.5% | ₹9.6L |
| Quant trading (Chan) | ~10% | ₹12L |
| ETF 50-50 | ~12% | ₹10L |
| **Hyperliquid crypto perps** | ~16% gross (after 30% VDA tax) | ₹10.5L |

**There is exactly ONE low-capital exception claimed: "stat arb bot @ ₹25k MIS margin" — but our backtests prove that claim is based on gross win rate and is **net-negative after fees**. Do not fund it expecting ₹6–30k/month.**

**Honest summary:**
- ₹10–20k → ₹10k/month = 600–1200%/yr → **impossible safely**
- ₹10–20k → **learning + modest growth + building capital** = realistic
- To make pairs trading actually pay, either raise capital to ₹1.2L+ (NSE) or use Hyperliquid (small-capital-friendly venue)

---

## 9. Hyperliquid Pairs Research (Crypto)

This is the **most promising small-capital path**. Full stack exists in the studies dir.

### Why it fits
- Fees: taker 0.045%, maker 0.015% (no ₹5 floor). Round trip ~0.1–0.3%.
- Perps: short any time, arbitrary size, 24/7, no borrow.
- Small accounts are genuinely advantaged where institutions can't trade (funding dispersion lives on illiquid names).
- API readable from India, no account needed (read access).

### Screener (R1–R5 filter, 232 perps)
1. **R1** Cointegration (Engle-Granger, p<0.01, both directions)
2. **R2** Hurst exponent < 0.5 (mean-reverting)
3. **R3** Half-life 1–60 days
4. **R4** ≥6 mean-crossings/year
5. **R5** Live bid-ask must clear round-trip costs by ≥3×

**Funnel:** 4,005 candidate pairs → 173 (R1) → 47 (R2–R4). **47 pairs cleared all filters** ($250k/24h vol, ≥365-day maturity).

### Walk-forward backtest (40 testable pairs, 26 profitable)
| Pair | Return | Sharpe | MaxDD | Notes |
|---|---|---:|---:|---:|---|
| **BSV/FIL** | **+391%** | 2.82 | −7.4% | 7 trades, 0 stops — cleanest |
| MINA/FIL | +231% | 1.17 | −28.9% | |
| KAS/PEOPLE | +180% | 1.12 | −43.8% | |
| BSV/ICP | +161% | 1.48 | −27.1% | |
| FIL/ICP | +133% | 0.91 | −36.7% | |
| RUNE/POPCAT | +79% | 1.43 | −21.7% | |
| BSV/S | +20% | 2.08 | −9.6% | |

**Portfolio (equal-weight all testable pairs):** total **+202%**, Sharpe **1.0**, MaxDD **−38.6%**.

**Honest warnings:**
- **64% of all 476 simulated trades exited via stop-loss**, not clean reversion.
- Many pairs have −50 to −77% MaxDD (LTC/XRP, kSHIB/FIL, ADA/PYTH, SAND/IOTA) — **avoid these**.
- Pairs are selected on the same history they're tested on (flatters results).
- VIRTUAL/PAXG (best on paper) **never even triggered a trade** — "looks great" ≠ "makes money".

**Tradeable shortlist for small capital (suggested):** BSV/FIL, MINA/FIL, BSV/ICP, RUNE/POPCAT, BSV/S, kSHIB/SEI — high Sharpe, low MDD, few stop-outs.

---

## 10. Tax & Legal (India)

- **Crypto (VDA):** 30% flat tax on gains, **no loss set-off**, 1% TDS possible per trade — this alone roughly halves crypto edge (guide: ~16% gross → ~9% effective).
- **Hyperliquid perps classification** (VDA vs business income) and **offshore DEX custody risk** are open questions — get a CA's written answer **before funding** (this is the kill criterion in the research plan).
- **NSE/Groww:** STT/stamp/exchange fees are auto-deducted; standard capital-gains rules apply.

---

## 11. Risk Management Rules

1. **Never risk more than 1% of total equity on a single trade** (Hite/Kovner rule).
2. Position size from account equity, not from "gut".
3. Use stop-losses; expect ~64% of trades to hit them in crypto pairs — size for that.
4. Only take high-confidence signals (confidence gate ≥ 40 improves results).
5. Paper-trade first; **fund only if net Sharpe ≥ 1.0 after 3 months**.
6. Cap leverage — the basket backtest shows −38.6% MDD even unlevered.
7. Keep fees front-of-mind: at small size, every ₹ of fee matters.
8. Treat "₹10k/month from ₹10k" as a red flag — that's a scam-level return claim.

---

## 12. Recommendations & Next Steps

### Verdict
- **NSE/Groww pair bot at ₹10–20k: dead end** (fee floor). Only viable at ₹1.2L+ (intraday) or ₹1.2L (daily qty 100).
- **Hyperliquid pairs: the genuine small-capital venue** — but it's high-variance and tax-eroded. Treat as *learn + grow + build capital*, not ₹10k/month.

### Phased plan
| Phase | Action | Kill criterion |
|---|---|---|
| 0 | Fix the income-guide's false "₹25k → ₹6–30k/mo bot" claim (gross-win fantasy) | — |
| 1 | **Tax/legal** with a CA (VDA/TDS/custody) | 1% TDS per trade → stop |
| 2 | Build the small-account **tradeable shortlist** from backtest_results.csv | — |
| 3 | **Paper-trade** with honest cost model (fees + funding + 30% tax) | Net Sharpe < 1.0 after 3 mo → don't fund |
| 4 | **Minimum live capital** ($100–300) — measure modelled-vs-real fills | Fill gap too large → stop |
| 5 | Optionally test **intraday (5m/1h) pairs** for higher frequency (higher risk/return) | — |

### Realistic expectations
- With ₹10–20k: aim for **3–10%/mo high-frequency (high variance)** or **single-digit %/yr conservative**.
- Reaching **₹10k/month requires ~₹10L** of capital, or ~10× the risk.
- The single highest-leverage change for small capital is the **venue** (Hyperliquid), not the strategy.

---

## 13. File Map / Where Everything Lives

**Repo root:** `/home/null/Documents/development/statistical_arbitrage/spread_reversion/`
- `main.py`, `live_trader.py`, `portfolio_trader.py`, `indicator_groww.py`, `live_trade.py` — Python traders/indicators
- `backtesting/` — all backtests + reports + charts
- `src/` — Rust engine + `indicator.rs` + `bin/simulator.rs`
- `documentation/` — this master doc + PDF
- `AGENTS.md`, `.env.example`, `README.md` — config/docs
- ⚠️ `get_access_token.py`, `.env` — **credentials, do not commit/upload**

**Studies dir:** `/home/null/Documents/studies/trading/`
- `Machine_Learning_Base_Pairs_Trading/` — Hyperliquid screener/backtest + reports
- `hyperliquid_pairs/` — `pairs_screener.py`, `backtest.py`, `hl_data.py`, `results_final.csv`, `backtest_results.csv`, `backtest_portfolio_equity.csv`
- `The_Indian_Market_10000_INR_Monthly_Income_Study_Guide.md` (+ PDF) — master income study
- Books (Graham, Chan, Pole, Schwager, Sarmento/Horta) + summaries

---

## 14. Appendix — Fees & Formulas

### Gross P&L (pair, unit-neutral)
- **LONG** (buy A, sell B): `gross = (PA_exit − PA_entry)·qty − (PB_exit − PB_entry)·qty`
- **SHORT** (sell A, buy B): `gross = (PA_entry − PA_exit)·qty + (PB_exit − PB_entry)·qty`

### z-score
```
spread = ln(PA) − ln(PB)
mean = avg(spread window)
std  = sqrt(var(spread window))  (floor 1e-4 to avoid div-by-zero)
z    = (spread − mean) / std
```

### Confidence score (simulator/indicator)
`confidence = clamp((|z| − 2) / 3 × 100, 0, 100)` — 0 at the entry threshold, 100 at |z|=5.

### Groww intraday MIS leg fee
`fee = min(20, 0.001·V)  (min 5) + STT(sell 0.025%V) + stamp(buy 0.003%V) + 0.00297%V + 0.0001%V + 0.0001%V + 18%·(brokerage+exchange+SEBI+IPFT)`

### Hyperliquid fee
`taker 0.045% / maker 0.015% per side` + bid-ask crossing + funding (~0.03%/day flat estimate in backtests).

---

*End of master doc. Maintain as findings evolve.*
