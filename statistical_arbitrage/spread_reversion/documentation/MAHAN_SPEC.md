# Mahan's spec

Requirements from Mahan Namin, 2026-09-16, on the divergence/pairs strategy.
Written down so they can be worked against rather than remembered.

His summary line: *"you need to bulk this out much to get it to an actual idea
worth looking at."*

---

## Requirement 0 — the venue filter (HARD)

> "can you trade it on hyperliquid or polymarkets?"

**Hyperliquid and Polymarket are the only venues. This is a hard filter, applied
before any other requirement is considered.**

It is numbered 0 rather than 8 because it is not scored alongside the others — it
gates them. A strategy that fails it is not a weak candidate, it is out of scope,
and no performance on any other axis brings it back. An idea that needs NSE
single-stock futures, an IBKR equity book, a stock borrow, a cash ETF or an
Indian brokerage account is not a worse version of this strategy; it is a
different project.

This requirement was stated first, not last. It is recorded in
`backtesting/hyperliquid/hip3/MAHAN_BRIEF.md` as his requirement #1, sourced from
the `#crypto-trading-research` Slack channel, and was simply omitted when the
seven below were written down. Restoring it invalidates work already done, which
is exactly why it belongs in writing.

**Acceptance:** every leg of every position is listed and liquid on Hyperliquid
(native perpetuals or HIP-3 builder-deployed markets) or Polymarket, on the date
the backtest trades it. Costs charged at that venue's real schedule — ~9bp/leg
taker on HIP-3, ~4.5bp native — not at a rate imported from another market.

### What the filter leaves

| Venue | Tradeable | Note |
|---|---|---|
| Hyperliquid native perps | **64** | after the ≥$500k/day liquidity filter |
| Hyperliquid HIP-3 | **60** | equities, commodities, FX, indices |
| **Total Hyperliquid** | **124** | of 304 scanned, 4 Sep 2026 |
| Polymarket | open read API | trading access gated on the legal question below |

Three consequences follow immediately, and all three are binding:

- **124 names is a small universe for a breadth strategy**, and it splits across
  asset classes that cannot sensibly be paired with each other.
- **A two-legged round trip costs 36–40bp here.** That is 5–10× the cost line of
  any conventional equity venue, and it is the reason 12 of 30 strategies in
  `research_log/MASTER_V3.md` died. Under this filter, cost is the binding
  constraint again.
- **History is ~5,000 bars (~7 months)** from the candle endpoint. Long backtests
  are not available on this venue; the recorder exists because of this.

**Open question that gates Polymarket entirely:** whether an offshore prediction
market is legally accessible from India under the Promotion and Regulation of
Online Gaming Act, 2025. Read access works and proves nothing about order
placement. Until that is answered, Polymarket is a data-collection and research
target, not a trading venue.

---

## The seven requirements

### 1. One instrument is not evidence

> "a backtest on one stock is never going to be enough to justify a strategy"
> "if the backtest only worked on one stock you are probably over-fitting"

Surviving on one name out of many tested is a selection result, not an edge. The
strategy has to hold across a population.

**Acceptance:** results reported across the whole tested universe — median and
distribution, not the winner. The number of names tested must be stated, so the
survivor count can be read against what chance alone would produce.

---

### 2. A process, not a hand-picked name

> "you need to approach this from a more macro level - a process to identify the
> opportunities and then take them. not just manually finding this one stock"

The deliverable is the *selection mechanism*, not a pair. Whatever picks
BANKBEES/SETFNIFBK today must pick next year's pair on its own, by rule.

**Acceptance:** a screener that ranks the full universe by a stated criterion and
outputs a tradeable set with no human in the loop. Re-running it on a past date
must reproduce what it would have chosen then, using only data available then.

---

### 3. Train and test must be separate

> "backtesting on its own still not enough, you need training data and then test
> it on out of sample data"

**Acceptance:** parameters and pair selection fitted on a training window only,
then applied unchanged to a withheld window. Walk-forward preferred: rolling
refit with an embargo gap, reporting the concatenated out-of-sample series. Any
number quoted must say which window produced it.

*Precedent that makes this non-negotiable:* `research_log/README.md` already
records a reported Sharpe of 1.48 that re-ran at **−3.43**. That is exactly the
failure this requirement prevents.

---

### 4. Enough trades, spread across instruments

> "it needs to be taking enough trades a day across different to minimise noise
> and variance"

