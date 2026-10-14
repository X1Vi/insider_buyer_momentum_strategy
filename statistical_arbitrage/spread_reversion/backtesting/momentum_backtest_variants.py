#!/usr/bin/env python3
"""Honest equity-curve backtest of the NSE breakout-momentum strategy, across a
PRE-REGISTERED grid of entry/exit variants. Reports Sharpe, max drawdown, win
rate, avg R and cost-inclusive P&L — not the flattering "hit-rate" metric.

Why this exists: the earlier studies showed high "made a higher high" hit-rates
(~85-100%) that did NOT translate to profit. This tool measures actual returns
with costs, so we stop celebrating a misleading number.

Bias controls (visible throughout):
  * no look-ahead: signal on day t uses data <= t only; outcomes t+1..t+H
  * signals deduplicated (>= 10-day gap between trades)
  * full grid reported (nothing hidden)
  * OOS (train/test by time) reported for the best variant
  * costs (~0.1%/side) included
  * survivorship bias flagged (universe = today's large caps/ETFs)

Data caveat: cached OHLCV has open/low = 0 on many bars (API artifact), so
entries/exits here are modeled on close & high (the clean fields). Realistic
limit/pullback orders cannot be tested faithfully on this data.
"""

import glob
import os

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")

W, H, MULT, SEP = 20, 20, 3.0, 10
COST = 0.001          # ~0.1% per side (0.2% round trip)
MAX_EXTENSION = 0.03  # entry filter: close <= anchor * (1 + MAX_EXTENSION)

# ---------------- pre-registered variant grid ----------------
ENTRIES = ["all", "notextended"]          # all breakouts, vs non-extended only
EXITS = ["hold20", "tp10", "trail10", "fail5", "tp10_trail"]


def load_symbols():
    syms = {}
    for p in sorted(glob.glob(os.path.join(DATA, "*.csv"))):
        name = os.path.basename(p)[:-4]
        if name in ("instruments", "SP500"):
            continue
        df = pd.read_csv(p, parse_dates=["ts"])
        df = df[df.close > 0].reset_index(drop=True)
        if len(df) < 260:
            continue
        syms[name] = df
    return syms


def signals(df):
    c = df["close"].to_numpy()
    h = df["high"].to_numpy()
    v = df["volume"].to_numpy()
    n = len(c)
    volma = pd.Series(v).rolling(20, min_periods=20).mean().to_numpy()
    sig = [False] * n
    for t in range(W, n):
        anchor = h[t - W:t].max()
        mom = c[t] / c[t - 252] - 1 if t >= 252 else 0
        if v[t] >= MULT * volma[t] and c[t] > anchor and mom > 0:
            sig[t] = True
    idx = []
    i = 0
    while i < n:
        if sig[i]:
            idx.append(i)
            j = i
            while j + 1 < n and sig[j + 1]:
                j += 1
            i = j + SEP + 1
        else:
            i += 1
    return np.array(idx), c, h, n


def run_variant(syms, entry_mode, exit_mode):
    """Returns list of per-trade returns (cost-inclusive) and a date->daily-returns map."""
    trades = []
    daily = {}
    for sym, df in syms.items():
        idx, c, h, n = signals(df)
        dates = df["ts"].dt.date.to_numpy()
        for t in idx:
            anchor = h[t - W:t].max()
            if entry_mode == "notextended" and c[t] > anchor * (1 + MAX_EXTENSION):
                continue  # skip chasing an extended breakout
            entry = c[t]
            exit_px = None
            exit_day = None
            run_hi = entry
            for k in range(t + 1, min(t + H + 1, n)):
                run_hi = max(run_hi, c[k])
                do_exit = False
                if exit_mode == "tp10" and c[k] >= entry * 1.10:
                    do_exit = True
                elif exit_mode == "trail10" and (k - t) >= 3 and c[k] < min(h[k - 9:k + 1]):
                    do_exit = True
                elif exit_mode == "fail5" and (k - t) >= 5 and run_hi <= entry:
                    do_exit = True
                elif exit_mode == "tp10_trail":
                    if c[k] >= entry * 1.10 or ((k - t) >= 3 and c[k] < min(h[k - 9:k + 1])):
                        do_exit = True
                if do_exit:
                    exit_px = c[k]
                    exit_day = k
                    break
            if exit_px is None:
                exit_day = min(t + H, n - 1)
                exit_px = c[exit_day]
            for k in range(t + 1, exit_day + 1):
                daily.setdefault(dates[k], []).append(c[k] / c[k - 1] - 1)
            trades.append(exit_px / entry - 1 - 2 * COST)
    return np.array(trades), daily


