# Where we are, in one page

**Last updated 8 September 2026**

---

## The situation in five sentences

We have been trying to build an automated trading strategy on Hyperliquid. We have tested about
thirty distinct ideas. **Every one of them has failed**, and they have almost all failed for the
same reason: the profit per trade turned out to be smaller than the cost of making the trade.
One idea is still alive but blocked on a practical problem rather than a statistical one. We
have also had to retract a result we previously reported as good.

---

## The one thing that explains almost everything

> **The edge was real. It was just smaller than the toll.**

Trading on Hyperliquid costs about 0.09% every time you touch a position — 0.36% for a
round trip on a two-legged trade. Here is what our ideas actually earned against that:

| Idea | Earned per trade | Cost per trade |
|---|---:|---:|
| Gold vs gold-token | 0.18% | 0.27% |
| Dual-listed shares (35 companies, 22 years) | 0.23% | 0.40% |
| Buying the day's losers | +59%/yr *before* costs | 314%/yr in fees |
| Overnight stock drift | 0.203% | 0.200% |

That last row is the whole project in miniature. The idea works. It earns three-thousandths of a
percent more than it costs. That is not a business.

---

## What we retracted

We previously reported a strategy with a **Sharpe ratio of 1.48** — a genuinely good number.

Re-running our own code on our own data produces **−3.43**. Not one figure in that report
reproduces, and most flip from positive to negative.

We cannot fully explain how it happened, and the reason we cannot is itself the lesson: **that
research was never put under version control**, so no result could be traced back to the code
that produced it. This directory is version-controlled. That is deliberate.

---

## The one lead still alive — **re-rated 16–17 September 2026**

> This section previously said crude oil perpetuals pay roughly **0.6% per day**, stably.
> **That figure was measured on the one day it was true.** It is not retracted to zero, but it
> is about 6× smaller than recorded and the on-venue hedge removes three quarters of what is
> left. Full working: [CRUDE_CARRY_RECHECK.md](CRUDE_CARRY_RECHECK.md).

| | Claimed | Measured over 6 months |
|---|---:|---:|
| Carry to a long, `xyz:CL` | 0.6%/day (~219%/yr) | **0.09%/day (~33%/yr)** |
| Hedged CL/BRENT | — | **~6%/yr, Sharpe ~0.44** on the carry alone |

Unhedged that is 33%/yr of carry against 64%/yr of price volatility — not investable. Hedged
it survives, but only at low turnover: holding throughout nets +9.09% over six months, and
**weekly rebalancing takes that to +0.19%** as fees eat it. An independent check on the stored
funding panel agrees on direction and order of magnitude, and adds that funding *extremes*
have a median half-life of **2.0 hours** against a pre-registered 6-hour kill criterion — so
the carry is a slow, structural thing, not something to time.

The open question is no longer the funding level but **whether the discount generating it
persists**. That is what the recorder should be measuring.

### Three leads, one shared blocker

| Lead | Where it stands | Document |
|---|---|---|
| Crude carry, hedged | ~6%/yr; dies at weekly turnover | [CRUDE_CARRY_RECHECK.md](CRUDE_CARRY_RECHECK.md) |
| Combined momentum book | Sharpe 1.44, **DSR 0.710** against a 0.95 bar | [SURVIVORS_RECHECK.md](SURVIVORS_RECHECK.md) |
| Fast reversal book | Net Sharpe **1.09 at 3bp**, −0.52 at 4.5bp | [FAST_BOOK_TEST.md](FAST_BOOK_TEST.md) |

**All three terminate at the same question, independently: can we get filled as a maker, and
at what effective cost including adverse selection?** One live datapoint exists — a single day
of paper trading returned **0.00bp median slippage on an $11 order**. That is one small order
on one day, and it is the only evidence in the project on the measurement that decides all
three.

---

## What is running right now — **nothing. The recorder stopped on 10 September.**

A **recorder** that samples every market on Hyperliquid every five minutes — funding payments,
order-book depth, prices — and stores it. Its last written day is **2026-09-10**.

> This is now the most urgent item in the project, and worse than it looks. Polymarket's price
> history is only retrievable for about **six weeks**; everything older returns an empty series,
> including the $1.5bn Trump-2024 market. **Every day the recorder is off is calibration ground
> truth that cannot be backfilled at any price.**

It exists because we have exhausted what our historical data can tell us. We have tested so many
ideas against the same short history that statistically, we can no longer trust anything new we
find in it. The only way forward is to gather data nobody has yet.

It also answers the single question that could change everything: **if we place orders patiently
instead of taking whatever price is offered, do they actually get filled?** That difference is
worth 0.06% per leg — larger than almost every edge we found. It cannot be answered from price
history. It has to be measured live.

---

## Reading order

