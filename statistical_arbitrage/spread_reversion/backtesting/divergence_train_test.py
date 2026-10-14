#!/usr/bin/env python3
"""
DIVERGENCE — train/test split, fully causal, SHORT holds ("make some bucks, leave").
  train = first 60% of the data, test = last 40% (purely informational).
  Rolling-beta z (252d), confirmed swing low (L=3), BUY at confirmation — no look-ahead.
  Legs are selected ONLY from the train period (avg 5d forward > 0, >= 2 signals);
  the test period reports their short forward returns (3/5/10d). Then plots the
  test-period BUY signals for the selected legs.
"""
import glob
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

SPLIT, W_BETA, W_Z, Z_ARM, L = 0.6, 252, 60, -3.0, 3
HORIZONS = (3, 5, 10)

files = sorted(glob.glob("backtesting/data/*.csv"))
names = [f.split("/")[-1][:-4] for f in files]
data = {nm: pd.read_csv(f)["close"].values for nm, f in zip(names, files)}
print(f"universe: {len(names)} names")


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
    n = len(pa)
    sigs = []
    state = "ARMED"
    last_low = None
    arm_i = None
    for i in range(n):
        if state == "ARMED":
            if z[i] < Z_ARM:
                state, arm_i = "HUNT", i
        elif state == "HUNT":
            if z[i] > -1.0 or i - arm_i > 150:
                state, last_low = "ARMED", None
        j = i - L
        if j >= L and is_confirmed_low(j, pa, L):
            pj, zj = pa[j], z[j]
            if state == "HUNT":
                if last_low is None:
                    last_low = (pj, zj, j)
                elif pj < last_low[0]:
                    if zj > last_low[1]:
                        sigs.append((i, pa[i], j, pj, zj, last_low[1]))
                        state, last_low = "ARMED", None
                    else:
                        last_low = (pj, zj, j)
    return sigs


# ---- collect all causal signals per pair, with short forward returns ----
all_sigs = []  # (bought_leg, conf_i, conf_px, split, fwd3, fwd5, fwd10, pair)
n_global = min(len(d) for d in data.values())
for a in range(len(names)):
    for b in range(a + 1, len(names)):
        A, B = names[a], names[b]
        pa, pb = data[A], data[B]
        n = min(len(pa), len(pb))
        if n < W_BETA + W_Z + 50:
            continue
        pa, pb = pa[:n], pb[:n]
        z = rolling_beta_z(pa, pb)
        split_idx = int(SPLIT * n)
        for ci, cp, li, lp, lz, pz in run_signal(pa, pb, z):
            f = {}
            for h in HORIZONS:
                if ci + h < n:
                    f[h] = 100 * (pa[ci + h] / pa[ci] - 1)
            all_sigs.append((A, ci, cp, ci >= split_idx, f.get(3), f.get(5), f.get(10), f"{A}/{B}"))

# ---- train selection by bought leg ----
train = [s for s in all_sigs if not s[3]]
leg_stats = {}
for A, ci, cp, is_test, f3, f5, f10, pair in train:
    if f5 is None:
        continue
    st = leg_stats.setdefault(A, [0, 0.0])
    st[0] += 1
    st[1] += f5
selected = {A: st for A, st in leg_stats.items() if st[0] >= 2 and st[1] / st[0] > 0}
print(f"\nTRAIN signals: {len(train)}   legs with >=2 signals: {len(leg_stats)}   "
      f"SELECTED legs (train avg 5d>0): {sorted(selected)}")

# ---- test (purely informational) ----
test = [s for s in all_sigs if s[3]]
sel_test = [s for s in test if s[0] in selected]
all_test = test

def stats(rows, label):
    print(f"\n=== {label} ===")
    for h, idx in ((3, 4), (5, 5), (10, 6)):
        v = [r[idx] for r in rows if r[idx] is not None]
        if v:
            print(f"  {h}d: avg={np.mean(v):+.1f}%  med={np.median(v):+.1f}%  win={100*np.mean([x>0 for x in v]):.0f}%  "
                  f"(n={len(v)})")

stats(sel_test, f"TEST — SELECTED legs ({len(sel_test)} signals, purely informational)")
stats(all_test, f"TEST — ALL legs ({len(all_test)} signals)")

# per selected leg detail
print("\n=== TEST per selected leg ===")
for A in sorted(selected):
    rows = [r for r in sel_test if r[0] == A]
    if rows:
        v5 = [r[5] for r in rows if r[5] is not None]
        if v5:
            print(f"  {A:<12} n={len(rows):>2}  fwd5 avg={np.mean(v5):+.1f}%  win={100*np.mean([x>0 for x in v5]):.0f}%")

# ---- plot test-period signals for selected legs ----
print("\n=== PLOTS ===")
for A in sorted(selected):
    pa = data[A]
    n = len(pa)
    split_idx = int(SPLIT * n)
    rows = [r for r in sel_test if r[0] == A]
    if not rows:
        continue
    dates = np.arange(split_idx, n)
    fig, ax = plt.subplots(figsize=(14, 5))
    ax.plot(np.arange(n), pa, color="#1f77b4", lw=1.1)
    ax.axvline(split_idx, color="black", ls="--", lw=1, alpha=0.7, label="train|test split")
    for r in rows:
        ax.axvline(r[1], color="green", ls="--", lw=0.9, alpha=0.6)
        ax.scatter(r[1], r[2], marker="^", s=70, color="green", edgecolors="k", lw=0.5, zorder=6)
        ax.annotate(f"BUY@{r[2]:.0f}", (r[1], r[2]), textcoords="offset points",
                    xytext=(0, 7), ha="center", fontsize=7, color="green")
    ax.set_xlim(split_idx - 30, n + 5)
    ax.set_ylabel("Price ₹")
    ax.set_title(f"{A} — TEST period divergence BUY signals (causal, short holds), "
                 f"train-selected leg")
    ax.legend(loc="upper left"); ax.grid(alpha=0.3)
    plt.tight_layout()
    path = f"backtesting/plots/traintest_{A}.png"
    plt.savefig(path, dpi=110)
    plt.close(fig)
    print(f"  {A}: {path}")
