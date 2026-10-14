# Everything we've tried — plain summary

*One document covering both venues and every approach. Updated 1 Sep 2026.*

---

## The goal

Find a repeatable edge that is **hedged** — information in one market giving a tradeable
signal in another — rather than a directional bet. Small capital (₹10–25k / ~$1,000).

---

## The one-line answer

We tested **13 approaches across two venues**. **One works.** One is real but costs more to
trade than it earns. Everything else is dead. And the biggest single win was discovering that
a strategy we were about to fund was **losing money, not making it**.

---

## Part 1 — Indian stocks (Groww / NSE)

### What we tried
Buy the laggard when two cointegrated stocks gap apart. Long-only, profit margin computed
before entry. Built in Rust, tested on Yahoo data 2023–2026.

### What happened
The idea works statistically — the gap does close ~72% of the time. **Fees kill it.**

At ₹10–25k, a pair round trip costs ~₹24–133 because of the ₹5-per-leg minimum. On a
₹2,400 position that's a wall you cannot trade through. It needs **₹1.2 lakh+** to be
net-profitable.

**Verdict: correct idea, wrong account size.** Proven four separate ways.

---

## Part 2 — Hyperliquid (crypto perps)

We moved here because fees are 0.045% with no minimum — the only venue where small capital
isn't structurally punished.

### The big catch

The first strategy reported **+22.9% a year**. It was actually **−54.5%**.

The backtest only checked its stop-loss every 4 hours. Trades that crashed through the stop
and recovered by the next check were recorded as *wins*. All 11 pairs flipped negative once
that was fixed. An independent audit confirmed it against real hourly data.

**This is the most valuable thing we found — money not lost.**

### What we tested here

| Approach | Verdict |
|---|---|
| **Cross-sectional momentum** | ✅ **WORKS** — +11.8%/yr, running as paper account |
| Intraday reversal | Real signal (+59%/yr gross) but fees cost 314%/yr |
| Funding carry | Real dispersion, unproven on one year of data |
| Pairs / spread reversion | Dead — the stop-loss bug above |
| Cointegration screening | 1,008 pairs tested → **1** survived. That one failed too |
| Minute-scale whale lag | Gap 15bp vs 18bp cost — underwater before you start |
| Daily-scale lag | Being *stricter* made it worse. Confidence score is meaningless |
| Waiting for gaps to close | Gaps **widen**, they don't close |
| Profit targets | Both buy *and* sell looked profitable — impossible, so it was noise |
| Volume confirmation | The setup happens **1.6%** of the time |
| Cross-venue funding | Mechanical difference, not a mispricing. Needs two venues |
| Real whale prints | Big orders don't push price — they slightly pull it back |

### The thing that explains almost all of it

**Fees.** Not slippage — real order books cost 0.0–0.4 basis points at our size; the books
are deep. It's the flat fee: four legs × 4.5bp = **18 basis points per round trip.**

Almost every dead idea above died at exactly that line.

### What does work

**Cross-sectional momentum** — buy the ~10 best performers, short the ~10 worst, hold three
weeks. +11.8%/yr, worst drop −12.8%, genuinely market-neutral.

It works *because* it doesn't claim to know that coin A leads coin B. It spreads across a
hundred names so no single guess has to be right.

It's slow, and it won't feel like trading.

---

## Part 3 — The ML reversal model (Indian stocks, v3)

### What it does
Watch pairs of stocks. When the spread stretches to z < −3, wait 10 days. If the *spread*
recovered but the *price* hasn't, that's a candidate reversal — buy the laggard. XGBoost
ranks the candidates.

### What we found when we tested it

**It is not statistically significant.**

| Target | AUC | 95% confidence range | Verdict |
|---|---|---|---|
| +3%/−2%/10d | 0.573 | 0.417 – 0.729 | includes 0.5 — indistinguishable from random |
| +2%/−2%/10d | 0.590 | 0.451 – 0.729 | indistinguishable from random |
| +3%/−2%/5d | 0.489 | 0.308 – 0.670 | worse than random |

The top-12 ranked picks went 5 wins / 12 — versus 3.4 expected by chance. p = 0.23.
**Indistinguishable from picking at random.**

### Why: not enough events

The gate is very tight — 1,062 raw signals become **115 events**, and only **67** are
out-of-sample. To prove an AUC of 0.59 you need about **300**.

So the model isn't badly built. There simply isn't enough data to know if it works.

### Two concrete bugs found

**1. The labels are wrong ~1 in 6 times.** The model judges win/loss on *closing* prices, but
real trades hit their target or stop *intraday*. Checking against actual highs and lows,
**15–17% of the training labels flip.** On 115 events, that's substantial noise.

**2. Volume is in the data but never used.** A free feature set, unused.

### The fix that matters most

**More events.** The universe can expand from **18 to 44 stocks** (all fetchable), which
scales events to ~280 and out-of-sample to ~163. Combined with multiple observation windows
that crosses into significance territory.

*Note: the v4 rebuild was started but stopped partway through the audit stage — no v4 code
exists yet. The audit findings and the plan are what's captured here.*

---

## What's running right now

| | Status |
|---|---|
| Hyperliquid trade collector | **Live** — capturing every large order. 85,000+ prints today |
| Momentum paper account | Live, day 1, 18 positions, exposure neutral |
| Candle collector | 5 days stored, needs a daily cron job |

---

## The pattern across everything

Every promising result we investigated had one of these in it:

| Trap | What it did |
|---|---|
| Checking stops only every 4 hours | Turned −54% into +23% |
| Testing thousands of pairs without correcting for luck | 55 "great" pairs → 1 real |
| Leaving out coins/stocks that got delisted | Hid that shorts would've been short the dying ones |
| Judging trades on closing prices | 1 in 6 labels wrong |
| Picking a start day for a 3-week cycle | Same strategy scored −0.38 to +1.43 |
| Quoting a Sharpe or AUC without its error bar | "0.84" was really "0.84 ± 0.82" |
| Fitting and testing on the same data | 2.43 collapsed to 0.49 on fresh data |
| Counting overlapping trades as independent | "1,400 trades" was really 241 days |

**The lesson: anything that looks good on the first pass probably has one of these in it.**
Thirteen dead ends is a good outcome — they were dead before we started, and the alternative
way to find out costs money.

---

## What's actually left

1. **Post orders instead of taking them.** Fees killed nearly everything. Taking costs 4.5bp,
   posting costs 1.5bp, breakeven is 1.8bp. This single change could revive the +59%/yr
   signal. **Untested — highest value item.**
2. **More data for the ML model.** 18 → 44 stocks, plus honest intrabar labels. That's the
   difference between "we don't know" and an answer.
3. **Keep the momentum paper account running.** It works; it needs patience.
4. **Large whale orders over more time.** First read is discouraging, but it's one session.
