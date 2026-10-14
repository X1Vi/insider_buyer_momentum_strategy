# Reducing drawdown on the crude books — corrected

**Run 21 September 2026. This file replaces an earlier version of itself from the same day,
whose main recommendation was wrong.** See §6 for what changed and why.

Data as in `CRUDE_OIL_STATS.md`: `xyz:CL` 258 closed daily bars (2026-01-06 → 2026-09-20),
`xyz:BRENTOIL` 201 bars (2026-03-04 →), paginated hourly funding. Every overlay weight is
computed from **closed bar t and applied to bar t+1**, net of |Δw| × legs × 9bp HIP-3 taker.

*Reproduce:* `oil_overlays.py` (sweep, equal-risk, split-half), `oil_hedge_ratios.py`,
`oil_ddctrl.py` in `backtesting/hyperliquid/hip3/`.

**Verdict: no overlay is recommended. On the hedged book there is nothing left to improve —
its entire positive result is March plus three days of April. On unhedged CL, vol targeting
raises return per unit of risk but does not reduce drawdown at matched risk, which is what
was asked for.**

---

## 0. The two rules this study runs on

**Rule 1 — equal risk.** Any overlay lowers drawdown by holding less, and holding less is
free: it is the position-size dial. So every variant is rescaled to a common 15% ex-post
realised volatility before its drawdown is compared. Only a rule that is *selectively*
smaller — out of the market during bad stretches, full size during good ones — survives
rescaling. A rule that is merely *uniformly* smaller does not, and should not.

**Rule 2 — one common window.** Overlays warm up at different speeds; a 30-day lookback
starts a month later than a 10-day one. Scoring them over their own available ranges lets a
slow rule silently skip the sample's worst days and call it risk management. Every number
below is scored on a single window where all variants have a valid weight.

Rule 2 is the one that broke the earlier version of this file.

---

## 1. CL long — 227 days, 2026-02-06 → 2026-09-20

Sorted by Calmar (equal-risk return ÷ equal-risk drawdown).

| Driver | Overlay | Raw vol | Raw DD | Ann @15% | **DD @15%** | Calmar | SR | H1 | H2 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| self | trend SMA10 × voltarget 30% | 28.7% | −11.0% | +39.0% | **−5.8%** | **6.68** | 2.27 | 2.15 | 2.44 |
| self | trend SMA10 | 57.8% | −22.6% | +26.3% | **−5.6%** | 4.69 | 1.63 | 1.50 | 2.17 |
| self | voltarget 20% (rv30) | 22.9% | −14.1% | +36.3% | −9.5% | 3.83 | 2.14 | 2.72 | 1.46 |
| self | voltarget 20% (rv20) | 23.2% | −15.1% | +35.4% | −9.9% | 3.55 | 2.09 | 2.53 | 1.59 |
| **—** | **none (baseline)** | **69.2%** | **−33.9%** | **+26.7%** | **−8.3%** | **3.24** | **1.65** | 2.06 | 1.11 |
| self | trend SMA50 | 63.6% | −30.1% | +22.3% | −7.3% | 3.07 | 1.42 | 1.53 | 1.48 |
| self | trend SMA20 × voltarget 30% | 30.9% | −19.2% | +25.5% | −9.6% | 2.66 | 1.59 | 1.51 | 1.72 |
| self | voltarget 20% (rv10) | 24.4% | −18.1% | +29.2% | −11.5% | 2.54 | 1.78 | 2.33 | 1.19 |
| self | trend SMA20 | 60.9% | −39.8% | +12.7% | −10.6% | 1.20 | 0.87 | 0.73 | 1.26 |
| self | carry>0 (30d) | 48.5% | −33.9% | +5.5% | −11.6% | 0.48 | 0.43 | 0.24 | 0.73 |
| self | carry>0 (14d) | 47.9% | −45.7% | −12.1% | **−16.5%** | −0.73 | −0.78 | −0.17 | −1.68 |

**Vol targeting does not reduce drawdown here.** Every setting lands at −9.5% to −11.8% at
matched risk, against the baseline's **−8.3%**. Raw DD falls from −33.9% to −14.1%, and all
of that is position size. What vol targeting *does* buy is return per unit of risk: Sharpe
1.65 → 2.14, Calmar 3.24 → 3.83. That is a real effect, consistent across all nine
target × lookback settings — it is just not an answer to the question you asked.

