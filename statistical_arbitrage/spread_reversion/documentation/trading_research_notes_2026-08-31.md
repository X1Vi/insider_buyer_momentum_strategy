# Trading Research Notes — 31 Aug 2026

## 1. Overall objective

The main theme of the discussion was **finding a repeatable trading edge and, especially, finding a hedge between related markets** rather than simply making a directional bet.

The key question was:

> Can we identify information in one market that gives us a tradable signal in another market, while reducing directional risk?

The markets discussed most were:
- Hyperliquid
- Polymarket
- Crypto markets more broadly
- Traditional trading platforms/markets where fees can materially affect a hedge

---

## 2. Order-book / market-microstructure idea

We discussed using **Hyperliquid order-book data** to detect unusually large orders or aggressive buying/selling.

The naive version of the idea is:

1. Read the order book.
2. Detect a very large bid/ask or unusually strong imbalance.
3. Infer that someone is expressing strong buying/selling pressure.
4. Trade in the same direction.
5. Exit when the pressure disappears/reverses.

A more refined version would look at:
- Bid/ask depth
- Order-book imbalance
- Market-order aggression
- Trade flow
- Changes in depth over time
- Large order placement/cancellation
- Persistence of the imbalance
- Price response after the imbalance
- Short-term momentum

### Important realization

We questioned whether this is **too basic**.

If the strategy is simply:

> "There is a big buy order → buy."

then sophisticated firms, market makers, and fast traders are likely already doing some version of it, often with:
- lower latency
- better data
- better execution
- better models
- more complete market context

Therefore the raw presence of a large order is probably **not enough by itself** to constitute an edge.

---

## 3. The whale-order problem

A major question was what a large order actually means.

A large visible order could represent:
- Genuine demand/supply
- A market maker's liquidity
- Hedging
- A passive limit order
- Inventory management
- A temporary liquidity test
- Spoofing / cancellation before execution
- A trader attempting to influence short-term behavior

Therefore:

**Large order ≠ guaranteed future price direction.**

The more interesting signal is potentially:

> Large order + actual execution + persistent trade flow + price response.

This moves the research away from simply observing the static order book and toward **market microstructure and order-flow analysis**.

---

## 4. "Whale puts a huge order — should we trade opposite?"

We also considered the opposite interpretation:

> What if a whale places a large visible order and we trade against it, or use its behavior to trade another coin?

This led to an important distinction.

A large order may be useful not because we blindly follow it or fade it, but because it can reveal something about the participant's **intent, inventory, or hedging activity**.

The more interesting research question is therefore:

> Can activity in one instrument reveal information about what the same participant is likely doing elsewhere?

That is much closer to a real cross-market hedge/relative-value strategy.

---

## 5. Cross-asset / cross-market idea

One potentially interesting direction is to avoid trading the same market that generated the signal.

For example:

**Market A produces unusual flow → Market B reacts later.**

Potential mechanisms:
- BTC flow affects ETH/altcoins
- Perpetuals lead spot
- One exchange leads another
- A major coin's order flow propagates into correlated coins
- Crypto price moves affect prediction-market probabilities
- Prediction-market prices react to information that may first appear elsewhere

This creates a possible **lead-lag strategy** rather than a simple directional strategy.

The research question becomes:

> Is there a statistically persistent delay between two related markets?

If yes, the signal can potentially be traded in the lagging market.

---

## 6. Polymarket + Hyperliquid

We discussed looking for a connection between **Polymarket and Hyperliquid** that could create a hedge.

The important conceptual distinction is that these markets can encode different forms of information:

- Hyperliquid: continuous, highly liquid crypto trading and derivatives
- Polymarket: event probabilities / prediction-market pricing

The goal is **not** to assume they always move together.

Instead, look for situations where:

1. The same underlying event or information affects both markets.
2. One market reprices before the other.
3. The relationship is stable enough to estimate.
4. Trading and settlement mechanics still leave enough edge after fees/slippage.

