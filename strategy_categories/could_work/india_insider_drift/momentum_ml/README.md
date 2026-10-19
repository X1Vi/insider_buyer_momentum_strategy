# Momentum-onset ML filter (long + short)

Research-only panel model that scores NSE symbols in **both directions** over the
next 20 sessions, measured from the next session's open:

- **Long:** forward return `>= +8%`
- **Short:** forward return `<= -8%`
- **Neutral:** neither probability clears the 40% direction threshold

A low long probability is **not** a short signal. The app uses two separate
classifiers, so a stock only gets `S` when the down model actually fires.

## What is published

- `build_scores.py` — trains both models and writes the live score file.
- `build_history.py` — builds walk-forward historical buy/sell points for charts.
- `model.pkl` — both fitted pipelines, feature list, targets, direction threshold.
- `scores.csv` — latest score per symbol, sorted by directional strength.
- `data/nifty.csv` — NIFTY 50 benchmark used for market-state features.
- `../web/public/momentum_ml_scores.json` — live score file.
- `../web/public/momentum_ml_history.json` — chart point file (walk-forward only).

`OSINT/moneyflow/frontend/public/momentum_ml_scores.json` is a copy of the same
file. The insider app is the source of truth; moneyflow only renders the scores.

## Method

- Universe: symbols with at least 300 daily bars in `data/app_cache/` (150 symbols
  in the current run; 163 symbols exist in the cache).
- Labels: `close[t+20] / open[t+1] - 1` with separate `y` (>= +8%) and `y_down`
  (<= -8%) targets.
- Features: price returns, moving-average distance/slope, drawdowns, distance from
  20/60/250-day highs, ATR, RSI(2/14), up-day fraction, gaps, intraday return,
  volume ratios, and NIFTY market-state features. No insider features: the
  MANINFRA test showed they reduced OOS AUC.
- Models: two `HistGradientBoostingClassifier` pipelines with median imputation.
- Split: train on dates `< 2025-01-01`, test on dates `>= 2025-01-01`. This is a
  single time split, not a full walk-forward. The original MANINFRA model used
  annual walk-forward; this panel deployment version uses the simpler split so it
  can be regenerated quickly.
- The 20-session labels overlap. The 62,835 test rows are therefore not an
  effective independent sample size.
- Direction: `long` if `p_up >= 0.40` and `p_up >= p_down`; `short` if
  `p_down >= 0.40` and `p_down > p_up`; otherwise `neutral`.

## Historical chart points

`build_history.py` uses an expanding annual walk-forward. For each year, the
model is trained only on data before that year, with a 35-calendar-day embargo
for the 20-session label. The 2019-2026 test years are therefore out-of-sample.

A point is emitted only on a **direction transition** (long -> short or short ->
long), with a 10-session cooldown. The point is the signal close; entry would be
the next open. `momentum_ml_history.json` also carries each point's realized
20-session return for reference.

Current historical point set: **744 long, 847 short**. Outcomes at the 8% target:

| Point type | Hit rate | Mean 20-session return |
|---|---:|---:|
| Long | 28.9% | +2.22% |
| Short | 29.8% | -0.17% |

The short points are especially weak on return: hit rate is above the 23.9% base
rate, but the mean is essentially flat before costs. Do not treat the markers as
trades.

## Current OOS numbers

| Metric | Long (+8%) | Short (-8%) |
|---|---:|---:|
| OOS rows | 62,835 | 62,835 |
| Base rate | 19.97% | 23.93% |
| Pooled AUC | 0.553 | 0.542 |
| Mean daily cross-sectional AUC | 0.537 (425 days) | 0.581 (424 days) |
| OOS top-decile hit rate | 24.19% (1.21x base) | 27.39% (1.14x base) |

Latest direction counts at the 40% threshold: **14 long, 3 short, 133 neutral**.
Top current long: `ESFL` 64.6%; top current short: `VPRPL` 46.4%. Scores cover
different latest bar dates per symbol, so always show the as-of date.

The scores are weak. They are ranking/filter inputs, not standalone strategies.
They have no stop, holding-period, cost, overlap, or position-sizing model. Gross
labels are before the 27 bp delivery / 75 bp small-account cost assumptions used
elsewhere. Short signals are **informational only for cash equities**: overnight
shorting requires futures or an index-ETF hedge, which is a scope change.

## Regenerate

From this directory:

```bash
/home/null/Documents/development/trading_and_investing/volume_indicator_studies/.venv/bin/python build_scores.py
/home/null/Documents/development/trading_and_investing/volume_indicator_studies/.venv/bin/python build_history.py
cp ../web/public/momentum_ml_scores.json \
   /home/null/Documents/development/trading_and_investing/OSINT/moneyflow/frontend/public/momentum_ml_scores.json
cp ../web/public/momentum_ml_history.json \
   /home/null/Documents/development/trading_and_investing/OSINT/moneyflow/frontend/public/momentum_ml_history.json
```

The script prints both OOS AUCs, daily cross-sectional AUCs, top-decile hit rates,
direction counts, and the top latest names.

## UI filters

Both apps expose:

- ML signal: `long + short`, `long only`, `short only`, `neutral`
- ML strength: `any`, `>= 40%`, `>= 50%`

Charts show gold diamonds for historical ML buy points and purple diamonds for
historical ML sell points. These are walk-forward signals, not insider
disclosures; the tooltip shows the realized next-20-session move.

The insider app also exposes:

- minimum distinct insider buyers in the trailing 30 days (2/3/5)
- minimum insider purchase value divided by 20-day median traded value (0.5x/1x/2x)

`scores.json` is not point-in-time for the *latest* row; it uses the most recent
bar available per symbol. That is deliberate for a live filter, but it means the
file must not be used to reconstruct historical backtests.
