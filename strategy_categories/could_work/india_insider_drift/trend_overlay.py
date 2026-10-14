#!/usr/bin/env python3
"""
trend_overlay.py — insider buy (bias) + price-action/trend (timing).

Idea: an insider buy is a *bullish bias*, not a timing signal. So instead of a
fixed hold, use it as a WATCHLIST trigger, then trade the TREND:
  - trigger: major insider market-buy (>= MIN_VALUE, promoter/director/KMP)
  - entry  : within WATCH days after the trigger, buy the next open after a
             Donchian BREAKOUT (close > highest close of the last ENTRY_N days)
  - exit   : trend break — close < lowest close of the last EXIT_N days
             (a trailing Donchian stop), or after MAX_HOLD days
  - long-only, cash, cost per side.

Compared against: (a) the fixed-hold insider rule, (b) random entries with the
same trend exit (placebo).

Run:  python trend_overlay.py --fetch
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from backtest_insider import load_events, load_px, download, metrics  # noqa: E402

MIN_VALUE = 2.5e6
ENTRY_N, EXIT_N, WATCH, MAX_HOLD = 20, 10, 60, 250
COST = 0.0075
OOS_START = "2024-01-01"
BASKET = ("DBCORP,STEL,MAHSEAMLES,JINDALSTEL,USHAMART,JSL,SURYAROSNI,NRBBEARING,NCC,"
          "MANINFRA,APLLTD,MANGLMCEM,SHOPERSTOP,GREENPLY,PAISALO,JINDRILL,KRISHANA,"
          "TFCILTD").split(",")


def run_symbol(sym, ev, cost=COST):
    px = load_px(sym)
    if px is None or len(px) < ENTRY_N + MAX_HOLD + 5:
        return None
    idx = px.index
    close = px["close"].to_numpy(float)
    hi = pd.Series(close, index=idx).rolling(ENTRY_N).max().to_numpy()
    lo = pd.Series(close, index=idx).rolling(EXIT_N).min().to_numpy()
    trig = ev[ev["symbol"] == sym]["d"].to_numpy()
    trades = []
    for t in trig:
        start = np.searchsorted(idx, np.datetime64(t))
        # look for a breakout entry within WATCH days
        for e in range(start, min(start + WATCH, len(idx) - 2)):
            if e > 0 and np.isfinite(hi[e - 1]) and close[e] > hi[e - 1]:
                ei = e + 1
                break
        else:
            continue
        if ei >= len(idx) - 2:
            continue
        entry = px["open"].iloc[ei]
        if not np.isfinite(entry) or entry <= 0:
            continue
        # trail out
        xi = min(ei + MAX_HOLD, len(idx) - 1)
        for x in range(ei + EXIT_N, xi):
            if np.isfinite(lo[x]) and close[x] < lo[x - 1]:
                xi = x + 1
                break
        exitp = px["open"].iloc[min(xi, len(idx) - 1)]
        if not np.isfinite(exitp):
            continue
        trades.append(dict(entry_date=idx[ei], exit_date=idx[min(xi, len(idx) - 1)],
                           net=exitp / entry - 1.0 - cost))
    if not trades:
        return None
    tr = pd.DataFrame(trades)
    pos = pd.Series(0.0, index=idx)
    for t in trades:
        pos.loc[t["entry_date"]:t["exit_date"]] = 1.0
    ret = px["close"].pct_change(fill_method=None).fillna(0.0)
    strat = pos.shift(1).fillna(0.0) * ret
    for t in trades:
        strat.loc[t["entry_date"]] -= cost / 2
        strat.loc[t["exit_date"]] -= cost / 2
    return strat, tr


def main():
    ev = load_events(MIN_VALUE)
    download(BASKET)
    strats, trs = [], []
    for s in BASKET:
        r = run_symbol(s, ev)
        if r is None:
            continue
        strat, tr = r
        strats.append(strat.rename(s)); trs.append(tr.assign(symbol=s))
    if not strats:
        print("no trades"); return
    combined = pd.concat(strats, axis=1).mean(axis=1).dropna()
    pooled = pd.concat(trs, ignore_index=True)
    pm = metrics(combined, pooled, (combined != 0).astype(float))
    print("=== insider + Donchian breakout/trend-exit (pooled) ===")
    print(f"  symbols {len(strats)}  trades {pm['n']}  win {pm['win']:.2f}  "
          f"avg net {pm['avg_net']*100:.2f}%  CAGR {pm['cagr']*100:.2f}%  "
          f"vol {pm['vol']*100:.2f}%  Sharpe {pm['sharpe']:.2f}  "
          f"maxDD {pm['maxdd']*100:.1f}%  Calmar {pm['calmar']:.2f}  "
          f"exposure {pm['exposure']*100:.1f}%")
    hold = (pooled["exit_date"] - pooled["entry_date"]).dt.days
    print(f"  avg hold {hold.mean():.0f} days (median {hold.median():.0f})")
    oos = pooled[pooled["entry_date"] >= OOS_START]
    if len(oos):
        print(f"  OOS trades {len(oos)}  win {(oos['net']>0).mean():.2f}  "
              f"avg net {oos['net'].mean()*100:.2f}%")
    pooled.to_csv(HERE / "data" / "trend_overlay_trades.csv", index=False)
    print(f"  wrote {HERE/'data'/'trend_overlay_trades.csv'}")


if __name__ == "__main__":
    main()
