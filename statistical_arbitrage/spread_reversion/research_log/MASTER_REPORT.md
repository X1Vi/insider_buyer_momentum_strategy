# The whole project, in plain English

**Master report · 18 September 2026 · start here**

Everything this project has tested, why each thing failed, what is still alive, and the
one question that decides the rest. Written so it can be read without the statistics.
Every number here is traceable to a document listed in §10.

---

## The one-paragraph version

We are trying to build an automated trading strategy on Hyperliquid or Polymarket that
makes money whichever way the market moves. We have tested **38 distinct ideas**. None is
currently fundable. Almost all of them died the same way: **the profit per trade turned
out to be smaller than the cost of making the trade.** Three ideas are still breathing,
and all three fail on the *same* unanswered question — whether we can get our orders
filled at the cheap price rather than the expensive one. Nobody has measured it. It would
take days, not months, and it decides everything.

---

## 1. What we are trying to do

Make money steadily, on Hyperliquid or Polymarket, **without betting on whether markets go
up or down.**

That last part is the point. Anyone can make money in a rising market by buying things.
The goal is to make money either way, by finding relationships between instruments that
hold regardless of direction.

---

## 2. The rules it has to satisfy

These come from Mahan, who decides whether an idea gets built out or funded.

| | Rule | What it means in practice |
|---|---|---|
| **0** | **Hyperliquid or Polymarket only** | A hard filter. Anything else is not a weaker idea, it is a different project. |
| 1 | Many instruments, not one | One winner out of many tested is what luck looks like |
| 2 | A process, not a hand-picked find | A rule that picks next year's trade on its own |
| 3 | Tested on data it has not seen | Backtests alone prove nothing |
| 4 | Lots of trades, spread across instruments | One good trade is luck; a thousand is a process |
| 5 | Works in falling markets too | Direction should not matter |
| 6 | Hedged — one long against one short | Never just long the market |
| 7 | Good enough to sell | It has to survive an allocator's questions |

We added a ninth rule ourselves, learned the expensive way:

> **8. It has to survive fees.** Every idea we killed died here.

**Rule 0 was stated first and got lost.** It is in Mahan's own words in `MAHAN_BRIEF.md`
as his requirement #1 — *"can you trade it on hyperliquid or polymarkets?"* — and was
simply left out when the seven were written down. It was added back on 16 September. It
matters because it invalidates a lot of otherwise good work: anything needing Indian
futures, a US broker, or a stock loan is out of scope no matter how well it tests.

---

## 3. The score

| | |
|---|---:|
| Distinct ideas tested | **38** |
| Currently fundable | **0** |
| Still breathing | **3** |
| Blocked on the same single question | **3 of 3** |

---

## 4. The four ways everything dies

Before the list of what we tried, the summary. Nearly every failure is one of these four.

| Pattern | Count | What it means |
|---|---:|---|
| **A — Below the fee line** | 15 | The effect was real. It was just smaller than the cost of trading it. |
| **B — The relationship moved** | 10 | The "hedge" drifted, so it quietly became a directional bet. |
| **C — An artifact of how we measured** | 6 | Looked profitable until a bias was removed. |
| **D — Too few observations** | 7 | Might be real. Sample too small to ever know. |
| | **38** | |

**Pattern A is the dominant one and the most important finding in the project.**

Here is why, in one table. Hyperliquid charges about 0.09% each time you touch a
position, so a two-legged trade opened and closed costs **0.36–0.40%**. Against that:

| Idea | What it earned per trade | What it cost |
|---|---:|---:|
| Gold vs gold-token | 0.18% | 0.27% |
| Dual-listed shares (35 companies, 22 years) | 0.23% | 0.40% |
| Buying the day's losers | +59%/yr *before* costs | 314%/yr in fees |
| Overnight stock drift | 0.203% | 0.200% |
| Market making | 0.001–0.008% | 0.03–0.06% |

