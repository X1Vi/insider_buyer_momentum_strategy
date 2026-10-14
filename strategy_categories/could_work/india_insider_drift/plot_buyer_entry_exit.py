#!/usr/bin/env python3
"""plot_buyer_entry_exit.py — per-stock charts showing:
  * the insider BUY dates (when the buyer placed the order, from trade_date)
  * the cluster completion (public disclosure date)
  * OUR entry and exit (under the best rule: trail-20% exit + full regime gate)
  * shaded bands = market risk-off (Nifty below 200-DMA) where we sit in cash
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import cluster_and_fast as base
import cluster_advantage as ca
from exit_optimize import FIND
import profit_protect as pp
from regime_gate import gated

COST = base.COST
MAJOR = base.MAJOR


def main():
    events = base.load_events()
    prices = base.load_prices()
    bench = base.load_bench()
    ev = events[events.symbol.isin(prices)]
    cluster = ca.cluster_events(ev, 30, 2, 1e6, 20)[["symbol", "signal_date"]]
    S, cal = pp.build(prices)

    nifty = bench.reindex(cal, method="ffill")
    ma = bench.rolling(200).mean().reindex(cal, method="ffill")
    gate_arr = np.roll((nifty > ma).to_numpy(), 1)
    gate_arr[0] = True

    # final rule: profit-lock exit (arm .15, stop .25, wait 3) + full regime gate
    trades = pp.simulate(cluster, prices, S, 0.15, 0.25, 3)
    trades = gated(trades, S, gate_arr, "full")

    # major insider buys per symbol (>= Rs10L) for the markers
    buys = ev[ev.personCategory.isin(MAJOR) & (ev.value >= 1e6) & ev.is_equity]

    cnt = pd.Series([t[0] for t in trades]).value_counts()
    out = FIND / "plots" / "buyer_entry_exit"
    out.mkdir(parents=True, exist_ok=True)

    for sym in cnt.head(8).index:
        px = prices[sym]
        c = px.close
        ema50 = c.ewm(50, adjust=False).mean()
        ema200 = c.ewm(200, adjust=False).mean()

        fig, ax = plt.subplots(figsize=(15, 6.5))
        # risk-off shading
        off = pd.Series(~gate_arr, index=cal).reindex(px.index, method="ffill").fillna(False)
        ax.fill_between(px.index, 0, 1, where=off.to_numpy(), transform=ax.get_xaxis_transform(),
                        color="#d62727", alpha=0.06, lw=0, label="risk-off (cash)")
        ax.plot(px.index, c, color="#333", lw=0.9, label="close")
        ax.plot(px.index, ema50, color="#3b73b9", lw=0.9, label="EMA50")
        ax.plot(px.index, ema200, color="#b58b3c", lw=0.9, label="EMA200")

        # insider buy dates
        b = buys[buys.symbol == sym]
        by = c.reindex(b.trade_date, method="nearest")
        ax.scatter(b.trade_date, by, marker="v", s=55, color="#2ca02c",
                   edgecolor="white", lw=0.4, zorder=5, label="insider BUY (order date)")

        # cluster completion (disclosure)
        cs = cluster[cluster.symbol == sym]
        cy = c.reindex(cs.signal_date, method="nearest")
        ax.scatter(cs.signal_date, cy, marker="D", s=40, color="#fdae61",
                   edgecolor="white", lw=0.4, zorder=5, label="cluster (public)")

        # our entry / exit
        first = {"e": True, "x": True}
        for _, ei, xi in [t for t in trades if t[0] == sym]:
            ax.scatter(px.index[ei], px.open.iloc[ei], marker="^", s=130, color="#00c853",
                       edgecolor="black", lw=0.6, zorder=7,
                       label="our ENTRY" if first["e"] else None)
            ax.scatter(px.index[xi], px.open.iloc[xi], marker="x", s=85, color="#d62728",
                       lw=1.8, zorder=7, label="our EXIT" if first["x"] else None)
            first["e"] = first["x"] = False

        ax.set_title(f"{sym} — insider buys vs our entry/exit  "
                     f"({len([t for t in trades if t[0]==sym])} trades, profit-lock + regime gate)")
        ax.set_ylabel("price"); ax.grid(alpha=0.2); ax.legend(fontsize=8, loc="best", ncol=2)
        fig.tight_layout(); fig.savefig(out / f"{sym}.png", dpi=150); plt.close(fig)

    print(f"charts -> {out}  ({min(8, len(cnt))} symbols)")
    print("symbols:", ", ".join(cnt.head(8).index))


if __name__ == "__main__":
    raise SystemExit(main())
