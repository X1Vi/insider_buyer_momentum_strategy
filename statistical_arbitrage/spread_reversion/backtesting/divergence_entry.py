#!/usr/bin/env python3
"""
TRADING INTENT — PAIR DISLOCATION / CAPITULATION ENTRY (divergence-confirmed).

  z-score is NOT the entry. z < -3 only ARMS a hunt.
  After the arm: wait for the target leg (the beaten-down laggard) to make a
  POST-SIGNAL LOWER LOW. The BUY fires when PRICE makes a new lower low but the
  pair Z-SCORE does NOT make a new low (price-z divergence = capitulation, the
  statistical dislocation stopped worsening). Then ride the recovery and exit
  on a 4% trailing reversal off the post-entry high.
"""
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

WINDOW, Z_ARM, TRAIL, CAPITAL = 60, -3.0, 0.04, 15000.0
WINNING = [
    ("NESTLEIND", "TATASTEEL"), ("AXISBANK", "INDUSINDBK"), ("HDFCBANK", "KOTAKBANK"),
    ("HINDUNILVR", "TATASTEEL"), ("AXISBANK", "BAJAJFINSV"), ("TCS", "HCLTECH"),
    ("RELIANCE", "TATASTEEL"), ("TCS", "WIPRO"), ("NESTLEIND", "HCLTECH"),
]


def load(name):
    return pd.read_csv(f"backtesting/data/{name}.csv")["close"].values


def leg_fees(price, qty, side):
    v = price * qty
    brk = max(min(20.0, 0.001 * v), 5.0)
    stt = v * 0.00025 if side == "SELL" else 0.0
    stp = v * 0.00003 if side == "BUY" else 0.0
    e = v * 0.0000297; s = v * 1e-6; i = v * 1e-6
    return brk + stt + stp + e + s + i + 0.18 * (brk + e + s + i)


def run(pa, pb, arm=Z_ARM):
    n = len(pa)
    la, lb = np.log(pa), np.log(pb)
    beta, alpha = np.polyfit(lb, la, 1)
    sp = la - beta * lb - alpha
    mu = pd.Series(sp).rolling(WINDOW).mean().values
    sd = pd.Series(sp).rolling(WINDOW).std().values
    z = np.zeros(n)
    for i in range(n):
        z[i] = (sp[i] - mu[i]) / max(sd[i], 1e-6)

    state = "ARMED"
    p_low = z_low = None
    trades, buys, sells, marks = [], [], [], []
    entry_px = entry_i = peak = 0.0
    for i in range(n):
        if state == "ARMED":
            if z[i] < arm:
                state = "HUNT"
                p_low, z_low = pa[i], z[i]
                marks.append((i, "arm", pa[i]))
        elif state == "HUNT":
            if pa[i] < p_low:
                if z[i] >= z_low:
                    entry_px, entry_i, peak = pa[i], i, pa[i]
                    buys.append((i, "buy", pa[i]))
                    state = "HOLD"
                else:
                    p_low, z_low = pa[i], z[i]
                    marks.append((i, "ll", pa[i]))
            else:
                if z[i] < z_low:
                    z_low = z[i]
        elif state == "HOLD":
            peak = max(peak, pa[i])
            if pa[i] < peak * (1 - TRAIL):
                qty = max(int(CAPITAL / entry_px), 1)
                gross = (pa[i] - entry_px) * qty
                fees = leg_fees(entry_px, qty, "BUY") + leg_fees(pa[i], qty, "SELL")
                trades.append({"in": entry_i, "out": i, "bp": entry_px, "sp": pa[i],
                               "hold": i - entry_i, "ret": 100 * (pa[i] / entry_px - 1),
                               "net": gross - fees})
                sells.append((i, "sell", pa[i]))
                state = "ARMED"
    return trades, buys, sells, marks, z, beta


