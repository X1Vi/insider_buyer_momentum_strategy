# Venue sweep — every angle measured against Mahan's spec

**16–17 September 2026.** Extends `MASTER_V3.md`. Where this contradicts an earlier
document, this one is later and the numbers below are reproducible from the code paths
in §9.

Two days of measurement against the requirement-0 venue filter. **Eight routes were
tested: six are closed, one is re-rated rather than dead, one is a volatility view rather
than an arbitrage — and every remaining thread in the project terminates at the same
unanswered measurement.**

Read with [CRUDE_CARRY_RECHECK.md](CRUDE_CARRY_RECHECK.md),
[SURVIVORS_RECHECK.md](SURVIVORS_RECHECK.md) and [FAST_BOOK_TEST.md](FAST_BOOK_TEST.md),
written in parallel on 16 Sep; two of them hold results closer to viable than anything
here. See §6b.

---

## Contents

1. [The finding in one page](#1-the-finding-in-one-page)
2. [Requirement 0 — the venue filter](#2-requirement-0--the-venue-filter)
3. [The sweep, in one table](#3-the-sweep-in-one-table)
4. [Hyperliquid results](#4-hyperliquid-results)
5. [Polymarket results](#5-polymarket-results)
6. [Off-venue work — method kept, strategy out of scope](#6-off-venue-work--method-kept-strategy-out-of-scope)
6b. [Reconciliation with the 16 September rechecks](#6b-reconciliation-with-the-16-september-rechecks)
7. [Three claims corrected](#7-three-claims-corrected)
8. [What is still open](#8-what-is-still-open)
9. [Reproduction](#9-reproduction)
10. [Caveats that apply throughout](#10-caveats-that-apply-throughout)

---

## 1. The finding in one page

Every *structural* objection Mahan raised is now answerable inside the venue filter.
Breadth, process, hedging, neutrality and trade count are all demonstrably achievable —
requirement 4, the one furthest off a week ago, is comfortably met at 31 Polymarket
markets resolving per day. What has not appeared is an edge that exceeds its own cost
line.

That is now a measured finding rather than an absence:

> **On Hyperliquid the cost line is 36–40bp and nothing clears it. On Polymarket the
> market is well calibrated, which is the same statement from the other direction — the
> prices are right, so there is nothing to take.**

Both venues are efficient at the scale a small account operates at. The three places
inefficiency was supposed to live — funding extremes, liquidity subsidies, longshot bias
— each turned out to be competed away or too small to measure against its spread.

Two measurements would change this assessment and **neither is a new signal**:

| | What it would settle |
|---|---|
| **Do posted orders fill at ~3bp?** | Decides four independent threads at once (§6b): the pairs book (−0.64 → +0.11), the fast reversal book (−0.52 → 1.09), crude carry, and the momentum book |
| **A year of recorded data** | Makes the Polymarket calibration study properly powered instead of resting on 31 days; makes the ladder's vol question answerable across many expiries; and settles whether crude's discount persists |

If neither delivers, the honest conclusion is that these two venues at this account size
do not contain a strategy meeting requirement 7. That is a legitimate answer to give.

**One qualification on the paragraph above.** Read alone this document is more negative
than the evidence warrants. The 16 September rechecks (§6b) show a fast reversal book at
net Sharpe **1.09 at 3bp** on a survivorship-free panel and a momentum book at Sharpe
**1.44, DSR 0.710** against a 0.95 bar. Neither clears the project's own standard, but both
are far closer than anything measured here, and both fail on the *same* unanswered
question. The sweep below closes routes; it does not close the project.

---

## 2. Requirement 0 — the venue filter

> *"can you trade it on hyperliquid or polymarkets?"*

**Hyperliquid and Polymarket only. A hard filter, applied before anything else is
scored.** Recorded in `backtesting/hyperliquid/hip3/MAHAN_BRIEF.md` as his requirement
#1 and omitted when the seven in `documentation/MAHAN_SPEC.md` were written down; added
back as requirement 0 on 16 Sep 2026.

### What it leaves

| Venue | Tradeable | Note |
|---|---:|---|
| Hyperliquid native perps | **64** | crypto |
| Hyperliquid HIP-3 | **60** | equities, commodities, FX, indices |
| **Total Hyperliquid** | **124** | of 304 scanned, after a ≥$500k/day liquidity filter |
| Polymarket | 25,361 | resolved binaries ≥$25k volume since 2020; trading access gated on the legal question |

### Three consequences, all binding

1. **124 names is a small universe** for a breadth strategy, split across asset classes
   that cannot sensibly be paired with one another.
2. **A two-legged round trip costs 36–40bp** — 5–10× any conventional equity venue, and
   the reason 12 of 30 strategies in `MASTER_V3.md` died. Under this filter, cost is the
   binding constraint.
3. **History is short.** Hyperliquid: ~5,000 bars (~7 months) from the candle endpoint.
   Polymarket: price history retrievable for **~6 weeks only** (see §7.1).

---

## 3. The sweep, in one table

| # | Angle | What decided it | Verdict |
|---|---|---|---|
| 1 | Funding carry (extremes) | Median extreme half-life **2.0h** vs a pre-registered 6h kill line | **Closed** |
| 2 | The crude-oil lead | Re-rated 0.6%/day → **~0.09%/day**, ~6%/yr hedged; dies at weekly turnover | **Re-rated, not closed** |
| 3 | Crypto pairs on perps | Sharpe **−0.43 at zero cost**, 2,751 trades, 7.2 OOS years | **Closed** |
| 4 | Funding as a return signal | Rank IC 0.01–0.03, best t = **1.46**, sign opposite to the thesis | **Closed** |
| 5 | Cross-listing funding carry | Only **2 pairs exist**; 1 clears cost and is halving monthly | **Fails breadth** |
| 6 | Polymarket calibration / longshots | Brier skill **+0.53**; selling loses at 6 of 8 thresholds net of spread | **Closed** |
| 7 | Polymarket LP rewards | 4.5c reward band vs **0.1c** median quoted spread | **Closed** |
| 8 | Barrier ladder vs the perp | No model-free arb; implied vol 35% vs realised 39–44% | **A vol view** |
| — | **Maker fills on Hyperliquid** | One day of paper trading: **0.00bp on an $11 order**. Decides four threads | **OPEN** |

---

## 4. Hyperliquid results

### 4.1 Funding carry fails its own kill criterion

`HYPERLIQUID-POLYMARKET-RESEARCH-PLAN.md` pre-registered the test in August:
*"median funding-extreme half-life < 6 hours and the strategy is dead. This single
measurement decides it."* Five months of hourly funding across 148 markets had been
accumulating since April and the test had never been run.

**Persistence** (extreme = |annualised funding| > 50%; 137 markets with ≥10 extreme hours):

| Measure | p25 | Median | p75 |
|---|---:|---:|---:|
| Hours to decay to half | 2.0 | **2.0** | 3.0 |
| Run length of an extreme (hrs) | 1.0 | 1.0 | 2.0 |
| Share of time in extreme | 2.1% | 5.4% | 14.6% |

Markets whose extremes persist beyond 24h at the median: **0 of 137.**

Run length alone would be an unfair test — funding oscillating around a threshold still
pays. So the trade was run properly: enter on an extreme, take the receiving side, hold,
sum what actually arrives, charge a 60bp hedged round trip.

| Hold | Episodes | Collected | Net of 60bp | Profitable |
|---|---:|---:|---:|---:|
| 6 hours | 14,554 | 1.7 bp | −58.3 bp | 0.2% |
| 24 hours | 14,417 | 4.2 bp | −55.8 bp | 1.2% |
| 72 hours | 14,039 | 9.4 bp | −50.6 bp | 6.2% |
| 1 week | 13,712 | 19.6 bp | −40.4 bp | 16.3% |
| 1 week, top 12 markets | 3,626 | 24.2 bp | −35.8 bp | 31.2% |

**The sharper result:** holding the prevailing funding sign *without timing the entry at
all* collects **5.2bp/day and 31.7bp/week** — more than waiting for an extreme. The
extremity signal is not merely too small to trade; it is **worse than not using it**.

### 4.2 The crude-oil lead is re-rated, not closed

**See [CRUDE_CARRY_RECHECK.md](CRUDE_CARRY_RECHECK.md) (16 Sep) for the authoritative
version** — it pulls `fundingHistory` directly from the API over six months (20 Mar –
16 Sep, 4,320 hourly points) and is a better measurement than mine, which used the stored
panel. Its verdict governs:

| | Claimed | Measured over 6 months |
|---|---:|---:|
| Carry to a **long**, `xyz:CL` | 0.6%/day (~219%/yr) | **0.09%/day (~33%/yr)** |
| Hedged CL/BRENT | — | **~6%/yr, Sharpe ~0.44** on the carry alone |

The 0.6% figure was measured on the one day it was true (the daily series ran −0.02%,
−0.00%, +0.13%, **+0.60%** — the note was written on the last of those). Unhedged it is
33%/yr of carry against 64%/yr of price vol. Hedged it survives only at low turnover:
holding throughout nets +9.09% over six months, **weekly rebalancing +0.19%.**

**My independent check agrees on direction and order of magnitude**, and is recorded here
only as corroboration: over 3,597 stored hourly points (11 Apr – 8 Sep), holding `xyz:CL`
*short* loses 6.73% (−16.4% annualised) — i.e. crude pays **longs**, which is the same
sign. My headline used the *median* (+0.015%/day); funding is strongly right-skewed, so
the median badly understates the mean (+0.09%/day) that a holder actually receives. **The
mean is the correct statistic for a carry trade and the median is not.**

So `MASTER_V3.md` §5's last open item is re-rated rather than closed. What it now turns on
is **whether the discount generating the funding persists** — the current snapshot shows
mark 99.368 vs oracle 99.400, a −0.03% discount with funding near zero, i.e. currently
absent. Six months cannot separate a structural discount from a transient one. That is a
measurement for the recorder.

### 4.3 Funding does not predict returns either

§4.1 closed funding as *carry*. It is also dead as a *signal*. The crowding thesis —
persistently positive funding means crowded longs, so fade them — predicts a **negative**
information coefficient.

Rank IC vs forward residual return (117 markets × 3,496 hourly bars, market factor
removed, signal lagged one bar):

| Signal | 1h | 12h | 24h | 72h | 168h |
|---|---:|---:|---:|---:|---:|
| Funding, current | −0.010 | 0.005 | 0.013 | 0.012 | 0.021 |
| Mean, trailing 72h | 0.009 | 0.011 | 0.017 | **0.029** | 0.028 |
| Mean, trailing 168h | 0.010 | 0.016 | 0.021 | **0.030** | 0.028 |
| Change vs 24h mean | −0.012 | 0.002 | 0.006 | −0.001 | −0.001 |

Best t-statistic across every horizon and signal: **1.46**. The sign is *positive*, so
high funding weakly precedes high returns — consistent with funding proxying for trend,
and the opposite of what the crowding thesis requires.

### 4.4 There are two cross-listings, not nine

`MASTER_V3.md` item 27 recorded nine companies with duplicate Hyperliquid listings. In
the funding panel there are **two**. The price-convergence version was already tested and
killed (spreads 8–98bp against a 40bp cost, second leg frozen 15–59% of the time); the
**funding differential** had never been measured.

| Pair | Hours | Annualised | bp/day | Days to cover 36bp | % hrs positive | Recent months |
|---|---:|---:|---:|---:|---:|---|
| SK Hynix ord vs ADS | 1,462 | **+34.2%** | 9.37 | 4 | 56.9% | +3.6 +1.8 +0.3 |
| SNDK (io vs xyz) | 478 | +2.0% | 0.55 | 65 | 42.3% | −0.0 +0.1 |

This is the only structure on the venue where the hedge ratio comes from the instrument
definition rather than a regression — the exact failure mode that killed items 5, 16, 17,
18 and 19. But **one usable pair is not a book**: it fails requirements 1, 3 and 4 on its
face, and the differential is halving every month on a 61-day sample.

### 4.5 Cost sensitivity of the pairs book

A rule-based, walk-forward, both-legs pairs book (universe by rule, pairs ranked by spread
half-life on the training window only, hedge ratio frozen at formation, 2-year train /
10-day embargo / 6-month OOS step, 21 refits, 10.5 concatenated OOS years, 2,311 trades):

| Round trip | Venue | Sharpe | Ann. return | Max DD |
|---|---|---:|---:|---:|
| 0 bp | gross | 0.49 | 1.6% | −7.1% |
| 4 bp | US equity (out of scope) | 0.36 | 1.2% | −7.2% |
| 8 bp | — | 0.24 | 0.8% | −7.4% |
| **12 bp** | **Hyperliquid maker** (3bp/leg, *unverified*) | **0.11** | 0.4% | −7.6% |
| 20 bp | — | −0.14 | −0.5% | −10.6% |
| **36 bp** | **Hyperliquid taker** (9bp/leg HIP-3) | **−0.64** | −2.1% | −22.9% |

Measured on US equity history because Hyperliquid has seven months of bars — read it as a
**cost sensitivity, not a HIP-3 backtest**. The signal class is the same either way.

**The maker/taker gap is the whole result**, and the 3bp figure is an assumed constant in
the codebase that has never been checked against a real fill.

### 4.6 Crypto pairs lose at zero cost

Native perps are 64 of the 124 permitted names, so this is half the universe. The same
engine on 80 cleaned coins over 7.2 out-of-sample years and 2,751 trades returns
**Sharpe −0.43 before any fee is charged.** No execution improvement reaches a negative
gross number. Settles the question deferred in
`volume_indicator_studies/perform_operations/STAT_ARB_PLAN.md` §6 on multiple-testing
grounds.

---

## 5. Polymarket results

No code or data for Polymarket existed in either repository before 17 Sep 2026.

### 5.1 The market is well calibrated

976 resolved binary markets ≥$25k volume, 407 distinct events, 4,722 observations, all
closing in a 31-day window (17 Aug – 17 Sep 2026) — the entire retrievable history.
Standard errors clustered on the **event**, because twenty props on one match are not
twenty observations.

**24h before close** (n=972, 405 events):

| Price bucket | n | Events | Mean price | Actual | Gap | t |
|---|---:|---:|---:|---:|---:|---:|
| 0 – 0.02 | 440 | 156 | 0.003 | 0.000 | −0.003 | † |
| 0.02 – 0.05 | 57 | 37 | 0.034 | 0.105 | +0.072 | 1.45 |
| 0.05 – 0.10 | 34 | 26 | 0.075 | 0.118 | +0.043 | 0.62 |
| 0.10 – 0.20 | 73 | 63 | 0.150 | 0.233 | +0.083 | 1.49 |
| 0.20 – 0.35 | 80 | 64 | 0.265 | 0.300 | +0.035 | 0.63 |
| 0.35 – 0.50 | 90 | 82 | 0.423 | 0.422 | −0.001 | −0.02 |
| 0.50 – 0.65 | 71 | 70 | 0.569 | 0.577 | +0.009 | 0.15 |
| 0.65 – 0.80 | 29 | 29 | 0.720 | 0.862 | +0.142 | 2.17 |
| 0.80 – 0.90 | 23 | 22 | 0.855 | 0.739 | −0.115 | −1.13 |

† The deepest bucket had **zero** YES resolutions, which collapses the clustered standard
error and produces a meaningless t-statistic. The rule-of-three bound is used instead
(§5.2). **Only one bucket of eight clears |t| > 2**, which is roughly what testing eight
buckets produces by chance.

| Horizon | Brier | Base-rate Brier | Skill |
|---|---:|---:|---:|
| 24h before close | 0.0898 | 0.1895 | **+0.526** |
| 7 days before close | 0.1027 | 0.1794 | **+0.428** |

**This is a market that knows things, and a market that knows things is the one with no
edge left in it.**

### 5.2 The longshot bias is real in direction and untradeable in size

Sell everything priced below a threshold, post full collateral, hold to resolution,
charge a 1c spread:

| Horizon | Sell below | n | YES | Net / contract | At the 95% upper bound |
|---|---:|---:|---:|---:|---:|
| 24h | 0.02 | 440 | **0** | +0.20c | **−0.49c** |
| 24h | 0.05 | 497 | 6 | −0.70c | −2.11c |
| 24h | 0.10 | 531 | 10 | −0.96c | −2.52c |
| 24h | 0.20 | 604 | 27 | −1.91c | −3.88c |
| 7d | 0.02 | 307 | 1 | −0.05c | −1.53c |
| 7d | 0.05 | 376 | **1** | +0.46c | **−0.74c** |
| 7d | 0.10 | 427 | 8 | −0.43c | −2.22c |
| 7d | 0.20 | 500 | 20 | −0.67c | −2.78c |

**Six of eight combinations lose outright.** The two positive cells rest on **zero and
one** observed YES resolutions respectively; with k successes in n trials the 95% upper
bound is what a short-tail seller is actually exposed to, and at that bound both go
negative.

**Concentration:** selling everything below 5c at 24 hours loses 350.1c across 181 events,
and **one event is 55% of the loss**. That is the short-tail signature — many small wins,
repaid at once.

**Breadth is not the problem here:** 31.4 markets resolve per day in this window, which
satisfies requirement 4 comfortably. There is simply nothing to trade.

### 5.3 The liquidity subsidy is already competed away

Of 600 liquid open markets, **81% carry a reward configuration** with a median max-spread
band of **4.5c**. The median quoted spread is **0.1c** — market makers are quoting 45×
tighter than the subsidy requires. That is what a subsidy looks like once it has been bid
into the spread, and it is the same shape as Hyperliquid's majors quoting at 0.14bp.

Noted separately: several of these markets carry $40m+ of recorded volume on questions
like whether a basketball player wins a presidential nomination, priced at a tenth of a
cent. Those volumes are not plausible as forecasting interest. Reward farming is the
obvious explanation — and it is also the mechanism that competes the subsidy away.

### 5.4 The barrier ladder is a volatility view, not an arbitrage

Polymarket lists ~83 liquid binaries on BTC and ETH price (*"Will Bitcoin reach $X by…"*),
forming full one-touch strike ladders, and Hyperliquid lists the perp that hedges them.
**This is the only structure where both legs sit on permitted venues and the hedge ratio
is not fitted**, so it keeps coming up.

**Model-free test first** — barrier prices must be monotone in strike, since touching
$110k implies touching $100k. Across **6 ladders and 45 strikes: zero executable
violations** across the bid/ask. With $100k–$2.7m of volume per strike that is the
expected answer, and it matches the published finding that Polymarket mispricings are tiny
and fleeting.

**That leaves the level of the surface.** Fitting a single implied volatility to the body
of the BTC ladder gives **~35%**, against trailing realised of 42% (full sample), 39%
(30-day) and 44% (14-day). The market is forecasting a calmer fortnight than the recent
past. That is a disagreement about volatility, and on that the market is usually right,
because volatility mean-reverts.

**The tail cannot be estimated, and the tail is the whole trade.** The apparent edge sits
entirely in strikes priced at 1–4c:

| Benchmark | Sample | Deep-tail verdict |
|---|---|---|
| Bootstrap of HL hourly returns | 5 months, no crash | market **overprices** tails ~2.6× |
| Empirical 14-day windows | 8 years, three crashes | market **underprices** every strike |
| GBM at fitted implied vol | constant vol | meaningless — thin tails by construction |

On the 8-year sample (3,158 overlapping 14-day windows; worst 14-day drawdown −45.5%) the
95% confidence interval on the true hit rate **covers the market price at 10 of 10
deep-tail strikes**. The disagreement between two defensible estimates is larger than any
edge either implies.

---

## 6. Off-venue work — method kept, strategy out of scope

Fails requirement 0 and is recorded here so it is not re-derived. The engine, the
walk-forward harness and the cost-sweep discipline all port unchanged; the universes do
not.

- **The excursion measurement.** Median gross excursion at |z| ≥ 2 is **1,023bp** (US
  equity), 2,182bp (crypto), 1,046bp (commodity), with spread half-life ~44 days and 66%
  reverting within 20 days. Against a 4bp conventional round trip, cost is not the
  constraint off-venue — **34% never reverting** is. This does not transfer to Hyperliquid,
  where the cost line is 9× higher.
- **Breadth destroys Sharpe.** Gross Sharpe by pairs held: 5 → 0.38, 10 → **0.74**,
  20 → 0.64, 40 → 0.49, 80 → 0.32, 150 → 0.27, 300 → 0.20, 600 → 0.27. The fundamental law
  fails because pairs are ranked best-first, so every added pair is worse than the last.
- **More names does not fix it.** At a fixed 20 pairs on a freshly fetched 466-name S&P
  panel: 30 → 0.02, 60 → 0.18, 133 → **0.32**, 250 → 0.07, 350 → 0.22, 466 → 0.11. The
  curve peaks near 133 and falls.
- **Market neutrality is solved and venue-independent.** Realised OOS beta **+0.04**,
  correlation +0.195. 2018: S&P −6.2%, book **+4.4%**. 2022: S&P −19.4%, book **+6.0%**.
  Q1 2020: S&P −20.0%, book +1.0%. Fragility: Sharpe 0.52 → 0.35 (excl. best 5 days) →
  0.22 (excl. 10) → −0.02 (excl. 20); 82/127 positive months.
- **The Indian fee wall is a capital-size artifact**, not a structural one. Single-stock
  futures pair round trip: ₹25k/leg → 9.7bp, ₹1L → 7.3bp, ₹2.5L → 4.5bp, ₹10L → 3.1bp,
  ₹50L → 2.7bp. Excludes bid-ask, which is the larger cost outside the top ~50 names.
  **Out of scope regardless.**

---

## 6b. Reconciliation with the 16 September rechecks

Three documents were written on 16 Sep in parallel with this work. **Two of them hold
results closer to viable than anything measured here**, and all three terminate at the same
open question. Read alongside, not instead of, this document.

| Document | Result | Status against the project's own bar |
|---|---|---|
| [CRUDE_CARRY_RECHECK.md](CRUDE_CARRY_RECHECK.md) | Hedged CL/BRENT carry ~6%/yr, Sharpe ~0.44 | Re-rated 6× down; survives only at low turnover |
| [SURVIVORS_RECHECK.md](SURVIVORS_RECHECK.md) | Combined momentum book, Sharpe **1.44**, t = 2.63 | **DSR 0.710** against a 0.95 bar — closest thing in the project |
| [FAST_BOOK_TEST.md](FAST_BOOK_TEST.md) | 4h reversal, net Sharpe **1.09 at 3bp**, 6.58 turns/day | **DSR 0.072**; −0.52 at 4.5bp |

Two things follow that this document would get wrong on its own.

**First, "requirement 4 is unreachable" is too strong.** `FAST_BOOK_TEST.md` gets 6.58
turns per day at net Sharpe 1.09 on a **survivorship-free** panel (147 coins, 45 of them
venue-flagged delisted — 31%), with a real train/test split. Requirement 4 is not forbidden
by the fee schedule; it is reachable *if and only if* fills land between 0 and ~4bp.

**Second, the fill question is not entirely unmeasured.** §8.1 below called it "never
measured against a single real fill." That is not quite right: the paper harness ran for
**one day** and returned **0.00bp median slippage on an $11 order**. One small order on one
day is not evidence about capacity or adverse selection, but it exists and it points the
right way. The harness then stopped and has not run in over two weeks.

**Four independent threads now terminate at the same measurement** — crude carry (dies at
weekly turnover), the momentum book (needs live out-of-sample evidence to move DSR), the
fast reversal book (pays only between 0 and 4bp), and the pairs book in §4.5 (−0.64 at
36bp, +0.11 at 12bp). When four unrelated lines of work converge on one unanswered
question, that question is the project.

---

## 7. Three claims corrected

Recorded because repeating them costs more than writing them down. All three were caught
by checking, not by reasoning.

### 7.1 Polymarket price history is NOT retrievable — corrected same day

I wrote on the morning of 17 Sep that calibration does **not** need a recorder, because the
CLOB `/prices-history` endpoint serves resolved markets. **That is true only for roughly
the last six weeks.**

Everything older returns an empty series — including the $1.5bn Trump-2024 market — under
`interval=max`, `interval=1m` and explicit `startTs`/`endTs` alike. Gamma still lists
**25,361** resolved binaries above $25k volume going back to 2020; their prices are gone.

**The earlier note was right: a long calibration history can only be built by recording
forward.** Every day the recorder is off is permanently unrecoverable ground truth.

### 7.2 A 50-cent edge that was a stale spot price

The first barrier run showed a **+53c edge** on every up-strike. Cause: the stored hourly
panel ends 4 September and put BTC at **80,758** when the live mid was **76,444**. A
**5.3% spot error** made *"touch $80,000"* look nearly certain against a market price of
0.455.

**A stale hedge price does not add noise to barrier or option work — it manufactures a
large, clean, entirely fictional edge.** Spot must be taken live from the venue at the
moment of comparison.

### 7.3 "Cost is the wrong wall" — true off-venue, false here

The 16 Sep analysis found a 1,023bp excursion against a 4bp toll and concluded the fee line
was the wrong problem. **Under requirement 0 that conclusion does not hold.** At 36–40bp
the same book returns −0.64. `MASTER_V3.md`'s dominant failure pattern was right all along;
the off-venue finding simply does not transfer.

---

## 8. What is still open

### 8.1 Do posted orders fill? — the largest item by some distance

Taker is ~9bp/leg; posting is ~3bp/leg. On the book in §4.5 that is **−0.64 Sharpe against
+0.11**; on the fast book it is **1.09 against −0.52**; on crude it is the difference
between holding and rebalancing. The 3bp figure is an assumed constant in the codebase.

**The only live evidence is one day of paper trading: 0.00bp median slippage on an $11
order** (§6b). That is one small order, says nothing about capacity or adverse selection,
and the harness has not run since 1 September.

It cannot be answered from price history. Restart the harness, post orders at size you do
not mind losing, and measure two things: **what fraction fill**, and **where the mid goes
in the following minute**. `MASTER.md` already names the trap — *"you get filled
preferentially when you are wrong"* — so the honest expectation sits between 1.5 and 3.0bp,
which is exactly the band where every result above is decided.

Everything else on this list is downstream of the answer.

### 8.2 Restart the recorder — and add Polymarket

It stopped on **10 September**. §7.1 makes this worse than it looked: Polymarket price
history is only retrievable for about six weeks, so every day it is off is calibration
ground truth that **cannot be backfilled at any price**.

The calibration result in §5 rests on a 31-day window. A year of recorded data would make
it a real study rather than a first look, and it is the only way to get one.

### 8.3 The legal question on Polymarket

Unanswered, and it now gates more than it did, because Polymarket is where the breadth is:
25,361 resolved binaries and 31 resolving per day, against Hyperliquid's 124 names.

Whether an offshore prediction market is accessible from India under the **Promotion and
Regulation of Online Gaming Act, 2025** is a lawyer's answer, not a modelling one. Worth
asking despite the negative results above: a negative answer removes half the permitted
surface permanently, which is itself worth knowing before more effort goes into it.

### 8.4 The ladder, if a volatility book is wanted

Not an arbitrage and should not be presented as one. If it is worth running it needs
implied-versus-subsequent-realised measured across **many expiries**, which again means
recording. One snapshot of one expiry cannot answer it, and today's snapshot says the two
estimates of the tail disagree by more than the trade is worth.

---

## 9. Reproduction

| What | Where |
|---|---|
| Polymarket collector | `backtesting/polymarket/fetch_calibration.py` |
| Polymarket calibration | `backtesting/polymarket/calibration.py` |
| Longshot book | `backtesting/polymarket/sell_longshots.py` |
| Funding panel (source) | `backtesting/hyperliquid/hip3/funding_panel.csv.gz` |
| HL hourly prices (source) | `backtesting/hyperliquid/hip3/universe_1h.csv.gz` |
| HL universe filter spec | `backtesting/hyperliquid/hip3/FILTERING_CRITERIA.md` |
| Cross-venue price work (prior) | `backtesting/hyperliquid/hip3/crossvenue.py`, `hardlink.py` |
| The spec | `documentation/MAHAN_SPEC.md` (requirement 0 added 16 Sep) |
| The brief it came from | `backtesting/hyperliquid/hip3/MAHAN_BRIEF.md` |

**Data spans.** Funding panel: 148 markets × 3,599 hourly bars, 11 Apr – 8 Sep 2026.
HL hourly prices: 124 markets × 5,004 bars, ends 4 Sep 2026. Polymarket: 976 markets /
407 events closing 17 Aug – 17 Sep 2026, plus metadata on 25,361 resolved binaries back
to 2020. Barrier ladder: 45 strikes across 6 ladders, spot live from the Hyperliquid
`allMids` endpoint.

Scripts for the barrier, funding-signal and cross-listing analyses were written in a
scratch directory and are **not yet committed** — that is a gap worth closing, and the
reason is §4 of `MASTER_V3.md`: a result that cannot be traced to the code that produced
it cannot be defended.

---

## 10. Caveats that apply throughout

- **The Polymarket sample is 31 days** and weighted toward short-dated sports and crypto
  props. A different month could move the bucket gaps materially, and only one bucket of
  eight clears |t| > 2 as it is.
- **The barrier conclusion rests on one expiry at one moment.** Tail probabilities are not
  estimable from either available sample, and the two defensible estimates disagree in
  sign.
- **The funding panel covers five months of a single regime.**
- **Equity results are cost sensitivities, not HIP-3 backtests** — Hyperliquid has seven
  months of bars.
- **Survivorship.** The off-venue equity panels are current constituents only, so they
  overstate the short leg.
- **Multiple testing.** ~30 strategies were already tested against this venue before these
  eight. Any *positive* result now needs a deflated Sharpe ratio computed alongside it.
  **None of the results here are positive, so none required it** — which is the only
  reason that correction does not appear above.
