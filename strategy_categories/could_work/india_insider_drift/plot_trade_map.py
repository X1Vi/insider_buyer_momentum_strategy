#!/usr/bin/env python3
"""plot_trade_map.py — where did we take ALL the trades?

Rule: cluster -> wait-for-momentum entry (breakout+trend, min_rise 10%)
      -> profit-lock exit (.15/.25/3) -> cash when Nifty < 200-DMA.

Plot 1 (trade_map.png): one horizontal bar per trade (entry->exit), grouped by stock,
        coloured by net return (green profit / red loss); red bands = risk-off.
Plot 2 (trade_scatter.png): every trade as a dot, entry date vs net return.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import cluster_and_fast as base
import cluster_advantage as ca
import momentum_entry_pp as mep
from regime_gate import gated
from exit_optimize import FIND

COST = base.COST


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

    trades = gated(mep.simulate(cluster, prices, S, 0.10), S, gate_arr, "full")
    rows = []
    for sym, ei, xi in trades:
        rows.append((sym, prices[sym].index[ei], prices[sym].index[xi],
                     prices[sym].open.iloc[xi] / prices[sym].open.iloc[ei] - 1 - COST,
                     xi - ei))
    df = pd.DataFrame(rows, columns=["symbol", "entry", "exit", "net", "hold"])
    print(f"{len(df)} trades across {df.symbol.nunique()} stocks; "
          f"win { (df.net>0).mean():.3f}; mean {df.net.mean()*100:+.1f}%")

    plots = FIND / "plots"
    plots.mkdir(exist_ok=True)
    order = df.groupby("symbol").entry.min().sort_values().index.tolist()
    ypos = {s: i for i, s in enumerate(order)}
    cmap = plt.cm.RdYlGn
    norm = plt.Normalize(-0.30, 0.30)

    fig, ax = plt.subplots(figsize=(15, max(6, 0.26 * len(order))))
    ax.fill_between(cal, -1, len(order), where=~gate_arr, color="#d62727", alpha=0.05, lw=0)
    ax.axvline(base.SPLIT, color="black", ls=":", lw=1.0)
    for r in df.itertuples():
        y = ypos[r.symbol]
        ax.plot([r.entry, r.exit], [y, y], color=cmap(norm(r.net)), lw=3.2,
                solid_capstyle="round")
        ax.scatter(r.entry, y, marker="|", color="black", s=26, zorder=4)
    ax.set_yticks(range(len(order)))
    ax.set_yticklabels(order, fontsize=6)
    ax.set_ylim(-1, len(order))
    ax.set_title(f"Trade map — {len(df)} trades (cluster -> momentum entry -> profit-lock exit, gated)")
    ax.set_xlabel("date  (black tick = entry; bar runs to exit; red bands = risk-off)")
    ax.grid(axis="x", alpha=0.2)
    sm = plt.cm.ScalarMappable(norm=norm, cmap=cmap)
    fig.colorbar(sm, ax=ax, fraction=0.02, pad=0.01, label="net return")
    fig.tight_layout(); fig.savefig(plots / "trade_map.png", dpi=150); plt.close(fig)

    fig2, ax2 = plt.subplots(figsize=(13, 6))
    off = pd.Series(~gate_arr, index=cal)
    reg = np.array([bool(off.reindex([prices[s].index[ei]], method="ffill").iloc[0]) for s, ei, xi in trades])
    ax2.scatter(df.entry[~reg], df.net[~reg] * 100, s=14, alpha=0.6, color="#17964b", label="risk-on entry")
    ax2.scatter(df.entry[reg], df.net[reg] * 100, s=14, alpha=0.6, color="#d62727", label="risk-off entry")
    ax2.axhline(0, color="#888", lw=0.8)
    ax2.set_title("Every trade — entry date vs net return (coloured by regime at entry)")
    ax2.set_ylabel("net return (%)"); ax2.set_xlabel("entry date")
    ax2.grid(alpha=0.25); ax2.legend()
    fig2.tight_layout(); fig2.savefig(plots / "trade_scatter.png", dpi=150); plt.close(fig)

    print(f"plots -> {plots / 'trade_map.png'}, {plots / 'trade_scatter.png'}")


if __name__ == "__main__":
    raise SystemExit(main())
