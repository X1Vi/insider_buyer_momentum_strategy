# Opportunity Map — Groww (NSE India) + Hyperliquid at ₹10–25k

*Every real opportunity we've identified across your two venues, with honest verdicts, Kelly sizing, and a recommended allocation. Data-backed (2023–2026) + from your studies.*

**Date:** 2026-08-29

---

## 1. The constraint, in one line

At ₹10–25k, **NSE intraday edges die to fees** (proven 4 ways this session), and **Hyperliquid is the only venue where small-capital edges survive** (0.045% fees vs Groww's ~0.4% pair round trip). The income guide's own conclusion stands: ₹10k/month needs ~₹10L; at ₹10–25k the goal is **learning + building capital**.

---

## 2. Groww (NSE India) opportunities

| # | Opportunity | Capital | Verdict | Status |
|---|---|---|---|---|
| A | **NIFTYBEES + GOLDBEES 50/50 SIP** | any (₹3–15k/mo) | ✅ **The one net-positive relation in India** (+89% / 25% CAGR 2023–25, MDD −6.7%) | In your studies, verified |
| B | **Weekly BANK NIFTY options selling** (strangle, 5–8% OTM) | ₹30–50k/lot | ⚠️ 90–95% win, ₹1,200–3,200/mo/lot, but 5–10× tail risk; **not backtested**; 80–95% of retail F&O lose | Idea in your guide |
| C | Stat-arb pair bot (BANKBEES/SETFNIFBK) | ₹25k | ❌ **Disproven**: net-negative after fees (intraday −₹1,126 / daily −₹215 at ₹20k) | Killed by our backtests |
| D | Intraday momentum on ETFs / relations | ₹15k | ❌ **Disproven**: every config net-negative, fees 4–6× edge | Killed by our backtests |

**Groww verdict at ₹10–25k:** only **A (SIP)** is viable now. **B (options)** is the closest *trading* income, but needs ₹30k+ and real risk management + paper-trading first. C & D are closed.

---

## 3. Hyperliquid opportunities

| # | Opportunity | Edge | Kelly f* | Verdict |
|---|---|---|---|---|
| A | **Positive-Kelly pairs shortlist**: BSV/ICP, BSV/MINA, BSV/FIL, MINA/FIL | 54–71% win, payoff 2.6–3.1 | 0.37–0.61 | ✅ **The real small-capital engine** (100+ trades each, solid) |
| B | Confidence-gated entries (only |z| well beyond 2) | improves quality | — | ✅ Proven on NSE daily; apply here |
| C | Full basket (all 40 pairs) | 48% win, R 1.68 | 0.167 | ✅ real, but high variance (MDD −38.6%) |
| D | Churn pairs: LTC/XRP, ADA/PYTH, DOGE/PYTH, SAND/IOTA | f* ≈ 0.02–0.05 | ~0 | ❌ Kelly says don't trade |

**Hyperliquid verdict:** this is where a ₹10–25k account can actually **grow** — positive-Kelly, high-Sharpe pairs, sized at **half-Kelly capped by 1–2% risk**.

---

## 4. Recommended allocation for ₹10–25k

**Split capital into two jobs:**

| Bucket | Amount (of ₹10–25k) | What | Why |
|---|---|---|---|
| **Growth (Hyperliquid)** | ₹8–15k | Trade the 4-pair positive-Kelly shortlist, 1–2% risk/trade, compound | The only small-capital net edge (f*=0.37–0.61) |
| **Capital-building (Groww)** | ₹5–10k | NIFTYBEES+GOLDBEES SIP (monthly) | The only net-positive Indian relation; builds the base for options/larger trading later |

**Kelly sizing example (₹10k Hyperliquid, BSV/ICP, half-Kelly 0.30 capped at 1.5%):**
- Risk/trade = 1.5% × ₹10,000 = **₹150**
- Position = risk ÷ stop-distance (≈20×) = ~₹3,000 notional
- 4 pairs, one position each = ~₹12k deployed, each risking ₹150

**Rules (non-negotiable):**
1. Risk ≤1–2% per trade, min(half-Kelly, cap).
2. Trade only positive-Kelly pairs (≥100 trades sample).
3. Stop-loss on every position (the 4σ engine stop).
4. Cut size −3% / pause −6% (BlueCrest rule).
5. Compound — no withdrawals until ₹1L+.
6. Paper-trade Hyperliquid ≥3 months; fund only if net Sharpe ≥1.0.

---

## 5. What to build next (pick one)

1. **Hyperliquid paper trader** (recommended) — a script that runs the 4-pair shortlist with confidence-gated entries, Kelly-sized risk, stop-losses, and logs equity. This is the strongest opportunity and has no live tool yet (your research is backtest-only).
2. **Groww options screener** — for when capital reaches ₹30k+: BANK NIFTY weekly strangle selection with the hard-exit rule, paper-traded first.
3. **Consolidate the docs** — MASTER_DOC + opportunity map + Kelly doc + PDF (mostly done).

---

## 6. Files
- `documentation/OPPORTUNITY_MAP.md` — this document
- `documentation/MASTER_DOC.md` (+ PDF) — everything we know
- `documentation/KELLY_GROWTH.md` — sizing numbers from 37k trades
- `documentation/kelly_analysis.py` — recompute Kelly
- Engine/data: `~/Documents/studies/trading/Machine_Learning_Base_Pairs_Trading/hyperliquid_pairs/`

*End.*
