# The idea, and how it measures against your spec

16 Sep 2026. Short read. Everything below is out-of-sample unless it says otherwise.

---

## The idea in four lines

Every 4–8 hours, rank the ~130 liquid Hyperliquid perps by how they moved over the
last 8 hours. **Short the ones that just ran up, buy the ones that just sold off,
equal dollars each side.** Hold 4–8 hours, then re-rank. About 31 names on at any
time, roughly 5–7 turns a day.

It is a bet that short-term moves overshoot and come back. No coin is ever picked
by hand — it is a ranking rule and nothing else.

---

## Against your spec

| # | What you asked for | Status | Evidence |
|---|---|---|---|
| **0** | Hyperliquid or Polymarket only | **PASS** | Hyperliquid native perps, nothing else |
| **1** | Not one instrument | **PASS** | 147 coins, **45 of them delisted** — no survivorship bias |
| **2** | A process, not a hand-picked name | **PASS** | Pure ranking rule. No name is ever chosen. |
| **3** | Train and test separated | **PASS** | Chosen on data to Oct 2025, scored only on the 10 months after |
| **4** | Enough trades a day, across instruments | **PASS** | **5–7 turns/day, ~31 names held** |
| **5** | Market neutral, works in a down market | **PASS** | beta to BTC **+0.001**, beta to market **−0.020** |
| **6** | Hedged, one long one short | **PASS** | Long the bottom quintile, short the top, dollar-neutral every bar |
| **7** | Sellable | **PARTIAL** | See the honest part below |

**This is the first thing in the project that passes all of them.** The momentum
book we had before failed #4 — it held for 20 days and traded 1.2 times a year,
which is an investment tilt, not a strategy.

On #5, one number is worth calling out because it is exactly your concern:

| | Return per bar |
|---|---:|
| Bars when the market **fell** | **+8.34bp** |
| Bars when the market **rose** | −0.06bp |

It makes everything in down markets and nothing in up markets. That is the
opposite failure mode to being naked long — but it is still regime-dependent, and
you should know that rather than hear "market neutral" and stop.

---

## The honest part

The signal is real and it is the strongest we have found. Out of sample, before
costs, it runs at **Sharpe 2.3 to 4.3**.

The problem is that all of the profit lives inside four basis points of cost:

| Cost per side | What that is | Net Sharpe (best config) |
|---|---|---:|
| 0.0bp | perfect fill | 4.30 |
| **1.5bp** | maker fee only | **2.69** |
| **3.0bp** | maker + 1.5bp slippage | **1.09** |
| 4.5bp | taker fee | −0.52 |

Every 1.5bp of cost removes about 1.6 of Sharpe. At taker fees nothing works.

**Two things stop me calling this a strategy yet:**

1. **Ten months of test data is not enough.** The deflated Sharpe — which adjusts
   for the fact that we have now tried ~80 variants against this venue — comes out
   at **0.07 against a bar of 0.95**. At this sample length the result cannot be
   told apart from the luckiest of 80 attempts.

2. **We cannot pick the winning configuration in advance.** The best single config
   nets Sharpe 1.09 at 3bp. Hold all six of the good ones — which is what you would
   actually do, not knowing which — and you get **Sharpe 0.11**, because they
   correlate 0.73 and you end up averaging in the weak ones.

---

## What we are asking for

One measurement, not more research: **can we get filled as a maker, and at what
real cost once adverse selection is counted?**

That single number decides it. At 1.5bp this is a strategy. At 3bp it is marginal.
At 4.5bp it is dead. Nothing in the price history can answer it — it needs orders
posted on the book and watched.

It is also the same question that blocks the other two live leads (the crude carry
trade and the slow momentum book), so it is worth doing once and properly.

**Proposal: one week to run the paper harness live and measure fill rates and
effective cost.** If it comes back at 3bp or worse, we stop and say so.

---

## What we are not claiming

- Not that it makes money. The test window is 10 months and the deflated Sharpe
  says we cannot distinguish it from luck yet.
- Not that the 4.30 gross Sharpe is achievable. It requires free execution.
- Not that we can pick the right configuration. We measured that we cannot.
