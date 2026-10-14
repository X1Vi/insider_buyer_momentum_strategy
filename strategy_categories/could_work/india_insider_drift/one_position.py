#!/usr/bin/env python3
"""
one_position.py — ONE position at a time, ~1-2 trades per year.

Candidate signal (your rule): after a major insider buys, wait for price to BREAK
its highest high (new HI_N-day high) with EMA50 and EMA200 BELOW the price
(close > EMA50 > EMA200) — catch momentum.

Portfolio: hold ONE position at a time. Enter next open after a candidate; hold up
to MAX_HOLD (6 months); exit early only on the hard stop-loss SL. When flat, take
the next candidate that appears after the previous exit. => ~1-2 trades/year.

Plots: price + EMA50 + EMA200 + insider buys + our entry/exit (few markers), RSI
below; plus the equity curve.
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from backtest_insider import load_events, load_px  # noqa: E402

MIN_VALUE = 2.5e6
WATCH = 60
HI_N = 20
SL = 0.20            # hard stop-loss 20% (only early exit)
MAX_HOLD = 126       # ~6 months
COST = 0.0075
BASKET = ("ADANIPORTS,CHAMBLFERT,MAHSEAMLES,JSWSTEEL,GRASIM,GODREJAGRO,GODREJIND,"
          "APOLLOTYRE,DBCORP,STEL,NCLIND,NRBBEARING,NCC,MANINFRA,APLLTD,JSL,"
          "SURYAROSNI,BAJAJHLDNG,TFCILTD,KRISHANA").split(",")


def rsi(s, p=14):
    d = s.diff()
    ag = d.clip(lower=0).ewm(alpha=1 / p, min_periods=p, adjust=False).mean()
    al = (-d.clip(upper=0)).ewm(alpha=1 / p, min_periods=p, adjust=False).mean()
    return 100 - 100 / (1 + ag / al.replace(0, np.nan))


def candidates(sym, ev, px):
    idx = px.index
    close = px["close"].to_numpy(float)
    open_ = px["open"].to_numpy(float)
    hi = px["close"].rolling(HI_N).max().shift(1).to_numpy()
    e50 = px["close"].ewm(span=50, adjust=False).mean().to_numpy()
    e200 = px["close"].ewm(span=200, adjust=False).mean().to_numpy()
    out = []
    for t in ev[ev["symbol"] == sym]["d"].sort_values().to_numpy():
        s0 = np.searchsorted(idx, np.datetime64(t))
        for e in range(s0, min(s0 + WATCH, len(idx) - 2)):
            if e > 0 and np.isfinite(hi[e]) and close[e] > hi[e] \
                    and np.isfinite(e50[e]) and np.isfinite(e200[e]) \
                    and close[e] > e50[e] > e200[e]:
                out.append((idx[e + 1], e + 1))       # enter next open
                break
    return out


def main():
    ev = load_events(MIN_VALUE)
    pxmap, cands = {}, []
    for s in BASKET:
        px = load_px(s)
        if px is None or len(px) < 250:
            continue
        pxmap[s] = px
        for d, ei in candidates(s, ev, px):
            cands.append((d, s, ei))
    cands.sort()
    print(f"candidates (breakout after insider, EMAs below): {len(cands)}")

    # single-position walk
    trades = []
    cur_exit = None
    for d, s, ei in cands:
        if cur_exit is not None and d < cur_exit:
            continue
        px = pxmap[s]
        close = px["close"].to_numpy(float)
        entry = px["open"].iloc[ei]
        if not np.isfinite(entry) or entry <= 0:
            continue
        xi = min(ei + MAX_HOLD, len(px) - 1)
        for x in range(ei + 1, min(ei + MAX_HOLD, len(px) - 1)):
            if close[x] <= entry * (1 - SL):
                xi = x
                break
        exitp = px["open"].iloc[min(xi, len(px) - 1)]
        trades.append(dict(symbol=s, entry_date=px.index[ei],
                           exit_date=px.index[min(xi, len(px) - 1)],
                           entry_px=float(entry), exit_px=float(exitp),
                           net=exitp / entry - 1 - COST))
        cur_exit = px.index[min(xi, len(px) - 1)]
    tr = pd.DataFrame(trades)
    yrs = (tr["exit_date"].max() - tr["entry_date"].min()).days / 365.25
    hold = (tr["exit_date"] - tr["entry_date"]).dt.days
    print(f"\n=== ONE position at a time ===")
    print(f"  trades {len(tr)} over {yrs:.1f}y = {len(tr)/yrs:.1f} per year")
    print(f"  win {np.mean(tr['net']>0):.2f}  avg net {tr['net'].mean()*100:.1f}%  "
          f"median {tr['net'].median()*100:.1f}%")
    print(f"  avg hold {hold.mean():.0f}d (median {hold.median():.0f}, max {hold.max():.0f})")
    for C in (8000, 5000):
        cash = float(C); eq = [cash]
        for _, t in tr.iterrows():
            cash *= (1 + t["net"]); eq.append(cash)
        eq = np.array(eq)
        dd = (eq / np.maximum.accumulate(eq) - 1).min()
        cagr = (eq[-1] / C) ** (1 / yrs) - 1
        print(f"  Rs {C:,}: {len(tr)} trades  final Rs {eq[-1]:,.0f} "
              f"({100*(eq[-1]/C-1):.0f}%, CAGR {100*cagr:.1f}%, maxDD {100*dd:.0f}%)")

    OUT = HERE / "plots" / "one_position"
    OUT.mkdir(parents=True, exist_ok=True)
    for s in tr["symbol"].unique():
        px = pxmap[s]
        tt = tr[tr["symbol"] == s]
        fig, (ax, ax2) = plt.subplots(2, 1, figsize=(13, 7.5), sharex=True,
                                      gridspec_kw={"height_ratios": [3, 1]})
        ax.plot(px.index, px["close"], color="#333", lw=0.9, label="close")
        ax.plot(px.index, px["close"].ewm(span=50, adjust=False).mean(),
                color="#4575b4", lw=1.0, label="EMA(50)")
        ax.plot(px.index, px["close"].ewm(span=200, adjust=False).mean(),
                color="#8c6d31", lw=1.1, label="EMA(200)")
        buys = ev[ev["symbol"] == s]
        ax.scatter(buys["trade_date"], px["close"].reindex(buys["trade_date"], method="nearest"),
                   marker="o", s=14, color="#9ecae1", alpha=0.7, label="insider bought", zorder=3)
        ax.scatter(tt["entry_date"], px["close"].reindex(tt["entry_date"], method="nearest"),
                   marker="^", s=150, color="#1a9850", edgecolor="white", lw=0.6,
                   label="invest", zorder=5)
        ax.scatter(tt["exit_date"], px["close"].reindex(tt["exit_date"], method="nearest"),
                   marker="x", s=90, color="#d73027", lw=1.5, label="sell", zorder=5)
        ax.set_title(f"{s} — {len(tt)} trade(s) taken")
        ax.legend(fontsize=8, loc="upper left"); ax.grid(alpha=0.25)
        r = rsi(px["close"])
        ax2.plot(px.index, r, color="#555", lw=0.9)
        ax2.axhline(70, color="#d73027", ls="--", lw=0.7)
        ax2.axhline(30, color="#1a9850", ls="--", lw=0.7)
        ax2.set_ylim(0, 100); ax2.set_ylabel("RSI(14)"); ax2.grid(alpha=0.25)
        fig.tight_layout(); fig.savefig(OUT / f"{s}.png", dpi=140); plt.close(fig)
    # equity curve
    eqs = [8000]
    for _, t in tr.iterrows():
        eqs.append(eqs[-1] * (1 + t["net"]))
    fig, ax = plt.subplots(figsize=(12, 5))
    ax.plot(tr["exit_date"], eqs[1:], "-o", color="#1a9850", ms=4)
    ax.axhline(8000, color="#999", lw=0.8)
    ax.set_title(f"Rs 8,000 — one-position strategy ({len(tr)} trades, "
                 f"{len(tr)/yrs:.1f}/yr)")
    ax.set_ylabel("balance (Rs)"); ax.grid(alpha=0.25)
    fig.tight_layout(); fig.savefig(OUT / "equity.png", dpi=140); plt.close(fig)
    print(f"\nplots -> {OUT} ({len(tr['symbol'].unique())} symbols + equity.png)")


if __name__ == "__main__":
    main()
