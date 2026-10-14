# What we are trying to do, and why it is hard

**A plain explanation of the goal, the rules, and the obstacles.**

---

## The goal

Build an automated trading strategy that makes money steadily, on Hyperliquid, **without betting
on whether markets go up or down.**

That last part is the important one. Anyone can make money in a rising market by buying things.
The point here is to make money *whichever way the market goes*, by finding relationships between
instruments that hold regardless of direction.

---

## The rules it has to satisfy

These come from Mahan, who decides whether an idea gets funded. In his words, compressed:

| # | Rule | Why he wants it |
|---|---|---|
| 1 | Tradeable on Hyperliquid | Where we operate |
| 2 | **Lots of trades** | One good trade is luck; a thousand is a process |
| 3 | **Many instruments, not one** | *"focusing on one stock will not be high sharpe ratio"* |
| 4 | **Hedged — one long, one short** | *"i dont want to be naked long the stock market"* |
| 5 | **Works in falling markets too** | Direction should not matter |
| 6 | **A process, not a hand-picked find** | *"not just manually finding this one stock"* |
| 7 | **Tested on data it has not seen** | Backtests alone prove nothing |
| 8 | **Not trivially simple** | *"we cannot sell this strategy to anyone"* |

Rules 2, 3 and 6 are really one rule wearing three hats: **breadth**. A strategy that trades one
instrument fails several of these at once, no matter how well it performs.

We added a ninth rule ourselves, learned the expensive way:

> **9. It has to survive fees.** Every idea we killed died here.

---

## The core idea we started with

The cleanest version of "make money without picking a direction" is this:

> Find two things that are *the same thing*, priced differently. Buy the cheap one, sell the
> expensive one, wait for them to converge.

If you own both sides, you do not care where the market goes — only whether the gap closes.

The best example we found: **SK Hynix**, a Korean chipmaker, trades on Hyperliquid as both its
Korean share and its US share. Same company, fixed conversion ratio between them. When they
drift apart, one is objectively too cheap relative to the other.

That is a genuine relationship, not a statistical coincidence — which matters, because most
apparent relationships in markets are coincidences.

---

## Why it is hard

### Obstacle 1 — the toll

Every trade costs about 0.09% per leg. A two-legged trade, opened and closed, costs 0.36%.

That number is unremarkable until you discover how small real market inefficiencies are. The
gaps we found were typically 0.2% to 0.5%. Roughly the same size as the toll.

**Efficient markets do not leave large gaps lying around.** Where a gap is large and obvious,
someone has already closed it. Where it survives, it usually survives *because* it is too small
to be worth anyone's while — including ours.

### Obstacle 2 — the venue only lists one such pair

For a "same thing, two prices" trade, both sides must be tradeable. Hyperliquid lists roughly
104 stock-like markets, and **exactly one company has both of its listings available** in a form
worth trading. So the strategy cannot scale, and rule 3 fails structurally.

*(There are nine companies whose identical shares trade on two different Hyperliquid venues. We
tested all nine. The gaps are 0.08%–0.98% against a 0.40% cost, and the second listing is frozen
15–59% of the time. Real relationships, too efficient to trade.)*

### Obstacle 3 — short history

Hyperliquid's data goes back about 5,000 hours — roughly seven months. Many of its markets are
newer than that. The pair we care most about has existed since July.

You cannot establish that something works with two months of data. Statistically, our best pair
needs about two years.

### Obstacle 4 — the one that eventually undid us

If you test enough ideas against the same short history, you will eventually find one that looks
excellent purely by chance.

There is arithmetic for this. Testing about twenty variations at ordinary confidence levels will
produce a convincing false positive. **We tested about thirty.**

So when a late idea looked good, we could no longer tell whether it was real or the expected
false positive. Applying the correct statistical adjustment — which discounts a result by how
many things you tried — every single idea failed, including two we had been genuinely excited
about.

---

## Where that leaves the approach

The historical data is exhausted. Not because we ran out of ideas, but because we have used up
our statistical budget against it: any new idea now has to clear a bar so high that nothing
realistic will.

So the work has changed shape:

**1. Gather data nobody has.** A recorder now samples every Hyperliquid market every five
minutes. In a month it will hold information no backtest can currently see — how payments between
traders behave over time, how deep the order books really are, how it all shifts hour by hour.

**2. Measure the toll rather than assume it.** Every idea died at the fee line, and the gap
between taking a price and patiently offering one is worth more than any signal we found. Whether
patient orders actually get filled cannot be answered from price history — only by watching.

**3. Change what counts as a lead.** We now look for structural facts — a market paying people
to hold it, an inefficiency with a mechanism behind it — rather than patterns in a price series.
Patterns in a price series is exactly what thirty failures were made of.

---

## What honest success looks like from here

Not a backtest with a good number. We have produced several of those and none survived.

Success is: **a mechanism we can explain, measured on data we collected ourselves, that clears
the fee line with room to spare, across enough instruments to satisfy rule 3.**

We do not have that yet. We have one candidate that satisfies the first two conditions and is
blocked on the third. That is further than a good-looking backtest, and further than we were a
week ago.
