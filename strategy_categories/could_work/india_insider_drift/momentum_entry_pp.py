#!/usr/bin/env python3
"""momentum_entry_pp.py — wait for momentum before entering (don't take every cluster).

Entry (changed): a cluster ARMS the stock; we only BUY when price confirms momentum:
    close > prior 252-session high  AND  close > EMA50 > EMA200
    AND  close >= disclosure_close x (1 + min_rise)
  (persistent watch, up to 126 sessions; skip if it never confirms.)

Exit (kept): profit-lock (arm .15 / stop .25 / wait 3) + full regime gate.

Grid-searches min_rise on the CLUSTER signal; random-catalyst control uses the SAME
entry + exit rule on shuffled dates (matched count per stock).
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
from exit_optimize import portfolio, metrics, FIND
from profit_protect import exit_pp
from regime_gate import gated

COST = base.COST


def build(prices):
    cal = pd.DatetimeIndex(sorted(set().union(*(set(p.index) for p in prices.values()))))
    S = {}
    for s, p in prices.items():
        c = p.close
        S[s] = dict(c=c.to_numpy(float), o=p.open.to_numpy(float),
                    ema20=c.ewm(20, adjust=False).mean().to_numpy(float),
                    ema50=c.ewm(50, adjust=False).mean().to_numpy(float),
                    ema200=c.ewm(200, adjust=False).mean().to_numpy(float),
                    ph=c.rolling(252).max().shift(1).to_numpy(float),
                    g=np.asarray(cal.searchsorted(p.index)))
    return S, cal


def find_entry(sd, ref_i, min_rise, max_wait=126):
    c = sd["c"]
    e50, e200, ph = sd["ema50"], sd["ema200"], sd["ph"]
    ref = c[ref_i]
    if not (np.isfinite(ref) and ref > 0):
        return None
    hi = min(ref_i + max_wait, len(c) - 2)
    for i in range(ref_i, hi):
        if (np.isfinite(ph[i]) and c[i] > ph[i]
                and c[i] > e50[i] > e200[i]
                and c[i] >= ref * (1 + min_rise)):
            return i + 1
    return None


def entry_pullback(sd, ref_i, min_rise=0.10, max_wait=126, pb_wait=20):
    """Wait for the breakout, then buy the first dip to EMA20 while still > EMA200."""
    c = sd["c"]
    e50, e200, ph, ema20 = sd["ema50"], sd["ema200"], sd["ph"], sd["ema20"]
    ref = c[ref_i]
    if not (np.isfinite(ref) and ref > 0):
        return None
    hi = min(ref_i + max_wait, len(c) - 2)
    br = None
    for i in range(ref_i, hi):
        if (np.isfinite(ph[i]) and c[i] > ph[i] and c[i] > e50[i] > e200[i]
                and c[i] >= ref * (1 + min_rise)):
            br = i
            break
    if br is None:
        return None
    for j in range(br + 1, min(br + 1 + pb_wait, hi)):
        if c[j] <= ema20[j] and c[j] > e200[j]:
            return j + 1
    return None


def simulate_pullback(catalysts, prices, S, min_rise=0.10):
    last, trades = {}, []
    for row in catalysts.sort_values("signal_date").itertuples():
        sd = S.get(row.symbol)
        if sd is None:
            continue
        px = prices[row.symbol]
        idx = px.index
        ref_i = idx.searchsorted(row.signal_date)
        ei = entry_pullback(sd, ref_i, min_rise)
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


def simulate(catalysts, prices, S, min_rise, A=0.15, S_pct=0.25, W_far=3, max_wait=126):
    last = {}
    trades = []
    for row in catalysts.sort_values("signal_date").itertuples():
        sd = S.get(row.symbol)
        if sd is None:
            continue
        px = prices[row.symbol]
        idx = px.index
        ref_i = idx.searchsorted(row.signal_date)
        ei = find_entry(sd, ref_i, min_rise, max_wait)
        if ei is None or ei + 1 >= len(idx):
            continue
        if row.symbol in last and ei <= last[row.symbol]:
            continue
        xi = exit_pp(sd, ei, A, S_pct, W_far)
        if xi <= ei or xi >= len(idx):
            continue
        trades.append((row.symbol, int(ei), int(xi)))
        last[row.symbol] = xi
    return trades


def run(catalysts, prices, S, cal, gate_arr, min_rise, n_ctrl=20, seed=base.SEED):
    trades = gated(simulate(catalysts, prices, S, min_rise), S, gate_arr, "full")
    n = len(trades)
    if n == 0:
        return {"n": 0}
    daily, exposure = portfolio(trades, S, cal, COST)
    rets = np.array([prices[s].open.iloc[xi] / prices[s].open.iloc[ei] - 1 - COST
                     for s, ei, xi in trades])
    m = metrics(daily)

    by = {}
    for sym in catalysts.symbol:
        by[sym] = by.get(sym, 0) + 1
    rng = np.random.default_rng(seed)
    ctrl_sh = np.empty(n_ctrl)
    for it in range(n_ctrl):
        rows = []
        for sym, k in by.items():
            px = prices[sym]
            elig = px.index[base.MIN_HISTORY_SESSIONS:-2]
            if len(elig) == 0:
                continue
            for d in rng.choice(elig.to_numpy(), size=k, replace=k > len(elig)):
                rows.append((sym, pd.Timestamp(d)))
        pseudo = pd.DataFrame(rows, columns=["symbol", "signal_date"])
        ct = gated(simulate(pseudo, prices, S, min_rise), S, gate_arr, "full")
        if not ct:
            ctrl_sh[it] = 0.0
            continue
        cd, _ = portfolio(ct, S, cal, COST)
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
    nifty = bench.reindex(cal, method="ffill")
    ma = bench.rolling(200).mean().reindex(cal, method="ffill")
    gate_arr = np.roll((nifty > ma).to_numpy(), 1)
    gate_arr[0] = True

    print("CLUSTER -> wait for momentum -> profit-lock exit -> full gate:\n")
    hdr = (f"{'min_rise':10}{'n':>5}{'win':>6}{'mean':>8}{'CAGR':>8}{'Sharpe':>8}"
           f"{'maxDD':>8}{'exp':>6}{'ctrlSh':>8}{'p':>7}")
    print(hdr); print("-" * len(hdr))
    results = {}
    for mr in (0.00, 0.05, 0.10, 0.20):
        r = run(cluster, prices, S, cal, gate_arr, mr)
        key = f"rise{mr:.2f}"
        results[key] = {k: v for k, v in r.items() if k != "_daily"}
        if r["n"] == 0:
            print(f"{key:10}  no trades")
            continue
        print(f"{key:10}{r['n']:>5}{r['win']:>6.3f}{r['mean']*100:>7.2f}%"
              f"{r['cagr']*100:>7.2f}%{r['sharpe']:>8.2f}{r['maxdd']*100:>7.1f}%"
              f"{r['exposure']*100:>5.1f}%{r['ctrl_sharpe_median']:>8.2f}{r['p_sharpe']:>7.3f}")

    try:
        plots = FIND / "plots"
        plots.mkdir(exist_ok=True)
        fig, ax = plt.subplots(figsize=(13, 7))
        for mr, col in ((0.00, "#888"), (0.05, "#17964b"), (0.10, "#8e3a9c")):
            d = run(cluster, prices, S, cal, gate_arr, mr, n_ctrl=1)["_daily"]
            ax.plot((1 + d).cumprod().index, (1 + d).cumprod(), lw=1.5, color=col,
                    label=f"min_rise={mr}")
        nb = bench.reindex(cal, method="ffill").dropna()
        ax.plot(nb.index, nb / nb.iloc[0], ls=":", color="#b3261e", lw=1.0, label="NIFTY")
        off = ~gate_arr
        ax.fill_between(cal, off.astype(float), color="#d62727", alpha=0.07, lw=0)
        ax.set_yscale("log")
        ax.set_title("Wait-for-momentum entry (cluster -> breakout+trend -> profit-lock + gate)")
        ax.set_ylabel("growth of Rs 1"); ax.grid(alpha=0.25); ax.legend(fontsize=9)
        fig.tight_layout(); fig.savefig(plots / "momentum_entry_pp.png", dpi=150); plt.close(fig)
        print(f"\nplot -> {plots / 'momentum_entry_pp.png'}")
    except Exception as exc:
        print(f"plot warning: {exc}")

    (FIND / "momentum_entry_pp.json").write_text(
        json.dumps(results, indent=2, default=float) + "\n")
    print(f"wrote {FIND / 'momentum_entry_pp.json'}")


if __name__ == "__main__":
    raise SystemExit(main())