**The trend results do not cohere.** SMA10 is the best thing in the table, SMA20 is close to
the worst, SMA50 is middling. No ordering in the lookback, no mechanism, best-of-11 selection.
Treat `trend SMA10 × voltarget 30%` as a forward-test candidate and nothing more; its Calmar
of 6.68 is the single most over-fitted number in this document.

---

## 2. CL/BRENT hedged — 170 days, 2026-04-04 → 2026-09-20

**The baseline is negative over this window.** −0.33 Sharpe, −5.9%/yr at 15% risk.

| Driver | Overlay | Raw vol | Raw DD | Ann @15% | DD @15% | Calmar | SR |
|---|---|---:|---:|---:|---:|---:|---:|
| CL | trend SMA10 × voltarget 30% | 4.4% | −2.0% | +9.8% | −6.7% | 1.47 | 0.70 |
| CL | trend SMA10 | 8.3% | −5.3% | +5.1% | −9.4% | 0.54 | 0.41 |
| CL | voltarget 20% (rv20) | 3.7% | −1.9% | −1.9% | −7.6% | −0.24 | −0.05 |
| self | voltarget 20% (rv20) | 10.7% | −7.4% | −5.1% | −10.2% | −0.50 | −0.28 |
| **—** | **none (baseline)** | **11.4%** | **−8.4%** | **−5.9%** | **−11.0%** | **−0.54** | **−0.33** |
| self | trend SMA20 | 8.6% | −4.0% | −5.6% | −6.9% | −0.81 | −0.31 |
| self | carry>0 (30d) | 10.3% | −8.4% | −12.3% | −12.1% | −1.02 | −0.80 |
| CL | carry>0 (14d) | 10.0% | −8.0% | −15.0% | −11.8% | −1.27 | −1.01 |

Twenty-eight of thirty variants lose money. The two that don't are both `trend SMA10`
descendants and both driven by CL rather than the spread — the same incoherent filter flagged
above, now selected from a larger pool.

### Why the baseline turned negative

`CRUDE_OIL_STATS.md` reports the hedged book at **+10.37% / Sharpe 1.13** over 200 days from
5 March. Both are correct. They decompose as:

| Segment | Days | Return |
|---|---:|---:|
| 5–31 March | 27 | **+8.07%** |
| **1–3 April** | **3** | **+4.26%** |
| 4 April – 20 September | 170 | **−2.04%** |

**Three days in April are worth more than the other 197 combined.** The split-half table in
the stats report (H1 1.99 → H2 −0.78) was pointing at this; the common-window requirement
made it explicit. The hedged crude book does not have a drawdown problem worth solving — it
has an edge problem, and §3–5 are exercises in re-sorting noise.

---

## 3. Carry filters remain the clearest negative result

| Book / driver | Overlay | Sharpe | DD @15% |
|---|---|---:|---:|
| CL long | carry>0 (14d) | **−0.78** | **−16.5%** |
| CL/BRENT, spread-driven | carry>0 (30d) | −0.80 | −12.1% |
| CL/BRENT, CL-driven | carry>0 (14d) | **−1.01** | −11.8% |

Worst or near-worst in every table, under both drivers, at every lookback, before and after
the bug fix. The intuitive trade — "hold crude only when the funding is actually paying" —
inverts the Sharpe.

The mechanism is that funding is a *consequence* of price, not a predictor. A long pays when
the perp runs to a premium and receives when it sags to a discount, so trailing carry is a
lagged price signal read backwards, and conditioning on it systematically buys after the move
that created the funding. **Carry is a thing to collect, not a thing to time.** This is the
most transferable finding in the study and it applies to every funding-carry idea in `hip3/`.

---

## 4. Drawdown control does nothing

Cut exposure while the book's own equity is underwater, judged at equal risk:

| Rule | CL: Calmar | Hedged: Calmar |
|---|---:|---:|
| baseline | **3.26** | **2.35** |
| cut to 50% after −5% DD | 3.34 | 0.87 |
| cut to 0% after −5% DD | 1.89 | 0.44 |
| cut to 0% after −10% DD | 3.73 | 2.30 |
| cut to 50% after −20% DD | 3.20 | 2.30 |

