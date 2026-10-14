# Spread Reversion Trading — Plain-English Guide & Report

**What we trade:** BANKBEES vs SETFNIFBK (two ETFs that both track the Nifty Bank index)
**Data:** Yahoo Finance, 2023–2026 daily + last 60 days of 5-minute data
**Strategy:** Buy/sell the *gap* between the two, betting it snaps back to normal.

---

## 1. What is "the spread" and "the spread ratio"?

BANKBEES and SETFNIFBK are two different ETFs that track the **same thing** (the Nifty Bank index). So their prices should move up and down together, always staying in roughly the same ratio to each other.

- **The spread** = how far apart the two prices are, in percentage terms:
  `spread = ln(BANKBEES price) − ln(SETFNIFBK price)` (ln = natural log; using logs just converts "ratio" into a "gap" number that behaves nicely).
- **The spread ratio** = `BANKBEES price ÷ SETFNIFBK price`. Because both track the same index, this ratio should hover near one fixed number (≈ 1.008 in our data). When it drifts away from normal, that's an opportunity.

**The idea (statistical arbitrage):**
- If the spread gets **unusually wide** (BANKBEES is expensive vs SETFNIFBK), we bet it will **shrink back** → sell BANKBEES, buy SETFNIFBK.
- If the spread gets **unusually narrow**, we bet it will **widen back** → buy BANKBEES, sell SETFNIFBK.
- **The z-score** tells us "how unusual": it counts how many standard-deviations the current spread is away from its recent average. `|z| > 2` means "this gap is really abnormal" → that's our entry signal. We exit when the gap returns to normal (z crosses 0).

This is a real, sound idea — the data confirms both ETFs snap back together ~72% of the time. **The strategy isn't broken. The problem is money size vs. fees.**

---

## 2. Why is the quantity "2"? What does that even mean?

**Quantity** = how many units of each ETF you buy/sell in one trade.

The script sizes it from your balance:
```
qty = balance × 50% ÷ (price of A + price of B)
    = ₹5,000 × 0.5 ÷ (₹594 + ₹589)
    = ₹2,500 ÷ ₹1,183
    = 2
```

So with **₹5,000** you can only buy **2 units of BANKBEES and 2 units of SETFNIFBK** per trade. Your whole "investment" per trade is ~₹2,366.

**That's tiny.** And tiny is exactly the problem — see the fee floor below.

---

## 3. The hidden killer: the fee floor (₹5 minimum per order)

Every round-trip trade has **4 orders** (sell A + buy B to enter, then buy A + sell B to exit). Groww charges brokerage per order, and it has a **minimum of ₹5 per order** — even for a tiny order.

| | Fees for 1 round trip |
|---|---|
| 4 orders × ₹5 minimum brokerage | ₹20 |
| STT + stamp + exchange + GST | ~₹4 |
| **Total per round trip** | **~₹24** |

Now compare to what the strategy makes:

| Quantity | Gross profit per trade | Fees per trade | Net |
|---:|---:|---:|---:|
| **2 (₹5k)** | ~₹2 | ₹24 | **−₹22 (loss)** |
| 100 | ~₹87 | ₹136 | −₹49 |
| 300 | ~₹261 | ₹220 | **+₹41** |
| 500 | ~₹435 | ₹304 | **+₹131** |

**Key point:** fees are mostly *fixed* (~₹24 minimum), while profit grows with quantity. At qty=2, fees are **6× bigger** than the profit. That's the whole reason the graph goes down.

---

## 4. How much money do we need? How much quantity?

The strategy only becomes profitable once **profit per trade > fees per trade**. Based on real backtest data:

### Per-unit numbers (intraday, 5-min bars, last 60 days)
- The edge: ~**₹0.87 gross profit per unit per trade** (mean reversion works)
- Fees: ₹24 fixed + proportional (fees per unit drop as qty rises)

### Break-even quantity (intraday): **~200–250 units**
### Safe profitable quantity (intraday): **~300–500 units**

### Capital needed

