#!/usr/bin/env python3
"""plot_be3.py — the clearest possible chart: insider BUYER vs our ENTRY vs our EXIT.

One panel per stock, big labelled markers:
  green ▼  = insider BUYER (order date)
  blue  ▲  = OUR ENTRY (momentum entry, next open)
  red   ✕  = OUR EXIT  (profit-lock, next open), labelled with net %
Price + EMA200 only, to keep it readable.
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
MAJOR = base.MAJOR
SYMBOLS = ["MANINFRA", "CHAMBLFERT", "STEL", "MAHSEAMLES"]


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
    buys = ev[ev.personCategory.isin(MAJOR) & (ev.value >= 1e6) & ev.is_equity]
    off = pd.Series(~gate_arr, index=cal)

    fig, axes = plt.subplots(len(SYMBOLS), 1, figsize=(16, 4.2 * len(SYMBOLS)))
    for ax, sym in zip(np.atleast_1d(axes), SYMBOLS):
        px = prices[sym]
        c = px.close
        ax.plot(px.index, c, color="#333", lw=1.0, label="price")
        ax.plot(px.index, c.ewm(200, adjust=False).mean(), color="#b58b3c", lw=1.0, label="EMA200")
        offs = off.reindex(px.index, method="ffill").fillna(False)
        ax.fill_between(px.index, 0, 1, where=offs.to_numpy(),
                        transform=ax.get_xaxis_transform(), color="#d62727", alpha=0.06, lw=0)
        b = buys[buys.symbol == sym]
        ax.scatter(b.trade_date, c.reindex(b.trade_date, method="nearest"), marker="v",
                   s=110, color="#00a000", edgecolor="black", lw=0.6, zorder=6,
                   label="insider BUYER")
        first = {"e": True, "x": True}
        for _, ei, xi in [t for t in trades if t[0] == sym]:
            net = px.open.iloc[xi] / px.open.iloc[ei] - 1 - COST
            ax.scatter(px.index[ei], px.open.iloc[ei], marker="^", s=220, color="#1e88e5",
                       edgecolor="black", lw=0.8, zorder=7,
                       label="OUR ENTRY" if first["e"] else None)
            ax.scatter(px.index[xi], px.open.iloc[xi], marker="x", s=170, color="#d62728",
                       lw=2.6, zorder=7, label="OUR EXIT" if first["x"] else None)
            ax.annotate(f"{net*100:+.0f}%", (px.index[xi], px.open.iloc[xi]),
                        textcoords="offset points", xytext=(6, 8), fontsize=8,
                        color="#0a0" if net > 0 else "#c00")
            first["e"] = first["x"] = False
        ax.set_title(f"{sym}", fontsize=11)
        ax.set_ylabel("price"); ax.grid(alpha=0.2)
        ax.legend(fontsize=8, loc="upper left", ncol=3)
    fig.suptitle("Insider BUYER (▼) vs our ENTRY (▲, PULLBACK) vs our EXIT (✕) — net % at exit",
                 fontsize=13)
    fig.tight_layout(rect=(0, 0, 1, 0.98))
    out = FIND / "plots" / "BUYER_ENTRY_EXIT_pullback.png"
    fig.savefig(out, dpi=150); plt.close(fig)
    print(f"plot -> {out}")


if __name__ == "__main__":
    raise SystemExit(main())