That fourth row is the project in miniature. The idea works. It earns three-thousandths
of a percent more than it costs. That is not a business.

**Why this keeps happening:** efficient markets do not leave large gaps lying around.
Where a gap is big and obvious, someone has already closed it. Where it survives, it
usually survives *because* it is too small to be worth anyone's while — including ours.

---

## 5. What we tried

Grouped by what kind of idea it was. Full detail in `MASTER_V3.md` and
`VENUE_SWEEP_2026-09-17.md`.

### 5a. "Two things that are really the same thing"

The cleanest version of direction-neutral trading: find two instruments that are the same
claim priced differently, buy the cheap one, sell the dear one.

| Idea | Outcome |
|---|---|
| SK Hynix Korean share vs its US share | The best-structured idea in the project. 11 trades, 2 of which carried the whole result. Not enough to know. |
| Gold perp vs gold token (same ounce) | Relationship real; the gap is 0.18% against a 0.27% cost |
| Nine companies listed twice on Hyperliquid | Gaps of 0.08–0.98% against 0.40% cost, and the second listing is frozen 15–59% of the time |
| Bitcoin vs MicroStrategy, chipmaker vs chip price, gold vs silver | The relationship is not stable enough to hedge with |

**Why this family matters:** it is the only one where the hedge ratio comes from the
instrument definition rather than from fitting a line to past data. Fitted hedge ratios
drift, and that drift killed five separate attempts. **But Hyperliquid lists only a
handful of such pairs, so it can never satisfy rule 1.**

### 5b. Ranking the whole market and buying the best

| Idea | Outcome |
|---|---|
| Buy cheap / sell expensive across 124 markets | **The signal was backwards.** The "expensive" names returned +148%/yr, the "cheap" ones +6.3% |
| Plain momentum, same universe | Cannot be told apart from luck once you account for how many things we tried |
| Momentum with market moves stripped out | Same |
| Combined momentum book | **Still alive — see §6** |

### 5c. Getting paid to hold something

| Idea | Outcome |
|---|---|
| Funding on extreme markets | Extremes last a **median of 2 hours**. You need days to earn back the trade cost. |
| Crude oil funding | **Re-rated, still alive — see §6** |
| Buy the real thing, sell the perpetual | Only 8 tokens have both. Fails rule 1 on arithmetic. |
| Polymarket liquidity rewards | The reward allows a 4.5c spread. Market makers already quote **0.1c**. The subsidy has been competed away. |

A finding worth keeping from this family: **timing your entry on extreme funding is worse
than not timing it at all.** Just holding the prevailing side collects more.

### 5d. Prediction markets (Polymarket)

Nothing had ever been built here. Two days of work in September established:

| Question | Answer |
|---|---|
| Is Polymarket well priced? | **Yes.** When it says 30%, it happens about 30% of the time. Its forecasts beat a naive guess by a wide margin. |
| Are longshots overpriced? | Slightly, in the right direction — but by less than the cost of trading them |
| Can you sell longshots profitably? | **No.** Loses at 6 of 8 settings. The two that "win" rest on 0 and 1 actual events. |
| Riskless arbitrage between related bets? | **None found** across 45 related contracts |
| Bitcoin price bets vs the Bitcoin perp | Not an arbitrage. It is a bet on how volatile Bitcoin will be — a forecast, not a free lunch. |

**A well-priced market is exactly the market with no edge in it.** That is the finding, and
it is the same conclusion as Hyperliquid arrived at from the other direction.

### 5e. Things we tested that are out of scope under rule 0

Real work, real results, **not tradeable on our venues.** Kept because the methods carry
over and because knowing they fail saves repeating them.

- A wide sweep of 310 instruments across five asset classes: **6 passed**, which is about
  what chance produces from 310 tries.
- A market-neutral engine on US equities: genuinely removed market exposure (the book made
  money in 2018 and 2022, the two down years) but only earned about half a Sharpe before
  costs.
