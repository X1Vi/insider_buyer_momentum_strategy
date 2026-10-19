#!/usr/bin/env python3
"""Build walk-forward ML buy/sell points for chart reference.

The score file (`build_scores.py`) is a live cross-section. This script produces
only historical signal points, using an expanding annual walk-forward so the
markers do not use the year they are scoring:

  train: dates < year_start - 35 calendar days (20-session label embargo)
  test:  dates in [year_start, next year_start)

Output: ../web/public/momentum_ml_history.json
"""
from __future__ import annotations
import glob, json, re
from datetime import datetime, timezone
from pathlib import Path
import numpy as np, pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from build_scores import CACHE, NIFTY, H, TARGET, SEED, features, longest_price

APP = Path(__file__).resolve().parents[1]
OUT = APP / 'web/public/momentum_ml_history.json'
START_YEAR = 2019
END_YEAR = 2026
DIR_THRESHOLD = 0.40
COOLDOWN = 10
EMBARGO_DAYS = 35

def make_model():
    return Pipeline([
        ('imp', SimpleImputer(strategy='median')),
        ('m', HistGradientBoostingClassifier(
            max_iter=350, learning_rate=.05, max_leaf_nodes=31,
            min_samples_leaf=100, l2_regularization=1.0, random_state=SEED)),
    ])

def build_panel():
    syms = sorted({re.sub(r'^price_|_\d+y\.json$', '', Path(f).name)
                   for f in glob.glob(str(CACHE / 'price_*.json'))})
    nif = pd.read_csv(NIFTY, parse_dates=['date']).set_index('date').sort_index()
    nif = nif[~nif.index.duplicated()]
    nc = nif.close; nr = nc.pct_change()
    frames = []
    for sym in syms:
        bars = longest_price(sym)
        if not bars:
            continue
        df = pd.DataFrame(bars)
        df['date'] = pd.to_datetime(df['date'], errors='coerce')
        df = df.dropna(subset=['date']).set_index('date').sort_index()
        for col in ['open', 'high', 'low', 'close', 'volume']:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        df = df.dropna(subset=['open', 'high', 'low', 'close'])
        df = df[df.close > 0]
        if len(df) < 300:
            continue
        F = features(df)
        ncr = nc.reindex(F.index, method='ffill')
        F['mkt_r1'] = nr.reindex(F.index, method='ffill')
        F['mkt_r5'] = ncr / ncr.shift(5) - 1
        F['mkt_r20'] = ncr / ncr.shift(20) - 1
        F['mkt_r60'] = ncr / ncr.shift(60) - 1
        F['mkt_above200'] = (ncr > ncr.rolling(200).mean()).astype(float)
        F['mkt_dist200'] = ncr / ncr.rolling(200).mean() - 1
        o = df.open; c = df.close
        fwd = np.full(len(df), np.nan)
        for i in range(len(df) - H - 1):
            fwd[i] = c.iloc[i + H] / o.iloc[i + 1] - 1
        F['fwd20'] = fwd
        F['y'] = (fwd >= TARGET).astype(float)
        F['y_down'] = (fwd <= -TARGET).astype(float)
        F.loc[~np.isfinite(fwd), ['y', 'y_down']] = np.nan
        F['symbol'] = sym
        F['date'] = F.index
        frames.append(F.reset_index(drop=True))
    P = pd.concat(frames, ignore_index=True)
    for col in ['r20', 'r60', 'vol20', 'dist_hi250']:
        P[f'xs_{col}'] = P.groupby('date')[col].rank(pct=True)
    feature_cols = [c for c in P.columns if c not in (
        'symbol', 'date', 'close', 'fwd20', 'y', 'y_down')]
    return P, feature_cols

