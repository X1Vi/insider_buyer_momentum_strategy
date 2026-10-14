#!/usr/bin/env python3
"""plot_trade_grid.py — the TRADE GRAPH: every traded stock's price with
insider BUYER (▼), our ENTRY (▲) and EXIT (✕), in one neat grid.

Rule: cluster -> pullback entry -> profit-lock exit -> cash when Nifty < 200-DMA.
"""
from __future__ import annotations

import math

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
NCOLS = 6


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
    by = {}
    for s, e, x in trades:
        by.setdefault(s, []).append((e, x))
    buys = ev[ev.personCategory.isin(MAJOR) & (ev.value >= 1e6) & ev.is_equity]

    syms = sorted(by, key=lambda s: min(e for e, _ in by[s]))
    nrows = math.ceil(len(syms) / NCOLS)
    fig, axes = plt.subplots(nrows, NCOLS, figsize=(3.4 * NCOLS, 2.5 * nrows))
    axes = np.atleast_1d(axes).ravel()

    for ax, sym in zip(axes, syms):
        px = prices[sym]
        c = px.close
        ax.plot(px.index, c, color="#444", lw=0.7)
        ax.plot(px.index, c.ewm(200, adjust=False).mean(), color="#b58b3c", lw=0.7)
        b = buys[buys.symbol == sym]
        ax.scatter(b.trade_date, c.reindex(b.trade_date, method="nearest"), marker="v",
                   s=16, color="#2e7d32", edgecolor="white", lw=0.2, zorder=4)
        for e, x in by[sym]:
            ax.scatter(px.index[e], px.open.iloc[e], marker="^", s=70, color="#1565c0",
                       edgecolor="white", lw=0.5, zorder=6)
            ax.scatter(px.index[x], px.open.iloc[x], marker="x", s=48, color="#c62828",
                       lw=1.4, zorder=6)
        ax.set_title(f"{sym} ({len(by[sym])})", fontsize=8)
        ax.tick_params(labelsize=6)
        ax.grid(alpha=0.15)
    for ax in axes[len(syms):]:
        ax.axis("off")

    legend = [Line2D([], [], marker="v", ls="", color="#2e7d32", label="insider BUYER"),
              Line2D([], [], marker="^", ls="", color="#1565c0", label="our ENTRY"),
              Line2D([], [], marker="x", ls="", color="#c62828", label="our EXIT"),
              Line2D([], [], color="#b58b3c", label="EMA200")]
    fig.suptitle("Trade graph — insider BUYER vs our ENTRY vs our EXIT  "
                 f"({len(trades)} trades / {len(syms)} stocks)", fontsize=15, y=1.002)
    fig.legend(handles=legend, loc="upper center", bbox_to_anchor=(0.5, 0.988),
               ncol=4, fontsize=11, frameon=False)
    fig.tight_layout(rect=(0, 0, 1, 0.978))
    out = FIND / "plots" / "TRADE_GRAPH.png"
    fig.savefig(out, dpi=150); plt.close(fig)
    print(f"plot -> {out}  ({len(trades)} trades, {len(syms)} stocks, {nrows}x{NCOLS})")


if __name__ == "__main__":
    raise SystemExit(main())
