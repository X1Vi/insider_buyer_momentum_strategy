#!/usr/bin/env python3
"""plot_backtest.py — show what the backtest actually did.

Produces:
  plots/backtest/equity.png            pooled equal-weight equity curve
  plots/backtest/<sym>_trades.png      price + LONG entries (green ▲) and exits (red ✕)

Uses the best variant: entry on a dip, require close > 200-day MA, hold 20 days.
"""
from __future__ import annotations
from pathlib import Path
import sys
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from backtest_insider import load_events, load_px, signals, backtest  # noqa: E402

SYMS = ("DBCORP,STEL,MAHSEAMLES,JINDALSTEL,USHAMART,JSL,SURYAROSNI,NRBBEARING,NCC,"
        "MANINFRA,APLLTD,MANGLMCEM,SHOPERSTOP,GREENPLY,PAISALO,JINDRILL,KRISHANA,"
        "TFCILTD").split(",")
HOLD, COST, ENTRY, MA = 20, 0.0075, "dip", 200
OUT = HERE / "plots" / "backtest"
OUT.mkdir(parents=True, exist_ok=True)

ev = load_events(2.5e6)
strats, trade_counts = [], {}
for s in SYMS:
    px = load_px(s)
    if px is None:
        continue
    sig = signals(ev[ev["symbol"] == s], px, 40)
    if sig.empty:
        continue
    strat, tr, pos = backtest(px, sig, HOLD, COST, ENTRY, 40, MA)
    if tr.empty:
        continue
    strats.append(strat.rename(s))
    trade_counts[s] = (px, tr)

# ---- pooled equity curve ----
combined = pd.concat(strats, axis=1).mean(axis=1).dropna()
eq = (1 + combined).cumprod()
fig, ax = plt.subplots(figsize=(12, 5))
ax.plot(eq.index, eq.values, color="#1a9850", lw=1.2)
ax.set_title(f"Insider RSI-dip strategy — pooled equity (equal-weight, hold {HOLD}d, "
             f"above-200DMA, cost {COST:.2%})")
ax.set_ylabel("equity (start = 1.0)")
ax.grid(alpha=0.25)
fig.tight_layout()
fig.savefig(OUT / "equity.png", dpi=140)
plt.close(fig)
print(f"equity -> {(OUT/'equity.png').relative_to(HERE)}")

# ---- per-symbol trade plots (the most-active names) ----
top = sorted(trade_counts, key=lambda s: len(trade_counts[s][1]), reverse=True)[:6]
for s in top:
    px, tr = trade_counts[s]
    fig, ax = plt.subplots(figsize=(12, 5))
    ax.plot(px.index, px["close"].values, color="#333", lw=0.9)
    ax.scatter(tr["entry_date"], px["close"].reindex(tr["entry_date"], method="nearest"),
               marker="^", s=70, color="#1a9850", edgecolor="white", lw=0.4,
               label="LONG entry", zorder=3)
    ax.scatter(tr["exit_date"], px["close"].reindex(tr["exit_date"], method="nearest"),
               marker="x", s=55, color="#d73027", lw=1.2, label="exit", zorder=3)
    wins = (tr["net"] > 0).mean()
    ax.set_title(f"{s} — {len(tr)} trades, win {wins:.0%}, "
                 f"avg net {tr['net'].mean()*100:.1f}%")
    ax.legend(fontsize=8, loc="upper left")
    ax.grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(OUT / f"{s}_trades.png", dpi=140)
    plt.close(fig)
    print(f"trades -> {(OUT/f'{s}_trades.png').relative_to(HERE)}  (n={len(tr)})")
