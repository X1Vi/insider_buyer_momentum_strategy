#!/usr/bin/env python3
"""
Kelly / half-Kelly position sizing computed from the REAL Hyperliquid walk-forward
backtest trades (uses the cached candles + engine in hyperliquid_pairs/).

Kelly (discrete trades):  f* = W - (1-W)/R      R = avg win / avg loss
Growth-optimal (continuous): f* = mean / var of per-trade return
Recommendation everywhere in the literature: use HALF-Kelly.
"""
import csv
import os
import sys

import numpy as np

HL = "/home/null/Documents/studies/trading/Machine_Learning_Base_Pairs_Trading/hyperliquid_pairs"
sys.path.insert(0, HL)
import backtest as bt  # reuse engine: load_series, constants, fold logic


def collect_trades(a_full, b_full, beta, alpha, mu, sigma, cost_bps):
    """Replicate backtest.simulate_fold but return per-trade fractional P&L."""
    common = a_full.index.intersection(b_full.index).sort_values()
    a_log = np.log(a_full.loc[common].values)
    b_log = np.log(b_full.loc[common].values)
    spread = a_log - (beta * b_log + alpha)
    z = (spread - mu) / sigma
    d_spread = np.diff(spread, prepend=spread[0])
    crossing = (cost_bps + 2 * bt.TAKER_FEE_BPS) / 10000.0
    funding = bt.FUNDING_BPS_PER_DAY / 10000.0
    n = len(z)
    pos, entry_i, trade_pnl, trades = 0, None, 0.0, []
    for i in range(n):
        pnl = 0.0
        if pos == 0:
            if z[i] >= bt.ENTRY_Z:
                pos, entry_i = -1, i
            elif z[i] <= -bt.ENTRY_Z:
                pos, entry_i = 1, i
            if pos != 0:
                pnl -= crossing
                trade_pnl = pnl
        else:
            pnl += pos * d_spread[i] - funding
            exit_now = (pos == 1 and z[i] >= bt.EXIT_Z) or (pos == -1 and z[i] <= bt.EXIT_Z) \
                or abs(z[i]) >= bt.STOP_Z or i == n - 1
            if exit_now:
                pnl -= crossing
                trade_pnl += pnl
                trades.append(trade_pnl)
                pos = 0
            else:
                trade_pnl += pnl
    return trades


def walk_pair(row, formation=365, trade=90):
    dep, indep = row["dep"], row["indep"]
    a, b = bt.load_series(dep), bt.load_series(indep)
    common = a.index.intersection(b.index).sort_values()
    n = len(common)
    if n < formation + trade:
        return None
    a_log = np.log(a.loc[common].values)
    b_log = np.log(b.loc[common].values)
    cost = (row["spread_bps_dep"] + row["spread_bps_indep"]) / 2.0
    all_trades = []
    t = formation
    while t + trade <= n:
        f = slice(t - formation, t)
        beta, alpha = np.polyfit(b_log[f], a_log[f], 1)
        sp = a_log[f] - (beta * b_log[f] + alpha)
        mu, sigma = sp.mean(), sp.std()
        all_trades += collect_trades(a, b, beta, alpha, mu, sigma, cost)
        t += trade
    return all_trades


def kelly(pnls):
    pnls = np.asarray([p for p in pnls if p is not None and not np.isnan(p)])
    if len(pnls) < 2:
        return None
    wins = pnls[pnls > 0]
    losses = -pnls[pnls <= 0]
    W = len(wins) / len(pnls)
    aw = wins.mean() if len(wins) else 0.0
    al = losses.mean() if len(losses) else 0.0
    R = aw / al if al > 0 else float("inf")
    f = W - (1 - W) / R if np.isfinite(R) else W
    mu, sigma = pnls.mean(), pnls.std(ddof=1)
    f_cont = mu / (sigma * sigma) if sigma > 0 else 0.0
    return {"n": len(pnls), "W": W, "avg_win": aw, "avg_loss": al, "R": R,
            "kelly": f, "half_kelly": f / 2.0, "kelly_cont": f_cont}


def main():
    rows = list(csv.DictReader(open(os.path.join(HL, "results_final.csv"))))
    for r in rows:
        for k in ("spread_bps_dep", "spread_bps_indep"):
            r[k] = float(r[k])

    per_pair, all_trades = {}, []
    for r in rows:
        try:
            tr = walk_pair(r)
        except Exception as e:
            print(f"skip {r['pair']}: {e}", file=sys.stderr)
            continue
        if tr:
            per_pair[r["pair"]] = tr
            all_trades += tr

    print(f"{'PAIR':<14} {'n':>4} {'W%':>5} {'avgW':>7} {'avgL':>7} {'R':>5} "
          f"{'KELLY':>7} {'HALF':>7} {'f=μ/σ²':>7}")
    print("-" * 80)
    for pair, tr in sorted(per_pair.items(), key=lambda kv: -(kelly(kv[1]) or {}).get("kelly", -9)):
        k = kelly(tr)
        if not k:
            continue
        print(f"{pair:<14} {k['n']:>4} {100*k['W']:>4.0f}% {100*k['avg_win']:>6.1f}% "
              f"{100*k['avg_loss']:>6.1f}% {k['R']:>5.2f} {k['kelly']:>7.3f} "
              f"{k['half_kelly']:>7.3f} {k['kelly_cont']:>7.3f}")

    k_all = kelly(all_trades)
    print("\n=== BASKET (all pairs pooled) ===")
    if k_all:
        print(f"trades={k_all['n']}  win%={100*k_all['W']:.0f}  avgWin={100*k_all['avg_win']:.2f}%  "
              f"avgLoss={100*k_all['avg_loss']:.2f}%  payoffR={k_all['R']:.2f}")
        print(f"KELLY f* = {k_all['kelly']:.3f}  ({100*k_all['kelly']:.1f}% of account per trade)")
        print(f"HALF-KELLY = {k_all['half_kelly']:.3f}  ({100*k_all['half_kelly']:.1f}% of account per trade)")
        print(f"continuous f* (μ/σ²) = {k_all['kelly_cont']:.3f}")
        # apply to 15k
        for label, f in (("Full Kelly", k_all["kelly"]), ("Half Kelly", k_all["half_kelly"])):
            if f > 0:
                print(f"  -> {label} on ₹15,000 = ₹{15000*f:.0f} risk per trade")
            else:
                print(f"  -> {label}: f*<=0 -> Kelly says DON'T trade (no edge after costs)")


if __name__ == "__main__":
    main()
