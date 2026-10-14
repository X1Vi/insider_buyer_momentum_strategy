# OSINT enrichment plan — India insider + momentum

**Date:** 2026-10-13  
**Purpose:** determine whether public information available at the time of an
insider disclosure can distinguish the rare momentum runs from the many stopped
trades. OSINT ranks the quality of an armed watch; it does **not** replace or
silently change the price rules.

## 1. Fixed baseline

Keep `faithful_momentum.py` unchanged as the control:

1. Public disclosure of a major insider's **Market Purchase** worth at least
   ₹25 lakh arms the stock.
2. The watch persists until price confirms momentum.
3. Entry requires a rise of at least 10% from the disclosure close, a breakout
   above the prior 252-session true high, and `close > EMA50 > EMA200`.
4. Buy next open. Exit next open after `close <= EMA50` or a 10% stop; maximum
   hold 126 sessions.
5. Charge at least 27 bp round trip plus a separately measured spread.

This separation is essential. The earlier optimizer failed because it changed
the strategy while claiming to test the insider signal.

## 2. What OSINT can add

The most useful OSINT is information that answers one of three questions at the
moment the watch is armed:

- **Who is buying?** Is this a controlling promoter, operating director, KMP,
  several independent insiders, or a routine/designated-person transaction?
- **How meaningful is the purchase?** Is it large relative to the buyer's prior
  holding, company market value, and normal traded value—not merely large in
  rupees?
- **What else was publicly happening?** Is the purchase isolated, or does it
  coincide with a contract, earnings change, pledge release, restructuring,
  dilution, auditor warning, or other announcement?

### Priority source map

| Priority | Source from `OSINT/` | Feature enabled | Why it may help |
|---|---|---|---|
| P0 | NSE PIT API (already verified) | buyer identity, category, value, transaction mode, disclosure time | Core event; must retain the dissemination timestamp |
| P0 | NSE corporate announcements | point-in-time event context around the purchase | Separates an informed quiet purchase from a purchase contaminated by an already-public catalyst |
| P0 | NSE official bhavcopy + delivery report | true OHLCV, traded value, delivery ratio, liquidity/spread proxies | Measures purchase size relative to trading activity and fixes Yahoo/corporate-action risks |
| P0 | NSE shareholding patterns | promoter/FII/institutional ownership and changes | Tests the documented low-FII and ownership-concentration hypotheses |
| P0 | BSE insider filings/announcements | cross-exchange verification and BSE-only names | Expands coverage and catches missing/duplicate NSE records |
| P0 | Corporate-action history | splits, bonuses, demergers, symbol changes | Prevents false breakouts and enables delisted/history-safe prices |
| P1 | SAST, pledge and pledge-release disclosures | promoter accumulation and financing stress | A purchase plus declining pledge risk may be more credible than a purchase beside new pledging |
| P1 | MCA/MCA21 company and director records | director identity, subsidiaries, promoter-group graph, government/conglomerate flags | Enables entity resolution and the non-conglomerate/non-government cuts |
| P1 | Bulk/block deals | institutional counterparty activity near the event | Tests whether the purchase is confirmed or opposed by large public flow |
| P1 | Results/annual reports | debt, cash flow, dilution, auditor qualifications | A small, predeclared quality/distress gate; not a large factor-mining exercise |
| P2 | CPPP/GeM procurement awards | contract confirmation for government-facing companies | Useful only for affected sectors; sparse and entity-resolution heavy |
| P2 | Primary RSS/GDELT | attention and news saturation | Can test whether the edge is stronger when the purchase receives little coverage |
| Reject initially | social sentiment, usernames, general OSINT person searches | noisy personal/social signals | Weak PIT integrity, legal/privacy burden, and high overfitting risk |

## 3. Five predeclared hypotheses

Do not mine hundreds of text features. Test these five families first and count
all variants in the multiple-testing correction.

### H1 — Relative commitment

The purchase is stronger when its value is large relative to information known
at disclosure:

- purchase value / 20-day median traded value;
- purchase shares / shares outstanding;
- change in the named buyer's disclosed holding, where available;
- aggregate purchase value / market capitalization.

Use ranks within calendar year and size bucket. Absolute ₹ value remains in the
baseline; relative commitment is the new feature.

### H2 — Independent buyer clustering

Flag two or more **distinct major insiders** making Market Purchases within the
prior 30 calendar days. Aggregate repeated filings by the same person before
counting. Compare clustered purchases with singleton purchases while matching
on stock, size, year, and total rupee value.

### H3 — Ownership structure

Test only the literature-motivated cuts:

