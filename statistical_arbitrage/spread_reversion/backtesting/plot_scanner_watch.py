#!/usr/bin/env python3
"""
Plot the ML v3 WATCH scanner findings (AXISBANK / KOTAKBANK / TATASTEEL).
For each WATCH event (arm z<-3 -> OBS=10 -> candidate): shows the leg price +
pair z (the recovering-divergence), the arm/entry bars, and the arm->entry->+10d
path, colored by whether the +2% before -2% in 10d target was hit.
"""
import os
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

W_BETA, W_Z, Z_ARM, OBS = 252, 60, -3.0, 10
WATCH = [
    ("AXISBANK", "RELIANCE", 511),
    ("TATASTEEL", "TCS", 627),
    ("KOTAKBANK", "RELIANCE", 881),
    ("TATASTEEL", "TCS", 1033),
    ("KOTAKBANK", "RELIANCE", 1037),
]
OUT = "backtesting/plots/scanner_watch"
os.makedirs(OUT, exist_ok=True)


def load(name):
    return pd.read_csv(f"backtesting/data/{name}.csv")["close"].values


def rbz(pa, pb):
    sla, slb = pd.Series(np.log(pa)), pd.Series(np.log(pb))
    beta = (sla.rolling(W_BETA).cov(slb) / slb.rolling(W_BETA).var()).values
    alpha = (sla.rolling(W_BETA).mean() - pd.Series(beta) * slb.rolling(W_BETA).mean()).values
    spread = (sla - pd.Series(beta) * slb - pd.Series(alpha)).values
    mu = pd.Series(spread).rolling(W_Z).mean().values
    sd = pd.Series(spread).rolling(W_Z).std().values
    z = np.where(sd > 1e-9, (spread - mu) / np.maximum(sd, 1e-9), 0.0)
    z[:W_BETA + W_Z] = 0.0
    return z, beta


def t2_hit(pa, entry):
    e0 = pa[entry]
    for k in range(1, 11):
        if entry + k >= len(pa):
            return 0
        c = pa[entry + k]
        if c >= e0 * 1.02:
            return 1
        if c <= e0 * 0.98:
            return 0
    return 0


events = []
for leg, partner, arm in WATCH:
    pa, pb = load(leg), load(partner)
    n = min(len(pa), len(pb))
    pa, pb = pa[:n], pb[:n]
    z, beta = rbz(pa, pb)
    entry = arm + OBS
    hit = t2_hit(pa, entry)
    f5 = 100 * (pa[entry + 5] / pa[entry] - 1)
    f10 = 100 * (pa[entry + 10] / pa[entry] - 1)
    events.append({"leg": leg, "partner": partner, "arm": arm, "entry": entry,
                   "hit": hit, "pa": pa, "pb": pb, "z": z, "f5": f5, "f10": f10})
    print(f"WATCH {leg} arm={arm} entry={entry}  {'HIT +2%' if hit else 'MISS'}  "
          f"fwd5={f5:+.1f}% fwd10={f10:+.1f}%")

# ---- per-leg overview: all WATCH markers on the leg's price ----
for leg in sorted({e["leg"] for e in events}):
    evs = [e for e in events if e["leg"] == leg]
    pa = evs[0]["pa"]
    n = len(pa)
    fig, ax = plt.subplots(figsize=(14, 5))
    ax.plot(np.arange(n), pa, color="#1f77b4", lw=1.1)
    for e in evs:
        c = "green" if e["hit"] else "red"
        ax.axvline(e["arm"], color="gray", ls=":", lw=0.8, alpha=0.6)
        ax.scatter(e["entry"], pa[e["entry"]], marker="^", s=110, color=c,
                   edgecolors="k", lw=0.6, zorder=6)
        f5l = e["f5"]
        ax.annotate(f"WATCH {e['entry']}\n{f5l:+.1f}%/5d",
                    (e["entry"], pa[e["entry"]]), textcoords="offset points",
                    xytext=(0, 10), ha="center", fontsize=7, color=c, fontweight="bold")
    ax.set_ylabel("Price ₹")
    ax.set_title(f"{leg} — WATCH scanner signals (grey | = z<-3 arm, ^ = entry at arm+{OBS}; "
                 f"green = hit +2%, red = missed)")
    ax.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(f"{OUT}/{leg}_overview.png", dpi=110)
    plt.close(fig)

