#!/usr/bin/env python3
"""
Plot the Rust scanner-backtest results (tests/scanner_backtest.rs output).
Shows: per-leg T2 win rate (the model's candidate set), event count vs win
rate (does the model over-fire on losing legs?), and probability vs outcome.
No survivorship (all 18 stocks, all pairs) — causal, no look-ahead.
"""
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

df = pd.read_csv("backtesting/scanner_backtest_results.csv")
df["watch"] = df["prob"] >= 0.5
print(f"events: {len(df)}  watch(prob>=0.5): {df['watch'].sum()}  T2 base: {df['t2'].mean():.0%}")

per = df.groupby("leg").agg(n=("t2", "size"), win=("t2", "mean"), watch=("watch", "sum"),
                            f5=("fwd5", "mean"), f10=("fwd10", "mean"),
                            prob=("prob", "mean")).reset_index()
per = per.sort_values("win", ascending=True)
print("\nper-leg (model candidate set):")
for _, r in per.iterrows():
    print(f"  {r['leg']:<12} n={int(r['n']):>3}  watch={int(r['watch']):>3}  "
          f"T2win={100*r['win']:>4.0f}%  fwd5={r['f5']:+.1f}%  fwd10={r['f10']:+.1f}%  avgP={r['prob']:.0%}")

fig, axes = plt.subplots(2, 2, figsize=(15, 11))

# 1) per-leg win rate bar
ax = axes[0, 0]
cols = ["#2e8b57" if w >= 0.5 else ("#d4a017" if w >= 0.33 else "#c0392b") for w in per["win"]]
ax.barh([str(x) for x in per["leg"]], per["win"] * 100, color=cols)
for yi, (_, r) in enumerate(per.iterrows()):
    ax.text(r["win"] * 100 + 1, yi, f" n={int(r['n'])}", va="center", fontsize=8)
ax.axvline(50, color="k", ls="--", lw=0.8)
ax.set_xlabel("T2 win rate % (hit +2% before -2% in 10d)")
ax.set_title("Per-leg win rate — ML model's candidate set (ALL pairs, no survivorship)")
ax.grid(alpha=0.3)

# 2) event count vs win rate (over-firing on losers?)
ax = axes[0, 1]
sc = ax.scatter(per["n"], per["win"] * 100, s=80, c=per["prob"], cmap="RdYlGn",
                edgecolors="k", zorder=3)
for _, r in per.iterrows():
    ax.annotate(r["leg"], (r["n"], r["win"] * 100), fontsize=7, xytext=(3, 3),
                textcoords="offset points")
ax.axhline(50, color="k", ls="--", lw=0.8)
ax.set_xlabel("# candidates the model generates")
ax.set_ylabel("T2 win rate %")
ax.set_title("Model over-fires on HCLTECH/AXISBANK (many events) but they win the least")
plt.colorbar(sc, ax=ax, label="avg model prob")
ax.grid(alpha=0.3)

# 3) probability vs outcome (does P separate winners within its own set?)
ax = axes[1, 0]
for t, col, lab in ((0, "red", "LOSS"), (1, "green", "WIN")):
    sub = df[df["t2"] == t]
    ax.hist(sub["prob"], bins=12, alpha=0.6, color=col, label=f"{lab} (n={len(sub)})")
ax.axvline(0.5, color="k", ls="--", lw=0.8)
ax.set_xlabel("model probability")
ax.set_ylabel("count")
ax.set_title("Outcome by model probability (within its own candidates)")
ax.legend(); ax.grid(alpha=0.3)

# 4) WATCH vs ALL: win rate of the model's high-confidence picks per leg
ax = axes[1, 1]
watch_rows = df[df["watch"]].groupby("leg").agg(n=("t2", "size"), win=("t2", "mean"))
all_rows = df.groupby("leg").agg(n=("t2", "size"), win=("t2", "mean"))
legs = sorted(set(all_rows.index) & set(watch_rows.index))
x = np.arange(len(legs))
ax.bar(x - 0.2, [all_rows.loc[l, "win"] * 100 for l in legs], width=0.4, label="all candidates", color="#999")
ax.bar(x + 0.2, [watch_rows.loc[l, "win"] * 100 if l in watch_rows.index else 0 for l in legs],
       width=0.4, label="WATCH only (P>=0.5)", color="#14568c")
ax.set_xticks(x)
ax.set_xticklabels(legs, rotation=45, fontsize=8)
ax.axhline(50, color="k", ls="--", lw=0.8)
ax.set_ylabel("T2 win %")
ax.set_title("Does the WATCH threshold help? (all candidates vs WATCH-only)")
ax.legend(fontsize=8); ax.grid(alpha=0.3)

plt.tight_layout()
plt.savefig("backtesting/plots/scanner_backtest.png", dpi=110)
print("\nsaved backtesting/plots/scanner_backtest.png")