def main():
    P, feature_cols = build_panel()
    print('panel rows', len(P), 'symbols', P.symbol.nunique())
    pred_frames = []
    for year in range(START_YEAR, END_YEAR + 1):
        start = pd.Timestamp(f'{year}-01-01')
        end = pd.Timestamp(f'{year + 1}-01-01')
        train = P[P.date < start - pd.Timedelta(days=EMBARGO_DAYS)].dropna(subset=['y', 'y_down'])
        test = P[(P.date >= start) & (P.date < end)].dropna(subset=['y', 'y_down']).copy()
        if len(train) < 5000 or len(test) == 0:
            print('skip', year, 'train', len(train), 'test', len(test))
            continue
        for label, target in [('up', 'y'), ('down', 'y_down')]:
            model = make_model().fit(train[feature_cols], train[target])
            test[f'p_{label}'] = model.predict_proba(test[feature_cols])[:, 1]
        keep = test[['symbol', 'date', 'close', 'p_up', 'p_down', 'fwd20']].copy()
        pred_frames.append(keep)
        print('scored', year, 'rows', len(keep))
    pred = pd.concat(pred_frames, ignore_index=True).sort_values(['symbol', 'date'])
    pred['direction'] = np.select(
        [(pred.p_up >= DIR_THRESHOLD) & (pred.p_up >= pred.p_down),
         (pred.p_down >= DIR_THRESHOLD) & (pred.p_down > pred.p_up)],
        ['long', 'short'], default='neutral')
    pred['strength'] = pred[['p_up', 'p_down']].max(axis=1)

    points = {}
    counts = {'long': 0, 'short': 0}
    for sym, g in pred.groupby('symbol'):
        g = g.sort_values('date').reset_index(drop=True)
        last = -10**9
        active_direction = None
        events = []
        for i, row in g.iterrows():
            if row.direction == 'neutral' or row.direction == active_direction:
                continue
            if i - last < COOLDOWN:
                continue
            events.append({
                'date': str(pd.Timestamp(row.date).date()),
                'direction': row.direction,
                'price': round(float(row.close), 3),
                'p_up': round(float(row.p_up), 4),
                'p_down': round(float(row.p_down), 4),
                'strength': round(float(row.strength), 4),
                'fwd20': round(float(row.fwd20), 4) if pd.notna(row.fwd20) else None,
            })
            counts[row.direction] += 1
            last = i
            active_direction = row.direction
        if events:
            points[sym] = events
    all_events = [e for events in points.values() for e in events]
    long_events = [e for e in all_events if e['direction'] == 'long' and e['fwd20'] is not None]
    short_events = [e for e in all_events if e['direction'] == 'short' and e['fwd20'] is not None]
    outcome = {
        'long_n': len(long_events),
        'long_hit_rate': round(sum(e['fwd20'] >= TARGET for e in long_events) / len(long_events), 4) if long_events else None,
        'long_mean_fwd20': round(float(np.mean([e['fwd20'] for e in long_events])), 4) if long_events else None,
        'short_n': len(short_events),
        'short_hit_rate': round(sum(e['fwd20'] <= -TARGET for e in short_events) / len(short_events), 4) if short_events else None,
        'short_mean_fwd20': round(float(np.mean([e['fwd20'] for e in short_events])), 4) if short_events else None,
    }
    payload = {
        'generated_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'method': 'expanding annual walk-forward; no year is scored by a model trained on that year',
        'embargo_days': EMBARGO_DAYS,
        'start_year': START_YEAR,
        'end_year': END_YEAR,
        'targets': {'long': '20-session forward return >= +8%', 'short': '<= -8%'},
        'direction_threshold': DIR_THRESHOLD,
        'cooldown_sessions': COOLDOWN,
        'point_count': len(points),
        'event_counts': counts,
        'event_outcome': outcome,
        'note': 'price is the close on the signal date; entry would be the next open. Research reference only.',
        'by_symbol': points,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2, sort_keys=True))
    print('wrote', OUT)
    print('symbols with points', len(points), 'events', counts)
    for sym in list(points)[:3]:
        print(sym, points[sym][:3])

if __name__ == '__main__':
    main()
