# Relations, Cointegration & Momentum in the Indian Market

*A strategy idea for ₹10,000–25,000 — what actually works, what doesn't, and why. Grounded in real data (2023–2026) and the study materials in `~/Documents/studies/trading`.*

**Date:** 2026-08-29 · **Author:** trading research project

---

## 1. The question you asked

> Capture a relation / cointegration / momentum lift between broad market proxies — Nifty 50 vs Bank Nifty, and more niche: silver vs gold, copper vs gold. Manage risk on ₹10–25k with a confidence score, prefer intraday.

This is the right instinct — but the data says the **kind** of relation matters enormously, and it changes the answer. This document walks through: what these relations actually are (cointegration vs momentum), what the market data shows, why fees keep killing the edge at ₹10–25k, and what (if anything) still has a chance.

---

## 2. Cointegration vs Momentum — the distinction that decides everything

| | **Cointegration (pairs / mean reversion)** | **Momentum (trend / relative strength)** |
|---|---|---|
| Belief | Two assets drift apart but **always snap back** to a fixed ratio | Two assets **keep moving apart** for a while — ride the trend |
| Trade | Buy the gap when wide, sell when it closes | Buy the stronger, sell the weaker, follow the ratio |
| Horizon | Days–months | Days–months (but *directionally* different logic) |
| Danger | Gap never closes (relation breaks) | Reversal (trend ends) |
| Fee impact | High (2–4 legs, round trip) | High (2–4 legs, round trip) |

**Critical:** `correlation ≠ cointegration`. Two things can move together 97% of the time yet never return to a fixed ratio — they just keep drifting together. Only cointegrated pairs give you a *statistical* snap-back to trade. We tested yours:

| Relation (log ratio) | Correlation | ADF coint p | Verdict |
|---|---|---|---|
| NIFTYBEES / BANKBEES (broad vs bank) | 0.97 | 0.63 | **NOT cointegrated** |
| GOLDBEES / SILVERBEES (gold–silver) | 0.93 | 0.34 | **NOT cointegrated** |
| GOLDBEES / NIFTYBEES (gold vs equities) | 0.69 | 0.98 | **NOT cointegrated** |

**None of your candidate relations is cointegrated** (p > 0.05 everywhere). Gold–silver famously reverted in past decades, but in 2023–2026 gold outran silver for long stretches — the ratio **trends**, it doesn't snap back. So your idea is really **momentum on the ratio**, not pairs trading.

