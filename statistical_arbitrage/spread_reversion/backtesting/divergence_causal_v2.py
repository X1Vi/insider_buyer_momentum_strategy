#!/usr/bin/env python3
"""
DIVERGENCE v4 — fully CAUSAL (rolling hedge ratio + confirmation entry), universe-wide.

Fixes:
  1. ROLLING beta/alpha (252d) — hedge ratio at day t uses ONLY data <= t.
  2. Confirmed-swing-low entry (L=3) — BUY at the confirmation bar, no look-ahead.
  3. Runs across ALL pairs (not just pre-selected winners).
  4. A/B/C classification of every z<-3 arm:
       A = lower-low + higher-z divergence   B = z recovers, no lower-low
       C = keeps deteriorating
     then compares forward 60d returns of pa (the leg we'd buy).
"""
import glob
import numpy as np
import pandas as pd

W_BETA, W_Z, Z_ARM, L = 252, 60, -3.0, 3

files = sorted(glob.glob("backtesting/data/*.csv"))
names = [f.split("/")[-1][:-4] for f in files]
data = {nm: pd.read_csv(f)["close"].values for nm, f in zip(names, files)}
print(f"universe: {len(names)} names -> {len(names)*(len(names)-1)//2} pairs")


def rolling_beta_z(pa, pb):
    n = len(pa)
    sla, slb = pd.Series(np.log(pa)), pd.Series(np.log(pb))
    beta = sla.rolling(W_BETA).cov(slb) / slb.rolling(W_BETA).var()
    alpha = sla.rolling(W_BETA).mean() - beta * slb.rolling(W_BETA).mean()
    spread = sla - beta * slb - alpha
    mu = spread.rolling(W_Z).mean()
    sd = spread.rolling(W_Z).std()
    z = ((spread - mu) / sd).values
    z[np.isnan(z)] = 0.0
    return z


def is_confirmed_low(j, pa, L):
    lft = pa[max(0, j - L):j]
    rgt = pa[j + 1:j + L + 1]
    return len(lft) and len(rgt) and pa[j] <= lft.min() and pa[j] <= rgt.min()


def run_signal(pa, pb, z):
    """Returns list of (conf_i, conf_px, low_i, low_px, low_z, prev_z)."""
    n = len(pa)
    buys = []
    state = "ARMED"
    last_low = None
    arm_i = None
    for i in range(n):
        if state == "ARMED":
            if z[i] < Z_ARM:
                state, arm_i = "HUNT", i
        elif state == "HUNT":
            if z[i] > -1.0 or i - arm_i > 150:
                state = "ARMED"
                last_low = None
        j = i - L
        if j >= L and is_confirmed_low(j, pa, L):
            pj, zj = pa[j], z[j]
            if state == "HUNT":
                if last_low is None:
                    last_low = (pj, zj, j)
                elif pj < last_low[0]:
                    if zj > last_low[1]:
                        buys.append((i, pa[i], j, pj, zj, last_low[1]))
                        state = "ARMED"
                        last_low = None
                    else:
                        last_low = (pj, zj, j)
    return buys


def classify_arms(pa, pb, z):
    """A/B/C for each z<-3 arm; forward 60d return of pa from the arm."""
    n = len(pa)
    out = []
    i = 0
    while i < n:
        if z[i] < Z_ARM:
            arm_i = i
            last_low = None
            cls = None
            for t in range(i, min(n, i + 60)):
                j = t - L
                if j >= 0 and is_confirmed_low(j, pa, L):
                    pj, zj = pa[j], z[j]
                    if last_low is None:
                        last_low = (pj, zj)
                    elif pj < last_low[0]:
                        if zj > last_low[1]:
                            cls = "A"
                            break
                        else:
                            last_low = (pj, zj)
                if z[t] > -1.0 and last_low is not None:
                    cls = "B"
                    break
            if cls is None:
                cls = "C"
            fwd = 100 * (pa[min(n - 1, arm_i + 60)] / pa[arm_i] - 1) if arm_i + 60 < n else np.nan
            out.append((cls, fwd, z[i]))
            i = arm_i + 5
        else:
            i += 1
    return out


# ---- run across all pairs ----
all_buys = []      # (pair, conf_i, conf_px, low_i, low_px, low_z, prev_z)
abc = {"A": [], "B": [], "C": []}

for a in range(len(names)):
    for b in range(a + 1, len(names)):
        A, B = names[a], names[b]
        pa, pb = data[A], data[B]
        n = min(len(pa), len(pb))
        if n < W_BETA + W_Z + 50:
            continue
        pa, pb = pa[:n], pb[:n]
        z = rolling_beta_z(pa, pb)
        for sig in run_signal(pa, pb, z):
            all_buys.append((A, B, *sig))
        for cls, fwd, _ in classify_arms(pa, pb, z):
            abc[cls].append(fwd)

print("\n=== DIVERGENCE SIGNALS (fully causal, universe-wide) ===")
print(f"total BUY signals: {len(all_buys)}\n")
# forward returns per signal
signals = []
for A, B, ci, cp, li, lp, lz, pz in all_buys:
    pair = f"{A}/{B}"
    pa = data[A][:min(len(data[A]), len(data[B]))]
    f = {}
    for h in (5, 20, 60):
        if ci + h < len(pa):
            f[h] = 100 * (pa[ci + h] / pa[ci] - 1)
    signals.append((pair, ci, cp, f))

print(f"{'PAIR':<20} {'day':>5} {'buy₹':>7} {'5d':>7} {'20d':>7} {'60d':>8}")
for pair, ci, cp, f in signals:
    print(f"{pair:<20} {ci:>5} {cp:>7.0f} "
          f"{f.get(5, float('nan')):>+6.1f}% {f.get(20, float('nan')):>+6.1f}% {f.get(60, float('nan')):>+7.1f}%")

print("\n=== POOLED DIVERGENCE SIGNAL FORWARD RETURNS ===")
for h in (5, 20, 60):
    v = [s[3].get(h) for s in signals if h in s[3]]
    if v:
        print(f"  {h}d: avg={np.mean(v):+.1f}%  med={np.median(v):+.1f}%  win={100*np.mean([x>0 for x in v]):.0f}%  "
              f"best={max(v):+.1f}%  worst={min(v):+.1f}%  (n={len(v)})")

print("\n=== A/B/C CLASSIFICATION — forward 60d return of the target leg (pa) ===")
for cls in ("A", "B", "C"):
    v = [x for x in abc[cls] if x == x]
    if v:
        print(f"  {cls}: n={len(v)}  avg60d={np.mean(v):+.1f}%  med={np.median(v):+.1f}%  "
              f"win={100*np.mean([x>0 for x in v]):.0f}%  best={max(v):+.1f}%  worst={min(v):+.1f}%")
