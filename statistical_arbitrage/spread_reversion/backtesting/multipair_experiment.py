#!/usr/bin/env python3
"""
Multi-pair pairs experiment — pool the "reversal of the extreme" test across the
whole universe. For every |z|>=3 signal on every pair (per-pair OLS beta):
  1. forward pair P&L (short expensive + long cheap) at 1/5/10/20d
  2. Group A (z still rising) vs Group B (z started falling)
  3. Level-2 filter (extreme AND z already falling)
  4. mean-reversion vs momentum, overall and cointegrated-only
"""
import glob
import numpy as np
import pandas as pd
from statsmodels.tsa.stattools import coint

WINDOW, Z_ENTER, HOLD = 60, 3.0, 5
HORIZONS = (1, 5, 10, 20)

files = sorted(glob.glob("backtesting/data/*.csv"))
names = [f.split("/")[-1][:-4] for f in files]
data = {}
for name, f in zip(names, files):
    df = pd.read_csv(f)
    data[name] = df["close"].values

print(f"universe: {len(names)} names -> {len(names)*(len(names)-1)//2} pairs\n")

all_sigs = []   # pooled signals
pair_rows = []

for a in range(len(names)):
    for b in range(a + 1, len(names)):
        A, B = names[a], names[b]
        pa, pb = data[A], data[B]
        n = min(len(pa), len(pb))
        pa, pb = pa[:n], pb[:n]
        if n < 300:
            continue
        la, lb = np.log(pa), np.log(pb)
        beta, alpha = np.polyfit(lb, la, 1)
        sp = la - beta * lb - alpha
        mu = pd.Series(sp).rolling(WINDOW).mean().values
        sd = pd.Series(sp).rolling(WINDOW).std().values
        z = np.zeros(n)
        for i in range(n):
            z[i] = (sp[i] - mu[i]) / max(sd[i], 1e-6)
        # cointegration p
        try:
            _, cp, _ = coint(la, lb)
        except Exception:
            cp = 1.0

        last = -10**9
        n_sig = 0
        for i in range(n):
            if abs(z[i]) >= Z_ENTER and i >= last + HOLD and i + 20 < n:
                zs1 = z[i] - z[i - 1] if i >= 1 else np.nan
                zs3 = z[i] - z[i - 3] if i >= 3 else np.nan
                rec = {"pair": f"{A}/{B}", "date": i, "z": z[i], "z1": zs1, "z3": zs3,
                       "coint": cp, "i": i, "pa": pa, "pb": pb, "sp": sp}
                for d_ in HORIZONS:
                    if z[i] > 0:  # short A (expensive), long B
                        rec[f"f{d_}"] = (np.log(pb[i + d_]) - np.log(pb[i])) - (np.log(pa[i + d_]) - np.log(pa[i]))
                    else:         # short B, long A
                        rec[f"f{d_}"] = (np.log(pa[i + d_]) - np.log(pa[i])) - (np.log(pb[i + d_]) - np.log(pb[i]))
                all_sigs.append(rec)
                n_sig += 1
                last = i
        pair_rows.append((f"{A}/{B}", cp, n_sig))

print(f"{'PAIR':<24} {'coint_p':>8} {'signals':>7}")
for p, cp, ns in sorted(pair_rows, key=lambda r: -r[2]):
    if ns:
        print(f"{p:<24} {cp:>8.3f} {ns:>7}")


def summ(sigs, key):
    v = [s[key] for s in sigs if s[key] == s[key]]
    if not v:
        return "n/a"
    return f"avg={100*np.mean(v):+.2f}% win={100*np.mean([x>0 for x in v]):.0f}% (n={len(v)})"


def split_by(sigs, cond):
    return [s for s in sigs if cond(s)], [s for s in sigs if not cond(s)]

print(f"\n=== POOLED ({len(all_sigs)} signals) — forward PAIR P&L (short expensive + long cheap) ===")
for d_ in HORIZONS:
    print(f"  {d_:>2}d: " + summ(all_sigs, f"f{d_}"))

coint_sigs = [s for s in all_sigs if s["coint"] < 0.05]
print(f"\n=== COINTEGRATED-ONLY ({len(coint_sigs)} signals, coint p<0.05) ===")
for d_ in HORIZONS:
    print(f"  {d_:>2}d: " + summ(coint_sigs, f"f{d_}"))

print("\n=== KEY TEST — Group A (z rising, z3>0) vs Group B (z falling, z3<=0) ===")
A, B = split_by(all_sigs, lambda s: s["z3"] > 0)
print(f"  Group A (z rising, n={len(A)}):")
for d_ in HORIZONS:
    print(f"    {d_:>2}d: " + summ(A, f"f{d_}"))
print(f"  Group B (z falling, n={len(B)}):")
for d_ in HORIZONS:
    print(f"    {d_:>2}d: " + summ(B, f"f{d_}"))

print("\n=== LEVEL-2 FILTER — extreme AND z already falling (z[i] < z[i-1]) ===")
F = [s for s in all_sigs if s["z1"] < 0]
print(f"  filtered (n={len(F)}):")
for d_ in (5, 10):
    print(f"    {d_}d: " + summ(F, f"f{d_}"))
print(f"  plain (n={len(all_sigs)}):")
for d_ in (5, 10):
    print(f"    {d_}d: " + summ(all_sigs, f"f{d_}"))

print("\n=== HYPOTHESIS: mean-reversion vs momentum (pooled) ===")
for d_ in HORIZONS:
    v = [s[f"f{d_}"] for s in all_sigs if s[f"f{d_}"] == s[f"f{d_}"]]
    if v:
        avg = 100 * np.mean(v)
        print(f"  {d_:>2}d: {avg:+.2f}%  -> {'MEAN-REVERSION' if avg > 0 else 'MOMENTUM'}")
