# Momentum-onset ML filter

Research-only panel model that scores NSE symbols for a **+8% move over the next
20 sessions**, measured from the next session's open to the close 20 sessions later.

## What is published

- `build_scores.py` — trains the model and writes the score file.
- `model.pkl` — latest fitted pipeline plus feature list and target.
- `scores.csv` — latest score per symbol, sorted high to low.
- `data/nifty.csv` — NIFTY 50 benchmark used for market-state features.
- `../../web/public/momentum_ml_scores.json` — static file consumed by the React app.

`OSINT/moneyflow/frontend/public/momentum_ml_scores.json` is a copy of the same
file. The insider app is the source of truth; moneyflow only renders the scores.

## Method

- Universe: symbols with at least 300 daily bars in `data/app_cache/` (150 symbols
  in the current run; 163 symbols exist in the cache).
- Labels: `close[t+20] / open[t+1] - 1 >= 0.08`.
- Features: price returns, moving-average distance/slope, drawdowns, distance from
  20/60/250-day highs, ATR, RSI(2/14), up-day fraction, gaps, intraday return,
  volume ratios, and NIFTY market-state features. No insider features: the
  MANINFRA test showed they reduced OOS AUC.
- Model: `HistGradientBoostingClassifier` in a median-imputation pipeline.
- Split: train on dates `< 2025-01-01`, test on dates `>= 2025-01-01`. This is a
  single time split, not a full walk-forward. The original MANINFRA model used
  annual walk-forward; this panel deployment version uses the simpler split so it
  can be regenerated quickly.
- The 20-session labels overlap. The row count (62,835 test rows) is therefore not
  an effective independent sample size.

## Current OOS numbers

| Metric | Value |
|---|---:|
| OOS rows | 62,835 |
| Base rate | 19.97% |
| Pooled AUC | 0.565 |
| Mean daily cross-sectional AUC | 0.540 (425 days) |
| OOS top-decile hit rate | 25.66% (1.28× base) |

The score is weak. It is a ranking/filter input, not a standalone strategy. It has
no stop, holding-period, cost, overlap, or position-sizing model. Gross labels are
before the 27 bp delivery / 75 bp small-account cost assumptions used elsewhere.

## Regenerate

From this directory:

```bash
/home/null/Documents/development/trading_and_investing/volume_indicator_studies/.venv/bin/python momentum_ml/build_scores.py
cp ../web/public/momentum_ml_scores.json \
   /home/null/Documents/development/trading_and_investing/OSINT/moneyflow/frontend/public/momentum_ml_scores.json
```

The script prints the OOS AUC, daily cross-sectional AUC, top-decile hit rate, and
the top 20 latest scores.

## UI filters

Both apps expose a static score threshold:

- `any`
- `>= 40%` (10 symbols in the 2026-10-19 run)
- `>= 50%` (3 symbols)

The insider app also exposes:

- minimum distinct insider buyers in the trailing 30 days (2/3/5)
- minimum insider purchase value divided by 20-day median traded value (0.5×/1×/2×)

`scores.json` is not point-in-time for the *latest* row; it uses the most recent
bar available per symbol. That is deliberate for a live filter, but it means the
file must not be used to reconstruct historical backtests.
