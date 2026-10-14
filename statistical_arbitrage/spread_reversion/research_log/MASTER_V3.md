# MASTER V3 — every attempt, and exactly why it failed

**Complete record as of 8 September 2026.** Supersedes `backtesting/hyperliquid/MASTER_V2.md`
(1 Sep), which is retained for history but contains at least one number that does not reproduce.

Thirty distinct strategies have been tested. **None currently survives validation.** This
document records what each one was, what killed it, and — more usefully — the four failure
patterns that account for nearly all of them.

---

## The four ways everything died

Before the list, the summary. Almost every failure fits one of these:

| Pattern | Count | Description |
|---|---:|---|
| **A. Below the fee line** | ~12 | Real effect, smaller than the cost of trading it |
| **B. No stable relationship** | ~8 | The hedge ratio moved, so the "hedge" was a directional bet |
| **C. Artifact of method** | ~6 | Looked profitable until a bias was removed |
| **D. Too few observations** | ~4 | Might be real; sample too small to ever know |

**Pattern A is the dominant one and the most important finding in this project.** Hyperliquid
charges ~9bp per HIP-3 leg (4.5bp native). A two-legged round trip costs 36–40bp. Market
inefficiencies that survive in a liquid venue are typically smaller than that — *because* the
ones larger than that have already been arbitraged away.

---

## Part 1 — Native crypto work (before September)

Recorded in `MASTER_V2.md`, summarised here for completeness.

