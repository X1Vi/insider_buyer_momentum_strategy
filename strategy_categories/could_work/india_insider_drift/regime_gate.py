#!/usr/bin/env python3
"""regime_gate.py — is the drawdown systemic?  Gate the cluster book by Nifty's
200-day trend and PLOT where the losses actually come from.

Gate: risk-ON only when NIFTY (previous session) > its 200-day MA; risk-OFF = cash.
Two modes: 'entry' (no new positions when risk-off) and 'full' (also liquidate any
open position at the first risk-off day's open).

Produces three plots that make the answer visible:
  1. underwater drawdown of the UNGATED cluster book vs Nifty (they dive together)
  2. equity: ungated vs entry-gated vs full-gated vs Nifty (log), bear periods shaded
  3. per-trade net return vs entry date, coloured by regime at entry
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import cluster_and_fast as base
import cluster_advantage as ca
from exit_optimize import build, portfolio, metrics, exit_for, FIND

COST = base.COST


def cluster_trades(cluster, prices, S, rule):
    last = {}
    trades = []
    for row in cluster.sort_values("signal_date").itertuples():
        sd = S.get(row.symbol)
        if sd is None:
            continue
        px = prices[row.symbol]
        idx = px.index
        e = idx.searchsorted(row.signal_date)
        if e < len(idx) and idx[e] == row.signal_date:
            e += 1
        if e + 1 >= len(idx) or (row.symbol in last and e <= last[row.symbol]):
            continue
        xi = exit_for(sd, e, rule)
        if xi <= e or xi >= len(idx):
            continue
        trades.append((row.symbol, int(e), int(xi)))
        last[row.symbol] = xi
    return trades


def gated(trades, S, gate_arr, mode):
    out = []
    for sym, ei, xi in trades:
        g = S[sym]["g"]
        if not gate_arr[g[ei]]:
            continue
        if mode == "full":
            for d in range(ei + 1, xi + 1):
                if not gate_arr[g[d]]:
                    xi = d
                    break
        out.append((sym, ei, xi))
    return out


def main():
    events = base.load_events()
    prices = base.load_prices()
    bench = base.load_bench()
    ev = events[events.symbol.isin(prices)]
    cluster = ca.cluster_events(ev, 30, 2, 1e6, 20)[["symbol", "signal_date"]]
    S, cal = build(prices)

    # gate: previous session's Nifty vs 200-DMA decides today's exposure
    nifty = bench.reindex(cal, method="ffill")
    ma = bench.rolling(200).mean().reindex(cal, method="ffill")
    gate_today = (nifty > ma).to_numpy()
    gate_arr = np.roll(gate_today, 1)
    gate_arr[0] = True

    results = {}
    plots = FIND / "plots"
    plots.mkdir(exist_ok=True)

    # ---- rules to compare ----
    rules = [("hold", 250), ("trail", 0.20)]
    colors = {("hold", 250): "#1f77b4", ("trail", 0.20): "#17964b"}

    fig, ax = plt.subplots(figsize=(13, 7))
    fig2, ax2 = plt.subplots(figsize=(13, 7))

    # bear shading (risk-off) for both plots
    for a in (ax, ax2):
        off = ~gate_arr
        a.fill_between(cal, off.astype(float), color="#d62727", alpha=0.08, lw=0)
        a.axvline(base.SPLIT, color="black", ls=":", lw=1.0)

    print(f"{'rule':12}{'mode':10}{'n':>5}{'win':>6}{'CAGR':>8}{'Sharpe':>8}{'maxDD':>9}")
    print("-" * 62)
    for rule in rules:
        trades = cluster_trades(cluster, prices, S, rule)
        for mode in ("ungated", "entry", "full"):
            tr = trades if mode == "ungated" else gated(trades, S, gate_arr, mode)
            if not tr:
                continue
            daily, _ = portfolio(tr, S, cal, COST)
            m = metrics(daily)
            rets = np.array([prices[s].open.iloc[xi] / prices[s].open.iloc[ei] - 1 - COST
                             for s, ei, xi in tr])
            key = f"{rule[0]}{rule[1] if len(rule)>1 else ''}_{mode}"
            results[key] = dict(n=len(tr), win=float((rets > 0).mean()), **m)
            print(f"{rule[0]+str(rule[1] if len(rule)>1 else ''):12}{mode:10}"
                  f"{len(tr):>5}{(rets > 0).mean():>6.3f}{m['cagr']*100:>7.2f}%"
                  f"{m['sharpe']:>8.2f}{m['maxdd']*100:>8.1f}%")
            if mode != "ungated":
                continue
            eq = (1 + daily).cumprod()
            color = colors[rule]
            ax.plot(eq.index, eq, lw=1.5, color=color,
                    label=f"cluster {rule[0]}{rule[1] if len(rule)>1 else ''} ungated")
            ax2.plot(eq.index, eq / eq.cummax() - 1, lw=1.4, color=color,
                     label=f"cluster {rule[0]}{rule[1] if len(rule)>1 else ''} drawdown")

    # full-gated variants onto the equity plot (hold250 full as the headline)
    trades = cluster_trades(cluster, prices, S, ("hold", 250))
    for mode, ls, lab in (("entry", "--", "hold250 + entry gate (cash when Nifty<200DMA)"),
                          ("full", "-.", "hold250 + full gate (liquidate on risk-off)")):
        tr = gated(trades, S, gate_arr, mode)
        d, _ = portfolio(tr, S, cal, COST)
        eq = (1 + d).cumprod()
        ax.plot(eq.index, eq, lw=1.4, ls=ls, color="#8e3a9c", label=lab)

    # Nifty on equity plot + Nifty drawdown on underwater plot
    nb = bench.reindex(cal, method="ffill").dropna()
    ax.plot(nb.index, nb / nb.iloc[0], lw=1.0, ls=":", color="#b3261e", label="NIFTY buy&hold")
    ax2.plot(nb.index, nb / nb.cummax() - 1, lw=1.0, ls=":", color="#b3261e",
             label="NIFTY drawdown")

    ax.set_yscale("log")
    ax.set_title("Cluster book (hold 250) — ungated vs regime-gated (red = Nifty below 200-DMA)")
    ax.set_ylabel("growth of Rs 1"); ax.grid(alpha=0.25); ax.legend(fontsize=8)
    fig.tight_layout(); fig.savefig(plots / "regime_gate_equity.png", dpi=150); plt.close(fig)

    ax2.set_title("Underwater — the drawdown is the same crash as Nifty's (systemic)")
    ax2.set_ylabel("drawdown"); ax2.set_ylim(-0.65, 0.05); ax2.grid(alpha=0.25)
    ax2.legend(fontsize=8)
    fig2.tight_layout(); fig2.savefig(plots / "regime_gate_underwater.png", dpi=150)
    plt.close(fig2)

    # per-trade scatter coloured by regime at entry
    trades = cluster_trades(cluster, prices, S, ("hold", 250))
    xs, ys, cs = [], [], []
    for sym, ei, xi in trades:
        entry_date = prices[sym].index[ei]
        ret = prices[sym].open.iloc[xi] / prices[sym].open.iloc[ei] - 1 - COST
        xs.append(entry_date)
        ys.append(ret * 100)
        cs.append("risk-on" if gate_arr[S[sym]["g"][ei]] else "risk-off")
    dfa = pd.DataFrame({"date": xs, "ret": ys, "regime": cs})
    fig3, ax3 = plt.subplots(figsize=(13, 6))
    for regime, col in (("risk-on", "#17964b"), ("risk-off", "#d62727")):
        sub = dfa[dfa.regime == regime]
        ax3.scatter(sub.date, sub.ret, s=12, alpha=0.5, color=col, label=regime)
    ax3.axhline(0, color="#888", lw=0.8)
    ax3.set_title("Per-trade net return vs entry date, coloured by market regime at entry")
    ax3.set_ylabel("net return (%)"); ax3.grid(alpha=0.25); ax3.legend()
    fig3.tight_layout(); fig3.savefig(plots / "regime_gate_trades.png", dpi=150)
    plt.close(fig3)

    (FIND / "regime_gate.json").write_text(json.dumps(results, indent=2, default=float) + "\n")
    print(f"\nplots -> {plots / 'regime_gate_equity.png'}, {plots / 'regime_gate_underwater.png'}, "
          f"{plots / 'regime_gate_trades.png'}")
    print(f"wrote {FIND / 'regime_gate.json'}")


if __name__ == "__main__":
    raise SystemExit(main())