- Indian ETFs and single-stock futures: the famous "fees kill it in India" conclusion turns
  out to be an artifact of a small account meeting a flat ₹20 fee — at larger size the cost
  is 3–5bp, not 40bp. **Still out of scope.**

---

## 6. What is still alive

Three things. **All three fail on the same question**, which is §7.

### Lead 1 — Crude oil carry, hedged

Crude oil perpetuals pay people to hold them. The log recorded this as **0.6% per day,
stable**. Six months of data says otherwise:

| | Claimed | Actual |
|---|---:|---:|
| Paid per day | 0.6% | **0.09%** |
| Hedged against Brent | — | **~6% a year** |

The 0.6% figure was measured on the one day it was true. It is not zero, but it is about
six times smaller than recorded, and hedging it removes three quarters of what is left.

**What kills it:** turnover. Holding throughout earns +9.1% over six months. Rebalancing
weekly earns **+0.19%** — fees eat it entirely.

### Lead 2 — The combined momentum book

Two momentum strategies that are mediocre alone but good together.

| | |
|---|---:|
| Sharpe ratio | **1.44** |
| Confidence it is skill, not luck | **0.71** |
| The bar we set | **0.95** |

Individually each strategy is a coin flip. Combining them is what does the work. It is the
closest thing in thirty-odd attempts, and **it is not over the line.**

**What it needs:** about two more years of data, or genuinely live results. There is no
clever re-analysis of the existing data that gets there — the sample is the constraint.

### Lead 3 — The fast reversal book

The strongest signal in the project, and the one that actually delivers rule 4.

| Cost per trade | Result |
|---|---:|
| 1.5c (perfect, no slippage) | Sharpe **2.69** |
| 3.0c (realistic) | Sharpe **1.09** |
| 4.5c (taking the offered price) | Sharpe **−0.52** |

It trades 6.6 times a day. It was tested on data it had never seen, on a list of markets
that **includes the ones that died** — so it is not flattered by survivorship.

**What kills it:** it only pays between 0 and about 4 cents of cost, and nobody has
established that we can trade in that band.

---

## 7. The one question that decides everything

> **If we place orders patiently instead of taking whatever price is offered, do they
> actually get filled — and at what real cost once you account for being filled mainly
> when you are wrong?**

Taking the offered price costs about **9 basis points per leg**. Posting an order and
waiting costs about **3**. That difference is worth more than every signal improvement
found anywhere in this project, combined.

Here is the same table for every live idea:

| Idea | If we pay the expensive price | If we get the cheap price |
|---|---:|---:|
| Fast reversal book | Sharpe **−0.52** | Sharpe **+1.09** |
| Pairs book | Sharpe **−0.64** | Sharpe **+0.11** |
| Crude carry | dies at weekly turnover | survives |
| Momentum book | needs live evidence either way | needs live evidence either way |

**The 3 basis point figure is a guess.** It is a constant someone typed into the codebase
and it has never been checked against a real filled order.

The only evidence that exists: the paper-trading harness ran for **one day** and came back
with **0.00 basis points of slippage on an $11 order**. That is one tiny order on one day.
It points the right way and it proves nothing.

**This cannot be answered by more backtesting.** It requires placing orders and watching
what happens. That is the whole task.

---

## 8. What we got wrong about ourselves

These cost more than any individual strategy and are worth more attention than the list of
failures.

**We sent Mahan a number that does not reproduce.** A strategy was reported at Sharpe 1.48.
Re-running our own code on our own data produces **−3.43**. Not one figure in that report
reproduces and most flip from positive to negative. The cause: that work was never put
under version control, so no result could be traced back to the code that made it. *A
result you cannot trace to the code that produced it cannot be defended.*

**An independent check of six claims confirmed zero of them.** Not all were wrong in
direction, but every one was overstated — a loss rate exaggerated by bad arithmetic, a
"42% of markets died" that was really 15.8%, "only one dual-listed pair exists" when there
were nine.

