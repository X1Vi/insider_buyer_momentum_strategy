# Gap Strategy — HDFCBANK / KOTAKBANK & the Multi-Pair Screen

**Verbose technical report** — method, all test results, the 2024 diagnosis, honest verdicts, and next steps. Date: 2026-08-29.

---

## 1. Objective

Find a **high-confidence, big-gap-follow-up, high-profit-margin** strategy on Indian stocks (Groww), specifically: when one cointegrated stock is stretched far from the other (a "gap"), **buy the laggard** (long-only) and capture the catch-up, with the profit margin **precomputed before entering** (expected follow − fees). Preference: same-day or a few days; long stocks, not short. Built and stress-tested in **Rust** with Yahoo data.

---

## 2. The strategy (as implemented)

- **Pair:** two stocks with a real economic link (e.g., HDFCBANK/KOTAKBANK, AXISBANK/INDUSINDBK, TCS/HCLTECH, TATASTEEL/COALINDIA).
- **Spread:** `s = ln(PA) − β·ln(PB) − α` (log-price gap, β the cointegration hedge).
- **Z-score:** `z = (s − mean) / std` over a trailing 60-day window (sample std).
- **Entry:** `|z| ≥ 3` (an extreme gap).
  - `z > 0` → A stretched expensive → **B is the laggard** → buy B.
  - `z < 0` → B stretched expensive → **A is the laggard** → buy A.
- **Exit:** ~5 trading days later (mean reversion), or stop at |z| ≥ 4.5.
- **Margin precheck (before entering):** `expected_net = expected_follow(₹/unit) × qty − fees(₹35)`. Only signal if positive.
- **Fees:** 2-leg intraday round trip ≈ ₹35 at ~₹15k (Groww MIS); delivery costs more (~₹65–70).

### The Rust tracker (`src/bin/tracker.rs`)
- **Two producer threads** — one per stock — update shared state every **2.5s**.
- **Analyzer (main thread)** computes the rolling z, fires BUY-laggard signals with the precomputed margin + confidence, exits on reversion/stop/hold-window.
- Calibration constants (HDFCBANK/KOTAKBANK daily 2022–2026): `β = 1.1622`, `α = −0.2189` (i.e. `spread = ln(HDFC) − 1.1622·ln(KOTAK) + 0.2189`), `FOLLOW_RS_PER_UNIT ≈ 9–12`.
- Modes:
  - `cargo run --bin tracker -- --replay backtesting/hdfc_ktak_daily.csv` (stress test)
  - `cargo run --bin tracker -- --live backtesting/hdfc_ktak_5m.csv` (threaded demo)

---

## 3. Baseline result (HDFCBANK/KOTAKBANK, 2022–2026)

| Metric | Value |
|---|---|
| Signals (z≥3, 5-day hold, buy laggard) | 9 |
| **Win rate** | **67%** |
| Gross / fees / **NET** | ₹5,325 / ₹315 / **+₹5,010** |
| Net per trade | **+₹557** |
| On ₹15k | ~8.6%/yr (≈2 trades/yr) |

> **Bug note:** an early Rust version used a stale rolling window after its signal-skip and reported 45% win. Fixed by advancing bar-by-bar with a non-overlap gate — now 66–67%, matching the corrected Python. This is the true number.

---

## 4. Can volume / indicators raise the win rate? (z≥3, 5-day hold)

| Filter | Signals | Win% | Net ₹/trade |
|---|---|---:|---:|---:|
| **Baseline** | 9 | 67% | +564 |
| **Leader volume > 1.2×** | 7 | **71%** | +471 |
| **Index (BANKBEES up 3d)** | 7 | **71%** | +463 |
| Both > SMA20 (uptrend) | 3 | 100% | +537 |
| Laggard volume surge | 8 | 62% | +510 |
| Laggard < 20d high + vol | 7 | 57% | +584 |

**Read:** filters nudge win rate up modestly (67 → 71%), but samples are tiny (3–9 signals over 4.6 years). Nothing is statistically bulletproof.

---

## 5. Hold horizon (baseline, z≥3)

| Hold | Signals | Win% |
|---|---:|---:|
| **1 day (same-day)** | 24 | **46%** |
| 2 days | 14 | 64% |
| 3 days | 12 | 58% |
| **5 days** | 9 | **67%** |

**Same-day exit = lowest win rate.** The big-gap follow plays out over days. The user preference for same-day conflicts directly with a high win rate.

---

## 6. Opposite direction (buy the leader — momentum continuation)

| Hold | Leader win% | Laggard win% |
|---|---:|---:|
| 1 day | 54% | 46% |
| 3 days | 42% | 58% |
| 5 days | 33% | 67% |

**The laggard-catch (mean reversion) is the correct side.** Buying the stretched-ahead leader only wins at same-day, marginally.

---

## 7. Who rises first? (lead-lag, daily-return cross-correlation)

Same-day correlation is high; **lag 1–3 days ≈ 0** for every pair tested:

| Leader → Follower | t | t+1 | t+2 | t+3 |
|---|---:|---:|---:|---:|
| BANKBEES → HDFCBANK | +0.77 | −0.02 | +0.03 | −0.02 |
| BANKBEES → KOTAKBANK | +0.63 | −0.06 | 0.00 | −0.04 |
| NIFTYBEES → HDFCBANK | +0.70 | −0.02 | +0.03 | −0.02 |
| HDFCBANK → KOTAKBANK | +0.47 | −0.04 | +0.03 | −0.03 |