Possible research questions:
- Does crypto market volatility change Polymarket probabilities?
- Does a Polymarket probability change predict crypto price movements?
- Does crypto price/volatility predict probability changes?
- Are there event-driven lead-lag relationships?
- Can one market be used as a hedge for exposure in the other?

---

## 7. Pair trading / relative value

Pair trading came up as one of the more established approaches to capturing relationships instead of pure direction.

Basic structure:

**Long A + Short B**

The strategy is based on the **spread** rather than the absolute price.

Examples of research directions:
- Highly correlated crypto pairs
- Perpetual vs spot
- Different exchanges
- Related tokens
- Related event contracts

Important point:

**Correlation alone is not enough.**

We want evidence that the relationship is:
- Stable
- Economically explainable
- Mean-reverting or predictably directional
- Tradable after fees
- Robust out of sample

---

## 8. Momentum / trend capture

Another major direction was:

> How do we actually capture a trend?

One approach discussed was identifying **momentum** rather than trying to predict every move.

Possible momentum signals:
- Price acceleration
- Breakouts
- Volume expansion
- Order-flow imbalance
- Trade aggression
- Volatility expansion
- Cross-market confirmation

A strong strategy would ideally combine multiple pieces of evidence:

**Price + flow + volume + cross-market confirmation**

rather than relying on one simplistic signal.

---

## 9. Order flow as a momentum confirmation signal

A more interesting version of the order-book idea is therefore:

### Weak version
Large bid → buy.

### Better version
Large bid + buyers actually execute + selling is absorbed + price moves upward + imbalance persists → long signal.

This changes the problem from:

> "Can I see a big order?"

to:

> "Can I detect informed/aggressive flow that is actually moving the market?"

That is much closer to a genuine microstructure research problem.

---

## 10. Speed / competition concern

We explicitly questioned whether a retail or small system can compete with firms that have faster infrastructure.

This is an important concern.

If the edge comes from milliseconds of latency, competing directly with sophisticated market makers/HFT firms is difficult.

Therefore, a better strategy may be one where the edge survives at a slower time horizon, for example:
- Seconds
- Minutes
- Longer event-driven windows

The goal should be to identify **information asymmetry or structural relationships**, not simply to be the fastest order-book trader.

---

## 11. A potentially better direction: information extraction

The strongest idea emerging from the discussion was that the order book should perhaps be treated as **one input**, not the entire strategy.

Possible feature groups:

### Microstructure
- Order-book imbalance
- Depth
- Spread
- Large trades
- Aggressive buy/sell volume
- Cancellation rate
- Trade intensity

### Price
- Returns
- Momentum
- Breakouts
- Volatility
- Mean reversion

### Cross-market
- BTC → ETH
- Major asset → altcoins
- Spot → perpetual
- Exchange A → exchange B
- Hyperliquid → Polymarket
- Polymarket → Hyperliquid

### Event information
- News
- Announcements
- Scheduled events
- Market-specific information

Then test which features actually predict the future move.

---

## 12. Research methodology for finding a hedge

We asked how to systematically research hedge ideas rather than randomly inventing strategies.

A sensible process is:

### Step 1 — Find economically related markets

Examples:
- Same asset across venues
- Closely related crypto assets
- Spot/perpetual
- Crypto/event market relationships
- Markets exposed to the same underlying event

### Step 2 — Form a hypothesis

Example:

> "A large increase in aggressive BTC buying predicts ETH returns over the next 30–120 seconds."

### Step 3 — Collect historical data

Need synchronized:
- Trades
- Order book snapshots
- Prices
- Volumes
- Funding
- Open interest where available
- Event-market prices where relevant

### Step 4 — Define the signal precisely

Avoid vague rules like:
> "big order"

Instead define thresholds mathematically.

For example:
- order size > 99th percentile
- imbalance > X
- aggressive volume ratio > Y
- signal persists for Z seconds

### Step 5 — Measure predictive power

Test:
- Forward returns
- Hit rate
- Conditional returns
- Sharpe
- Drawdown
- Stability over time
- Different market regimes