Scattered either side of baseline on CL with no monotone response to trigger depth or cut
size — noise. Actively harmful on the hedged book at tight triggers. **Rejected.**

---

## 5. Hedge ratios don't reduce drawdown either

| Hedge (all causal) | Days | Ann. | Sharpe | Max DD | H1 | H2 |
|---|---:|---:|---:|---:|---:|---:|
| **1:1 notional** | 200 | +19.5% | 1.12 | −8.4% | 1.98 | −0.78 |
| rolling vol-ratio (20d) | 180 | +22.1% | **1.40** | −11.0% | 1.98 | +0.46 |
| rolling OLS beta (20d) | 180 | +20.1% | 1.30 | −10.5% | 1.78 | +0.52 |
| rolling vol-ratio (60d) | 140 | +9.6% | 0.88 | −5.2% | 1.52 | +0.06 |
| static beta 1.07 (look-ahead) | 200 | +13.0% | 0.82 | −9.6% | 1.86 | −1.49 |

A 20-day rolling ratio raises Sharpe and flips H2 positive, but **deepens** max drawdown.
Caveat: these rows have different start dates by construction (200 / 180 / 140 days), so the
max_dd column is *not* like-for-like — the 60-day row's shallow −5.2% partly reflects starting
after March. Stay at 1:1: free, unfitted, and not beaten on drawdown.

---

## 6. What changed from the earlier version of this file

The first version recommended *"add 20% vol targeting on the hedged spread, 20-day realised
vol"*, reporting −5.2% vs −7.3% drawdown and Calmar 2.30 → 4.78 at matched risk.
**That recommendation is withdrawn.** Two bugs, both mine, both in `oil_overlays.py`:

1. **Driver.** The CL frame was passed as the overlay source for *both* books, so every
   hedged-book overlay was computed from CL's outright price and carry rather than the
   spread's own. The rule I described and the rule I ran were different rules. CL-book
   results were unaffected.
2. **Window.** Variants with different warm-up lengths were scored over different date
   ranges. The 20-day vol-target rule began after the hedged book's worst stretch; the
   baseline did not. Its drawdown advantage was substantially a later start date.

Fixing (2) also surfaced §2's real finding — that the hedged book is flat-to-negative from
4 April — which the original framing hid completely.

**What survives both fixes:** the equal-risk method itself, which is what caught this;
the carry-filter rejection (§3); the drawdown-control rejection (§4); the hedge-ratio
rejection (§5); and the original core claim that vol targeting on unhedged CL reduces
drawdown only by reducing size (§1, now −9.5% vs −8.3% at matched risk — same conclusion,
corrected numbers).

**What was found by the bug hunt:** the first version's tables were generated and written up
without anyone checking that the reported exposure of a rule matched the rule as described.
The tell was visible in the output all along — a "20% vol target on the spread" that sat at
full size 76% of the time and never dropped below 57% is not targeting 20% vol on a book
whose vol is 17%. Check that a rule's realised exposure matches its stated intent before
tabulating anything.

---

## 7. Recommendation

1. **Change nothing on the hedged book.** It has no measurable edge outside March and the
   first three days of April. Overlay selection on a negative-expectancy base is noise
   mining, and 28 of 30 variants losing money is what that looks like.
2. **If crude is held at all, hold it unhedged and small, or with vol targeting for the
   Sharpe rather than the drawdown.** At matched risk, vol targeting gives +36.3%/yr vs
   +26.7% with a slightly *deeper* drawdown (−9.5% vs −8.3%). That is a return improvement,
   honestly labelled.
3. **Never condition entry on trailing carry** (§3).
4. **The real drawdown lever is diversification, not timing.** These books hold one bet.
   Running crude beside uncorrelated books from the HIP-3 universe already mapped in `hip3/`
   cuts drawdown in a way no timing rule on a single spread can, and it does not require the
   edge to be real in any one of them.
5. **Next measurement, unchanged from `CRUDE_CARRY_RECHECK.md`:** discount persistence — does
   `xyz:CL` trade at a structural discount to its oracle because HIP-3 markets are hard to
   arbitrage? That is the only question whose answer would change whether any of this is worth
   holding.