def plot_pair(A, B, out="backtesting/plots"):
    pa, pb = load(A), load(B)
    n = min(len(pa), len(pb))
    pa, pb = pa[:n], pb[:n]
    tr, buys, sells, marks, z, beta = run(pa, pb)
    dates = np.arange(n)
    fig, axes = plt.subplots(2, 1, figsize=(15, 9), sharex=True)
    ax = axes[0]
    ax.plot(dates, pa, color="#1f77b4", lw=1.2, label=A)
    ax.plot(dates, pb, color="#ff7f0e", lw=1.2, alpha=0.55, label=B)
    for i, kind, px in marks:
        if kind == "arm":
            ax.axvline(dates[i], color="gray", ls=":", lw=0.8, alpha=0.5)
        else:
            ax.scatter(dates[i], px, marker="_", s=40, color="gray", zorder=4)
    for i, kind, px in buys:
        ax.axvline(dates[i], color="green", ls="--", lw=0.9, alpha=0.7)
        ax.scatter(dates[i], px, marker="^", s=60, color="green", edgecolors="k", lw=0.5, zorder=6)
    for i, kind, px in sells:
        ax.axvline(dates[i], color="red", ls="--", lw=0.9, alpha=0.7)
        ax.scatter(dates[i], px, marker="v", s=60, color="red", edgecolors="k", lw=0.5, zorder=6)
    ax.set_ylabel("Price ₹")
    ax.set_title(f"{A} vs {B} — arm z<-3 (grey |), lower lows (_), DIVERGENCE BUY (^), trail 4% SELL (v)")
    ax.legend(loc="upper left"); ax.grid(alpha=0.3)
    ax = axes[1]
    ax.plot(dates, z, color="gray", lw=0.8)
    ax.axhline(0, color="k", lw=0.7)
    ax.axhline(-3, color="g", ls="--", lw=0.8, label="-3 arm")
    ax.axhline(3, color="g", ls="--", lw=0.8)
    for i, kind, px in marks:
        if kind == "arm":
            ax.scatter(dates[i], z[i], marker="o", s=30, color="gray", zorder=5)
        else:
            ax.scatter(dates[i], z[i], marker="_", s=30, color="gray", zorder=4)
    for i, kind, px in buys:
        ax.axvline(dates[i], color="green", ls="--", lw=0.9, alpha=0.7)
        ax.scatter(dates[i], z[i], marker="^", s=50, color="green", edgecolors="k", lw=0.5, zorder=6)
    for i, kind, px in sells:
        ax.axvline(dates[i], color="red", ls="--", lw=0.9, alpha=0.7)
        ax.scatter(dates[i], z[i], marker="v", s=50, color="red", edgecolors="k", lw=0.5, zorder=6)
    ax.set_ylabel("z-score"); ax.set_xlabel("trading day (2022-2026)")
    ax.set_title("Pair z — BUY when price makes a lower low but z does NOT (price-z divergence)")
    ax.legend(loc="upper left"); ax.grid(alpha=0.3)
    plt.tight_layout()
    import os
    os.makedirs(out, exist_ok=True)
    path = f"{out}/{A}_{B}_divergence.png"
    plt.savefig(path, dpi=110)
    plt.close(fig)
    return path, len(tr)


if __name__ == "__main__":
    results = []
    for A, B in WINNING:
        pa, pb = load(A), load(B)
        n = min(len(pa), len(pb))
        tr, buys, sells, marks, z, beta = run(pa[:n], pb[:n])
        wins = sum(1 for t in tr if t["net"] > 0)
        wr = 100 * wins / max(len(tr), 1)
        results.append((A, B, wr, len(tr), sum(t["net"] for t in tr)))
        print(f"{A}/{B:<16} buys={len(buys):>2} trades={len(tr):>2}  win={wr:>3.0f}%  net=₹{sum(t['net'] for t in tr):+.0f}")

    top = sorted([r for r in results if r[2] > 0 and r[3] > 0], key=lambda r: -r[2])
    print(f"\n=== PLOTTING HIGHEST-WIN-RATE PAIRS ({len(top)}) ===")
    for A, B, wr, nt, net in top:
        path, _ = plot_pair(A, B)
        print(f"  {A}/{B}: win={wr:.0f}% ({nt} trades, net ₹{net:+.0f}) -> {path}")