### Step 6 — Add realistic costs

A signal that works before costs may be useless after:
- Trading fees
- Bid/ask spread
- Slippage
- Funding
- Market impact
- Polymarket execution/settlement costs

### Step 7 — Out-of-sample testing

Separate:
- Research/training period
- Validation period
- Final unseen test period

Do not optimize directly on the entire dataset.

---

## 13. Fees are part of the strategy

We discussed how high fees can destroy a hedge.

This is especially important because a theoretically market-neutral pair can still lose money if:

**Expected edge < fees + spread + slippage + funding**

Therefore every strategy should calculate:

**Net expected P&L = Gross edge − transaction costs − funding − slippage**

This is not an implementation detail. It should be part of the initial strategy design.

The earlier discussion about Groww highlighted exactly this problem: a hedge can look attractive before costs but become useless once actual trading charges are included.

---

## 14. Why "just follow momentum" is not enough

Momentum is a real and widely studied phenomenon, so simply saying:

> "Price is going up → buy."

is also too simplistic.

Potential ways to improve it:
- Require volume confirmation
- Require order-flow confirmation
- Use volatility regime filters
- Use cross-asset confirmation
- Avoid low-liquidity periods
- Detect trend exhaustion
- Use adaptive holding periods
- Combine momentum with relative-value hedges

The objective is not to invent a complicated strategy for its own sake.

The objective is:

> Find the smallest set of signals that produces a robust and economically explainable edge.

---

## 15. Core strategic insight from the discussion

The conversation gradually moved from:

**"Can we see a whale order and trade it?"**

toward:

**"Can we extract information from order flow and use it to predict another market, while hedging away unwanted risk?"**

That is a much more promising framing.

The strongest research directions are therefore:

1. **Cross-market lead-lag**
2. **Order-flow-based momentum**
3. **Pair trading / relative value**
4. **Perpetual vs spot relationships**
5. **Exchange-to-exchange price/flow differences**
6. **Polymarket ↔ crypto information flow**
7. **Event-driven hedging**

---

## 16. Questions that still need to be answered

These are the important open research questions:

### Order book
- Which order-book features actually predict returns?
- Do large visible orders have information after controlling for executions?
- How much of the signal disappears after accounting for cancellations/spoofing?

### Momentum
- What horizon works best: seconds, minutes, or hours?
- Does order flow improve standard momentum signals?
- When does momentum fail?

### Cross-market
- Which asset leads which?
- Is the lead-lag relationship stable?
- Does it survive changing market regimes?

### Polymarket / Hyperliquid
- What instruments have a genuine economic link?
- Is there measurable information flow from one market to the other?
- Can the relationship be hedged rather than merely predicted?

### Economics
- What is the expected edge after all costs?
- How much size can the strategy actually trade?
- Does market impact erase the edge?

---

## 17. The strategy-development ladder

A useful progression is:

**Level 1 — Raw signal**
> Large order appears.

**Level 2 — Filtered signal**
> Large order + execution + persistence.

**Level 3 — Predictive signal**
> The flow historically predicts future returns.

**Level 4 — Cross-market signal**
> Flow in A predicts movement in B.

**Level 5 — Hedged strategy**
> Long B / short hedge instrument A or another related market.

**Level 6 — Portfolio strategy**
> Multiple independent signals with risk controls.

This helps prevent jumping directly from an interesting observation to an automated strategy.

---

## 18. Practical takeaway

The main lesson from yesterday is:

**Do not make "whale orders" the strategy.**

Treat order-book and trade-flow data as **features** that may reveal:
- informed activity,
- momentum,
- liquidity shifts,
- market impact,
- or cross-market information.

Then test whether those features create a **repeatable statistical edge** and whether the edge survives real trading costs.

The ultimate target is not simply:

> "Predict price."

A better target is:

> **Find a measurable relationship between markets, estimate the lead/lag or relative-value signal, and construct a trade where the expected edge remains positive after fees and execution costs.**
