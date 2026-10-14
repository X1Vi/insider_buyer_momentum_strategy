#!/usr/bin/env python3
"""exit_optimize.py — keep the insider-buy ENTRY, optimize the EXIT to cut drawdown
while retaining profit.

Entry (unchanged): cluster (>=2 distinct insiders / 30d, >= Rs10L) or major buy
(>= Rs25L); buy next OPEN; fully invested (equal weight across open positions).

Exit rules tested (all close-confirmed, exit at the NEXT open — no look-ahead):
  hold H        : exit after H sessions
  trail pct     : exit when close <= (1-pct) x highest close since entry (cap 250)
  ema50         : exit when close <= EMA50 (cap 250)

Random-entry control uses the SAME exit rule on random dates (same count/stock).
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

FIND = base.FINDING_DIR
COST = base.COST


def build(prices):
    cal = pd.DatetimeIndex(sorted(set().union(*(set(p.index) for p in prices.values()))))
    S = {}
    for s, p in prices.items():
        S[s] = dict(c=p.close.to_numpy(float), o=p.open.to_numpy(float),
                    ema50=p.close.ewm(50, adjust=False).mean().to_numpy(float),
                    g=np.asarray(cal.searchsorted(p.index)))
    return S, cal


def exit_for(sd, ei, rule, cap_max=250):
    c = sd["c"]
    o = sd["o"]
    kind = rule[0]
    if kind == "hold":
        return ei + rule[1]
    if kind == "trail":
        pct = rule[1]
        peak = c[ei]
        for i in range(ei + 1, min(ei + cap_max, len(c))):
            if c[i] > peak:
                peak = c[i]
            if c[i] <= peak * (1 - pct):
                return i + 1
        return min(ei + cap_max, len(c) - 1)
    if kind == "ema50":
        ema = sd["ema50"]
        for i in range(ei + 1, min(ei + cap_max, len(c))):
            if c[i] <= ema[i]:
                return i + 1
        return min(ei + cap_max, len(c) - 1)
    raise ValueError(kind)


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
        xi = exit_for(sd, e, rule)
        if xi <= e or xi >= len(idx):
            continue
        trades.append((row.symbol, int(e), int(xi)))
        last[row.symbol] = xi
    return trades


def portfolio(trades, S, cal, cost):
    ret = np.zeros(len(cal))
    act = np.zeros(len(cal))
    for sym, ei, xi in trades:
        sd = S[sym]
        c, o, g = sd["c"], sd["o"], sd["g"]
        ret[g[ei]] += c[ei] / o[ei] - 1 - cost / 2
        act[g[ei]] += 1
        if xi > ei + 1:
            ret[g[ei + 1:xi]] += c[ei + 1:xi] / c[ei:xi - 1] - 1
            act[g[ei + 1:xi]] += 1
        ret[g[xi]] += o[xi] / c[xi - 1] - 1 - cost / 2
        act[g[xi]] += 1
    denom = np.where(act > 0, act, 1.0)
    return pd.Series(ret / denom, index=cal), float((act > 0).mean())


def metrics(daily):
    d = daily[daily != 0] if (daily != 0).sum() > 20 else daily
    sd = d.std(ddof=1)
    eq = (1 + d).cumprod()
    yrs = len(d) / 252
    return dict(cagr=float(eq.iloc[-1] ** (1 / yrs) - 1) if yrs > 0 else np.nan,
                vol=float(sd * math.sqrt(252)) if sd and sd > 0 else np.nan,
                sharpe=float(d.mean() / sd * math.sqrt(252)) if sd and sd > 0 else np.nan,
                maxdd=float((eq / eq.cummax() - 1).min()))


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
                xi = exit_for(sd, int(ei), rule)
                if xi > int(ei) and xi < len(prices[s]):
                    c_trades.append((s, int(ei), int(xi)))
        cd, _ = portfolio(c_trades, S, cal, COST)
        ctrl_sh[it] = metrics(cd)["sharpe"]
    return dict(n=n, win=float((rets > 0).mean()), mean=float(rets.mean()),
                exposure=exposure, **m,
                ctrl_sharpe_median=float(np.median(ctrl_sh)),
                p_sharpe=float((ctrl_sh >= m["sharpe"]).mean()),
                _daily=daily)


def plot_symbol_trades(sym, trades, cluster, prices, S, path):
    px = prices[sym]
    c = px.close
    ema50 = pd.Series(S[sym]["ema50"], index=px.index)
    fig, ax = plt.subplots(figsize=(15, 6.5))
    ax.plot(px.index, c, color="#333", lw=0.9, label="close")
    ax.plot(px.index, ema50, color="#3b73b9", lw=1.0, label="EMA50")
    cs = cluster[cluster.symbol == sym]
    cy = c.reindex(cs.signal_date, method="nearest")
    ax.scatter(cs.signal_date, cy, marker="D", s=42, color="#fdae61",
               edgecolor="white", lw=0.5, zorder=5, label="insider cluster (disclosure)")
    tr = [t for t in trades if t[0] == sym]
    first = {"entry": True, "exit": True}
    for _, ei, xi in tr:
        ax.scatter(px.index[ei], px.open.iloc[ei], marker="^", s=120, color="#17964b",
                   edgecolor="white", lw=0.5, zorder=6,
                   label="entry (next open)" if first["entry"] else None)
        ax.scatter(px.index[xi], px.open.iloc[xi], marker="x", s=80, color="#d62728",
                   lw=1.6, zorder=6, label="exit (next open)" if first["exit"] else None)
        first["entry"] = first["exit"] = False
    ax.set_title(f"{sym} — cluster signal, entries & exits ({len(tr)} trades)")
    ax.set_ylabel("price"); ax.grid(alpha=0.22); ax.legend(fontsize=8, loc="best")
    fig.tight_layout(); fig.savefig(path, dpi=150); plt.close(fig)


def main():
    events = base.load_events()
    prices = base.load_prices()
    bench = base.load_bench()
    ev = events[events.symbol.isin(prices)]
    cluster = ca.cluster_events(ev, 30, 2, 1e6, 20)[["symbol", "signal_date"]]
    major = pd.DataFrame([(sym, pd.Timestamp(dd))
                          for sym, g in ev[ev.value >= 2.5e6].groupby("symbol")
                          for dd in g.d.dropna().unique()],
                         columns=["symbol", "signal_date"])

    S, cal = build(prices)
    rules = [("hold", 20), ("hold", 40), ("hold", 60), ("hold", 90), ("hold", 120),
             ("trail", 0.10), ("trail", 0.15), ("trail", 0.20), ("trail", 0.25),
             ("ema50",)]

    print("CLUSTER signal (>=2 insiders / 30d), fully invested:\n")
    hdr = (f"{'exit':22}{'n':>5}{'win':>6}{'mean':>8}{'CAGR':>8}{'vol':>7}"
           f"{'Sharpe':>8}{'maxDD':>8}{'exp':>6}{'ctrlSh':>8}{'p(Sh)':>7}")
    print(hdr); print("-" * len(hdr))
    results = {}
    for rule in rules:
        r = run(cluster, prices, S, cal, rule)
        label = rule[0] + (str(rule[1]) if len(rule) > 1 else "")
        results[f"cluster_{label}"] = {k: v for k, v in r.items() if k != "_daily"}
        print(f"{label:22}{r['n']:>5}{r['win']:>6.3f}{r['mean']*100:>7.2f}%"
              f"{r['cagr']*100:>7.2f}%{r['vol']*100:>6.1f}%{r['sharpe']:>8.2f}"
              f"{r['maxdd']*100:>7.1f}%{r['exposure']*100:>5.1f}%"
              f"{r['ctrl_sharpe_median']:>8.2f}{r['p_sharpe']:>7.3f}")

    print("\nMAJOR-BUY signal (>= Rs25L), fully invested:\n")
    print(hdr); print("-" * len(hdr))
    for rule in rules:
        r = run(major, prices, S, cal, rule)
        label = rule[0] + (str(rule[1]) if len(rule) > 1 else "")
        results[f"major_{label}"] = {k: v for k, v in r.items() if k != "_daily"}
        print(f"{label:22}{r['n']:>5}{r['win']:>6.3f}{r['mean']*100:>7.2f}%"
              f"{r['cagr']*100:>7.2f}%{r['vol']*100:>6.1f}%{r['sharpe']:>8.2f}"
              f"{r['maxdd']*100:>7.1f}%{r['exposure']*100:>5.1f}%"
              f"{r['ctrl_sharpe_median']:>8.2f}{r['p_sharpe']:>7.3f}")

    # plot best few vs the hold-250 baseline
    try:
        plots = FIND / "plots"
        plots.mkdir(exist_ok=True)
        fig, ax = plt.subplots(figsize=(13, 7))
        for rule, color in ((("trail", 0.15), "#17964b"), (("ema50",), "#8e3a9c"),
                            (("hold", 60), "#1f77b4")):
            r = run(cluster, prices, S, cal, rule, n_ctrl=1)
            d = r["_daily"]
            ax.plot((1 + d).cumprod().index, (1 + d).cumprod(), lw=1.5, color=color,
                    label=f"cluster exit {rule[0]}{rule[1] if len(rule)>1 else ''}")
        nb = bench.reindex((1 + d).cumprod().index, method="ffill").dropna()
        ax.plot(nb.index, nb / nb.iloc[0], ls=":", color="#b3261e", lw=1.1, label="NIFTY")
        ax.axvline(base.SPLIT, color="black", ls=":", lw=1.0)
        ax.set_yscale("log"); ax.set_title("Cluster book, fully invested — exit rule comparison")
        ax.set_ylabel("growth of Rs 1"); ax.grid(alpha=0.25); ax.legend(fontsize=9)
        fig.tight_layout(); fig.savefig(plots / "exit_optimize.png", dpi=150); plt.close(fig)
        print(f"\nplot -> {plots / 'exit_optimize.png'}")
    except Exception as exc:
        print(f"plot warning: {exc}")

    # per-symbol charts: where the clusters were and where we entered/exited
    try:
        sub = FIND / "plots" / "cluster_trades"
        sub.mkdir(parents=True, exist_ok=True)
        best_rule = ("trail", 0.15)
        trades = simulate(cluster, prices, S, best_rule)
        cnt = pd.Series([t[0] for t in trades]).value_counts()
        for sym in cnt.head(6).index:
            plot_symbol_trades(sym, trades, cluster, prices, S, sub / f"{sym}.png")
        print(f"trade charts -> {sub}  (exit = trail 15%)")
    except Exception as exc:
        print(f"trade-chart warning: {exc}")

    (FIND / "exit_optimize.json").write_text(json.dumps(results, indent=2, default=float) + "\n")
    print(f"wrote {FIND / 'exit_optimize.json'}")


if __name__ == "__main__":
    raise SystemExit(main())
