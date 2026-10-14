#!/usr/bin/env python3
"""diagnose_entries.py — examine the LOSING trades: are we buying the peak?

For each trade (cluster -> momentum entry min_rise 10% -> profit-lock exit -> gate),
measure the entry's extension:
  ext50  = entry_open / EMA50  - 1     (how far above the mean we bought)
  ext200 = entry_open / EMA200 - 1
  extph  = entry_open / prior252high - 1   (how far above the breakout level)
  runup  = entry_open / disclosure_close - 1
  worst  = worst close vs entry_open during the hold
  net    = realised net return
Then: list the losers, bucket by ext50, and test skipping entries that are too
extended (a cap).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import cluster_and_fast as base
import cluster_advantage as ca
import momentum_entry_pp as mep
from profit_protect import exit_pp
from regime_gate import gated
from exit_optimize import portfolio, metrics, FIND

COST = base.COST


def entry_capped(sd, ref_i, min_rise, cap, max_wait=126):
    """Find the momentum breakout; return the entry bar, or None if it (or the
    extension) is over the cap."""
    c, o = sd["c"], sd["o"]
    e50, e200, ph = sd["ema50"], sd["ema200"], sd["ph"]
    ref = c[ref_i]
    if not (np.isfinite(ref) and ref > 0):
        return None
    hi = min(ref_i + max_wait, len(c) - 2)
    for i in range(ref_i, hi):
        if (np.isfinite(ph[i]) and c[i] > ph[i] and c[i] > e50[i] > e200[i]
                and c[i] >= ref * (1 + min_rise)):
            ei = i + 1
            ext = o[ei] / e50[ei] - 1 if e50[ei] > 0 else 0
            if cap is None or ext <= cap:
                return ei
            return None            # extended -> skip this catalyst
    return None


def simulate(catalysts, prices, S, cap=None):
    last, trades = {}, []
    for row in catalysts.sort_values("signal_date").itertuples():
        sd = S.get(row.symbol)
        if sd is None:
            continue
        idx = prices[row.symbol].index
        ref_i = idx.searchsorted(row.signal_date)
        ei = entry_capped(sd, ref_i, 0.10, cap)
        if ei is None or ei + 1 >= len(idx):
            continue
        if row.symbol in last and ei <= last[row.symbol]:
            continue
        xi = exit_pp(sd, ei, 0.15, 0.25, 3)
        if xi <= ei or xi >= len(idx):
            continue
        trades.append((row.symbol, int(ei), int(xi), int(ref_i)))
        last[row.symbol] = xi
    return trades


def gate_full(trades4, S, gate_arr):
    """Full regime gate for 4-tuples (sym, ei, xi, ref_i) -> 3-tuples."""
    out = []
    for sym, ei, xi, ref in trades4:
        g = S[sym]["g"]
        if not gate_arr[g[ei]]:
            continue
        for d in range(ei + 1, xi + 1):
            if not gate_arr[g[d]]:
                xi = d
                break
        out.append((sym, ei, xi, ref))
    return out


def features(trades, prices, S):
    rows = []
    for sym, ei, xi, ref_i in trades:
        sd = S[sym]
        c, o = sd["c"], sd["o"]
        e50, e200, ph = sd["ema50"], sd["ema200"], sd["ph"]
        entry = o[ei]
        net = o[xi] / entry - 1 - COST
        worst = (c[ei:xi + 1] / entry - 1).min()
        rows.append(dict(
            symbol=sym, entry_date=prices[sym].index[ei], net=net, worst=worst,
            ext50=entry / e50[ei] - 1, ext200=entry / e200[ei] - 1,
            extph=entry / ph[ei] - 1 if np.isfinite(ph[ei]) else np.nan,
            runup=entry / c[ref_i] - 1, hold=xi - ei))
    return pd.DataFrame(rows)


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

    base_trades = gate_full(simulate(cluster, prices, S, None), S, gate_arr)
    df = features(base_trades, prices, S)
    print(f"baseline trades {len(df)}  win {(df.net>0).mean():.3f}  mean {df.net.mean()*100:+.1f}%\n")

    print("WORST 15 TRADES (the 'buy the peak' candidates):")
    print(f"{'sym':10}{'entry':11}{'ext50':>7}{'ext200':>7}{'extph':>7}{'runup':>7}"
          f"{'hold':>5}{'worst':>7}{'net':>7}")
    for r in df.sort_values("net").head(15).itertuples():
        print(f"{r.symbol:10}{str(r.entry_date.date()):11}{r.ext50*100:>6.0f}%{r.ext200*100:>6.0f}%"
              f"{r.extph*100:>6.0f}%{r.runup*100:>6.0f}%{r.hold:>5}{r.worst*100:>6.0f}%{r.net*100:>6.0f}%")

    print("\nBUCKET by entry extension above EMA50 (ext50):")
    print(f"{'bucket':16}{'n':>5}{'win':>6}{'mean':>8}{'worst':>8}")
    bins = [-1, 0.05, 0.10, 0.20, 0.40, 10]
    labels = ["<5%", "5-10%", "10-20%", "20-40%", ">40%"]
    df["bucket"] = pd.cut(df.ext50, bins=bins, labels=labels)
    for lab in labels:
        g = df[df.bucket == lab]
        if len(g):
            print(f"{lab:16}{len(g):>5}{(g.net>0).mean():>6.3f}{g.net.mean()*100:>7.1f}%{g.worst.min()*100:>7.0f}%")

    print("\nCAP TEST — skip entries whose ext50 exceeds the cap:")
    print(f"{'cap':>6}{'n':>5}{'win':>6}{'mean':>8}{'CAGR':>8}{'Sharpe':>8}{'maxDD':>8}{'exp':>6}")
    for cap in (None, 0.20, 0.15, 0.10, 0.08, 0.05):
        tr4 = gate_full(simulate(cluster, prices, S, cap), S, gate_arr)
        tr = [(s, e, x) for s, e, x, _ in tr4]
        if not tr:
            print(f"{str(cap):>6}  no trades"); continue
        d, exp = portfolio(tr, S, cal, COST)
        m = metrics(d)
        rets = np.array([prices[s].open.iloc[xi] / prices[s].open.iloc[ei] - 1 - COST
                         for s, ei, xi in tr])
        print(f"{('none' if cap is None else f'{cap:.2f}'):>6}{len(tr):>5}{(rets>0).mean():>6.3f}"
              f"{rets.mean()*100:>7.1f}%{m['cagr']*100:>7.1f}%{m['sharpe']:>8.2f}"
              f"{m['maxdd']*100:>7.1f}%{exp*100:>5.0f}%")

    df.to_csv(FIND / "entry_diagnosis.csv", index=False)
    print(f"\nwrote {FIND / 'entry_diagnosis.csv'}")


if __name__ == "__main__":
    raise SystemExit(main())
