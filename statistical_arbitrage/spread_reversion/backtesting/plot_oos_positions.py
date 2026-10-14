#!/usr/bin/env python3
"""
Per-stock OUT-OF-SAMPLE position plots (from backtesting/oos_results.csv —
quarterly walk-forward: model trained only on events BEFORE, scored on events
AFTER training). No look-ahead, no survivorship. Saved to
backtesting/plots/oos_positions/.
"""
import os
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

CSV = "backtesting/oos_results.csv"
OUT = "backtesting/plots/oos_positions"
os.makedirs(OUT, exist_ok=True)

df = pd.read_csv(CSV)
print(f"OOS events: {len(df)}   T2 win: {df['t2'].mean():.0%}   watch: {(df['prob']>=0.5).sum()}")

per = df.groupby("leg").agg(n=("t2", "size"), win=("t2", "mean")).sort_values("win", ascending=False)
for leg in sorted(df["leg"].unique()):
    rows = df[df["leg"] == leg].sort_values("arm")
    price = pd.read_csv(f"backtesting/data/{leg}.csv")["close"].values
    n = len(price)
    wr = per.loc[leg, "win"]
    fig, ax = plt.subplots(figsize=(15, 6))
    ax.plot(np.arange(n), price, color="#1f77b4", lw=1.1)
    for _, r in rows.iterrows():
        e, a = int(r["arm"]) + 10, int(r["arm"])
        c = "green" if r["t2"] == 1 else "red"
        ax.axvline(a, color="gray", ls=":", lw=0.7, alpha=0.5)
        if r["prob"] >= 0.5:
            ax.scatter(e, price[e], marker="^" if r["t2"] == 1 else "v", s=110,
                       color=c, edgecolors="k", lw=0.6, zorder=6)
            ax.annotate(f"{r['prob']:.0%} {'WIN' if r['t2'] else 'MISS'}",
                        (e, price[e]), textcoords="offset points", xytext=(0, 9),
                        ha="center", fontsize=7, color=c, fontweight="bold")
        else:
            ax.scatter(e, price[e], marker="o", s=45, color="gray", edgecolors="k", lw=0.4, zorder=5)
    ax.set_ylabel("Price ₹")
    ax.set_title(f"{leg} — OUT-OF-SAMPLE positions (n={len(rows)}, T2 win {100*wr:.0f}%): "
                 f"model never saw these events in training")
    ax.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(f"{OUT}/{leg}.png", dpi=110)
    plt.close(fig)
    print(f"  wrote {OUT}/{leg}.png")

print(f"\nall OOS plots in {OUT}/")