| # | Strategy | Outcome | Pattern |
|---|---|---|---|
| 1 | Cross-sectional momentum (10 best / 10 worst, 3-week hold) | +11.8%/yr claimed, paper-traded since 1 Sep — **never validated with the methods below** | — |
| 2 | Intraday reversal (buy day's losers, 4h rebalance) | +59%/yr gross, **314%/yr in fees** | **A** |
| 3 | Pairs trading with 4-hourly stop checks | Backtest said +22.9%; checking stops against intrabar highs/lows gave **−54.5%** | **C** |
| 4 | Cointegration search across 1,008 pairs | 55 looked significant; ~10 expected by luck; **exactly 1 survived** correction | **C** |
| 5 | That survivor (ARB/LDO) | Carried **beta +1.10 to Bitcoin** — a leveraged crypto bet, not a hedge | **B** |
| 6 | Whale-order lead-lag, minutes | Gap averages 15bp; cost 18bp | **A** |
| 7 | Whale-order lead-lag, days | Stricter pair selection made results *worse* — the confidence score was meaningless | **C** |
| 8 | Waiting for whale gaps to close | Gaps **widen**, not close — biggest widen 3.4% over three days | — |
| 9 | Profit-target variant | Long *and* short both appeared profitable — impossible; it was measuring volatility | **C** |
| 10 | Volume-filtered pairs | The required setup occurs 1.6% of the time | **D** |
| 11 | Cross-venue funding arbitrage | Gaps are mechanical (Hyperliquid pins funding to a baseline), and you cannot trade a two-venue spread on one venue | — |
| 12 | Whale orders, real trade-feed data | Large orders do **not** push price — every size bucket drifts −0.9 to −1.2bp afterwards | — |

---

## Part 2 — The SK Hynix line

The best-structured idea in the project, and worth understanding in detail because it failed
last and hardest.

**The setup.** SK Hynix trades on Hyperliquid twice: the Korean ordinary share (`xyz:SKHX`) and
the US depositary share (`xyz:SKHY`), linked by a fixed 1:10 conversion. Same company, hedge
ratio known from the instrument definition rather than fitted from data. That last property is
what separates it from every failed pair above.

| # | Attempt | Outcome | Pattern |
|---|---|---|---|
| 13 | Long-only SKHX when cheap vs its twin and turning up | 4 trades, 4 wins, +19.7% — but naked long, and rejected on those grounds | **D** |
| 14 | Hedged pair (long one leg, short the other) | 11 trades, +57bp/trade — **but see below** | **D** |
| 15 | PAXG vs GOLD (same ounce of gold) | Relationship real; spread 18bp against 27bp cost | **A** |
| 16 | HYPE vs PURRDAT (treasury NAV) | Naive spread not stationary (p=0.25) | **B** |
| 17 | BTC vs MSTR (capital structure) | Naive spread not stationary (p=0.15) | **B** |
| 18 | MU vs DRAM (producer vs product) | Not stationary (p=0.24) | **B** |
| 19 | GOLD vs SILVER (deliberate control) | Not stationary (p=0.23) — as expected | **B** |

### Why the hedged pair ultimately failed

Four independent problems, discovered in this order:

1. **Sample.** 11 trades, of which 2 carry the entire result. Reaching significance at its
   observed signal rate needs ~24 months; it has ~2.
2. **Breadth.** It is one instrument, which fails several of Mahan's rules structurally. No
   amount of good performance fixes that.
3. **Instability.** The +57bp/trade halves to +25bp if you assume a one-bar delay between signal
   and execution, and goes *negative* at a slightly different entry threshold. Every t-statistic
   sits between −0.88 and +0.62.
4. **The relationship does not pay elsewhere.** Testing the same structure across 35 companies
   and 22 years of real exchange data (below) shows it earns about half the fee line — and
   *Korean* pairs specifically lose 21.7bp per trade.

**It is not scalable either.** Across 104 live Hyperliquid stock markets, SK Hynix is the only
company with both listings available.

---

## Part 3 — September's work

| # | Strategy | Outcome | Pattern |
|---|---|---|---|
| 20 | Cross-sectional book, 124 markets, buy cheap / sell rich | Signal is **backwards** — the "rich" names returned +148%/yr vs +6.3% for "cheap". Deflated Sharpe **0.000** | **C** |
| 21 | Raw momentum, same universe | Deflated Sharpe **0.000** | **A/D** |
| 22 | Residual (factor-neutral) momentum | Deflated Sharpe **0.000**; the factor model did **not** beat raw | **A/D** |
| 23 | Dual-listing class, 35 companies, 1999–2026, 5,662 out-of-sample trades | Gross **+22.7bp** vs **40bp** cost. Deflated Sharpe **0.000** | **A** |
| 24 | India+Taiwan subgroup of the above | +26.5bp/trade, t=3.90 — the only result to pass a trials correction (DSR 0.969). **But decayed to nothing**: +135.8bp in 2002–09 → **−3.0bp since 2018**. 2008 alone is 36.6% of total profit | **C** |
| 25 | Market making | Spreads measured 0.13–0.75bp against a 3–6bp maker round trip — fees are **4–25× the spread** | **A** |
| 26 | Basis trading (spot vs perp) | Only **8 tokens** have both a spot market and a perp. BTC, ETH and SOL have no Hyperliquid spot | — |
| 27 | Cross-venue duplicate listings (9 companies) | Perfectly stationary (identical security), but spreads 8–98bp vs 40bp cost, and the second leg is frozen 15–59% of the time | **A** |
| 28 | Extended-hours continuation | **20.3bp/day gross against 20.0bp/day cost.** Deflated Sharpe **0.050** | **A** |
| 29 | Korean internal-session fade | Gross 32–70bp vs 20bp cost, but only 3 instruments, ~89 trades each, t between 0.31 and 1.19. Deflated Sharpe **0.085** | **D** |
| 30 | Funding carry | **Still open — see Part 5** | — |

---

## Part 4 — The process failures

These cost more than any individual strategy, and are worth more attention than the list above.

### The Sharpe 1.48 does not reproduce

A cross-sectional strategy was reported to Mahan at **Sharpe 1.48, +29.1%/yr**. Re-running the
committed code on the committed data — which matches the report's own description of its dataset
exactly — produces **−3.43**, with every rebalance frequency negative:

| Rebalance | Reported | Actual |
|---|---:|---:|
| 6h | −0.33 | −4.66 |
| 24h | +1.32 | −3.79 |
| **48h** | **+1.48** | **−3.43** |
| 168h | +0.39 | −0.31 |

**Root cause:** `backtesting/hyperliquid/` is in `.gitignore`. With no version history, it is
impossible to determine whether the number came from code that was never saved, a data file
rebuilt afterwards, or a bug introduced later. **A result that cannot be traced to the code that
produced it cannot be defended.**

### Five findings that were overstated

An independent replication pass checked six claims. **Zero came back confirmed.**

| Claimed | Actual |
|---|---|
| Book loses −142%/yr | −36% to −60%. The −142% subtracted two compounded rates — not an attainable return |
| 42% of markets died | **15.8%.** 49 of 85 were still trading and merely fell below a liquidity screen |
| Only one dual-listed pair exists | **Nine exist** — the original scan covered one venue instead of four |
| Dual-listing earns half the fee line | 28 of 35 pairs earn **one sixth**; pooling hid a bimodal split |
| India/Taiwan is a live edge | Negative since 2018; the grouping was chosen after seeing which regions won |

### Duplicated work

Several September "discoveries" already existed in
`studies/trading/Machine_Learning_Base_Pairs_Trading/HYPERLIQUID-POLYMARKET-RESEARCH-PLAN.md`,
dated 20 August: that funding sits at a baseline on nearly everything, that BTC/ETH spreads are
too tight to make markets in, that the candle endpoint caps at ~5,000 bars, and that a recorder
was "the highest value in the document." **Reading the existing library first would have saved
several days.**

### The statistical budget was spent without anyone tracking it

Testing ~20 variations at ordinary confidence produces a convincing false positive by chance
alone. We tested about thirty. Once the Deflated Sharpe Ratio was finally applied — the
correction for how many things you tried — **every strategy failed**, including the two that had
looked most promising.

This should have been computed continuously from the start. It is cheap. It was applied on day
three, after the conclusions had already been written up.

---

## Part 5 — What is still open

### Funding carry on commodity perpetuals

Crude oil perps on Hyperliquid pay holders roughly **0.6%/day**, and it is the most stable
measurement in the dataset (`xyz:CL` moved 9pp across 97 minutes, versus 13,567pp for the most
volatile market).

**It is not free money.** The payment is entirely explained by the contract trading below its
oracle price — funding is the mechanism correcting that, so you are paid to hold something at a
discount.

**The blocker is structural, not statistical.** Collecting it means owning crude oil, which moves
~2%/day — three times the payment. Hedging that exposure requires an offsetting instrument, and
Hyperliquid has no crude spot market. Pairing crude against natural gas would collect from both
sides but reintroduces exactly the fitted-beta problem that killed items 5, 16, 17, 18 and 19.

**Status:** a recorder is accumulating data to determine whether the discount persists over days
rather than minutes.

### The execution question

Every strategy above died at the fee line. The gap between taking the offered price (9bp/leg) and
patiently posting an order (3bp/leg) is worth more than any signal improvement found anywhere in
this project — enough to turn item 28 from +0.8%/yr into roughly +31%/yr.

**Whether posted orders actually fill cannot be determined from price history.** It requires live
observation of the order book. That is the second thing the recorder is for.

Caveat worth stating: the 3bp maker figure is an assumed constant in this codebase and has never
been verified against an actual filled order.

---

## What we would tell someone starting over

1. **Measure your costs before writing strategy code.** Not after. Twelve of thirty failures were
   decided by a number we could have looked up on day one.
2. **Track how many things you have tested.** The statistical budget is finite and invisible. Once
   spent, no new backtest on that dataset can be believed.
3. **Version-control the research.** Anything else means results that cannot be defended when
   questioned — and they will be questioned.
4. **Read your own library first.** Several findings here were rediscoveries.
5. **Prefer mechanisms to patterns.** Every idea built on a pattern in a price series failed. The
   only survivor is built on a structural fact about how the venue works.
6. **A single observation with a good story attached is the most dangerous thing in this
   document.** It appears at least four separate times above, each time producing a conclusion
   that later had to be withdrawn.
