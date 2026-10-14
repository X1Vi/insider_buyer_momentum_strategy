#!/usr/bin/env python3
"""
Plot BUY/SELL signals over real prices + z-score for the winning pairs.
Per-pair OLS beta. |z|>=3 -> BUY the laggard; exit on reversion / stop / 5 days.
Markers are SMALL and placed exactly at the signal-day price/z, with a thin
vertical guide line so the exact buy/sell bar is pinpointed.
"""
import os
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

WINDOW, Z_ENTER, Z_STOP, HOLD = 60, 3.0, 4.5, 5
DATA = "backtesting/data"
OUT = "backtesting/plots"

WINNING = [
    ("AXISBANK", "INDUSINDBK"), ("HDFCBANK", "KOTAKBANK"),
    ("HINDUNILVR", "TATASTEEL"), ("NESTLEIND", "TATASTEEL"),
    ("HCLTECH", "ITC"), ("TATASTEEL", "COALINDIA"),
    ("AXISBANK", "BAJAJFINSV"), ("TCS", "HCLTECH"),
    ("RELIANCE", "TATASTEEL"), ("TCS", "WIPRO"),
]


def load(name):
    return pd.read_csv(f"{DATA}/{name}.csv")["close"].values


def analyze(pa, pb):
    n = len(pa)
    la, lb = np.log(pa), np.log(pb)
    beta, alpha = np.polyfit(lb, la, 1)
    sp = la - beta * lb - alpha
    mu = pd.Series(sp).rolling(WINDOW).mean().values
    sd = pd.Series(sp).rolling(WINDOW).std().values
    z = np.zeros(n)
    for i in range(n):
        z[i] = (sp[i] - mu[i]) / max(sd[i], 1e-6)
    buys, sells = [], []          # (index, leg)  leg: 1 = buy B, 0 = buy A
    state, entry_z, held, last, cur_leg = "FLAT", 0.0, 0, -10**9, 0
    for i in range(n):
        if state == "FLAT":
            if abs(z[i]) >= Z_ENTER and i >= last + HOLD:
                cur_leg = 1 if z[i] > 0 else 0
                buys.append((i, cur_leg))
                state, entry_z, held, last = "POSITION", z[i], 0, i
        else:
            held += 1
            exit_now = ((entry_z > 0 and z[i] <= 0) or (entry_z < 0 and z[i] >= 0)
                        or abs(z[i]) >= Z_STOP or held >= HOLD)
            if exit_now:
                sells.append((i, cur_leg))
                state = "FLAT"
    return pa, pb, z, beta, buys, sells


def plot_pair(A, B):
    pa, pb = load(A), load(B)
    n = min(len(pa), len(pb))
    pa, pb = pa[:n], pb[:n]
    pa, pb, z, beta, buys, sells = analyze(pa, pb)
    dates = np.arange(n)

    fig, axes = plt.subplots(2, 1, figsize=(15, 9), sharex=True)
    ax = axes[0]
    ax.plot(dates, pa, color="#1f77b4", lw=1.2, label=A)
    ax.plot(dates, pb, color="#ff7f0e", lw=1.2, label=B)
    for i, leg in buys:
        color = "#ff7f0e" if leg else "#1f77b4"
        y = pb[i] if leg else pa[i]
        sym = B if leg else A
        ax.axvline(dates[i], color=color, ls=":", lw=0.7, alpha=0.4)
        ax.scatter(dates[i], y, marker="^", s=38, color=color, edgecolors="k", lw=0.5, zorder=5)
        ax.annotate(f"B {sym}", (dates[i], y), textcoords="offset points", xytext=(0, 5),
                    ha="center", fontsize=6, color=color)
    for i, leg in sells:
        color = "#1f77b4" if leg else "#ff7f0e"
        y = pa[i] if leg else pb[i]
        ax.axvline(dates[i], color="red", ls=":", lw=0.7, alpha=0.4)
        ax.scatter(dates[i], y, marker="v", s=34, color="red", edgecolors="k", lw=0.5, zorder=5)
        ax.annotate("S", (dates[i], y), textcoords="offset points", xytext=(0, -7),
                    ha="center", fontsize=6, color="red")
    ax.set_ylabel("Price ₹")
    ax.set_title(f"{A} vs {B} — ^ = BUY the laggard at |z|>=3, v = SELL (vertical line = exact bar), "
                 f"beta={beta:.3f}")
    ax.legend(loc="upper left"); ax.grid(alpha=0.3)

    ax = axes[1]
    ax.plot(dates, z, color="gray", lw=0.8)
    ax.axhline(0, color="k", lw=0.7)
    ax.axhline(Z_ENTER, color="g", ls="--", lw=0.8, label="+3")
    ax.axhline(-Z_ENTER, color="g", ls="--", lw=0.8)
    ax.axhline(Z_STOP, color="r", ls=":", lw=0.8, label="stop ±4.5")
    ax.axhline(-Z_STOP, color="r", ls=":", lw=0.8)
    for i, leg in buys:
        ax.axvline(dates[i], color="green", ls=":", lw=0.7, alpha=0.4)
        ax.scatter(dates[i], z[i], marker="^", s=36, color="green", edgecolors="k", lw=0.5, zorder=5)
    for i, leg in sells:
        ax.axvline(dates[i], color="red", ls=":", lw=0.7, alpha=0.4)
        ax.scatter(dates[i], z[i], marker="v", s=32, color="red", edgecolors="k", lw=0.5, zorder=5)
    ax.set_ylabel("z-score"); ax.set_xlabel("trading day (2022-2026)")
    ax.set_title("Gap z-score — BUY the laggard when |z|>=3, SELL when z returns to 0")
    ax.legend(loc="upper left"); ax.grid(alpha=0.3)

    plt.tight_layout()
    os.makedirs(OUT, exist_ok=True)
    path = f"{OUT}/{A}_{B}.png"
    plt.savefig(path, dpi=110)
    plt.close(fig)
    return path, len(buys)


if __name__ == "__main__":
    for A, B in WINNING:
        try:
            path, ns = plot_pair(A, B)
            print(f"{A}/{B}: {ns} BUY signals -> {path}")
        except Exception as e:
            print(f"{A}/{B}: ERROR {e}")
