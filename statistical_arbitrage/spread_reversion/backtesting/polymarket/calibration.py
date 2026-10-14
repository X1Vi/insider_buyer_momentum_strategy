"""
Is Polymarket calibrated? When it says 0.90, does it happen 90% of the time?

This is the one Polymarket route the published arbitrage result does not close,
because it works on a timescale of days rather than the 3.6-second windows in which
complete-set mispricings live.

Design choices that decide whether the answer means anything:

  * HORIZON. A price 1 hour before resolution is nearly the answer; a price 7 days
    out is a forecast. Calibration is reported at several horizons before close.
  * CLUSTERING. Twenty markets on one football match are not twenty observations.
    Standard errors are clustered on the EVENT, not the market.
  * BOTH SIDES. A YES at 0.03 and its NO at 0.97 are the same claim. Including both
    double-counts, so only the YES leg is used and the low-probability bucket is
    where the longshot question actually lives.
  * TRADEABILITY. Calibration gaps are only an edge if they exceed the spread.
"""
import json, os, sys, warnings
warnings.filterwarnings('ignore')
import numpy as np, pandas as pd

D = os.path.dirname(os.path.abspath(__file__))
SRC = f'{D}/pm_markets.jsonl'

rows = []
for line in open(SRC):
    try:
        rows.append(json.loads(line))
    except Exception:
        pass
print(f'markets with price history: {len(rows)}')

HORIZONS_H = [1, 6, 24, 72, 168, 720]          # hours before close


def price_at(hist, close_ts, hours_before):
    """Last traded price at or before (close - hours_before)."""
    cut = close_ts - hours_before * 3600
    prev = None
    for t, p in hist:
        if t <= cut:
            prev = p
        else:
            break
    return prev


recs = []
for r in rows:
    h = r.get('hist') or []
    if len(h) < 3:
        continue
    close_ts = h[-1][0]
    for H in HORIZONS_H:
        p = price_at(h, close_ts, H)
        if p is None or not (0.0 < p < 1.0):
            continue
        recs.append(dict(id=r['id'], event=r.get('slug') or r.get('event') or r['id'],
                         cat=r.get('cat', ''), vol=r.get('vol', 0.0),
                         y=r['y'], p=p, H=H, q=r.get('q', '')))
df = pd.DataFrame(recs)
if df.empty:
    print('no usable observations'); sys.exit()
print(f'observations: {len(df)}  unique markets: {df.id.nunique()}  '
      f'unique events: {df.event.nunique()}\n')

BINS = [0, .02, .05, .10, .20, .35, .50, .65, .80, .90, .95, .98, 1.0]


def cluster_se(g):
    """SE of (outcome - price) clustered on event."""
    d = g.groupby('event').agg(n=('y', 'size'), m=('resid', 'mean'))
    if len(d) < 2:
        return np.nan
    w = d.n / d.n.sum()
    return float(np.sqrt((w**2 * d.m.var(ddof=1)).sum() * len(d) / max(len(d) - 1, 1)))


for H in [24, 168]:
    sub = df[df.H == H].copy()
    if len(sub) < 200:
        continue
    sub['resid'] = sub.y - sub.p
    sub['bucket'] = pd.cut(sub.p, BINS)
    print(f"=== CALIBRATION {H}h BEFORE CLOSE "
          f"(n={len(sub)}, events={sub.event.nunique()}) ===")
    print(f"{'price bucket':>16}{'n':>7}{'events':>8}{'mean price':>12}"
          f"{'actual freq':>13}{'gap':>9}{'clustered SE':>14}{'  t'}")
    tot = 0
    for b, g in sub.groupby('bucket', observed=True):
        if len(g) < 20:
            continue
        gap = g.y.mean() - g.p.mean()
        se = cluster_se(g)
        t = gap / se if se and se > 0 else np.nan
        tot += len(g)
        print(f"{str(b):>16}{len(g):>7}{g.event.nunique():>8}{g.p.mean():>12.3f}"
              f"{g.y.mean():>13.3f}{gap:>+9.3f}{se if se==se else float('nan'):>14.4f}"
              f"{t:>7.2f}" if se == se else
              f"{str(b):>16}{len(g):>7}{g.event.nunique():>8}{g.p.mean():>12.3f}"
              f"{g.y.mean():>13.3f}{gap:>+9.3f}{'n/a':>14}")
    # overall Brier and the longshot test
    brier = ((sub.p - sub.y)**2).mean()
    base = ((sub.y.mean() - sub.y)**2).mean()
    print(f"  Brier {brier:.4f}   vs always-predicting-base-rate {base:.4f}   "
          f"skill {1-brier/base:+.3f}")
    lo = sub[sub.p <= 0.10]
    hi = sub[sub.p >= 0.90]
    if len(lo) > 30:
        print(f"  longshots (p<=0.10): price {lo.p.mean():.4f} vs actual "
              f"{lo.y.mean():.4f}  gap {lo.y.mean()-lo.p.mean():+.4f}")
    if len(hi) > 30:
        print(f"  favourites (p>=0.90): price {hi.p.mean():.4f} vs actual "
              f"{hi.y.mean():.4f}  gap {hi.y.mean()-hi.p.mean():+.4f}")
    print()

# by category, at 24h
sub = df[df.H == 24].copy()
if len(sub) > 500:
    sub['resid'] = sub.y - sub.p
    print("=== BY CATEGORY (24h before close) ===")
    print(f"{'category':<22}{'n':>7}{'events':>8}{'mean price':>12}"
          f"{'actual':>9}{'gap':>9}")
    for c, g in sub.groupby('cat', observed=True):
        if len(g) < 100:
            continue
        print(f"{(c or '(none)')[:20]:<22}{len(g):>7}{g.event.nunique():>8}"
              f"{g.p.mean():>12.3f}{g.y.mean():>9.3f}{g.y.mean()-g.p.mean():>+9.3f}")

sub.to_csv(f'{D}/calibration_24h.csv', index=False)
print(f"\nwrote {D}/calibration_24h.csv")
