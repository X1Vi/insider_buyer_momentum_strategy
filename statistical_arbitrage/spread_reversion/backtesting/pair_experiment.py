#!/usr/bin/env python3
"""
Proper pairs experiment — HDFCBANK/KOTAKBANK.
For EVERY |z|>=3 signal, record entry features + forward outcomes (1/5/10/20d),
for BOTH the buy-laggard-only version and the proper two-leg pair (short expensive,
long cheap). Tests the key hypothesis: is the signal the EXTREME itself, or the
REVERSAL of the extreme (z-slope)? Also checks mean-reversion vs momentum.
"""
import numpy as np
import pandas as pd
import yfinance as yf

df = pd.read_csv("backtesting/hdfc_ktak_daily.csv")
df["ts"] = pd.to_datetime(df["ts"])
pa, pb = df["pa"].values, df["pb"].values
dates = df["ts"].values
n = len(pa)

BETA, ALPHA = 1.1622, 0.2189
WINDOW, Z_ENTER, HOLD = 60, 3.0, 5

sp = np.log(pa) - BETA * np.log(pb) + ALPHA
mu = pd.Series(sp).rolling(WINDOW).mean().values
sd = pd.Series(sp).rolling(WINDOW).std().values
z = np.zeros(n)
for i in range(n):
    z[i] = (sp[i] - mu[i]) / max(sd[i], 1e-6)

ra = pd.Series(np.log(pa)).pct_change(1).fillna(0)   # hdfc daily log ret (approx)
rb = pd.Series(np.log(pb)).pct_change(1).fillna(0)

def ret(s, i, d):
    if i + d >= n or i < 0:
        return np.nan
    return np.log(s[i + d]) - np.log(s[i])

def pair_pnl(entry_i, d, mode):
    """mode 'pair' = short expensive + long cheap; 'laggard' = long the laggard only."""
    if entry_i + d >= n:
        return np.nan, np.nan
    if z[entry_i] > 0:  # HDFC expensive -> pair: short HDFC, long KOTAK
        r_h, r_k = ret(pa, entry_i, d), ret(pb, entry_i, d)
        if mode == "pair":
            return r_k - r_h, r_k - r_h
        return r_k, r_k - r_h
    r_h, r_k = ret(pa, entry_i, d), ret(pb, entry_i, d)
    if mode == "pair":
        return r_h - r_k, r_h - r_k
    return r_h, r_h - r_k

# detect signals (both sides, dedup non-overlap like tracker)
sigs = []
last = -10**9
for i in range(n):
    if abs(z[i]) >= Z_ENTER and i >= last + HOLD and i + 20 < n:
        # features
        zs1 = z[i] - z[i - 1] if i >= 1 else np.nan
        zs3 = z[i] - z[i - 3] if i >= 3 else np.nan
        h5, h20 = ret(pa, i - 5, 5) if i >= 5 else np.nan, ret(pa, i - 20, 20) if i >= 20 else np.nan
        k5, k20 = ret(pb, i - 5, 5) if i >= 5 else np.nan, ret(pb, i - 20, 20) if i >= 20 else np.nan
        rel5, rel20 = (h5 - k5), (h20 - k20)
        sigs.append({"i": i, "date": dates[i], "z": z[i], "zslope1": zs1, "zslope3": zs3,
                     "h5": h5, "k5": k5, "rel5": rel5, "rel20": rel20})
        last = i

print(f"signals: {len(sigs)}\n")
print(f"{'date':<12} {'z':>5} {'zslope3':>8} {'h5':>7} {'k5':>7} | {'fwd1_pair':>9} {'fwd5_pair':>9} "
      f"{'fwd10_pair':>10} {'fwd20_pair':>10} | {'fwd5_lag':>8} | {'leg':>8}")
print("-" * 118)
rows = []
for s in sigs:
    i = s["i"]
    f1, _ = pair_pnl(i, 1, "pair")
    f5, rel5 = pair_pnl(i, 5, "pair")
    f10, _ = pair_pnl(i, 10, "pair")
    f20, _ = pair_pnl(i, 20, "pair")
    f5l, _ = pair_pnl(i, 5, "laggard")
    leg = "KOTAK" if z[i] > 0 else "HDFC"
    s.update({"f1": f1, "f5": f5, "f10": f10, "f20": f20, "f5l": f5l, "leg": leg})
    rows.append(s)
    print(f"{s['date']:<12} {s['z']:>+5.2f} {s['zslope3']:>+8.2f} {s['h5']*100:>+6.1f}% "
          f"{s['k5']*100:>+6.1f}% | {f1*100:>+8.1f}% {f5*100:>+8.1f}% {f10*100:>+9.1f}% "
          f"{f20*100:>+9.1f}% | {f5l*100:>+7.1f}% | {leg:>8}")

def summ(vals, label):
    vals = [v for v in vals if v == v]  # drop nan
    if not vals:
        return f"{label}: n/a"
    wr = 100 * np.mean([v > 0 for v in vals])
    return f"{label}: avg={100*np.mean(vals):+.1f}% win={wr:.0f}% (n={len(vals)})"

print("\n=== FORWARD OUTCOMES (pair = short expensive + long cheap) ===")
for d_ in (1, 5, 10, 20):
    print(f"  {d_:>2}d pair  " + summ([s[f"f{d_}"] for s in rows], "pair"))
print("  5d laggard  " + summ([s["f5l"] for s in rows], "laggard-only"))

print("\n=== THE KEY TEST: Group A (z still rising) vs Group B (z started falling) ===")
A = [s for s in rows if s["zslope3"] is not None and s["zslope3"] > 0]
B = [s for s in rows if s["zslope3"] is not None and s["zslope3"] <= 0]
for d_ in (1, 5, 10, 20):
    print(f"  {d_:>2}d:  A(z rising, n={len(A)})  " + summ([s[f"f{d_}"] for s in A], "A")
          + "   |   B(z falling, n={})  ".format(len(B)) + summ([s[f"f{d_}"] for s in B], "B"))

print("\n=== HYPOTHESIS CHECK: mean-reversion vs momentum ===")
for d_ in (1, 5, 10, 20):
    v = [s[f"f{d_}"] for s in rows if s[f"f{d_}"] == s[f"f{d_}"]]
    if v:
        avg = 100 * np.mean(v)
        print(f"  {d_:>2}d pair P&L avg = {avg:+.1f}%  -> {'MEAN-REVERSION' if avg > 0 else 'MOMENTUM/regime break'}")

print("\n=== LEVEL-2 FILTER: extreme AND z already falling (z[i] < z[i-1]) ===")
conf = [s for s in rows if s["zslope1"] is not None and s["zslope1"] < 0]
plain = rows
for d_ in (5, 10):
    print(f"  {d_}d:  plain n={len(plain)} " + summ([s[f"f{d_}"] for s in plain], "plain")
          + "   |   z-falling-filter n={} ".format(len(conf)) + summ([s[f"f{d_}"] for s in conf], "filter"))
