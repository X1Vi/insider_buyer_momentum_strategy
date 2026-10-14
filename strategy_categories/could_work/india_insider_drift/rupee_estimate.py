#!/usr/bin/env python3
"""
rupee_estimate.py — what would Rs 8,000 and Rs 5,000 actually do?

Simulates a small cash account trading the best trend-overlay variant
(insider bias + above-200DMA&RSI>50 entry + 50DMA exit), ONE position at a time,
whole shares only (no fractions), 0.75% round-trip cost.

Reports, for each starting capital: trades taken, trades/year, final balance,
total return, CAGR, max drawdown, and a bootstrap of a typical YEAR.
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from backtest_insider import load_events, load_px, rsi  # noqa: E402

MIN_VALUE, COST, WATCH, MAX_HOLD = 2.5e6, 0.0075, 20, 250
BASKET = ("DBCORP,STEL,MAHSEAMLES,JINDALSTEL,USHAMART,JSL,SURYAROSNI,NRBBEARING,NCC,"
          "MANINFRA,APLLTD,MANGLMCEM,SHOPERSTOP,GREENPLY,PAISALO,JINDRILL,KRISHANA,"
          "TFCILTD").split(",")


def collect_trades(ev):
    out = []
    for s in BASKET:
        px = load_px(s)
        if px is None:
            continue
        idx = px.index
        c = px["close"].to_numpy(float)
        ser = pd.Series(c, index=idx)
        sma200 = ser.rolling(200).mean().to_numpy()
        sma50 = ser.rolling(50).mean().to_numpy()
        r = rsi(px["close"]).to_numpy()
        for t in ev[ev["symbol"] == s]["d"].to_numpy():
            start = np.searchsorted(idx, np.datetime64(t))
            ei = None
            for e in range(start, min(start + WATCH, len(idx) - 2)):
                if (np.isfinite(sma200[e]) and c[e] > sma200[e]
                        and np.isfinite(r[e]) and r[e] > 50):
                    ei = e + 1
                    break
            if ei is None or ei >= len(idx) - 2:
                continue
            entry = px["open"].iloc[ei]
            if not np.isfinite(entry) or entry <= 0:
                continue
            xi = min(ei + MAX_HOLD, len(idx) - 1)
            for x in range(ei + 1, min(ei + MAX_HOLD, len(idx) - 1)):
                if np.isfinite(sma50[x]) and c[x] < sma50[x]:
                    xi = x + 1
                    break
            exitp = px["open"].iloc[min(xi, len(idx) - 1)]
            if not np.isfinite(exitp):
                continue
            out.append(dict(symbol=s, entry_date=idx[ei],
                            exit_date=idx[min(xi, len(idx) - 1)],
                            entry_px=float(entry), exit_px=float(exitp)))
    df = pd.DataFrame(out).sort_values("entry_date").reset_index(drop=True)
    df["net"] = df["exit_px"] / df["entry_px"] - 1 - COST
    return df


def sim_account(tr, C):
    cash, cur_exit, taken, eq = float(C), None, [], [float(C)]
    for _, t in tr.iterrows():
        if cur_exit is not None and t["entry_date"] < cur_exit:
            continue
        n = int(cash // t["entry_px"])            # whole shares only
        if n < 1:
            continue
        cash += n * t["entry_px"] * t["net"]      # apply net (incl. cost)
        taken.append(t["net"])
        cur_exit = t["exit_date"]
        eq.append(cash)
    return np.array(taken), np.array(eq)


def report(C, tr):
    taken, eq = sim_account(tr, C)
    if len(taken) == 0:
        print(f"Rs {C:,.0f}: no affordable trades"); return
    yrs = (tr["exit_date"].max() - tr["entry_date"].min()).days / 365.25
    final = eq[-1]
    dd = (eq / np.maximum.accumulate(eq) - 1).min()
    print(f"\n=== Rs {C:,.0f} account (best variant) ===")
    print(f"  trades {len(taken)} over {yrs:.1f}y ({len(taken)/yrs:.1f}/yr)  "
          f"win {np.mean(taken>0):.2f}  avg net {np.mean(taken)*100:.2f}%")
    print(f"  final Rs {final:,.0f}  total {100*(final/C-1):.1f}%  "
          f"CAGR {100*((final/C)**(1/yrs)-1):.2f}%  maxDD {dd*100:.1f}%")
    rng = np.random.default_rng(1)
    per_year = max(1, round(len(taken)/yrs))
    sims = np.array([np.prod(1 + rng.choice(taken, size=per_year, replace=True)) - 1
                     for _ in range(5000)])
    for p in (5, 50, 95):
        v = np.percentile(sims, p)
        print(f"    year p{p:>2}: {v*100:6.1f}%  -> Rs {C*(1+v):,.0f}")
    print(f"    P(losing year) = {np.mean(sims<0):.2f}")


def main():
    ev = load_events(MIN_VALUE)
    tr = collect_trades(ev)
    print(f"variant-B trades: {len(tr)} across {tr['symbol'].nunique()} symbols")
    for C in (8000, 5000):
        report(C, tr)


if __name__ == "__main__":
    main()