def stats(trades, daily):
    tr = trades
    if len(tr) == 0:
        return dict(trades=0, win=np.nan, avg=np.nan, r_med=np.nan, sharpe=np.nan, maxdd=np.nan, equity=np.nan)
    dates = sorted(daily)
    day_ret = np.array([np.mean(daily[d]) for d in dates])
    eq = np.cumprod(1 + day_ret)
    dd = (eq / np.maximum.accumulate(eq) - 1).min()
    sharpe = day_ret.mean() / day_ret.std() * np.sqrt(252) if day_ret.std() > 0 else 0.0
    return dict(
        trades=len(tr),
        win=100 * (tr > 0).mean(),
        avg=100 * tr.mean(),
        r_med=100 * np.median(tr),
        sharpe=sharpe,
        maxdd=100 * dd,
        equity=100 * (eq[-1] - 1),
        days=len(dates),
    )


def main():
    syms = load_symbols()
    print("=" * 100)
    print(f"MOMENTUM STRATEGY — VARIANT BACKTEST  |  {len(syms)} symbols  |  "
          f"signal: close>{W}d high, vol>={MULT:.0f}x SMA20, 1y mom>0  |  costs {2*COST*100:.1f}% round trip")
    print("entry: all = every breakout  |  notextended = skip close > anchor*(1+3%)  (avoids chasing)")
    print("exits: hold20=20d hold | tp10=+10% TP | trail10=10d-low trail | fail5=exit if no higher high in 5d | tp10_trail=TP+trail")
    print("=" * 100)
    hdr = f"{'ENTRY':<12} {'EXIT':<11} {'n':>4} {'win%':>6} {'avg%':>7} {'med%':>7} {'Sharpe':>7} {'maxDD%':>7} {'Eq%':>7} {'days':>5}"
    print(hdr)
    print("-" * 100)

    results = {}
    for en in ENTRIES:
        for ex in EXITS:
            trades, daily = run_variant(syms, en, ex)
            s = stats(trades, daily)
            results[(en, ex)] = (trades, daily, s)
            print(f"{en:<12} {ex:<11} {s['trades']:>4} {s['win']:>5.1f} {s['avg']:>+6.2f} "
                  f"{s['r_med']:>+6.2f} {s['sharpe']:>7.2f} {s['maxdd']:>6.1f} {s['equity']:>+6.1f} {s['days']:>5}")

    # best by Sharpe (only if it has trades and positive-ish; else note)
    best = max(results, key=lambda k: results[k][2]["sharpe"] if results[k][2]["trades"] else -99)
    bt, bd, bs = results[best]
    print(f"\nBEST VARIANT: entry={best[0]} exit={best[1]}  (Sharpe {bs['sharpe']:.2f}, n={bs['trades']}, maxDD {bs['maxdd']:.1f}%)")

    # per-symbol for best variant
    print(f"\nPER-SYMBOL (best variant {best[0]}/{best[1]}, cost-inclusive):")
    per = {}
    for sym, df in syms.items():
        tr, dl = run_variant({sym: df}, best[0], best[1])
        if len(tr) == 0:
            continue
        per[sym] = (100 * tr.mean(), len(tr), 100 * (tr > 0).mean())
    for sym in sorted(per, key=lambda s: -per[s][0]):
        avg, n, win = per[sym]
        print(f"  {sym:<12} avg {avg:>+6.2f}%  n={n:>2}  win {win:>4.0f}%")

    # OOS split (train = first half of dates, test = second half)
    print(f"\nOUT-OF-SAMPLE (time split of best variant {best[0]}/{best[1]}):")
    dates = sorted(bd)
    if dates:
        mid = dates[len(dates) // 2]
        tr_train = np.array([np.mean(bd[d]) for d in dates if d < mid])
        tr_test = np.array([np.mean(bd[d]) for d in dates if d >= mid])
        sh = lambda x: x.mean() / x.std() * np.sqrt(252) if x.std() > 0 else 0
        eq_t = np.cumprod(1 + tr_test)
        print(f"  train (before {mid}): Sharpe {sh(tr_train):.2f}, days {len(tr_train)}")
        print(f"  test  (from  {mid}): Sharpe {sh(tr_test):.2f}, maxDD {100*((eq_t/np.maximum.accumulate(eq_t))-1).min():.1f}%, days {len(tr_test)}")

    print("\nBIAS CHECKLIST:")
    print("  [x] no look-ahead (signal <= t, outcomes t+1..t+H)")
    print("  [x] signals deduped (>=10d gap)")
    print("  [x] full pre-registered grid reported")
    print("  [x] costs (0.1%/side) included")
    print("  [x] OOS time-split reported")
    print("  [ ] SURVIVORSHIP: universe is today's large caps/ETFs — delisted absent (cannot remove)")
    print("  [ ] REGIME: sample is mostly a bull market; results may not hold in bear/chop")
    print("  [ ] small per-name samples (n in single digits) — pooled results are more trustworthy")
    print("  [ ] open/low = 0 in cache: realistic limit/pullback entries not testable on this data")


if __name__ == "__main__":
    main()
