#!/usr/bin/env python3
"""Plot where the momentum strategy actually takes trades, per symbol.

Uses the BEST variant from momentum_backtest_variants.py (entry=all breakouts,
exit=+10% take-profit or 20-day cap) and draws, for each symbol that had a trade:
  * the daily close price line
  * a green UP arrow at entry (breakout close)
  * a red DOWN arrow at exit, with the holding period shaded
  * per-trade % return (cost-inclusive) labeled

Output: backtesting/plots/momentum_trades/{SYMBOL}.png  +  overview.png (all names)
"""
import os

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
OUT = os.path.join(HERE, "plots", "momentum_trades")
os.makedirs(OUT, exist_ok=True)

W, H, MULT, SEP = 20, 20, 3.0, 10
COST = 0.001
EXIT_MODE = "tp10"   # +10% take-profit, else 20d cap
ENTRY_MODE = "all"


def load_symbols():
    syms = {}
    for p in sorted(__import__("glob").glob(os.path.join(DATA, "*.csv"))):
        name = os.path.basename(p)[:-4]
        if name in ("instruments", "SP500"):
            continue
        df = pd.read_csv(p, parse_dates=["ts"])
        df = df[df.close > 0].reset_index(drop=True)
        if len(df) < 260:
            continue
        syms[name] = df
    return syms


def trades_for(syms):
    """Return dict symbol -> list of (entry_idx, exit_idx, entry_px, exit_px, pnl)."""
    out = {}
    for sym, df in syms.items():
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
        trades = []
        for t in idx:
            anchor = h[t - W:t].max()
            if ENTRY_MODE == "notextended" and c[t] > anchor * (1 + 0.03):
                continue
            entry = c[t]
            exit_day = None
            for k in range(t + 1, min(t + H + 1, n)):
                if EXIT_MODE == "tp10" and c[k] >= entry * 1.10:
                    exit_day = k
                    break
            if exit_day is None:
                exit_day = min(t + H, n - 1)
            pnl = c[exit_day] / entry - 1 - 2 * COST
            trades.append((t, exit_day, entry, c[exit_day], pnl))
        out[sym] = trades
    return out


def main():
    syms = load_symbols()
    all_tr = trades_for(syms)
    total = sum(len(v) for v in all_tr.values())

    print(f"plotting {total} trades across {len(all_tr)} symbols into {OUT}/ ...")

    # per-symbol charts
    for sym, df in syms.items():
        trades = all_tr.get(sym, [])
        if not trades:
            continue
        c = df["close"].to_numpy()
        n = len(c)
        fig, ax = plt.subplots(figsize=(15, 6))
        ax.plot(np.arange(n), c, color="#1f77b4", lw=1.1, label="close")
        for (e, x, ep, xp, pnl) in trades:
            ax.annotate("", xy=(x, xp), xytext=(e, ep),
                        arrowprops=dict(arrowstyle="-|>", color="green", lw=1.6, ls="--"))
            ax.axvspan(e, x, color="green", alpha=0.08)
            ax.plot(e, ep, marker="^", color="green", ms=9)
            ax.plot(x, xp, marker="v", color="red", ms=9)
            ax.annotate(f"{pnl:+.1f}%", xy=(x, xp), xytext=(x, xp * (1 + 0.01)),
                        fontsize=9, color="red")
        ax.set_title(f"{sym}  —  {len(trades)} trade(s)   (entry=breakout close, exit=+10% TP/20d)")
        ax.set_xlabel("trading day"); ax.set_ylabel("price")
        ax.grid(alpha=0.3)
        fig.tight_layout()
        fig.savefig(os.path.join(OUT, f"{sym}.png"), dpi=110)
        plt.close(fig)

    # overview grid of all symbols with trades
    have = {s: t for s, t in all_tr.items() if t}
    cols = 4
    rows = (len(have) + cols - 1) // cols
    fig, axes = plt.subplots(rows, cols, figsize=(cols * 4.2, rows * 2.6), squeeze=False)
    for ax, (sym, trades) in zip(axes.flat, have.items()):
        df = syms[sym]
        c = df["close"].to_numpy()
        ax.plot(c, color="#1f77b4", lw=0.9)
        for (e, x, ep, xp, _) in trades:
            ax.plot(e, ep, marker="^", color="green", ms=6)
            ax.plot(x, xp, marker="v", color="red", ms=6)
        ax.set_title(sym, fontsize=9)
        ax.tick_params(labelsize=7)
        ax.grid(alpha=0.3)
    for ax in axes.flat[len(have):]:
        ax.axis("off")
    fig.suptitle("Momentum strategy trades (green=entry, red=exit)")
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "overview.png"), dpi=110)
    plt.close(fig)

    # summary print
    for sym in sorted(have):
        tr = np.array([t[4] for t in have[sym]])
        print(f"  {sym:<12} n={len(tr):>2}  avg {100*tr.mean():>+6.2f}%  win {100*(tr>0).mean():>3.0f}%")
    print(f"\nsaved -> {OUT}/  ({len(have)} symbols)")


if __name__ == "__main__":
    main()