- low versus high FII ownership;
- non-government versus government-controlled;
- non-conglomerate versus conglomerate/promoter-group company;
- promoter ownership increasing versus flat/decreasing.

Quarterly shareholding is PIT grade C, so use only the latest report that was
publicly available before the disclosure, never the period-end value as if it
were already known.

### H4 — Clean versus contaminated event

Parse official announcements in a window from five trading days before through
the disclosure timestamp. Predeclare categories:

- results/guidance;
- contract/order win;
- buyback/capital action;
- merger/demerger/restructuring;
- fundraise/dilution;
- pledge creation/release;
- resignation/auditor/regulatory warning.

Primary comparison: **quiet insider purchase** versus purchase accompanied by an
already-public positive catalyst. This tests whether the insider information is
incremental rather than merely echoing news.

### H5 — Tradability and accumulation

Use official bhavcopy/delivery files to test whether successful signals have:

- adequate rupee liquidity for an ₹5,000–₹8,000 account;
- rising delivery percentage during the breakout;
- purchase size meaningful relative to normal delivered value;
- no extreme spread/gap proxy that consumes the expected edge.

Liquidity is a feasibility gate, not an alpha feature. Delivery confirmation is
one alpha hypothesis and counts as a tested variant.

## 4. Event record to build

One immutable row per armed watch, with every field point-in-time:

```text
event_id
symbol, ISIN, company_id
buyer_id, buyer_name_raw, buyer_category
trade_date, disclosure_timestamp, source_observed_at
market_purchase_value, shares_bought
reference_close
market_cap_asof, median_value_20d_asof, delivered_value_20d_asof
purchase_to_market_cap, purchase_to_traded_value, purchase_to_delivered_value
distinct_major_buyers_30d, aggregate_major_buy_value_30d
promoter_pct_asof, fii_pct_asof, government_flag, conglomerate_flag
announcement_flags_asof, pledge_flags_asof
source_ids, raw_file_hashes, PIT_grade
```

Identity joins must be deterministic first: ISIN/exchange ID for companies and
normalized name plus company for people. Fuzzy/LLM matches remain unresolved
unless manually confirmed, and every manual resolution gets a receipt.

## 5. Research design

### Comparisons

Run four versions with identical price entry and exit rules:

1. **Pure momentum:** the same 252-session breakout/EMA rule without an insider
   requirement.
2. **Baseline insider momentum:** current `faithful_momentum.py`.
3. **OSINT score:** baseline watches ranked by the predeclared features.
4. **Matched random catalysts:** same catalyst count per stock with random dates.

This identifies separately whether momentum works, whether insiders improve it,
and whether OSINT improves the insider selection.

### Scoring rule

On development data only, convert each hypothesis family to one binary vote. Do
not tune continuous weights. Initial score:

```text
+1 relative commitment in top third of its size/year bucket
+1 at least two distinct major buyers in 30 days
+1 ownership structure passes the predeclared low-FII/non-government test
+1 no adverse announcement, dilution, or new pledge flag
+1 delivery accumulation passes its train-set threshold
```

Evaluate score thresholds `>=1`, `>=2`, `>=3`, and `>=4`. These four thresholds
are four trials and must be included in FDR/DSR. The production default, if the
cluster is stable, should be the centre of the surviving threshold region—not
the best cell.

### Splits and leakage control

The 2023–2026 period has already been viewed repeatedly and is no longer a
pristine holdout for strategy development. Therefore:

- use anchored walk-forward evaluation for historical estimates;
- add leave-one-sector-out and leave-one-company-out checks so a few known
  winners cannot determine the result;
- freeze the OSINT features and score before beginning a prospective paper
  period;
- require 6–12 months of prospective alerts before funding.

Parameters and text categories are learned on prior data only. Announcement
documents, quarterly ownership, and fundamentals use the actual publication
timestamp, not the accounting period end.

### Primary endpoint

The primary endpoint is the OSINT-selected minus baseline difference in **mean
net trade return**, because this momentum strategy is intentionally positively
skewed. Also report:

- median and win rate;
- fraction of trades above +25% and below −10%;
- mean-return bootstrap CI clustered by stock and overlapping calendar period;
- equal-weight-sleeve and one-position portfolio Sharpe/CAGR/max drawdown;
- breakeven cost in bp and measured spread;
- number of independent stocks, trades, and non-overlapping holding periods.

Apply Benjamini–Hochberg FDR across all feature cuts and score thresholds. Report
raw hits versus expected by chance and DSR against the honest total trial count.

## 6. Matched controls

Every OSINT claim must beat all three controls:

