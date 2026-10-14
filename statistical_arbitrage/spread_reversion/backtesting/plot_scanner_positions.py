#!/usr/bin/env python3
"""
Plot the ACTUAL positions the scanner took, per stock, into
backtesting/plots/scanner_positions/.
For each leg in backtesting/scanner_backtest_results.csv:
  grey | = z<-3 arm bar,  ^ green = ENTRY that hit +2% in 10d,  v red = missed,
  labeled with model probability (WATCH>=50% highlighted).
"""
import os
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

CSV = "backtesting/scanner_backtest_results.csv"
OUT = "backtesting/plots/scanner_positions"
os.makedirs(OUT, exist_ok=True)

df = pd.read_csv(CSV)
print(f"events: {len(df)}  legs: {df['leg'].nunique()}  "
      f"overall T2 win: {df['t2'].mean():.0%}")

per = df.groupby("leg").agg(n=("t2", "size"), win=("t2", "mean")).sort_values("win", ascending=False)
print("\nper leg:")
for leg, r in per.iterrows():
    print(f"  {leg:<12} n={int(r['n']):>3}  T2win={100*r['win']:>3.0f}%")

for leg in sorted(df["leg"].unique()):
    rows = df[df["leg"] == leg].sort_values("entry")
    price = pd.read_csv(f"backtesting/data/{leg}.csv")["close"].values
    n = len(price)
    wr = per.loc[leg, "win"]

    fig, ax = plt.subplots(figsize=(15, 6))
    ax.plot(np.arange(n), price, color="#1f77b4", lw=1.1)
    for _, r in rows.iterrows():
        e, a = int(r["entry"]), int(r["arm"])
        c = "green" if r["t2"] == 1 else "red"
        ax.axvline(a, color="gray", ls=":", lw=0.7, alpha=0.5)
        if r["prob"] >= 0.5:
            ax.axvline(e, color=c, ls="--", lw=0.9, alpha=0.6)
            ax.scatter(e, price[e], marker="^" if r["t2"] == 1 else "v", s=110,
                       color=c, edgecolors="k", lw=0.6, zorder=6)
            ax.annotate(f"{r['prob']:.0%} {'WIN' if r['t2'] else 'MISS'}",
                        (e, price[e]), textcoords="offset points", xytext=(0, 9),
                        ha="center", fontsize=7, color=c, fontweight="bold")
        else:
            ax.scatter(e, price[e], marker="o", s=45, color="gray", edgecolors="k", lw=0.4, zorder=5)
    ax.set_ylabel("Price ₹")
    ax.set_title(f"{leg} — actual scanner positions (n={len(rows)}, T2 win {100*wr:.0f}%): "
                 f"grey | = arm, filled = ENTRY (green hit / red missed, P>=50%), dot = low-conf candidate")
    ax.grid(alpha=0.3)
    plt.tight_layout()
    path = f"{OUT}/{leg}.png"
    plt.savefig(path, dpi=110)
    plt.close(fig)
    print(f"  wrote {path}")

print(f"\nall plots in {OUT}/")