Frequency and breadth are risk controls, not vanity metrics. A handful of trades
a year cannot distinguish skill from luck, and concentrating them in one name
means single-name risk dominates.

**Acceptance:** trades per day materially above zero, spread across many
instruments concurrently. Enough that the t-statistic on the result is
meaningful — as a rough bar, several hundred trades rather than several dozen.

---

### 5. Market neutral

> "it needs to be market neutral - i.e. work in a down market as well as an up market"
> "what if the market is going down"
> "i dont want to buy stocks and be net long when market is going down"

**Acceptance:** realised beta to the index near zero, measured out of sample, not
merely neutral by construction. Positive expectancy in down markets as well as up
— reported split by regime.

---

### 6. Hedged, one long against one short

> "i dont want to be naked long the stock market based on divergence with another stock"
> "it needs to be hedged"
> "one short vs one long"
> "something like that"

The current divergence trade buys one leg on a relative-value signal and is
thereby long the market. Both legs must be taken.

**Acceptance:** every position is a matched pair, long one leg and short the
other, sized so the pair is beta-neutral rather than merely dollar-neutral.
Shorting costs — borrow, funding, availability — must be charged.

---

### 7. It has to be sellable

> "we cannot sell this strategy to anyone"
> "its way too simple"
> "and even if we dont raise money for it, i dont want to be naked long"

Two distinct objections. The first is commercial: a single-pair z-score rule is
not a product. The second is personal risk tolerance and applies regardless of
whether anyone else ever sees it.

**Acceptance:** the strategy stands up to the questions an allocator asks —
universe, selection process, out-of-sample evidence, capacity, neutrality,
cost assumptions.

---

## Where the current work stands against this

Honest reading, not a defence.

| # | Requirement | Status |
|---|---|---|
| 0 | **Venue (hard filter)** | **Fails for most of the work on disk.** The 310-instrument sweep, the 466-name S&P panel, the India ETF and single-stock-futures work, the Nifty/Gold allocation results — none of it is tradeable on either venue. It remains valid as *method* and as *null results*, and is out of scope as strategy. What survives the filter: the Hyperliquid work in `backtesting/hyperliquid/`, and nothing on Polymarket, which has never been touched beyond an API check. |
| 1 | Multiple instruments | **Partly.** A wide universe has been tested (310 instruments across five asset classes), and the honest answer was that ~6 passed — close to what chance produces. That work satisfies the *testing* standard while failing the *result* standard. **Under requirement 0 the tested universe is 124, not 310.** |
| 2 | Process, not a name | **No.** BANKBEES/SETFNIFBK and the AXISBANK/KOTAKBANK/TATASTEEL triple are hand-chosen. There is a screener (`bin/volume_screener.rs`), but it does not select pairs. |
| 3 | Train/test separation | **Partly.** `strategy.py` has a real walk-forward loop with an embargo, and `signal_selection.py` does a pre-committed first-half selection. Most other results are full-sample. |
| 4 | Trade count and breadth | **No.** The BTC book takes ~6 trades/year. The pairs book is one pair at a time. Both are orders of magnitude short. |
| 5 | Market neutral | **Partly, and the honest result was negative.** A cross-sectional beta-neutral engine was built and did achieve beta ≈ 0.00 with drawdown cut from −90% to −15%; but gross Sharpe was only +0.47 and it needed sub-4bp execution to clear costs. |
| 6 | Long/short pairs | **No.** The divergence trade is single-leg. |
| 7 | Sellable | **No**, and requirement 4 is the binding reason. |

**The gap in one line:** the pieces exist separately — a neutral engine, a
walk-forward harness, a wide universe, a screener — but nothing joins them into
a single process that selects pairs by rule, trades both legs, and is validated
out of sample.

**What requirement 0 does to that sentence:** the wide universe is the piece that
does not survive. The engine and the harness are venue-agnostic and port
unchanged; the universe shrinks from 466 to 124 and the cost line rises from ~4bp
to 36bp. Both moves are in the wrong direction, and the second is the larger.

---

## What this implies for the next build

Not a new signal. A different shape of system:

1. **Define the universe by rule** — liquidity and history filters, not names.
2. **Form pairs by rule** — a stated criterion evaluated on the training window
   only, refreshed on a schedule.
3. **Trade both legs, beta-weighted**, with borrow and funding charged.
4. **Hold many pairs at once** so the trade count comes from breadth rather than
   from loosening the entry gate. Loosening the gate has already been measured
   and makes things strictly worse.
