#!/usr/bin/env python3
"""plot_all_trades_neat.py — one neat chart of EVERY trade: buyer, entry, exit.

Each row = a stock. For every trade: a bar from ENTRY to EXIT coloured by net P&L,
with the insider BUYER (▼), our ENTRY (▲) and EXIT (✕) marked.
Rule: cluster -> pullback entry -> profit-lock exit -> cash when Nifty < 200-DMA.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

import cluster_and_fast as base
import cluster_advantage as ca
import momentum_entry_pp as mep
from regime_gate import gated
from exit_optimize import FIND

COST = base.COST
MAJOR = base.MAJOR


def main():
    events = base.load_events()
    prices = base.load_prices()
    bench = base.load_bench()
    ev = events[events.symbol.isin(prices)]
    cluster = ca.cluster_events(ev, 30, 2, 1e6, 20)[["symbol", "signal_date"]]
    S, cal = mep.build(prices)
    nifty = bench.reindex(cal, method="ffill")
    ma = bench.rolling(200).mean().reindex(cal, method="ffill")
    gate_arr = np.roll((nifty > ma).to_numpy(), 1)
    gate_arr[0] = True

    trades = gated(mep.simulate_pullback(cluster, prices, S, 0.10), S, gate_arr, "full")
    df = pd.DataFrame([(s, prices[s].index[e], prices[s].index[x],
                        prices[s].open.iloc[x] / prices[s].open.iloc[e] - 1 - COST)
                       for s, e, x in trades], columns=["symbol", "entry", "exit", "net"])
    buys = ev[ev.personCategory.isin(MAJOR) & (ev.value >= 1e6) & ev.is_equity]

    order = df.groupby("symbol").entry.min().sort_values().index.tolist()
    ypos = {s: i for i, s in enumerate(order)}
    cmap = plt.cm.RdYlGn
    norm = plt.Normalize(-0.30, 0.30)

    fig, ax = plt.subplots(figsize=(15, 0.32 * len(order) + 2.2))
    ax.fill_between(cal, -1, len(order), where=~gate_arr, color="#d62727", alpha=0.05, lw=0)
    ax.axvline(base.SPLIT, color="#555", ls=":", lw=1.0)
    for r in df.itertuples():
        y = ypos[r.symbol]
        ax.plot([r.entry, r.exit], [y, y], color=cmap(norm(r.net)), lw=5,
                solid_capstyle="round", zorder=2)
        ax.scatter(r.entry, y, marker="^", s=42, color="#1565c0", edgecolor="white",
                   lw=0.4, zorder=4)
        ax.scatter(r.exit, y, marker="x", s=40, color="#c62828", lw=1.6, zorder=4)
    for sym in order:
        b = buys[buys.symbol == sym]
        ax.scatter(b.trade_date, np.full(len(b), ypos[sym]), marker="v", s=26,
                   color="#2e7d32", edgecolor="white", lw=0.3, zorder=3)
    ax.set_yticks(range(len(order)))
    ax.set_yticklabels(order, fontsize=6)
    ax.set_ylim(-1, len(order))
    ax.grid(axis="x", alpha=0.15)
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)
    ax.set_title(f"Every trade — {len(df)} trades / {len(order)} stocks   "
                 f"(win {(df.net>0).mean():.0%}, mean {df.net.mean()*100:+.1f}%)", fontsize=12)
    ax.set_xlabel("red bands = risk-off (cash)  ·  dotted line = 70/30 split")
    legend = [Line2D([], [], marker="v", ls="", color="#2e7d32", label="insider BUYER"),
              Line2D([], [], marker="^", ls="", color="#1565c0", label="our ENTRY"),
              Line2D([], [], marker="x", ls="", color="#c62828", label="our EXIT")]
    ax.legend(handles=legend, loc="upper left", fontsize=8, framealpha=0.9)
    sm = plt.cm.ScalarMappable(norm=norm, cmap=cmap)
    fig.colorbar(sm, ax=ax, fraction=0.015, pad=0.01, label="net return")
    fig.tight_layout()
    out = FIND / "plots" / "ALL_TRADES.png"
    fig.savefig(out, dpi=150); plt.close(fig)
    print(f"plot -> {out}  ({len(df)} trades, {len(order)} stocks)")


if __name__ == "__main__":
    raise SystemExit(main())