*(Copper: no Indian copper ETF exists on NSE and MCX futures aren't on Yahoo — would need an MCX data feed. Not tested here.)*

---

## 3. What I tested (real data)

### Intraday (5-min bars, last 60 days, ₹15,000, Groww-style fees)
Rule: LONG the instrument/ratio when it crosses above its SMA(n), exit when it crosses back (classic momentum). Swept n = 12/24/48 (≈1h/2h/4h).

| Strategy | SMA | Trades | Gross ₹ | Fees ₹ | **Net ₹** |
|---|---:|---:|---:|---:|---:|
| GOLDBEES momentum | 48 | 117 | +1,012 | 4,745 | **−3,733** |
| SILVERBEES momentum | 48 | 115 | +1,343 | 4,649 | **−3,306** |
| NIFTYBEES momentum | 48 | 157 | +26 | 6,333 | **−6,307** |
| GOLD/SILVER ratio | 48 | 158 | −68 | 6,370 | **−6,437** |
| NIFTY/BANK ratio | 48 | 223 | −739 | 9,136 | **−9,876** |
| GOLD/NIFTY ratio | 48 | 115 | +264 | 4,751 | **−4,487** |

**Every single configuration loses.** Even the best (GOLDBEES, SMA48) nets **−₹3,733/60 days** on ₹15k. Fees are 4–6× the gross edge.

### Daily (2023–2026, 3.6 years, ₹15,000)
Rule: LONG the ratio when it's above its SMA(n), exit when it crosses back. Swept n = 10/20/40 days.

| Relation | SMA | Trades | Gross ₹ | Fees ₹ | **Net ₹** |
|---|---:|---:|---:|---:|---:|
| GOLD/SILVER | 10 | 78 | −613 | 3,161 | **−3,773** |
| NIFTY/BANK | 10 | 66 | +415 | 2,646 | **−2,231** |
| GOLD/NIFTY | 20 | 45 | +559 | 1,994 | **−1,434** |
| GOLD/SILVER | 40 | 39 | −2,307 | 1,586 | **−3,894** |

Even on daily bars, gross is near-zero or small and **fees exceed it**. The slowest, most selective versions get closest to breakeven (GOLD/NIFTY SMA20: +₹559 gross vs ₹1,994 fees) — but still lose.

---

## 4. Why everything loses at ₹10–25k in India

1. **Fee floor:** Groww-style ₹5–20/leg means **~₹40–45 per round trip** at these sizes. The gross edge from intraday momentum on liquid Indian ETFs is only **~₹5–12/trade** — fees are 4–6× the edge.
2. **Intraday noise:** on 5-min bars, momentum rules churn (100–470 trades in 60 days) — every whip costs a round trip.
3. **No real edge to harvest:** gross is near-zero *before* fees. These relations are real but weak at the intraday horizon.
4. **The same math every strategy has hit:** at ₹10–25k, an edge that's only ₹1–2/unit (or ₹5–12/trade) cannot beat a ~₹40 fee floor. This is the identical wall that killed the ETF pair bot, single-stock reversion, and the wider stock pairs.

> **The fee structure, not the idea, is the wall.** Your relations ARE real — they just don't move enough per trade to pay Indian intraday fees at ₹10–25k.

---

## 5. A confidence score cannot fix a fee-negative edge

A confidence score is genuinely useful — we proved it on the pair bot (gating on confidence flipped net-negative → net-positive on daily data). But it only helps when the *gross* edge is real and positive. Here the gross is ≈ ₹0–12/trade; a confidence filter would only pick fewer, bigger moves — and the data shows even the most selective config (SMA40/48, fewest trades) still nets negative.

**Confidence scores work on:**
- Trend strength: `(ratio − SMA) / rolling_std` → how far above/below the mean the ratio is
- Momentum rate: `ROC(n)` → % change of the ratio over n bars
- Breadth/agreement: e.g., gold & silver both above their SMAs before trading the ratio

Use them to *pick quality* — not to rescue a strategy whose gross can't pay its fees.

---

## 6. What DOES have a chance in the Indian market at ₹10–25k

Ranked honestly, best → worst:

### 6.1 Passive — NIFTYBEES + GOLDBEES rebalancing (from your own studies)
Your `passive_income_strategy/` work showed 50/50 NIFTYBEES+GOLDBEES returned **+89% over 2023–25 (≈25% CAGR)** with −6.7% max drawdown — because gold and equities move at different times. This is the **only net-positive "relation" strategy in India** at small size. But it's an *investment* (buy & rebalance monthly), not intraday, and it's capital-building: at ~10–12% forward, **₹10k/month needs ~₹10L**.

**Fit for ₹10–25k:** start an SIP here. It builds the capital that later funds everything else.

### 6.2 Slow, selective relation momentum (GOLD/NIFTY, monthly cadence)
If you insist on trading the relations: the least-bad version is **GOLD/NIFTY ratio momentum on a ~20-day SMA**, entered only on high-confidence signals (ratio > SMA + 1σ), held for days, **monthly frequency** (~2 trades/month). Even this is fee-marginal — expect single-digit %/yr at ₹15k, not income. It's a learning vehicle, not an income source.

### 6.3 Intraday at ₹10–25k in India — verdict: not viable on these instruments
Intraday cross-asset momentum on liquid Indian ETFs at this capital is **fee-killed**. Confirmed three different ways this session (pair bot, single-stock reversion, now these relations).

### 6.4 The venue that actually fits small capital: Hyperliquid (crypto perps)
Your own Hyperliquid research is the real answer for small capital — **0.045% taker fees (no ₹5 floor)**, can short, arbitrary size. The same *relation/momentum* thinking applies there (e.g., BTC/ETH, and the 47 screened pairs; basket +202%, Sharpe ~1.0, 26/40 pairs profitable). At ₹10–25k this is the only place the math works. (Caveats: 30% VDA tax, no loss set-off, high variance, MDD −38.6%.)

---

## 7. Risk management for a ₹10–25k account

1. **Never risk > 1% of the account per trade** (₹100–250 on ₹10–25k).
2. Position size from the *risk amount*, not "feels right": `qty = risk ₹ / stop-distance ₹`.
3. Trade **2 legs max** (single instrument) — halves fees vs a 4-leg pair.
4. Fewer, higher-confidence trades beat churn: target ≤ 10 trades/month.
5. Stop-loss on every position (1–2% of account).
6. Paper-trade first; fund only after net-positive over 3 months.
7. Keep fees on the scoreboard in every backtest — if gross < fees, it's not a strategy.

---

## 8. Recommendation

**For your stated goal (₹10–25k, intraday, earn money):**

1. **Do NOT** trade intraday cross-asset momentum on Indian ETFs — the data is unambiguous (every config nets negative to fees).
2. **DO** start the NIFTYBEES+GOLDBEES SIP (₹5–10k/month) — your own studies show it's the one relation strategy that works in India; it builds capital.
3. **DO** put the *relation/momentum + confidence-score* idea where fees can't kill it: **Hyperliquid** (tiny fees, shortable, small-size friendly). Reuse the same ratios (e.g., BTC/ETH, gold-proxy/gold-backed perps) with the confidence-gated momentum logic.
4. Use this MD's numbers to keep expectations honest: **at ₹10–25k, the goal is learning + building capital, not ₹10k/month.**

**One-liner:** *Your relations are real, but Indian intraday fees at ₹10–25k eat 4–6× the edge they produce. Trade the relations where fees are ~0.1% (Hyperliquid) or slowly (NIFTYBEES+GOLDBEES), not intraday on NSE.*

---

## 9. Appendix — formulas & fee math

**Log ratio / "spread":** `s = ln(A) − ln(B)` — the gap between two assets in % terms.
**Ratio momentum signal:** LONG when `A/B > SMA_n(A/B)` and `(A/B − SMA) > σ` (confidence ≥ threshold); exit when it crosses back.
**Confidence score (0–100):** `conf = clamp(((A/B − SMA) / σ − 1) / 2 × 100, 0, 100)`.
**Groww intraday leg fee:** `min(20, 0.1%·V)` (min ₹5) + STT 0.025%(sell) + stamp 0.003%(buy) + exchange 0.00297% + SEBI 0.0001% + IPFT 0.0001% + 18% GST on (brokerage+exchange+SEBI+IPFT).
**Observed costs at ₹15k:** ~₹40–45 per round trip (4-leg ratio), ~₹33 per round trip (2-leg single).

**Data sources:** Yahoo Finance (NSE daily 2023–2026 + 5-min last 60 days). Studies: `~/Documents/studies/trading/` (passive income strategy, ML pairs research, income master guide).

---

*End of document.*