| Document | What it is |
|---|---|
| **[MASTER_REPORT.md](MASTER_REPORT.md)** | **Start here.** All 38 ideas, the three still alive, and the one question that decides them — in plain English, no statistics required. |
| **[WHAT_WE_ARE_DOING.md](WHAT_WE_ARE_DOING.md)** | The goal, the constraints, and why this is hard |
| **[MASTER_V3.md](MASTER_V3.md)** | The first 30 ideas, and exactly why each one failed |
| **[VENUE_SWEEP_2026-09-17.md](VENUE_SWEEP_2026-09-17.md)** | The most recent 8, measured against the venue filter. First Polymarket results. |
| **[CRUDE_CARRY_RECHECK.md](CRUDE_CARRY_RECHECK.md)** · **[SURVIVORS_RECHECK.md](SURVIVORS_RECHECK.md)** · **[FAST_BOOK_TEST.md](FAST_BOOK_TEST.md)** | The three surviving leads, each rechecked |
| **[CRUDE_OIL_STATS.md](CRUDE_OIL_STATS.md)** · **[CRUDE_OIL_DRAWDOWN.md](CRUDE_OIL_DRAWDOWN.md)** | The crude books measured, then eleven timing overlays on them rejected at equal risk |
| **[PORTFOLIO_DRAWDOWN.md](PORTFOLIO_DRAWDOWN.md)** | **21 Sep.** Drawdown reduction by combining books instead of timing one. The momentum + factor-residual pair at 1/N: Sharpe **1.34**, MaxDD −11.6%, breakeven **40bp/side**, DSR 0.58. Also: both published legs turn out to be the best cell of their own grid, and a zero-edge uncorrelated book does *not* pay for itself. **§7 sizes it in money:** usable band **$37.7k–$445k (£28k–£333k)** at a $1m liquidity floor. |

The detailed technical work, plots and code live in `backtesting/hyperliquid/hip3/` — note that
directory is **not** version-controlled, which is a problem worth fixing.

---

## Update — 16 September 2026

### "Did we find anything?" — the whole project in one table

| Category | Count | Status |
|---|---:|---|
| Strategies tested (Hyperliquid, `MASTER_V3.md`) | ~30 | all failed |
| Instruments swept (crypto / US / India / commodities) | 310 | 6 passed ≈ what chance produces |
| Results retracted | 1 | Sharpe 1.48 → **−3.43** |
| Deaths caused by the fee line alone | **12 of 30** | pattern **A** |
| **Tradeable strategies found** | **0** | — |

**The one durable finding is negative-shaped:** *the edge was real, it was just
smaller than the toll.* Gold vs gold-token 18bp against 27bp cost; dual-listed
ADRs 22.7bp against 40bp; overnight drift 20.3bp against 20.0bp; market making a
0.13–0.75bp spread against 3–6bp of fees.

### Two things still open, and only two

**1. Crude carry — re-rated downward, see `CRUDE_CARRY_RECHECK.md`.**
Rechecked against 6 months of funding data rather than 97 minutes. The 0.6%/day
figure was measured on the first day of a four-day spike; the six-month mean is
**0.09%/day**, and the only on-venue hedge (CL vs Brent, correlation 0.976)
collapses it to **~6%/yr** because the short leg's funding must be paid. Still
the best lead in the project — it rests on venue mechanics rather than a price
pattern — but it is a 6%/yr carry, not a 219%/yr one.

**2. The execution question — still the highest-value open item.**
Taker ~9bp/leg against posted ~3bp/leg. That gap is worth more than every signal
improvement found in this project combined: it turns extended-hours continuation
from +0.8%/yr to ~+31%/yr, the walk-forward equity-pairs book from −0.64 Sharpe
to +0.11, and the fast reversal book from −0.52 to +1.09. It cannot be answered
from price history. The 3bp figure is an assumed constant, and the **only** live
evidence against it is one day of paper trading that returned 0.00bp median
slippage on an $11 order — one small order, on one day, before the harness
stopped.

**If only one thing gets done next, it is item 2** — because roughly a dozen of
the thirty dead strategies were killed by a number that has never actually been
measured.

### What the BTC work adds

Nothing that changes the above. The BTC long/short book reaches Sharpe 1.55
(1.12 excess of the 4% cash rate) with a −11.6% max drawdown, but it is **one
instrument taking ~6 trades a year, single-leg**, and so fails requirements 1, 2,
4 and 6 of `documentation/MAHAN_SPEC.md`. It passes requirement 0 — BTC perps are
native on Hyperliquid, and at 4.5bp would be *cheaper* than the 15bp the backtest
assumes — which makes it a usable paper-trading testbed and not a strategy.

Two real bugs were found and fixed in the course of it, both of which had
inflated published numbers: a `sl_trail` float passed to a boolean parameter
(silently converting a fixed stop into a trailing one), and a backtest loop that
rebalanced to a constant 20% of equity daily at zero cost — which understated max
drawdown as −8.0% when the true figure is **−11.6%**.
