# PLAN — India insider-purchase drift (small caps)

**2026-10-13.** Build-and-test plan for Lead #1 in
`data/2026-10-13/NICHE_INEFFICIENCIES.md`. Cash-only, hold days. This is a
research plan; nothing here is a result. Follows `AGENTS.md` and the gates in
`data/2026-10-12/INVESTIGATION_PLAN.md`.

---

## 0. The one number this decides

> **Do disclosed insider *purchases* in small Indian firms predict positive
> abnormal returns over the following 5–90 days, net of cost and measured against
> a size-matched benchmark?**

If yes (excess CAR clears cost with a real CI), it becomes a paper-trade
candidate. If no, write the null and move to Lead #2.

**Kill number:** excess CAR (disclosure date → +90d) net of ₹16k delivery
(~27 bp round trip) + measured smallcap spread. **Dead if** the CI spans 0 after
FDR over all cuts × horizons, or the net number ≤ 0.

---

## 1. Pre-registered gates (written before any data is seen)

| Gate | Pass condition |
|---|---|
| Data integrity | prices split-repaired on close **and** open; benchmark aligned to same calendar |
| Point-in-time | events dated by **disclosure date**, never the trade date |
| Signal | excess CAR > 0 and beats a size-matched benchmark |
| Multiple testing | survives BH-FDR at 5%; raw hits > expected-by-chance |
| Cost | net excess CAR > 0 at measured all-in cost |
| OOS | positive on a held-out period (70/30) and walk-forward |
| Power | enough **non-overlapping** events to say anything (see §5) |

Anything failing **Signal / Cost / OOS** is not worth a live test.

---

## 2. Stage 0 — Define (before touching data)

- **Relationship:** event-driven post-disclosure drift (a PEAD-like anomaly),
  documented in India (`NICHE_INEFFICIENCIES.md` refs).
- **Economic reason:** insiders buy when they believe the firm is undervalued;
  small firms are under-covered, so the market incorporates it slowly.
- **Universe:** NSE/BSE small caps — e.g. Nifty Microcap 250 + Smallcap 250
  members at the time of the event (point-in-time membership if obtainable).
- **Cost:** ₹16k delivery ≈ 27 bp round trip; **plus a measured smallcap spread**
  (the spread is the number most likely to kill this).
- **Holding window:** 5 / 20 / 60 / 90 days (test all; pre-register the primary
  as 60d).

---

## 3. Data

| Need | Source | Note |
|---|---|---|
| Insider (PIT/SAST) disclosures: date, side, value, person, role | nse-bse MCP `get_stock_deals` (`india_markets/references/…mcp.md`); NSE/BSE insider pages | must carry the **disclosure/publication date** |
| Daily prices + volume | Groww historical candles (approved) + yfinance cross-check | split-repair **close and open**; flag thin names |
| Benchmark | Nifty Microcap 250 / Smallcap 250 index (or size-matched basket) | for excess return, not raw |
| Spread proxy | intraday (15-min/1-min) or bid-ask where available | required before claiming net-positive |

**Verify before use (do not assume):** current SEBI PIT disclosure threshold
(≈₹10 lakh) and deadline (≈2 trading days). These decide which trades are even
visible, so a selection cut — record it.

---

## 4. Method (event study)

1. **Build events.** First *market-purchase* disclosure per firm; collapse
   clusters (multiple insiders same week) into one event. Record `t0` =
   disclosure date.
2. **CAR windows.** `[0,+5]`, `[0,+20]`, `[0,+60]`, `[0,+90]`, market-adjusted
   against the size benchmark; also an estimation window for normal return.
3. **Benchmark control.** Report both market-adjusted and size-matched excess;
   the raw return is meaningless (small caps move with the segment).
4. **Non-overlap.** Count independent events, not rows (repo trap: overlapping
   trades counted independently).
5. **Eyeball.** Plot a few CAR paths + the event-time average; check for a
   disclose→pop→fade shape (if *both* long and short "work", it's noise).

---

## 5. Cuts and multiple testing

Cuts the literature says matter — each is a hypothesis, so **FDR them together**:
- small vs large firm; promoter vs employee/director; clustered vs singleton;
  non-conglomerate vs conglomerate; low-FII vs high-FII; trade value size bucket.

Report: raw hits, expected-by-chance, BH-FDR survivors. **If raw ≈ chance, stop.**

**Power check first:** if independent events are too few (rule of thumb: < ~50),
say so up front and either widen the universe (add Nifty 500) or shelve.

---

## 6. Cost and out-of-sample

- Convert gross excess to **breakeven cost**; compare to measured all-in cost.
- 70/30 split (choose on train only) then walk-forward.
- Report OOS Sharpe/CAR **with standard error** and a deflated Sharpe against the
  honest trial count.

---

## 7. Mandatory trap checks (AGENTS.md)

- Point-in-time disclosure date (look-ahead is also a legal issue).
- Survivorship: include delisted names or flag the bias.
- Non-synchronous closes: align calendars; no LTP-based "drift".
- Split repair on close **and** open.
- Overlapping events; start-day sensitivity sweep.
- Smallcap spread measured, not assumed.
- Both-sides-profitable = noise.

---

## 8. Deliverables

- `events.csv` (symbol, t0, side, value, role, size bucket).
- `prices/` split-repaired panel + benchmark.
- `car_tables.csv`, `car_plot.png`, `FINDINGS.md` (kill number first).
- Reusable `fetch_insider_events.py`, `event_study.py`.

---

## 9. Sequence

1. **Phase A — data reality check (half day).** Can we pull *dated* insider
   disclosures at all, and how far back? If not, stop and say so.
2. **Phase B — event table + power (half day).** Build events, count independent
   ones, decide if a test is even possible.
3. **Phase C — CAR study + FDR (§4–5).**
4. **Phase D — cost + OOS (§6).**
5. **Phase E — verdict.** Null → graveyard (as *tested-and-dead*, unlike the
   current shelved entries); survivor → paper-trade design.

---

## 10. Scope and caveats

- Cash-only, ~₹16k, delivery. No F&O.
- Regulatory numbers marked "verify" must be confirmed against current SEBI rules.
- If Phase A/B show the data can't be assembled point-in-time, that itself is the
  deliverable: record it and stop.

*Research only; not investment advice.*
