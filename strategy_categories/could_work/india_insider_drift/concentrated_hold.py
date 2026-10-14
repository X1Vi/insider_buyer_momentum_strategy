#!/usr/bin/env python3
"""concentrated_hold.py — capture post-insider momentum with FULL capital and LONGER
holds (no 1/200 dilution). Fully-invested equal-weight-across-open-positions.
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


def major_buy_dates(events, min_value):
    ev = events[events.value >= min_value].sort_values(["symbol", "d"])
    return pd.DataFrame([(sym, pd.Timestamp(dd))
                         for sym, g in ev.groupby("symbol")
                         for dd in g.d.dropna().unique()],
                        columns=["symbol", "signal_date"])


def build_arrays(prices):
    cal = pd.DatetimeIndex(sorted(set().union(*(set(p.index) for p in prices.values()))))
    A = {s: dict(c=p.close.to_numpy(float), o=p.open.to_numpy(float),
                 g=np.asarray(cal.searchsorted(p.index))) for s, p in prices.items()}
    return A, cal


def trades_for(signals, prices, hold):
    last, keep = {}, []
    for row in signals.sort_values("signal_date").itertuples():
        px = prices.get(row.symbol)
        if px is None:
            continue
        idx = px.index
        e = idx.searchsorted(row.signal_date)
        if e < len(idx) and idx[e] == row.signal_date:
            e += 1
        if e + hold >= len(idx):
            continue
        if row.symbol in last and e <= last[row.symbol]:
            continue
        keep.append((row.symbol, int(e), int(e + hold)))
        last[row.symbol] = e + hold
    return keep


def portfolio(trades, A, cal, cost):
    ret = np.zeros(len(cal))
    act = np.zeros(len(cal))
    for sym, ei, xi in trades:
        a = A[sym]
        c, o, g = a["c"], a["o"], a["g"]
        ret[g[ei]] += c[ei] / o[ei] - 1 - cost / 2
        act[g[ei]] += 1
        ret[g[ei + 1:xi + 1]] += c[ei + 1:xi + 1] / c[ei:xi] - 1
        act[g[ei + 1:xi + 1]] += 1
        ret[g[xi]] -= cost / 2
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


def run(signals, prices, A, cal, hold, cost, n_ctrl=30, seed=base.SEED):
    trades = trades_for(signals, prices, hold)
    n = len(trades)
    if n == 0:
        return {"n": 0}
    daily, exposure = portfolio(trades, A, cal, cost)
    rets = np.array([prices[s].close.iloc[xi] / prices[s].open.iloc[ei] - 1 - cost
                     for s, ei, xi in trades])
    m = metrics(daily)

    by = {}
    for s, _, _ in trades:
        by[s] = by.get(s, 0) + 1
    rng = np.random.default_rng(seed)
    ctrl_cagr, ctrl_sh = np.empty(n_ctrl), np.empty(n_ctrl)
    elig_cache = {s: np.arange(base.MIN_HISTORY_SESSIONS, len(prices[s]) - hold - 2)
                  for s in by if len(prices[s]) - hold - 2 > base.MIN_HISTORY_SESSIONS}
    for it in range(n_ctrl):
        c_trades = []
        for s, k in by.items():
            elig = elig_cache.get(s)
            if elig is None or len(elig) == 0:
                continue
            for ei in rng.choice(elig, size=k, replace=k > len(elig)):
                c_trades.append((s, int(ei), int(ei + hold)))
        cd, _ = portfolio(c_trades, A, cal, cost)
        cm = metrics(cd)
        ctrl_cagr[it], ctrl_sh[it] = cm["cagr"], cm["sharpe"]
    return dict(n=n, win=float((rets > 0).mean()), mean=float(rets.mean()),
                exposure=exposure, **m,
                ctrl_cagr_median=float(np.median(ctrl_cagr)),
                ctrl_sharpe_median=float(np.median(ctrl_sh)),
                p_cagr=float((ctrl_cagr >= m["cagr"]).mean()),
                p_sharpe=float((ctrl_sh >= m["sharpe"]).mean()))


def main():
    events = base.load_events()
    prices = base.load_prices()
    bench = base.load_bench()
    ev = events[events.symbol.isin(prices)]
    major = major_buy_dates(ev, 2.5e6)
    cluster = ca.cluster_events(ev, 30, 2, 1e6, 20)[["symbol", "signal_date"]]
    fast = pd.DataFrame([(sym, d) for sym, px in prices.items()
                         for g in [ev[ev.symbol == sym]]
                         if not g.empty
                         for d in base._fast_symbol(px, bench, g.d, 5, 0.03, 0.5, 2)],
                        columns=["symbol", "signal_date"])

    A, cal = build_arrays(prices)
    print(f"signals: major_buy={len(major)}  cluster={len(cluster)}  fast={len(fast)}\n")
    hdr = (f"{'signal':16}{'hold':>5}{'n':>5}{'win':>6}{'mean':>8}{'CAGR':>8}{'vol':>7}"
           f"{'Sharpe':>8}{'maxDD':>8}{'exp':>6}{'ctrlSh':>8}{'p(Sh)':>7}")
    print(hdr); print("-" * len(hdr))
    results = {}
    for sig_name, sig in (("major_buy", major), ("cluster", cluster), ("fast", fast)):
        for hold in (20, 60, 120, 250):
            r = run(sig, prices, A, cal, hold, COST)
            results[f"{sig_name}_h{hold}"] = r
            if r["n"] == 0:
                print(f"{sig_name:16}{hold:>5}  no trades")
                continue
            print(f"{sig_name:16}{hold:>5}{r['n']:>5}{r['win']:>6.3f}{r['mean']*100:>7.2f}%"
                  f"{r['cagr']*100:>7.2f}%{r['vol']*100:>6.1f}%{r['sharpe']:>8.2f}"
                  f"{r['maxdd']*100:>7.1f}%{r['exposure']*100:>5.1f}%"
                  f"{r['ctrl_sharpe_median']:>8.2f}{r['p_sharpe']:>7.3f}")

    # ---- plot the headline fully-invested curves vs Nifty + one random control ----
    try:
        plots = FIND / "plots"
        plots.mkdir(exist_ok=True)
        fig, ax = plt.subplots(figsize=(13, 7))
        for sig, hold, color in (("cluster", 250, "#17964b"), ("major_buy", 250, "#1f77b4")):
            d, _ = portfolio(trades_for(
                {"cluster": cluster, "major_buy": major}[sig], prices, hold), A, cal, COST)
            ax.plot((1 + d).cumprod().index, (1 + d).cumprod(), lw=1.6,
                    color=color, label=f"{sig} hold {hold}d (n={len(trades_for({'cluster': cluster, 'major_buy': major}[sig], prices, hold))})")
        # random control for the cluster signal, one draw
        ct = trades_for(cluster, prices, 250)
        by = {}
        for s, _, _ in ct:
            by[s] = by.get(s, 0) + 1
        rng = np.random.default_rng(base.SEED)
        c_trades = []
        for s, k in by.items():
            elig = np.arange(base.MIN_HISTORY_SESSIONS, len(prices[s]) - 250 - 2)
            if len(elig) == 0:
                continue
            for ei in rng.choice(elig, size=k, replace=k > len(elig)):
                c_trades.append((s, int(ei), int(ei + 250)))
        cd, _ = portfolio(c_trades, A, cal, COST)
        ax.plot((1 + cd).cumprod().index, (1 + cd).cumprod(), lw=1.2, ls="--",
                color="#999", label="random control (same stocks, hold 250d)")
        nb = bench.reindex((1 + d).cumprod().index, method="ffill").dropna()
        ax.plot(nb.index, nb / nb.iloc[0], lw=1.1, ls=":", color="#b3261e", label="NIFTY buy&hold")
        ax.axvline(base.SPLIT, color="black", ls=":", lw=1.0)
        ax.set_title("Fully-invested insider-buy books, hold 250 sessions (27 bp) — vs Nifty")
        ax.set_ylabel("growth of Rs 1"); ax.set_yscale("log"); ax.grid(alpha=0.25)
        ax.legend(fontsize=9)
        fig.tight_layout(); fig.savefig(plots / "concentrated_hold_equity.png", dpi=150)
        plt.close(fig)
        print(f"plot -> {plots / 'concentrated_hold_equity.png'}")
    except Exception as exc:
        print(f"plot warning: {exc}")

    (FIND / "concentrated_hold.json").write_text(
        json.dumps(results, indent=2, default=float) + "\n")
    print(f"\nwrote {FIND / 'concentrated_hold.json'}")


if __name__ == "__main__":
    raise SystemExit(main())
