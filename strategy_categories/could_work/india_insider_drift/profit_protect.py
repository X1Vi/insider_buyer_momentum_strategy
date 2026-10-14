#!/usr/bin/env python3
"""profit_protect.py — distance-to-stop, profit-protecting exit.

Rule (all close-confirmed, exit next open):
  * big trailing stop : stop = peak_close x (1 - S)   (peak = running max since entry)
  * arm once peak >= entry_open x (1 + A)             ("we have some profit")
  * when armed and a downtrend bar appears (close < EMA20):
        buffer = (close - stop) / close               # how far we are from the stop
        if buffer is small (near stop) -> exit in 1 session   (protect the profit)
        if buffer is large (far from stop) -> wait W_far more sessions (more risk capacity)
  * cap 250 sessions.

Grid-searches (A, S, W_far) on the CLUSTER signal, fully invested, to minimise
drawdown while keeping return.  Random-entry control uses the same rule.
"""
from __future__ import annotations

import json
import math

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import cluster_and_fast as base
import cluster_advantage as ca
from exit_optimize import portfolio, metrics, FIND

COST = base.COST


def build(prices):
    cal = pd.DatetimeIndex(sorted(set().union(*(set(p.index) for p in prices.values()))))
    S = {}
    for s, p in prices.items():
        S[s] = dict(c=p.close.to_numpy(float), o=p.open.to_numpy(float),
                    ema20=p.close.ewm(20, adjust=False).mean().to_numpy(float),
                    g=np.asarray(cal.searchsorted(p.index)))
    return S, cal


def exit_pp(sd, ei, A, S_pct, W_far, cap=250):
    c = sd["c"]
    o = sd["o"]
    ema = sd["ema20"]
    entry = o[ei]
    peak = c[ei]
    armed = False
    scheduled = None
    end = min(ei + cap, len(c) - 1)
    for i in range(ei, end + 1):
        if c[i] > peak:
            peak = c[i]
        stop = peak * (1 - S_pct)
        if i > ei and c[i] <= stop:
            return i + 1
        if not armed and peak >= entry * (1 + A):
            armed = True
        if armed and c[i] < ema[i] and scheduled is None:
            buffer = (c[i] - stop) / c[i] if c[i] > 0 else 0.0
            k = 1 if buffer < S_pct * 0.5 else W_far
            scheduled = i + k
        if scheduled is not None and i >= scheduled:
            return min(i + 1, end)
    return end


def simulate(signals, prices, S, A, S_pct, W_far):
    last = {}
    trades = []
    for row in signals.sort_values("signal_date").itertuples():
        sd = S.get(row.symbol)
        if sd is None:
            continue
        px = prices[row.symbol]
        idx = px.index
        e = idx.searchsorted(row.signal_date)
        if e < len(idx) and idx[e] == row.signal_date:
            e += 1
        if e + 1 >= len(idx):
            continue
        if row.symbol in last and e <= last[row.symbol]:
            continue
        xi = exit_pp(sd, e, A, S_pct, W_far)
        if xi <= e or xi >= len(idx):
            continue
        trades.append((row.symbol, int(e), int(xi)))
        last[row.symbol] = xi
    return trades


def run(signals, prices, S, cal, A, S_pct, W_far, n_ctrl=20, seed=base.SEED):
    trades = simulate(signals, prices, S, A, S_pct, W_far)
    n = len(trades)
    if n == 0:
        return {"n": 0}
    daily, exposure = portfolio(trades, S, cal, COST)
    rets = np.array([prices[s].open.iloc[xi] / prices[s].open.iloc[ei] - 1 - COST
                     for s, ei, xi in trades])
    m = metrics(daily)

    by = {}
    for s, _, _ in trades:
        by[s] = by.get(s, 0) + 1
    rng = np.random.default_rng(seed)
    ctrl_sh = np.empty(n_ctrl)
    for it in range(n_ctrl):
        c_trades = []
        for s, k in by.items():
            sd = S[s]
            elig = np.arange(base.MIN_HISTORY_SESSIONS, len(prices[s]) - 2)
            if len(elig) == 0:
                continue
            for ei in rng.choice(elig, size=k, replace=k > len(elig)):
                xi = exit_pp(sd, int(ei), A, S_pct, W_far)
                if xi > int(ei) and xi < len(prices[s]):
                    c_trades.append((s, int(ei), int(xi)))
        cd, _ = portfolio(c_trades, S, cal, COST)
        ctrl_sh[it] = metrics(cd)["sharpe"]
    return dict(n=n, win=float((rets > 0).mean()), mean=float(rets.mean()),
                exposure=exposure, **m,
                ctrl_sharpe_median=float(np.median(ctrl_sh)),
                p_sharpe=float((ctrl_sh >= m["sharpe"]).mean()),
                _daily=daily)


def main():
    events = base.load_events()
    prices = base.load_prices()
    bench = base.load_bench()
    ev = events[events.symbol.isin(prices)]
    cluster = ca.cluster_events(ev, 30, 2, 1e6, 20)[["symbol", "signal_date"]]
    S, cal = build(prices)

    print("CLUSTER, fully invested — profit-protect exit grid (A=arm, S=stop, W=wait):\n")
    hdr = (f"{'A/S/W':14}{'n':>5}{'win':>6}{'mean':>8}{'CAGR':>8}{'Sharpe':>8}"
           f"{'maxDD':>8}{'exp':>6}{'ctrlSh':>8}{'p':>7}")
    print(hdr); print("-" * len(hdr))
    results = {}
    for A in (0.05, 0.10, 0.15):
        for S_pct in (0.20, 0.25, 0.30):
            for W_far in (2, 3):
                r = run(cluster, prices, S, cal, A, S_pct, W_far)
                key = f"{A:.2f}/{S_pct:.2f}/{W_far}"
                results[key] = {k: v for k, v in r.items() if k != "_daily"}
                print(f"{key:14}{r['n']:>5}{r['win']:>6.3f}{r['mean']*100:>7.2f}%"
                      f"{r['cagr']*100:>7.2f}%{r['sharpe']:>8.2f}{r['maxdd']*100:>7.1f}%"
                      f"{r['exposure']*100:>5.1f}%{r['ctrl_sharpe_median']:>8.2f}{r['p_sharpe']:>7.3f}")

    ranked = sorted(results.items(),
                    key=lambda kv: (kv[1]["sharpe"] - 0.7 * abs(kv[1]["maxdd"])), reverse=True)
    print("\nTop 6 by (Sharpe - 0.7*|maxDD|):")
    for key, r in ranked[:6]:
        print(f"  {key:14} CAGR {r['cagr']*100:6.2f}% Sharpe {r['sharpe']:.2f} "
              f"maxDD {r['maxdd']*100:6.1f}% win {r['win']:.3f} n {r['n']}")

    (FIND / "profit_protect.json").write_text(json.dumps(results, indent=2, default=float) + "\n")
    print(f"wrote {FIND / 'profit_protect.json'}")


if __name__ == "__main__":
    raise SystemExit(main())