5. **Walk-forward end to end**, including pair selection, since selection is the
   step most likely to be leaking.
6. **Report the distribution**, not the survivor.

Point 4 deserves emphasis because it is the one most easily faked. More trades
must come from holding more pairs simultaneously, not from taking worse trades
on the same pair.

### What requirement 0 adds to that list

7. **Charge the venue's real cost, and sweep it.** 36–40bp round trip is the
   default assumption. A result quoted at any lower rate must say what makes that
   rate achievable, and the answer is only ever "we posted and were filled."
8. **Resolve the maker question before optimising the signal.** Taker is
   ~9bp/leg, posting is ~3bp/leg. On the walk-forward equity-pairs book measured
   16 Sep 2026, that difference is the whole result: −0.64 Sharpe at 36bp,
   +0.11 at 12bp. No signal improvement found anywhere in this project is worth
   as much, and the 3bp figure has never been verified against a real fill. It
   cannot be answered from price history — only by posting orders and watching.
9. **Treat the 7-month history as the hard constraint it is.** With ~5,000 bars
   and a statistical budget already spent (~30 strategies tested), any new result
   on this data needs a deflated Sharpe ratio computed alongside it, not after.

**Point 8 is the highest-value open item in the project**, and it is measurement,
not research.

---

## Requirement 4 vs the cost wall — the conflict, stated plainly

Added 16 Sep 2026, after checking the momentum book against the spec.

**The best candidate in the project passes 6 of the 7 requirements and fails only
#4 — and it fails #4 by construction, not by oversight.**

| # | Requirement | Cross-sectional momentum |
|---|---|---|
| 0 | Hyperliquid / Polymarket only | PASS — native perps |
| 1 | Not one instrument | PASS — 157 perps, delisted included |
| 2 | A process, not a hand-picked name | **PASS — a pure ranking rule** |
| 3 | Train/test separated | PASS — walk-forward 0.68→1.41, 1.13→0.98, 1.20→0.73 |
| **4** | **Enough trades a day** | **FAIL — 20-day holds, 0.003x/day turnover** |
| 5 | Market neutral | PASS — beta to BTC −0.018 |
| 6 | Hedged, one long one short | PASS — dollar-neutral, top 20% vs bottom 20% |
| 7 | Sellable | PARTIAL — recognisable product, but DSR 0.71 |

Requirements 2 and 6 are the two that everything else in the project failed.
`MASTER.md` describes this book in its own words as *"an investment tilt, not a
trading strategy."*

### Why #4 cannot simply be fixed

The frequent version exists. Its signal is **stronger**. Fees destroy it.

| Signal / hold | Gross Sharpe | Turnover | Annual cost | **Net Sharpe** |
|---|---:|---:|---:|---:|
| **4h / 4h** | **1.93** | 9.07×/day | **314%** | **−10.20** |
| 8h / 8h | 1.58 | 4.54×/day | 157% | −5.73 |
| 12h / 12h | 0.32 | 3.02×/day | 105% | −4.75 |
| **20 days** | 1.07 | 0.003×/day | 0.1% | **+1.07** |

The 4-hour book has nearly double the raw signal and loses ten times the money.
The 20-day hold is not a preference; it is the only speed the fee schedule
permits. **Requirement 4 and the venue's cost structure are in direct conflict:
frequency or net profitability, not both.**

### The single number that decides it

Breakeven on the 4-hour book is **1.80 bps per side**. The maker fee is **1.5 bps**
— inside it, barely.

| Execution | Cost/side | Net Sharpe |
|---|---:|---:|
| Perfect fill | 0.0 bp | +1.93 |
| **Maker only** | **1.5 bp** | **+0.01** |
| Taker only | 4.5 bp | −3.82 |

This is the same question as the crude carry (weekly rebalancing took it from
+9.09% to +0.19%) and the same question `MASTER_V3.md` already calls the
highest-value open item. **Three independent threads terminate at one unmeasured
number: can we get filled as a maker?** The only live evidence is a single day
returning 0.00bp median slippage on a small order.

### Where the requirement is right for a reason not yet stated

Mahan's justification for #4 is *"to minimise noise and variance"* — a
statistical argument, and the data confirms it exactly. Twenty-day holds mean
1,220 days of history yield only ~61 independent observations. That is precisely
why the combined book's t-stat is 2.63 and its deflated Sharpe only 0.71 after
three years. The slow book fails the requirement **for the reason the requirement
was given**: frequency is not cosmetic, it is what would make the result
provable.
