# Applying Kelly Criterion to Grow — Real Numbers from Our Backtests

*How to size positions to grow a ₹10–25k account, computed from 37,361 real Hyperliquid walk-forward trades (net of fees + funding), consistent with the Kelly guidance already in your studies.*

**Date:** 2026-08-29 · **Source data:** `~/Documents/studies/trading/Machine_Learning_Base_Pairs_Trading/hyperliquid_pairs/` (cached candles + walk-forward engine)

---

## 1. The Kelly formula (from your own studies)

```
f* = W − (1−W) / R        where:
  W  = win probability (fraction of trades that win)
  R  = payoff ratio = average win / average loss
  f* = fraction of your account to risk on this trade (growth-optimal)

Continuous version:  f* ≈ mean / variance of per-trade returns
```

Your studies (Market Wizards / Chan / income guide) are unanimous:
- **Use HALF-Kelly, not full Kelly** — full Kelly is the "edge of ruin"
- **Growth scales with Sharpe², not raw return** (prefer high-Sharpe, low-beta)
- **1% risk rule:** never risk >1% of equity per trade as a hard cap

---

## 2. What our data says (computed from 37,361 trades)

### The basket (all tradeable pairs pooled)
| Metric | Value |
|---|---|
| Trades | 37,361 |
| Win rate (W) | 48% |
| Avg win | +6.09% |
| Avg loss | −3.63% |
| Payoff ratio (R) | 1.68 |
| **Kelly f\*** | **0.167 (16.7% of account per trade)** |
| **Half-Kelly** | **0.084 (8.4%)** |
| continuous f\* (μ/σ²) | 0.81 (over-optimistic for fat tails — prefer discrete) |

**On ₹15,000:** Full Kelly = ₹2,505 risk/trade · **Half-Kelly = ₹1,253 risk/trade**

### Best pairs by Kelly (this is the real filter)
| Pair | Trades | Win% | Payoff R | Kelly f* | Half-Kelly |
|---|---|---:|---:|---:|---:|---:|
| VIRTUAL/ICP | 7 | 86% | 8.17 | 0.84 ⚠️ | 0.42 |
| BSV/MOVE | 9 | 78% | 20.7 | 0.77 ⚠️ | 0.38 |
| kSHIB/S | 14 | 71% | 6.6 | 0.67 ⚠️ | 0.34 |
| BSV/S | 17 | 71% | 5.1 | 0.65 ⚠️ | 0.32 |
| **BSV/ICP** | 220 | 71% | 2.8 | **0.61** | 0.30 |
| **BSV/MINA** | 114 | 70% | 2.7 | **0.59** | 0.30 |
| **BSV/FIL** | 126 | 66% | 3.1 | **0.55** | 0.27 |
| **MINA/FIL** | 356 | 54% | 2.6 | **0.37** | 0.18 |
| APT/FIL | 911 | 50% | 2.1 | 0.26 | 0.13 |
| FIL/ICP | 1,657 | 47% | 1.8 | 0.18 | 0.09 |

**Pairs Kelly says NOT to trade (f* ≈ 0.01–0.05, edge effectively gone after costs):**
LTC/XRP (0.053, 8,718 trades), SAND/IOTA (0.052), ADA/PYTH (0.035), DOGE/PYTH (0.031), BSV/WIF (0.022), FIL/WIF (0.13→small), kSHIB/FIL (0.106 but 8,085 trades of churn).

---

## 3. How to actually apply it to grow a ₹10–25k account

### Rule set (combining Kelly + your studies' risk rules)
1. **Trade only positive-Kelly pairs** — Kelly is a clean filter: if f* ≤ 0, there's no edge after costs (this also confirms: don't trade the NSE/Groww strategies at small size — their Kelly is ≤ 0).
2. **Size at half-Kelly, capped by the 1% rule:** `risk_per_trade = min(half-Kelly, 1–2%) × account`.
   - ₹15,000 → risk ₹150–300/trade (not ₹1,253 that half-Kelly suggests — the 64% stop-out rate and fat tails demand the cap).
3. **Prefer high-Sharpe pairs** (BSV/ICP, BSV/MINA, BSV/FIL, MINA/FIL) — growth scales with Sharpe². The ⚠️ high-Kelly pairs have only 7–17 trades; **don't trust Kelly on <30 trades** (small-sample Kelly overstates).
4. **Position size from risk, not notional:** `qty = risk_₹ / stop_distance_₹` (stop = the pair's ~4σ level, per the engine).
5. **Compound — don't withdraw** while ≤ ₹25k. At 1% risk with a positive-Kelly edge, growth is slow-but-safe; at ₹15k expect single-digit ₹/month early, accelerating as the base grows.
6. **Cut size after drawdowns** (BlueCrest rule from your studies): −3% → halve allocation; −6% → pause.

### Concrete ₹15,000 example (BSV/ICP, half-Kelly 0.30 but capped)
| Cap used | Risk/trade | ₹ at 15k | Position notional (≈20× risk) |
|---|---:|---:|---:|
| 1% rule | ₹150 | 150 | ~₹3,000 |
| 2% rule | ₹300 | 300 | ~₹6,000 |
| Half-Kelly (unsafe) | ₹4,500 | 4,500 | ~₹90,000 |

→ Use **1–2% (₹150–300)**. That's ~1/15th of half-Kelly — deliberately far below the growth-optimal point, because 64% of trades hit the stop and the basket's worst stretch was −38.6%.

### What Kelly says about the whole picture
- **Hyperliquid basket: real edge (f*=16.7%).** This is where growth is possible at ₹10–25k.
- **NSE/Groww at ₹10–25k: Kelly f* ≤ 0** (edge < fees). Kelly's verdict: don't trade it — use it only for the long-term NIFTYBEES+GOLDBEES SIP (compounding, not trading).
- **Growth expectation:** with 1% risk on a positive-Kelly, high-Sharpe pair, annual growth is roughly `Sharpe²-scaled` — realistic target is **learn + compound** at this size; ₹10k/month still needs ~₹10L.

---

## 4. Honest caveats (the studies' own warnings, now quantified)

- **Small-sample Kelly lies:** VIRTUAL/ICP shows f*=0.84 on 7 trades — meaningless until it has 100+.
- **Fat tails:** continuous f* (0.81) > discrete Kelly (0.167) — the gap is the tail risk. Trust the conservative number.
- **64% of trades exit via stop-loss** — sizing for the median trade, then getting hit by the 4σ stop repeatedly is exactly why full Kelly ruins accounts.
- **Selection bias:** pairs were chosen on the same data tested. Kelly on in-sample data overstates forward edge.
- **VDA tax (30%)** applies to realized gains — subtract before expecting Kelly-like compounding.

---

## 5. Bottom line

- **Kelly is the answer to "how much to bet to grow":** half-Kelly, capped at 1–2% risk, on positive-Kelly, high-Sharpe Hyperliquid pairs. **Compound.**
- **Kelly is also the filter for "what to trade":** if f* ≤ 0, don't. That kills the NSE/Groww small-capital path and the churn-y crypto pairs (LTC/XRP, ADA/PYTH, DOGE/PYTH).
- **At ₹10–25k:** growth is real but slow. The plan is: 1–2% risk/trade on 4–6 positive-Kelly pairs, compound, expect to learn + grow — not ₹10k/month yet.

---

## 6. Files
- `documentation/kelly_analysis.py` — recompute Kelly from the walk-forward engine (cached candles)
- `documentation/KELLY_GROWTH.md` — this document
- Engine + data: `~/Documents/studies/trading/Machine_Learning_Base_Pairs_Trading/hyperliquid_pairs/`

*End.*