1. random catalyst dates matched by stock and calendar regime;
2. non-qualifying insider purchases matched on stock, rupee value, and year;
3. pure momentum breakouts matched on stock, breakout strength, volatility, and
   market regime.

For clustering, shuffle buyer identities within stock/year while preserving the
number and value of filings. For announcement context, use placebo announcement
windows matched by company and reporting season.

## 7. Build order

### Phase 0 — freeze and manifest

- Freeze `faithful_momentum.py` and its current outputs as baseline v1.
- Write a machine-readable strategy manifest with constants, data hashes, and
  the already-observed test periods.
- Record the current result as exploratory, not prospective.

### Phase 1 — price and universe integrity

- Ingest official NSE security bhavcopy and delivery reports.
- Add corporate actions, symbol/ISIN history, delisted names, and point-in-time
  universe membership.
- Cross-check a sample against Yahoo and BSE.
- Measure executable spread from broker quotes/fills or state that funding is
  blocked.

**Gate:** if corrected prices materially remove the current edge, stop before
building text/OSINT features.

### Phase 2 — event integrity

- Verify NSE dissemination timestamp semantics using raw filings.
- Add BSE PIT/SAST and deduplicate cross-listed disclosures.
- Normalize buyer identity and aggregate same-person/same-episode filings.
- Build the relative-commitment and cluster features.

**Gate:** reproduce baseline v1 within documented differences and produce an
audit table for every excluded/merged event.

### Phase 3 — ownership and announcement context

- Ingest point-in-time shareholding reports.
- Resolve government/conglomerate/promoter-group entities via MCA and official
  filings.
- Ingest NSE/BSE announcements and classify only the predeclared categories.
- Manually audit a stratified sample of at least 100 classifications before use.

**Gate:** precision and recall on the manually labelled sample must be reported;
unknown documents remain unknown rather than being forced into a class.

### Phase 4 — controlled study

- Run H1–H5 and the four score thresholds on development/walk-forward folds.
- Apply FDR, clustered uncertainty, start-date sensitivity, and leave-one-stock
  and leave-one-sector-out tests.
- Open the final feature-blind fold only after the score is frozen.

**Gate:** OSINT must improve the baseline mean net return and random-control
percentile without relying on one stock or one giant winner.

### Phase 5 — prospective watchlist

- Generate a daily report after the NSE/BSE dissemination window.
- Show why each watch is armed, its OSINT score, source links, and missing data.
- Wait for the unchanged price confirmation; do not convert OSINT into immediate
  buying.
- Paper-track signals, next-open prices, spread, and exits for 6–12 months.

## 8. Acceptance and kill criteria

Call OSINT useful only if all are true:

- the OSINT-selected group beats baseline insider momentum on the primary
  endpoint out of sample;
- it beats matched random and matched pure momentum at empirical `p < 0.05`;
- the result survives FDR across the declared trials;
- leave-one-stock-out remains positive and no single winner supplies more than
  one third of total profits;
- the lower uncertainty bound is positive after measured all-in costs;
- at least 30 OOS trades across at least 10 stocks exist, followed by a positive
  prospective paper period.

Kill or simplify the OSINT overlay if:

- it merely selects generic momentum winners no better than pure momentum;
- classification timestamps cannot be made point-in-time;
- corrected/delisted-inclusive data remove the edge;
- the gain disappears after spread or is supplied by one stock;
- raw feature hits are no more numerous than expected by chance.

## 9. Tools from the OSINT harvest

Potentially useful references discovered in `OSINT/harvest/CODEBASES_CURATED.tsv`:

- `anandbaid/promoter-watch` — relevant daily NSE promoter/PIT/SAST screen, but
  no recorded license; inspect behavior, do not copy code.
- `abhijitchavhan14/corporate-announcement-intelligence` — NSE/BSE announcement
  PDF collection/classification pattern, no recorded license.
- `KushBhakkad/Spring-Boot-NSE-News-Application` — NSE announcement endpoint
  example, MIT.
- `Am1n1602/jugaad-rs` — MIT NSE market/bhavcopy/filing tooling candidate.
- `chartiny/nse-sec-bhavdata-full` and `chartiny/nse-cm-bhavcopy` — MIT daily
  security/delivery and cash-market report archives; verify completeness and
  provenance before relying on mirrors.
- `shAsh-cy/InsiderFlow` — NSE/BSE tracker with anomaly detection, AGPL-3.0;
  architecture reference only unless the license choice is deliberate.

Official exchange records remain the data authority. GitHub projects are
collectors or implementation references, not evidence by themselves.