**We spent our statistical budget without tracking it.** Testing about twenty variations at
ordinary confidence levels produces a convincing false positive by chance alone. We tested
about thirty before anyone applied the correction for that. When it was finally applied,
every strategy failed — including two we had been excited about. **It is cheap and should
be computed from day one.**

**We keep not running the tests we have already designed.** The crude-oil kill criterion was
written down in August and the data to answer it had been accumulating since April. It was
not run until September. The same is true of the funding-persistence test. *The bottleneck
is not ideas, it is executing the tests we already specified.*

**Two data-collection jobs are currently stopped.** The recorder last wrote on **10
September**. The paper-trading harness last ran on **1 September**. Both feed §7.

---

## 9. Where this leaves us

**The structural objections are answered.** A year ago the honest criticism was that we had
one hand-picked pair, no process, no out-of-sample test, and a book that was just long the
market. All of that is fixed. We can build a rule-based book across many instruments, hedge
it properly, test it on unseen data, and show it makes money when markets fall. Rule 4 —
enough trades — turned out to be reachable too.

**What is missing is an edge bigger than the toll.** Both venues are efficient at the size
we trade. The three places inefficiency was supposed to live — extreme funding payments,
liquidity subsidies, and mispriced longshots — each turned out to be already competed away
or too small to measure against the spread.

**That is a real finding, not an absence.** It is worth saying to Mahan plainly: the
constraint he set first (these two venues) and the outcome he asked for last (something
sellable) are in tension, and we can now show why with numbers rather than assert it.

**And it is not yet settled**, because the single measurement that decides three of our
leads has never been taken.

### What to do next, in order

1. **Restart the paper-trading harness and measure fills.** Days of work. Decides §7, which
   decides three leads. Nothing else should jump this queue.
2. **Restart the recorder.** It has been down over a week. Polymarket's price history is
   only readable about six weeks back, so **every day it is off is data that cannot be
   recovered at any price.**
3. **Ask a lawyer about Polymarket.** Whether an offshore prediction market is legally
   usable from India is unresolved, and a negative answer removes half our permitted venue
   surface permanently.
4. **Then, and only then, revisit the two surviving books** with whatever the fill
   measurement says.

If the fills come back expensive, the honest report is that these two venues at this
account size do not contain a fundable strategy. That is a legitimate answer, reachable in
about a week, and better than continuing to search for a signal large enough to pay a toll
nothing has yet cleared.

---

## 10. Where the detail lives

| Document | What it is |
|---|---|
| **[WHAT_WE_ARE_DOING.md](WHAT_WE_ARE_DOING.md)** | The goal and the obstacles, at length |
| **[MASTER_V3.md](MASTER_V3.md)** | The first 30 ideas, and exactly why each failed |
| **[VENUE_SWEEP_2026-09-17.md](VENUE_SWEEP_2026-09-17.md)** | The most recent 8, including all the Polymarket work |
| **[CRUDE_CARRY_RECHECK.md](CRUDE_CARRY_RECHECK.md)** | Lead 1, measured over six months |
| **[SURVIVORS_RECHECK.md](SURVIVORS_RECHECK.md)** | Lead 2, and the confidence test applied to it |
| **[FAST_BOOK_TEST.md](FAST_BOOK_TEST.md)** | Lead 3, tested out of sample |
| `../documentation/MAHAN_SPEC.md` | The rules, with acceptance criteria |
| `../backtesting/hyperliquid/hip3/MAHAN_BRIEF.md` | The rules in Mahan's own words |

---

## A note on how to read any number in this project

Ask three questions of anything reported here or anywhere else in the repository:

1. **Which window produced it?** Full-sample results and out-of-sample results are
   different claims, and we have mixed them up before.
2. **How many things were tried before this one worked?** Thirty-odd attempts means a
   result needs to clear a much higher bar than it looks.
3. **What cost was charged?** Almost every dead idea in §5 was alive until a realistic
   fee was applied.

If a number cannot answer all three, it is not yet a result.
