#!/usr/bin/env python3
"""entry_refine.py — kill the "buy the top, exit the bottom" losers.

Entry variants (exit unchanged: profit-lock .15/.25/3 + full regime gate):
  breakout   : first bar with close > prior 252-high & close>EMA50>EMA200 (baseline)
  buf2/buf3  : same but require close > prior_high x 1.02 / 1.03 (clear break)
  chase_cap  : breakout, but only if not overextended (close <= EMA50 x 1.10
               AND close <= prior_high x 1.03) — don't buy the impulse top
  pullback   : wait for the breakout, THEN buy the first dip back to EMA20
               (while still above EMA200) — buy the pullback, not the high
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
import momentum_entry_pp as mep
from profit_protect import exit_pp
from regime_gate import gated
from exit_optimize import portfolio, metrics, FIND

COST = base.COST


def entry(sd, ref_i, min_rise, mode, max_wait=126):
    c = sd["c"]
    e50, e200, ph = sd["ema50"], sd["ema200"], sd["ph"]
    ema20 = sd["ema20"]
    ref = c[ref_i]
    if not (np.isfinite(ref) and ref > 0):
        return None
    hi = min(ref_i + max_wait, len(c) - 2)

    def confirmed(i, buf=0.0):
        return (np.isfinite(ph[i]) and c[i] > ph[i] * (1 + buf)
                and c[i] > e50[i] > e200[i] and c[i] >= ref * (1 + min_rise))

    if mode == "breakout":
        for i in range(ref_i, hi):
            if confirmed(i):
                return i + 1
    elif mode == "buf2":
        for i in range(ref_i, hi):
            if confirmed(i, 0.02):
                return i + 1
    elif mode == "buf3":
        for i in range(ref_i, hi):
            if confirmed(i, 0.03):
                return i + 1
    elif mode == "chase_cap":
        for i in range(ref_i, hi):
            if confirmed(i) and c[i] <= e50[i] * 1.10 and c[i] <= ph[i] * 1.03:
                return i + 1
    elif mode == "pullback":
        br = None
        for i in range(ref_i, hi):
            if confirmed(i):
                br = i
                break
        if br is None:
            return None
        for j in range(br + 1, min(br + 1 + 20, hi)):
            if c[j] <= ema20[j] and c[j] > e200[j]:
                return j + 1
        return None
    return None


def simulate(catalysts, prices, S, min_rise, mode):
    last = {}
    trades = []
    for row in catalysts.sort_values("signal_date").itertuples():
        sd = S.get(row.symbol)
        if sd is None:
            continue
        px = prices[row.symbol]
        idx = px.index
        ref_i = idx.searchsorted(row.signal_date)
        ei = entry(sd, ref_i, min_rise, mode)
        if ei is None or ei + 1 >= len(idx):
            continue
        if row.symbol in last and ei <= last[row.symbol]:
            continue
        xi = exit_pp(sd, ei, 0.15, 0.25, 3)
        if xi <= ei or xi >= len(idx):
            continue
        trades.append((row.symbol, int(ei), int(xi)))
        last[row.symbol] = xi
    return trades


def run(catalysts, prices, S, cal, gate_arr, min_rise, mode):
    trades = gated(simulate(catalysts, prices, S, min_rise, mode), S, gate_arr, "full")
    n = len(trades)
    if n == 0:
        return {"n": 0}
    daily, exposure = portfolio(trades, S, cal, COST)
    rets = np.array([prices[s].open.iloc[xi] / prices[s].open.iloc[ei] - 1 - COST
                     for s, ei, xi in trades])
    m = metrics(daily)
    return dict(n=n, win=float((rets > 0).mean()), mean=float(rets.mean()),
                exposure=exposure, **m,
                _daily=daily, _trades=trades, _rets=rets)


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

    print("CLUSTER -> momentum entry variants -> profit-lock exit -> full gate:\n")
    hdr = (f"{'mode/min_rise':20}{'n':>5}{'win':>6}{'mean':>8}{'CAGR':>8}{'Sharpe':>8}"
           f"{'maxDD':>8}{'exp':>6}")
    print(hdr); print("-" * len(hdr))
    results = {}
    for mr in (0.10,):
        for mode in ("breakout", "buf2", "buf3", "chase_cap", "pullback"):
            r = run(cluster, prices, S, cal, gate_arr, mr, mode)
            key = f"{mode}@{mr:.2f}"
            results[key] = {k: v for k, v in r.items() if k not in ("_daily", "_trades", "_rets")}
            print(f"{key:20}{r['n']:>5}{r['win']:>6.3f}{r['mean']*100:>7.2f}%"
                  f"{r['cagr']*100:>7.2f}%{r['sharpe']:>8.2f}{r['maxdd']*100:>7.1f}%"
                  f"{r['exposure']*100:>5.1f}%")

    # trade-level: which entry mode has the smallest share of "big losers" (net < -15%)
    print("\nTrade tails (fraction of trades worse than -10% / -20%):")
    for key in results:
        r = run(cluster, prices, S, cal, gate_arr, float(key.split("@")[1]), key.split("@")[0])
        rets = r["_rets"]
        print(f"  {key:20} n={r['n']:3}  P(net<-10%)={(rets<-0.10).mean():.3f}  "
              f"P(net<-20%)={(rets<-0.20).mean():.3f}  worst={rets.min()*100:+.0f}%")

    # plot the two best
    try:
        plots = FIND / "plots"
        plots.mkdir(exist_ok=True)
        fig, ax = plt.subplots(figsize=(13, 7))
        for key, col in (("breakout@0.10", "#888"), ("chase_cap@0.10", "#1f77b4"),
                         ("pullback@0.10", "#17964b")):
            r = run(cluster, prices, S, cal, gate_arr, 0.10, key.split("@")[0])
            eq = (1 + r["_daily"]).cumprod()
            ax.plot(eq.index, eq, lw=1.5, color=col, label=key)
        nb = bench.reindex(cal, method="ffill").dropna()
        ax.plot(nb.index, nb / nb.iloc[0], ls=":", color="#b3261e", lw=1.0, label="NIFTY")
        off = ~gate_arr
        ax.fill_between(cal, off.astype(float), color="#d62727", alpha=0.07, lw=0)
        ax.set_yscale("log")
        ax.set_title("Entry refinement: breakout vs chase-cap vs pullback (profit-lock + gate)")
        ax.set_ylabel("growth of Rs 1"); ax.grid(alpha=0.25); ax.legend(fontsize=9)
        fig.tight_layout(); fig.savefig(plots / "entry_refine.png", dpi=150); plt.close(fig)
        print(f"\nplot -> {plots / 'entry_refine.png'}")
    except Exception as exc:
        print(f"plot warning: {exc}")

    (FIND / "entry_refine.json").write_text(json.dumps(results, indent=2, default=float) + "\n")
    print(f"wrote {FIND / 'entry_refine.json'}")


if __name__ == "__main__":
    raise SystemExit(main())