| Quantity | Total notional | Capital needed (delivery = 100%) | Capital needed (intraday margin @20–33%) |
|---:|---:|---:|---:|
| 100 | ₹1.18 L | ₹1.18 L | ₹24k–39k |
| 200 | ₹2.37 L | ₹2.37 L | ₹47k–78k |
| 300 | ₹3.55 L | ₹3.55 L | ₹71k–1.17 L |
| 500 | ₹5.92 L | ₹5.92 L | ₹1.18–1.95 L |

**Simplest honest answer:**
- With **₹5,000** → qty 2 → **guaranteed loss** (fees eat everything).
- With **~₹1.5–2 Lakh** (intraday margin, qty ~300) → roughly **break-even to modest profit**.
- With **~₹4–6 Lakh** (qty 400–500) → solid profit: backtest shows **~₹9k–14k net in 60 days** intraday.

### Slower, cheaper alternative — trade on daily closes instead
If you can't invest that much intraday, the **daily** version needs far less quantity:

| Quantity | Daily net over 3.6 yrs | Net per year |
|---:|---:|---:|
| 50 | +₹225 | +₹62 |
| 100 | +₹3,848 | +₹1,054 |
| 200 | +₹11,094 | +₹3,040 |

Daily at qty=100 (capital ~₹1.2 L delivery) is **already profitable** — just slowly (~₹1,000/year, ~1% on capital).

---

## 5. What the graphs mean (plain English)

The report saves **`report_equity.png`** with 3 panels:

**Panel 1 — Equity curves (the money graph):**
The line shows your portfolio balance over time, starting at ₹5,000.
- Line goes **up** = making money.
- Line goes **down / flat** = losing or barely breaking even.
- Our configs all go **down** — because of the fee floor at qty≈2, not because the idea is wrong.

**Panel 2 — Fee drag (the smoking gun):**
Two lines for the *same* strategy:
- **Red (with fees):** goes down → you lose money.
- **Green (fees = ₹0):** goes up, Sharpe 2.0, 100% win rate → the strategy genuinely works!
- The gap between them is **purely the fees**. This proves the edge exists and fees are the only reason you're losing.

**Panel 3 — Drawdown:**
Shows how far your balance is below its best point at any time. If the line dips to −15%, it means at that moment you were 15% below your peak. Every config's drawdown grows over time because the balance only ever declines (fees).

---

## 6. The ratios explained (what do these numbers mean?)

| Ratio | What it means | Plain-English rule of thumb | Our base config (₹5k) |
|---|---|---|---|
| **Sharpe ratio** | Profit per unit of risk | >1 good, >2 great, **negative = losing** | **−3.04** (losing) |
| **Sortino ratio** | Same as Sharpe but only punishes *down* moves | >1 good | **−1.36** (losing) |
| **Max Drawdown** | Biggest drop from peak to trough | Small is better | **−14.7%** |
| **CAGR** | Average yearly growth of your money | Positive = growing | **−4.25%/yr** |
| **Profit Factor** | Total winnings ÷ total losses | >1.0 profitable, >1.5 good | **0.00** (losing) |
| **Win Rate** | % of trades that made money | High is nice but fees matter | **3% net** (72% *gross*) |
| **Expectancy** | Average ₹ you make per trade | Positive = you win over time | **−₹20.34** |
| **Calmar** | Return ÷ drawdown | Higher = better reward per pain | −0.29 |

**The catch you must understand:** our *gross* win rate is ~72% (matches the "73.4% high-confidence pair" claim!). But **after fees**, at qty=2, almost every trade loses a little → net win rate 3%, expectancy −₹20. **You win often, but each tiny win can't pay the ₹24 fee.**

---

## 7. Bottom line (in one paragraph)

The pair is genuinely high-confidence: the gap between these two ETFs snaps back to normal ~72% of the time, and the strategy makes money on gross (green line proves it). But with only ₹5,000 you're forced to trade 2 units, and Groww's ₹5-per-order minimum means every round trip costs ~₹24 — six times your ~₹4 profit. **To actually make money you need enough quantity for profits to outgrow the fixed fees: roughly ₹1.5–2 Lakh for intraday (break-even), or ₹4–6 Lakh for a real profit; alternatively the daily version starts making money at ~₹1.2 Lakh (qty 100).** Below that, the strategy is a slow, reliable way to pay fees.