**Nobody leads at the daily level — they all move the same day.** The only exploitable relationship is the *relative gap reverting*, not one asset following another.

---

## 8. Multi-pair screen (20 liquid NSE names, 190 pairs)

Same logic (beta=1.0 screen), z≥3, 5-day hold, buy laggard:

| Pair | Signals | Win% | Net ₹/trade |
|---|---:|---:|---:|
| HINDUNILVR/TATASTEEL | 6 | 100% | +613 |
| NESTLEIND/TATASTEEL | 6 | 100% | +383 |
| HCLTECH/ITC | 5 | 100% | +485 |
| TATASTEEL/COALINDIA | 5 | 100% | +377 |
| AXISBANK/BAJAJFINSV | 7 | 86% | +492 |
| **AXISBANK/INDUSINDBK** | 10 | **80%** | +633 |
| **HDFCBANK/KOTAKBANK** | 10 | **80%** | +476 |
| TCS/HCLTECH | 5 | 80% | +369 |
| RELIANCE/TATASTEEL | 8 | 75% | +528 |
| TCS/WIPRO | 7 | 71% | +417 |
| … ~10 more at 70–80% | 5–10 | 70–80% | +300 to +800 |

**The high-confidence gap edge generalizes across many economically-linked pairs — it is not unique to HDFC/KOTAK.** Small samples remain the caveat.

---

## 9. The 2024 failure — diagnosed (your hypothesis was half right)

| Check | Result |
|---|---|
| **2024 regime** | HDFCBANK **+5%**, KOTAKBANK **−6%** (BANKBEES +6%, NIFTYBEES +10%). The pair **genuinely decoupled** — KOTAK was fundamentally weak, not temporarily stretched. |
| **Beta stability** | Rolling-60d beta: **0.24–0.78 by year** vs the 1.16 full-sample → the relationship is **not stable**. Your "measuring it wrong" instinct was correct that beta drifts. |
| **Did rolling beta fix it?** | **No.** Recomputing with rolling beta → 2024 still 0% win; total falls to 57% (7 sig). |
| **2024 signals** | 2024-01-23 LOSS (gap stayed), 2024-04-25 LOSS (KOTAK kept falling — spread widened), 2024-05-03 WIN (17.8% gap, big reversion), 2024-10-21 LOSS. |

**Conclusion:** 2024 was a **real decoupling, not a measurement error.** Pairs trading fails when the pair genuinely separates for a fundamental reason. No beta choice turns a real decoupling into a reversion.

---

## 10. Stability — is it permanent?

| Year | Signals | Win% |
|---|---:|---:|
| 2022 | 2 | 100% |
| 2023 | 1 | 100% |
| **2024** | 4 | **25%** |
| 2025 | 2 | 100% |
| 2026 | 0 | — |

**Not permanent.** One bad year, tiny samples everywhere. Fragile, not durable.

---

## 11. Honest verdicts

1. **Same-day + high-win + high-margin do NOT coexist** on this data. You can have any two of the three.
2. The best defensible configuration: **z≥3, 5-day hold, buy the laggard, with leader-volume or index-confirmation → ~71% win, +₹470–560 net/trade** — but only ~1–2 trades/year per pair, and it broke in 2024.
3. **Volume/indicator filters help modestly**, not dramatically.
4. **The opposite direction (buy leader) is worse** for multi-day holds.
5. **No daily lead-lag** exists among these assets — only the gap reversion is real.
6. **2024 was a genuine decoupling** (KOTAK fundamentally weak) — pairs trading's known failure mode, not a bug.
7. **The edge generalizes** across many pairs (70–100% win) but is fragile year-to-year.

---

## 12. Recommended next steps

1. **Re-run the multi-pair screen with per-pair OLS (rolling) beta** instead of beta=1.0, plus a **"laggard not in downtrend" filter** (laggard above its SMA20) — this targets the 2024 failure mode directly (don't buy a laggard that's genuinely falling).
2. **Add a yearly stability check** to the screener — only keep pairs with win% ≥ 65% in every year (or ≥ 60% with ≥ 4 signals).
3. **Paper-trade the surviving 3–5 pairs** (Rust tracker, 5-day holds) net of fees for 3–6 months; fund only if out-of-sample win ≥ 65%.
4. Accept **~2–5 trades/year** across the pair basket and **~5–15%/yr** potential on ₹15–25k — this is a "few big confident bets" strategy, not an intraday income engine.

---

## 13. Formulas (appendix)

- Spread: `s = ln(PA) − β·ln(PB) − α`
- Rolling z (60d, sample std): `z = (s − mean) / sqrt(Σ(s−mean)² / (n−1))`
- Entry: `|z| ≥ 3`; buy the laggard (the leg stretched cheap); exit ~5 days or `|z| ≥ 4.5`.
- Margin precheck: `net = follow(₹/unit) × qty − ₹35 fees`
- Qty (₹15k): `floor(15000 / price_laggard)`
- Payoff model (HDFC/KOTAK): ~67% win, avg follow ~2.9% (~₹12/unit)

## 14. Files

- `src/bin/tracker.rs` — threaded Rust tracker (replay + live)
- `backtesting/gap_winrate_analysis.py` — filters, holds, opposite, stability, lead-lag
- `backtesting/pair_gap_screener.py` — 20-name multi-pair screen
- `backtesting/hdfc_ktak_daily.csv`, `backtesting/hdfc_ktak_5m.csv` — data
- `documentation/GAP_STRATEGY_SIMPLE.md` — the plain-English version of this

*End.*
