# PLAN — Insider bias + price-action/trend overlay

**2026-10-13.** How to combine the insider signal with other logic (price action,
trend, momentum) to try to get a better result. Companion to `EVERYTHING.md`.
Research only; not investment advice.

---

## 0. The situation, stated plainly

After a major insider buys, the price **does** tend to go up — but **slowly and
unreliably**:

- Average excess vs Nifty: **+0.7% at 5 days → +25% at 250 days** (median +12%).
- But **30% of events (KNIFE) end down ≥5%** over the year.
- Time-to-peak: most events peak at **day 250** — i.e. the move is a *drift*, not a
  pop. Only **18% (FAST)** react within days.

**So "the trend is definitely upwards" is only ~70% true, and it takes a year.**
That is exactly why a fixed 20-day hold fails: it captures almost none of the drift
and all of the KNIFE.

**The reframe:** the insider buy is a **bullish bias / watchlist trigger**, not a
timing signal. Trade the **trend** it creates — enter on confirmation, ride it with
a trailing exit, cut it when it breaks.

---

## 1. What to combine

| Layer | Role | Options |
|---|---|---|
| **Insider buy** | the "who" — a bullish bias + candidate list | promoter/director/KMP, ≥ ₹25L |
| **Price action** | the "when to enter" | Donchian breakout (20-day high); close > 200-DMA; RSI recovery; volume surge |
| **Trend / exit** | the "when to leave" | trailing Donchian (10-day low); ATR trailing stop; close < 50-DMA |
| **Risk** | sizing | stop = 2% of capital; ATR-scaled position |
| **Selection** | which names | FAST reactors (STLTECH, JKLAKSHMI, AARTISURF, JSWHL, TFCILTD, COFORGE, MANGLMCEM) or any stock ≥X% FAST |

The point of the overlay: **let the winners run** (capture the fat right tail — e.g.
STLTECH +170% over the year) while the trailing stop **cuts the KNIFE names early**.

---

## 2. First proof-of-concept (already run) — honest result

`trend_overlay.py`: insider trigger → watch 60 days → buy next open after a
**20-day breakout** → exit on a **10-day-low trailing stop** (max hold 250 days).
Pooled across the 18-name basket:

| metric | value |
|---|--:|
| trades | 1,177 |
| win rate | 0.41 |
| avg net/trade | +1.29% |
| Sharpe | **0.05** |
| max drawdown | −24.5% |
| Calmar | 0.01 |
| exposure | 54% |
| avg hold | 31 days |
| **out-of-sample (2024+)** | **−1.33% avg/trade** |

**Verdict of the PoC: no improvement.** The breakout entry is too loose — the book
is long ~54% of the time (it is really a plain trend-follower), Sharpe ≈ 0, and the
OOS is negative. So *this particular* overlay does not work. The next designs must
be **tighter** (a short window after the insider buy, stronger confirmation) and
**risk-managed**.

---

## 3. Designs to test next (pre-registered)

Each is a separate, bounded experiment. Do them one at a time; keep parameters
fixed; judge on the placebo.

**V1 — Tight catalyst window.** Enter only if the breakout happens within **5 days**
of the insider disclosure (not 60). Rationale: trade the *fresh* catalyst, not any
uptrend months later.

**V2 — Bias + relative strength.** Enter when insider buys **and** the stock is
above its 200-DMA **and** outperforming its sector index over 20 days. Exit on a
trailing ATR stop. Rationale: only trade the names the market is already rewarding.

**V3 — Buy the pullback in an uptrend.** After the insider buy, wait for a shallow
pullback (e.g. RSI dips to 40–50 while price stays above the 50-DMA), enter on the
first up-day. Exit on trend break. Rationale: better entry price, less falling-knife.

**V4 — FAST-reactor basket only.** Restrict to stocks whose own history is ≥X% FAST
events (or the named fast reactors), 1–5 day holds. Rationale: this is the subset
that actually pops.

**V5 — Insider + volume confirmation.** Require a volume surge on the entry day.

**Control:** random entries with the *same* exit rule → the placebo. **If a variant
does not beat its placebo, it is dead.**

---

## 4. Metrics every run must report

Sharpe, CAGR, max drawdown, **Calmar**, win rate, avg net/trade, avg hold,
exposure, IS/OOS split, block-bootstrap Monte-Carlo, and the random-entry placebo.
Plus the ₹8,000 account estimate.

---

## 5. Maximising revenue — the honest levers

1. **Fat right tail.** The only reason to keep this alive is the big winners
   (STLTECH-type). A **trailing stop** is what captures them — not a fixed hold.
2. **Risk-first sizing.** With ₹8,000, risk ~2% (₹160) per trade; size = risk ÷ stop
   distance. This makes the ₹ estimate realistic (whole shares, variable size).
3. **Selectivity.** Fewer, higher-quality entries beat many weak ones — the 18-name
   basket gave ~2 trades/year; broadening adds noise, not edge.
4. **Compounding only after proof.** Do not size up until a variant beats its
   placebo out-of-sample.

---

## 6. The live layer (if "Tauri" = the Rust app)

The `OSINT/MASTER_PLAN.md` targets a **Rust/TUI (Tauri-style) app**. If the goal is
to run this live, the natural build is a **watcher**:

1. Poll the NSE PIT API (free) for new major buys → alert.
2. For each alert, track the price-action entry conditions (breakout / 200-DMA /
   pullback) and the trailing exit.
3. Log paper trades and P&L (paper-only, per repo rules).

That app is only worth building **after** a variant clears the gate in §3.

---

## 7. Gates / when to stop

- Any variant that does not beat its random-entry placebo (out-of-sample) is **dead**
  → move to `strategy_categories/dead/`.
- If none of V1–V5 beats the placebo, the whole insider family is dead and we stop.
- Do not add names or parameters to rescue a failing cell (multiple-testing trap).

---

## 8. Files

- `trend_overlay.py` — the PoC (insider + Donchian breakout/trend exit).
- `data/trend_overlay_trades.csv` — its trades.
- `backtest_insider.py`, `patterns.py`, `estimate.py` — the rest of the toolkit.
- `EVERYTHING.md` — all prior findings and mistakes.

*Research only; not investment advice.*
