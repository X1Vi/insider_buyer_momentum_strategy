"""
The calibration gap, priced as a trade.

Calibration says longshots are overpriced by 0.3-3.3 cents. That is a direction, not
a business. This turns it into a book: sell every market priced below a threshold at
a chosen horizon, hold to resolution, post full collateral, and count the money.

Three things this does that the bucket table cannot:

  * charges the SPREAD. The gap is a few cents and so is the spread; a calibration
    edge that does not survive crossing it is not an edge.
  * clusters on the EVENT. Twenty props on one match resolve together, so naive
    per-market standard errors overstate significance by ~sqrt(markets/events).
  * reports the RULE-OF-THREE bound. Several buckets have zero YES resolutions, which
    collapses the standard error and manufactures t-stats like -22. With 0 successes
    in n trials the 95% upper bound on the probability is ~3/n, and that bound - not
    the point estimate of zero - is what a short-tail seller is exposed to.
"""
import json, os, warnings
warnings.filterwarnings('ignore')
import numpy as np, pandas as pd

D = os.path.dirname(os.path.abspath(__file__))
rows = [json.loads(l) for l in open(f'{D}/pm_markets.jsonl')]


def price_at(hist, close_ts, hours):
    cut = close_ts - hours * 3600
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
    ct = h[-1][0]
    for H in (24, 168):
        p = price_at(h, ct, H)
        if p is None or not (0 < p < 1):
            continue
        recs.append(dict(id=r['id'], ev=r.get('slug') or r['id'], y=r['y'], p=p,
                         H=H, vol=r.get('vol', 0.0), q=r.get('q', '')[:70]))
df = pd.DataFrame(recs)
print(f"observations {len(df)}, markets {df.id.nunique()}, events {df.ev.nunique()}")
span = (max(h[-1][0] for h in [r['hist'] for r in rows])
        - min(h[0][0] for h in [r['hist'] for r in rows])) / 86400
print(f"sample spans ~{span:.0f} days -> {df[df.H==24].id.nunique()/max(span,1):.1f} "
      f"markets resolving per day\n")

# rule of three: 95% upper bound on p given k successes in n trials
def ub95(k, n):
    if n == 0:
        return np.nan
    if k == 0:
        return 3.0 / n
    from scipy.stats import beta
    return float(beta.ppf(0.975, k + 1, n - k))


print("SELL EVERYTHING BELOW A PRICE THRESHOLD, HOLD TO RESOLUTION")
print("Post $1 collateral per contract; receive the price; pay $1 if it resolves YES.\n")
print(f"{'horizon':>8}{'sell below':>12}{'n':>6}{'events':>8}{'hit rate':>10}"
       f"{'gross/contract':>16}{'net of 1c spread':>18}{'ann. on collateral':>20}")
out = []
for H in (24, 168):
    d0 = df[df.H == H]
    for thr in (0.02, 0.05, 0.10, 0.20):
        d = d0[d0.p <= thr]
        if len(d) < 30:
            continue
        # sell at price p (assume we hit the bid = p - half_spread)
        for spread in (0.0, 0.01):
            eff = (d.p - spread / 2).clip(lower=0.001)
            pnl = eff - d.y              # receive eff, pay 1 if YES
            gross = pnl.mean()
            # cluster on event
            ev = pnl.groupby(d.ev).mean()
            se = ev.std(ddof=1) / np.sqrt(len(ev)) if len(ev) > 2 else np.nan
            coll = (1 - eff).mean()
            days = H / 24
            ann = gross / coll * 365 / max(days, 1) * 100 if coll > 0 else np.nan
            if spread == 0.0:
                g0, t0 = gross, (gross / se if se and se > 0 else np.nan)
            else:
                out.append(dict(H=H, thr=thr, n=len(d), ev=len(ev),
                                hit=d.y.mean(), gross=g0, net=gross, t=t0, ann=ann,
                                k=int(d.y.sum())))
                print(f"{H:>7}h{thr:>12.2f}{len(d):>6}{len(ev):>8}{d.y.mean():>10.3f}"
                      f"{g0*100:>15.2f}c{gross*100:>17.2f}c{ann:>19.1f}%")
res = pd.DataFrame(out)

print("\nSIGNIFICANCE, clustered on event (gross, before spread)")
print(f"{'horizon':>8}{'thr':>7}{'YES count':>11}{'t-stat':>9}"
      f"{'  95% upper bound on hit rate':>32}")
for _, x in res.iterrows():
    u = ub95(x.k, x.n)
    print(f"{x.H:>7.0f}h{x.thr:>7.2f}{x.k:>11.0f}{x.t:>9.2f}{u:>27.4f}"
          f"   (priced ~{x.thr/2:.3f})")

print("\nWORST CASE THE SAMPLE CANNOT SEE")
print("With k YES resolutions observed, the 95% upper bound is what a seller must")
print("survive. Re-pricing the book at that bound instead of the point estimate:")
for _, x in res.iterrows():
    d = df[(df.H == x.H) & (df.p <= x.thr)]
    eff = (d.p - 0.005).clip(lower=0.001)
    worst = eff.mean() - ub95(x.k, x.n)
    coll = (1 - eff).mean()
    ann = worst / coll * 365 / (x.H / 24) * 100
    print(f"  {x.H:>3.0f}h  sell<={x.thr:.2f}:  point {x.net*100:+.2f}c/contract "
          f"-> at the 95% bound {worst*100:+.2f}c  ({ann:+.0f}%/yr)")

print("\nCONCENTRATION: how much of the P&L is one event?")
for H in (24,):
    for thr in (0.05, 0.20):
        d = df[(df.H == H) & (df.p <= thr)]
        if len(d) < 30:
            continue
        pnl = (d.p - 0.005).clip(lower=0.001) - d.y
        byev = pnl.groupby(d.ev).sum().sort_values()
        tot = byev.sum()
        print(f"  {H}h sell<={thr}: total {tot*100:+.1f}c over {len(byev)} events; "
              f"worst event {byev.iloc[0]*100:+.1f}c "
              f"({abs(byev.iloc[0]/tot)*100 if tot else float('nan'):.0f}% of total)")