# ---- per-event detail: price + z (the recovering-divergence) ----
for e in events:
    arm, entry = e["arm"], e["entry"]
    lo, hi = arm - 5, entry + 15
    pa, z = e["pa"], e["z"]
    fig, axes = plt.subplots(2, 1, figsize=(13, 7), sharex=True)
    ax = axes[0]
    ax.plot(np.arange(lo, hi), pa[lo:hi], color="#1f77b4", lw=1.4)
    ax.axvline(arm, color="gray", ls="--", lw=1, alpha=0.8, label="ARM z<-3")
    ax.axvline(entry, color="green" if e["hit"] else "red", ls="--", lw=1.2,
               label=f"ENTRY ({'HIT' if e['hit'] else 'MISS'})")
    ax.scatter(entry, pa[entry], marker="^", s=90, color="green" if e["hit"] else "red",
               edgecolors="k", zorder=6)
    ax.set_ylabel(f"{e['leg']} price ₹")
    ax.legend(loc="upper left"); ax.grid(alpha=0.3)
    ax.set_title(f"{e['leg']}/{e['partner']} WATCH arm={arm} -> entry={entry}  "
                 f"fwd5={e['f5']:+.1f}% fwd10={e['f10']:+.1f}%")
    ax = axes[1]
    ax.plot(np.arange(lo, hi), z[lo:hi], color="#c0392b", lw=1.2)
    ax.axhline(-3, color="k", ls=":", lw=0.8)
    ax.axhline(0, color="k", lw=0.6)
    ax.axvline(arm, color="gray", ls="--", lw=1, alpha=0.8)
    ax.axvline(entry, color="green" if e["hit"] else "red", ls="--", lw=1.2)
    ax.set_ylabel("pair z-score")
    ax.set_xlabel("trading day")
    ax.set_title("z recovering from the extreme while price is still depressed (divergence)")
    ax.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(f"{OUT}/detail_{e['leg']}_{arm}.png", dpi=110)
    plt.close(fig)

# ---- paths: arm -> ENTRY -> +10d, colored by outcome ----
fig, ax = plt.subplots(figsize=(12, 6))
for e in events:
    pa, arm, entry = e["pa"], e["arm"], e["entry"]
    path = np.array([pa[min(k, len(pa) - 1)] / pa[entry] - 1 for k in range(arm, entry + 11)])
    x = np.arange(len(path)) - (entry - arm)
    ax.plot(x, path * 100, color=("green" if e["hit"] else "red"), alpha=0.75, lw=1.3,
            label=f"{e['leg']} arm={arm}" if e is events[0] or True else None)
    ax.text(x[-1], path[-1] * 100, f" {e['leg']}@{arm}", fontsize=7,
            color="green" if e["hit"] else "red")
ax.axvline(0, color="k", ls="--", lw=0.8)
ax.axhline(0, color="k", lw=0.6)
ax.axhline(2, color="g", ls=":", lw=0.8)
ax.axhline(-2, color="r", ls=":", lw=0.8)
ax.set_xlabel("bars (arm=start, 0=ENTRY, +10=forward)")
ax.set_ylabel("% from entry")
ax.set_title("WATCH scanner trades: arm -> ENTRY(0) -> +10d  (green=hit +2%, red=missed; "
             "dotted ±2% target/stop)")
ax.grid(alpha=0.3)
plt.tight_layout()
plt.savefig(f"{OUT}/paths.png", dpi=110)
print(f"\nplots saved in {OUT}/")
