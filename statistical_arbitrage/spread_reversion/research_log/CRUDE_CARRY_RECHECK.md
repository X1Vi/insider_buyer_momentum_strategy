# Crude carry on Hyperliquid — rechecked against 6 months of data

**Checked 16 September 2026.** Source: Hyperliquid `fundingHistory` and
`candleSnapshot`, `xyz:CL` and `xyz:BRENTOIL`, 4,320 hourly funding points and
181 daily bars, 20 Mar → 16 Sep 2026.

**Verdict: the lead is real but roughly 6× smaller than recorded, and the only
hedge available on-venue removes three quarters of what is left.**

---

## What the log said

> "Crude oil perps on Hyperliquid pay holders roughly **0.6%/day**, and it is the
> most stable measurement in the dataset (`xyz:CL` moved 9pp across 97 minutes…)"
> — `research_log/MASTER_V3.md`, 8 Sep 2026

## What six months of data says

| | Claimed | Measured (6 months) |
|---|---:|---:|
| Carry to a long, `xyz:CL` | 0.6%/day (~219%/yr) | **0.0898%/day (~33%/yr)** |

**The 0.6%/day was measured on the one day it was true.** The daily series around
the measurement:

| Date | Carry to a long |
|---|---:|
| 2026-09-05 | −0.02% |
| 2026-09-06 | −0.00% |
| 2026-09-07 | +0.13% |
| **2026-09-08** | **+0.60%** ← the note was written this day |
| 2026-09-09 | +0.72% |
| 2026-09-10 | +0.82% |
| 2026-09-11 | +0.81% |
| 2026-09-12 | +0.00% |
| 2026-09-13 | −0.02% |
| 2026-09-15 | +0.02% |
| 2026-09-16 | +0.00% |

The "97 minutes" stability check measured stability *within* a spike. It could
not have detected that the spike was a spike. This is failure pattern **D**
(too few observations) wearing the costume of a stability test.

## It is episodic, not a yield

Over 181 days, total carry to a long was **+16.16%**:

- best **5 days** = +5.66% → **35% of the total**
- best **10 days** = +9.44% → **58% of the total**
- days that paid a long at all: **82 of 181 (45%)**
- **July 2026 was net negative** — a long *paid* 0.41% that month
- monthly spread: −0.41% (Jul) to +6.55% (Apr)

A number that arrives in five days out of six months is not income, it is a
series of events.

## Unhedged is not a trade

| | |
|---|---:|
| `xyz:CL` daily price vol | **3.34%** (64% annualised) |
| Carry | 0.0898%/day |

Price risk is **37× the daily carry**. The log already said this; it is confirmed.

## The only on-venue hedge, and what it costs

Hyperliquid has no crude spot, so the sole hedge is Brent against WTI.

| | |
|---|---:|
| CL / BRENT daily return correlation | **0.976** |
| Spread daily vol | 0.74% (14% annualised), down from 3.34% |
| **Carry, long CL / short BRENT** | **+0.0170%/day = +6.2%/yr** |
| Implied Sharpe if carry were the only edge | **0.44** |

The hedge works — correlation 0.976 cuts price vol by 78%. But **you pay the
short leg's funding**, and Brent's carry is nearly as negative as WTI's
(0.0728%/day vs 0.0898%/day), so only the *difference* survives: 6.2%/yr, not
33%/yr.

## The trap in the headline number

Long CL / short BRENT returned **+9.45%** over the six months. Decomposed:

| Component | 6 months |
|---|---:|
| **Price** (the WTI–Brent spread moved in our favour) | **+6.39%** |
| **Carry** (what the strategy claims to harvest) | +3.06% |
| Fees, one round trip, 2 HIP-3 legs @ ~9bp | −0.36% |
| **Net** | **+9.09%** |

**Two thirds of that is a directional bet on the WTI–Brent spread**, not carry.
It could as easily have gone the other way. Quoting +18%/yr for this strategy
would be repeating exactly the error that killed items 5, 16, 17, 18 and 19 — a
fitted hedge ratio dressed as a neutral position.

The honest number is the carry line: **+6.2%/yr gross, ~5.5%/yr after one round
trip**, on a spread carrying 14% annualised vol of its own.

Rebalancing frequency matters more than the signal:

| Rebalance | Fees over 6m | Net |
|---|---:|---:|
| Hold throughout | 0.36% | +9.09% |
| Monthly | 2.16% | +7.29% |
| **Weekly** | **9.26%** | **+0.19%** |

At weekly turnover the fee line eats it entirely — the same wall as the other
twelve.

## Where this leaves the lead

Still the best thing in the project, and still for the right reason: it rests on
a structural fact about the venue rather than a pattern in a price series. But it
must be re-rated.

- **Not** 0.6%/day. **0.09%/day unhedged, 0.017%/day hedged.**
- Unhedged: 33%/yr of carry against 64%/yr of price vol. Not investable.
- Hedged CL/BRENT: **~6%/yr carry, Sharpe ~0.44 on the carry alone**, plus
  unhedged exposure to the WTI–Brent spread itself.
- Capacity is not the binding constraint: `xyz:CL` shows $194m OI and $342m
  24h volume; BRENT $178m and $212m.

**What would change the verdict:** whether the discount that generates the
funding is persistent or mean-reverting. If `xyz:CL` trades at a structural
discount to its oracle because HIP-3 markets are hard to arbitrage, the carry is
durable. If the discount closes, the price loss offsets the funding gain. Six
months is not enough to separate these, and the current snapshot (mark 99.368 vs
oracle 99.400, a −0.03% discount, funding near zero) says the discount is
currently absent.

That is the measurement the recorder should be making — **discount persistence**,
not funding level.

---

*Reproduce:* Hyperliquid `POST /info` with `{"type":"fundingHistory","coin":"xyz:CL","startTime":…}`
— note the endpoint returns the **first** 500 points from `startTime`, so it must
be paginated forward or you will silently analyse the oldest window available.
