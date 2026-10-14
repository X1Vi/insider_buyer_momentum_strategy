#!/usr/bin/env python3
"""plot_momentum_trades.py — visualise the wait-for-momentum ENTRY.

Per-stock: insider buy dates, cluster completion (arms the watch), then the momentum
ENTRY (breakout + close>EMA50>EMA200) which happens LATER — the gap is the wait — and
the profit-lock EXIT. Plus a comparison equity + underwater chart:
  "take every cluster"  vs  "wait for momentum (min_rise 0 / 10%)".
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
from profit_protect import exit_pp
from regime_gate import gated
from exit_optimize import portfolio, metrics, FIND

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
    off = pd.Series(~gate_arr, index=cal)

    buys = ev[ev.personCategory.isin(MAJOR) & (ev.value >= 1e6) & ev.is_equity]

    # ---- per-stock charts (wait for momentum, min_rise = 0.10) ----
    mr = 0.10
    trades = gated(mep.simulate(cluster, prices, S, mr), S, gate_arr, "full")
    cnt = pd.Series([t[0] for t in trades]).value_counts()
    out = FIND / "plots" / "momentum_trades"
    out.mkdir(parents=True, exist_ok=True)
    for sym in cnt.head(8).index:
        px = prices[sym]
        c = px.close
        ema50 = c.ewm(50, adjust=False).mean()
        ema200 = c.ewm(200, adjust=False).mean()
        fig, ax = plt.subplots(figsize=(15, 6.5))
        offs = off.reindex(px.index, method="ffill").fillna(False)
        ax.fill_between(px.index, 0, 1, where=offs.to_numpy(),
                        transform=ax.get_xaxis_transform(), color="#d62727",
                        alpha=0.06, lw=0, label="risk-off (cash)")
        ax.plot(px.index, c, color="#333", lw=0.9, label="close")
        ax.plot(px.index, ema50, color="#3b73b9", lw=0.9, label="EMA50")
        ax.plot(px.index, ema200, color="#b58b3c", lw=0.9, label="EMA200")
        b = buys[buys.symbol == sym]
        ax.scatter(b.trade_date, c.reindex(b.trade_date, method="nearest"),
                   marker="v", s=55, color="#2ca02c", edgecolor="white", lw=0.4,
                   zorder=5, label="insider BUY (order date)")
        cs = cluster[cluster.symbol == sym]
        ax.scatter(cs.signal_date, c.reindex(cs.signal_date, method="nearest"),
                   marker="D", s=40, color="#fdae61", edgecolor="white", lw=0.4,
                   zorder=5, label="cluster (arms watch)")
        first = {"e": True, "x": True}
        for _, ei, xi in [t for t in trades if t[0] == sym]:
            ax.scatter(px.index[ei], px.open.iloc[ei], marker="^", s=130,
                       color="#00c853", edgecolor="black", lw=0.6, zorder=7,
                       label="momentum ENTRY" if first["e"] else None)
            ax.scatter(px.index[xi], px.open.iloc[xi], marker="x", s=85,
                       color="#d62728", lw=1.8, zorder=7,
                       label="EXIT (profit-lock)" if first["x"] else None)
            first["e"] = first["x"] = False
        ax.set_title(f"{sym} — wait for momentum (cluster ◆ -> breakout ▲ -> exit ✕)  "
                     f"{len([t for t in trades if t[0]==sym])} trades")
        ax.set_ylabel("price"); ax.grid(alpha=0.2); ax.legend(fontsize=8, loc="best", ncol=2)
        fig.tight_layout(); fig.savefig(out / f"{sym}.png", dpi=150); plt.close(fig)
    print(f"per-stock charts -> {out}  ({min(8, len(cnt))} symbols)")

    # ---- comparison equity + underwater ----
    fig, (ax, ax2) = plt.subplots(2, 1, figsize=(13, 11), sharex=True)
    for a in (ax, ax2):
        a.fill_between(cal, off.astype(float), color="#d62727", alpha=0.07, lw=0)
        a.axvline(base.SPLIT, color="black", ls=":", lw=1.0)
    # take-every-cluster baseline (no momentum wait): profit-lock + gate
    tr_base = gated([(s, e, exit_pp(S[s], e, 0.15, 0.25, 3))
                     for row in cluster.sort_values("signal_date").itertuples()
                     if (s := row.symbol) in S
                     and (e := prices[s].index.searchsorted(row.signal_date)) < len(prices[s]) - 2],
                    S, gate_arr, "full")
    for label, tr, col, ls in (
        ("take every cluster (no wait)", tr_base, "#888", "-"),
        ("wait for momentum, min_rise 0%", gated(mep.simulate(cluster, prices, S, 0.00), S, gate_arr, "full"), "#1f77b4", "-"),
        ("wait for momentum, min_rise 10%", gated(mep.simulate(cluster, prices, S, 0.10), S, gate_arr, "full"), "#8e3a9c", "-"),
    ):
        d, _ = portfolio(tr, S, cal, COST)
        eq = (1 + d).cumprod()
        ax.plot(eq.index, eq, lw=1.5, ls=ls, color=col, label=label)
        ax2.plot(eq.index, eq / eq.cummax() - 1, lw=1.4, ls=ls, color=col, label=label)
    nb = bench.reindex(cal, method="ffill").dropna()
    ax.plot(nb.index, nb / nb.iloc[0], ls=":", color="#b3261e", lw=1.0, label="NIFTY")
    ax2.plot(nb.index, nb / nb.cummax() - 1, ls=":", color="#b3261e", lw=1.0, label="NIFTY")
    ax.set_yscale("log"); ax.set_title("Wait-for-momentum entry vs take-every-cluster (both: profit-lock + gate)")
    ax.set_ylabel("growth of Rs 1"); ax.grid(alpha=0.25); ax.legend(fontsize=8)
    ax2.set_title("Underwater drawdown"); ax2.set_ylabel("drawdown")
    ax2.set_ylim(-0.6, 0.05); ax2.grid(alpha=0.25); ax2.legend(fontsize=8)
    fig.tight_layout()
    cmp = FIND / "plots" / "momentum_entry_compare.png"
    fig.savefig(cmp, dpi=150); plt.close(fig)
    print(f"comparison -> {cmp}")


if __name__ == "__main__":
    raise SystemExit(main())
