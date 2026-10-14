#!/usr/bin/env python3
"""plot_buyer_vs_us.py — when the insider bought vs when WE traded.

For the most-traded symbols, plots price with:
  blue ●   = insider (major) market-buy date      (when THEY placed the trade)
  green ▲  = OUR entry                            (when we placed the trade)
  red  ✕   = OUR exit

Variant B (insider bias + above-200DMA&RSI>50 entry + 50DMA exit).
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
from backtest_insider import load_events, load_px, rsi  # noqa: E402

MIN_VALUE, COST, WATCH, MAX_HOLD = 2.5e6, 0.0075, 20, 250
OUT = HERE / "plots" / "buyer_vs_us"
OUT.mkdir(parents=True, exist_ok=True)


def trades_for(sym, ev):
    px = load_px(sym)
    if px is None:
        return None, None
    idx = px.index
    c = px["close"].to_numpy(float)
    ser = pd.Series(c, index=idx)
    sma200 = ser.rolling(200).mean().to_numpy()
    sma50 = ser.rolling(50).mean().to_numpy()
    r = rsi(px["close"]).to_numpy()
    rows = []
    for t in ev[ev["symbol"] == sym]["d"].to_numpy():
        start = np.searchsorted(idx, np.datetime64(t))
        ei = None
        for e in range(start, min(start + WATCH, len(idx) - 2)):
            if np.isfinite(sma200[e]) and c[e] > sma200[e] and np.isfinite(r[e]) and r[e] > 50:
                ei = e + 1
                break
        if ei is None or ei >= len(idx) - 2:
            continue
        xi = min(ei + MAX_HOLD, len(idx) - 1)
        for x in range(ei + 1, min(ei + MAX_HOLD, len(idx) - 1)):
            if np.isfinite(sma50[x]) and c[x] < sma50[x]:
                xi = x + 1
                break
        rows.append(dict(entry_date=idx[ei], exit_date=idx[min(xi, len(idx) - 1)],
                         net=px["open"].iloc[ei] and px["open"].iloc[ei] / px["open"].iloc[ei] - 1))
    return px, pd.DataFrame(rows)


def main():
    ev = load_events(MIN_VALUE)
    # rank symbols by number of our trades
    counts = {}
    cache = {}
    for s in sorted(set(ev["symbol"])):
        px, tr = trades_for(s, ev)
        if tr is not None and len(tr):
            counts[s] = len(tr); cache[s] = (px, tr)
    top = sorted(counts, key=counts.get, reverse=True)[:6]
    print("plotting:", {s: counts[s] for s in top})
    for s in top:
        px, tr = cache[s]
        buys = ev[ev["symbol"] == s].dropna(subset=["trade_date"])
        fig, ax = plt.subplots(figsize=(13, 5.5))
        ax.plot(px.index, px["close"].values, color="#333", lw=0.9, zorder=1)
        ax.scatter(buys["trade_date"],
                   px["close"].reindex(buys["trade_date"], method="nearest"),
                   marker="o", s=28, color="#4575b4", alpha=0.7, edgecolor="white",
                   linewidth=0.3, label=f"insider BOUGHT ({len(buys)})", zorder=3)
        ax.scatter(tr["entry_date"],
                   px["close"].reindex(tr["entry_date"], method="nearest"),
                   marker="^", s=90, color="#1a9850", edgecolor="white", linewidth=0.4,
                   label=f"WE entered ({len(tr)})", zorder=4)
        ax.scatter(tr["exit_date"],
                   px["close"].reindex(tr["exit_date"], method="nearest"),
                   marker="x", s=55, color="#d73027", lw=1.1, label="we exited", zorder=4)
        ax.set_title(f"{s} — insider buys vs our trades (gap = we wait for confirmation)")
        ax.set_ylabel("price (Rs, adj)")
        ax.legend(fontsize=8, loc="upper left"); ax.grid(alpha=0.25)
        fig.tight_layout(); fig.savefig(OUT / f"{s}.png", dpi=140); plt.close(fig)
        print(f"  -> {(OUT/f'{s}.png').relative_to(HERE)}")


if __name__ == "__main__":
    main()
