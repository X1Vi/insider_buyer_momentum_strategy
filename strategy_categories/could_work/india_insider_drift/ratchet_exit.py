#!/usr/bin/env python3
"""ratchet_exit.py — profit-protection exit with a BIG hard stop, tuned by the numbers.

Rule (all close-confirmed, exit next open):
  * entry = next open after the cluster signal (unchanged)
  * hard stop  : if close <= entry_open x (1 - stop_pct)  -> exit   (big, lets it breathe)
  * profit lock: once close >= entry_open x (1 + arm_at) the trade is ARMED, then
                 trail from the running peak: exit when close <= peak x (1 - trail_pct)
  * cap 250 sessions

Grid-searches (arm_at, trail_pct, stop_pct) on the CLUSTER signal, fully invested,
vs the random-entry control (same rule), to find the combo that keeps the CAGR and
cuts the drawdown.
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
from exit_optimize import build, portfolio, metrics, FIND

COST = base.COST


def exit_ratchet(sd, ei, arm_at, trail_pct, stop_pct, cap=250):
    c = sd["c"]
    o = sd["o"]
    entry = o[ei]
    peak = c[ei]
    armed = False
    end = min(ei + cap, len(c) - 1)
    for i in range(ei, end + 1):
        if c[i] > peak:
            peak = c[i]
        if not armed and peak >= entry * (1 + arm_at):
            armed = True
        if armed:
            if c[i] <= peak * (1 - trail_pct):
                return i + 1
        else:
            if c[i] <= entry * (1 - stop_pct):
                return i + 1
    return end


def simulate(signals, prices, S, rule):
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
        xi = exit_ratchet(sd, e, *rule)
        if xi <= e or xi >= len(idx):
            continue
        trades.append((row.symbol, int(e), int(xi)))
        last[row.symbol] = xi
    return trades


def run(signals, prices, S, cal, rule, n_ctrl=20, seed=base.SEED):
    trades = simulate(signals, prices, S, rule)
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
                xi = exit_ratchet(sd, int(ei), *rule)
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

    grid = []
    for arm_at in (0.10, 0.20, 0.30):
        for trail_pct in (0.08, 0.10, 0.15):
            for stop_pct in (0.30, 0.40):
                grid.append((arm_at, trail_pct, stop_pct))

    print("CLUSTER signal, fully invested — ratchet exit grid:\n")
    hdr = (f"{'rule (arm/trail/stop)':26}{'n':>5}{'win':>6}{'mean':>8}{'CAGR':>8}"
           f"{'Sharpe':>8}{'maxDD':>8}{'exp':>6}{'ctrlSh':>8}{'p':>7}")
    print(hdr); print("-" * len(hdr))
    results = {}
    for rule in grid:
        r = run(cluster, prices, S, cal, rule)
        key = f"{rule[0]:.2f}/{rule[1]:.2f}/{rule[2]:.2f}"
        results[key] = {k: v for k, v in r.items() if k != "_daily"}
        print(f"{key:26}{r['n']:>5}{r['win']:>6.3f}{r['mean']*100:>7.2f}%"
              f"{r['cagr']*100:>7.2f}%{r['sharpe']:>8.2f}{r['maxdd']*100:>7.1f}%"
              f"{r['exposure']*100:>5.1f}%{r['ctrl_sharpe_median']:>8.2f}{r['p_sharpe']:>7.3f}")

    # rank by a simple objective: Sharpe with a drawdown penalty (prefer lower DD)
    ranked = sorted(results.items(),
                    key=lambda kv: (kv[1]["sharpe"] - 0.5 * abs(kv[1]["maxdd"])),
                    reverse=True)
    print("\nTop 5 by (Sharpe - 0.5*|maxDD|):")
    for key, r in ranked[:5]:
        print(f"  {key:16} CAGR {r['cagr']*100:6.2f}%  Sharpe {r['sharpe']:.2f}  "
              f"maxDD {r['maxdd']*100:6.1f}%  win {r['win']:.3f}  n {r['n']}")

    # baselines for reference
    from exit_optimize import exit_for
    for rule, tag in ((("hold", 250), "hold250"), (("trail", 0.20), "trail20")):
        trades = []
        last = {}
        for row in cluster.sort_values("signal_date").itertuples():
            sd = S.get(row.symbol)
            if sd is None:
                continue
            px = prices[row.symbol]; idx = px.index
            e = idx.searchsorted(row.signal_date)
            if e < len(idx) and idx[e] == row.signal_date:
                e += 1
            if e + 1 >= len(idx) or (row.symbol in last and e <= last[row.symbol]):
                continue
            xi = exit_for(sd, e, rule)
            if xi <= e or xi >= len(idx):
                continue
            trades.append((row.symbol, int(e), int(xi))); last[row.symbol] = xi
        d, _ = portfolio(trades, S, cal, COST)
        mm = metrics(d)
        print(f"baseline {tag:8}: CAGR {mm['cagr']*100:6.2f}% Sharpe {mm['sharpe']:.2f} "
              f"maxDD {mm['maxdd']*100:6.1f}% n={len(trades)}")

    # plot top-2 ratchet vs hold250
    try:
        plots = FIND / "plots"
        plots.mkdir(exist_ok=True)
        fig, ax = plt.subplots(figsize=(13, 7))
        for key in [ranked[0][0], ranked[1][0]]:
            arm, tr, st = (float(x) for x in key.split("/"))
            d = run(cluster, prices, S, cal, (arm, tr, st), n_ctrl=1)["_daily"]
            ax.plot((1 + d).cumprod().index, (1 + d).cumprod(), lw=1.5,
                    label=f"ratchet {key}")
        from exit_optimize import exit_for as ef
        trs = []
        last = {}
        for row in cluster.sort_values("signal_date").itertuples():
            sd = S.get(row.symbol)
            if sd is None:
                continue
            px = prices[row.symbol]; idx = px.index
            e = idx.searchsorted(row.signal_date)
            if e < len(idx) and idx[e] == row.signal_date:
                e += 1
            if e + 1 >= len(idx) or (row.symbol in last and e <= last[row.symbol]):
                continue
            xi = ef(sd, e, ("hold", 250))
            if xi <= e or xi >= len(idx):
                continue
            trs.append((row.symbol, int(e), int(xi))); last[row.symbol] = xi
        d250, _ = portfolio(trs, S, cal, COST)
        ax.plot((1 + d250).cumprod().index, (1 + d250).cumprod(), lw=1.2, ls="--",
                color="#888", label="hold 250 baseline")
        nb = bench.reindex((1 + d250).cumprod().index, method="ffill").dropna()
        ax.plot(nb.index, nb / nb.iloc[0], ls=":", color="#b3261e", lw=1.0, label="NIFTY")
        ax.axvline(base.SPLIT, color="black", ls=":", lw=1.0)
        ax.set_yscale("log"); ax.set_title("Cluster book — ratchet profit-lock exits vs hold-250")
        ax.set_ylabel("growth of Rs 1"); ax.grid(alpha=0.25); ax.legend(fontsize=9)
        fig.tight_layout(); fig.savefig(plots / "ratchet_exit.png", dpi=150); plt.close(fig)
        print(f"\nplot -> {plots / 'ratchet_exit.png'}")
    except Exception as exc:
        print(f"plot warning: {exc}")

    (FIND / "ratchet_exit.json").write_text(json.dumps(results, indent=2, default=float) + "\n")
    print(f"wrote {FIND / 'ratchet_exit.json'}")


if __name__ == "__main__":
    raise SystemExit(main())
