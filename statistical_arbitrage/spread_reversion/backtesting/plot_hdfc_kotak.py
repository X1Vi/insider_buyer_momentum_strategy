#!/usr/bin/env python3
"""Plot real HDFCBANK vs KOTAKBANK prices + the z-score signal, marking BUY/SELL."""
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# load real daily data (ts,pa=HDFC,pb=KOTAK)
df = pd.read_csv("backtesting/hdfc_ktak_daily.csv")
df["ts"] = pd.to_datetime(df["ts"])
pa, pb = df["pa"].values, df["pb"].values
dates = df["ts"].values

BETA, ALPHA = 1.1622, 0.2189
WINDOW, Z_ENTER, Z_STOP, HOLD = 60, 3.0, 4.5, 5

# spread + rolling z (matches the tracker)
sp = np.log(pa) - BETA * np.log(pb) + ALPHA
mu = pd.Series(sp).rolling(WINDOW).mean().values
sd = pd.Series(sp).rolling(WINDOW).std().values
z = np.zeros(len(sp))
for i in range(len(sp)):
    z[i] = (sp[i] - mu[i]) / max(sd[i], 1e-6)

# detect BUY/SELL (matching live_signal.rs)
buys, sells = [], []   # (index, leg)
state, entry_z, held, last = "FLAT", 0.0, 0, -10**9
for i in range(len(sp)):
    if state == "FLAT":
        if abs(z[i]) >= Z_ENTER and i >= last + HOLD:
            leg = "KOTAKBANK" if z[i] > 0 else "HDFCBANK"
            buys.append((i, leg))
            state, entry_z, held, last = "POSITION", z[i], 0, i
    else:
        held += 1
        exit_now = (entry_z > 0 and z[i] <= 0) or (entry_z < 0 and z[i] >= 0) \
                   or abs(z[i]) >= Z_STOP or held >= HOLD
        if exit_now:
            sells.append((i, "exit"))
            state = "FLAT"

print(f"BUY signals: {len(buys)}  SELL signals: {len(sells)}")

fig, axes = plt.subplots(2, 1, figsize=(15, 10), sharex=True)

# ---- top: prices ----
ax = axes[0]
ax.plot(dates, pa, color="#1f77b4", lw=1.4, label="HDFCBANK")
ax.plot(dates, pb, color="#ff7f0e", lw=1.4, label="KOTAKBANK")
for i, leg in buys:
    color = "#ff7f0e" if leg == "KOTAKBANK" else "#1f77b4"
    y = pb[i] if leg == "KOTAKBANK" else pa[i]
    ax.axvline(dates[i], color=color, ls=":", lw=0.7, alpha=0.4)
    ax.scatter(dates[i], y, marker="^", s=38, color=color, edgecolors="k", lw=0.5, zorder=5)
    ax.annotate(f"B {leg}", (dates[i], y), textcoords="offset points",
                xytext=(0, 5), ha="center", fontsize=6, color=color)
for i, _ in sells:
    ax.axvline(dates[i], color="red", ls=":", lw=0.7, alpha=0.4)
    ax.scatter(dates[i], pa[i], marker="v", s=34, color="red", edgecolors="k", lw=0.5, zorder=5)
    ax.annotate("S", (dates[i], pa[i]), textcoords="offset points",
                xytext=(0, -7), ha="center", fontsize=6, color="red")
ax.set_ylabel("Price ₹")
ax.set_title("HDFCBANK vs KOTAKBANK (real daily 2022-2026) — green ^ = BUY the laggard, red v = SELL")
ax.legend(loc="upper left"); ax.grid(alpha=0.3)

# ---- bottom: z-score ----
ax = axes[1]
ax.plot(dates, z, color="gray", lw=0.9, label="z-score")
ax.axhline(0, color="k", lw=0.7)
ax.axhline(Z_ENTER, color="g", ls="--", lw=0.9, label="+3 BUY zone")
ax.axhline(-Z_ENTER, color="g", ls="--", lw=0.9)
ax.axhline(Z_STOP, color="r", ls=":", lw=0.9, label="stop |z|≥4.5")
ax.axhline(-Z_STOP, color="r", ls=":", lw=0.9)
for i, leg in buys:
    c = "green" if (leg == "KOTAKBANK") == (z[i] > 0) else "blue"
    ax.scatter(dates[i], z[i], marker="^", s=160, color=c, edgecolors="k", zorder=5)
for i, _ in sells:
    ax.scatter(dates[i], z[i], marker="v", s=140, color="red", edgecolors="k", zorder=5)
ax.set_ylabel("z-score")
ax.set_xlabel("date")
ax.set_title("Gap z-score — BUY when |z|≥3 (on the laggard), SELL when z reverts to 0")
ax.legend(loc="upper left"); ax.grid(alpha=0.3)

plt.tight_layout()
plt.savefig("backtesting/hdfc_kotak_signals.png", dpi=120)
print("saved backtesting/hdfc_kotak_signals.png")
