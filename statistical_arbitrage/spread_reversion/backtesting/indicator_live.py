#!/usr/bin/env python3
"""
LIVE-REFRESH manual trading indicator — LONG side only, intraday 5-min (Yahoo).
Strategy: spread = ln(PA) - ln(PB), rolling z-score.
  ENTER LONG when z < -2   (spread stretched LOW -> buy the gap: BUY BANKBEES / SELL SETFNIFBK)
  EXIT        when z >= 0  (spread back to average)
Refreshes in place every REFRESH_SECS. Run with --once for a single snapshot.
"""
import math
import os
import sys
import time
from collections import deque
from datetime import datetime

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import yfinance as yf

PAIR_A, PAIR_B = "BANKBEES.NS", "SETFNIFBK.NS"
WINDOW = 6            # 6 x 5min = 30min lookback (mirrors live 60 x 30s)
WARMUP = 5
ENTRY_Z = 2.0         # enter LONG when z < -ENTRY_Z
EXIT_Z = 0.0          # exit LONG when z >= EXIT_Z
REFRESH_SECS = 60
CAPITAL = 10000.0     # 5000..20000 for qty suggestion
PERIOD, INTERVAL = "60d", "5m"
PNG = "backtesting/indicator_live.png"
ONCE = "--once" in sys.argv


def clear():
    print("\033[H\033[J", end="", flush=True)


def fetch():
    a = yf.Ticker(PAIR_A).history(period=PERIOD, interval=INTERVAL, auto_adjust=True)
    b = yf.Ticker(PAIR_B).history(period=PERIOD, interval=INTERVAL, auto_adjust=True)
    df = a["Close"].rename("pa").to_frame().join(b["Close"].rename("pb"), how="inner").dropna()
    return df


def compute(df):
    h = deque(maxlen=WINDOW)
    zs, sp = [], []
    for i in range(len(df)):
        s = math.log(df["pa"].iloc[i]) - math.log(df["pb"].iloc[i])
        h.append(s)
        sp.append(s)
        if len(h) < WARMUP:
            zs.append(float("nan"))
            continue
        m = sum(h) / len(h)
        v = sum((x - m) ** 2 for x in h) / len(h)
        zs.append((s - m) / max(math.sqrt(v), 1e-4))
    return zs, sp


LADDER = "\u2581\u2582\u2583\u2584\u2585\u2586\u2587\u2588"  # low..high blocks


def sparkline(vals, lo=-3.0, hi=3.0):
    out = []
    for z in vals:
        if math.isnan(z):
            out.append("\u00b7")
            continue
        t = max(0.0, min(1.0, (z - lo) / (hi - lo)))
        out.append(LADDER[int(round(t * (len(LADDER) - 1)))])
    return "".join(out)


def render(df):
    zs, sp = compute(df)
    pa, pb = df["pa"].iloc[-1], df["pb"].iloc[-1]
    z = zs[-1]
    spread = sp[-1]
    h = list(sp[-WINDOW:])
    mean = sum(h) / len(h)
    var = sum((x - mean) ** 2 for x in h) / len(h)
    std = max(math.sqrt(var), 1e-4)
    qty = max(int(CAPITAL / (pa + pb)), 1)

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    clear()
    print("=== LIVE LONG-ONLY INDICATOR — BANKBEES vs SETFNIFBK (5-min) ===")
    print(f"as of {now}  |  refresh {REFRESH_SECS}s  |  window={WINDOW} (~30min)  |  capital=₹{CAPITAL:,.0f}")
    print(f"BANKBEES={pa:.2f}  SETFNIFBK={pb:.2f}  spread(ln)={spread:.6f}")
    print(f"spread mean={mean:.6f}  std={std:.6f}  z={z:+.2f}  "
          f"qty suggestion={qty} (₹{qty*(pa+pb):,.0f} notional)")
    print("-" * 58)
    if math.isnan(z):
        print("STATUS: WARMING UP (need >= 5 bars)")
    elif z < -ENTRY_Z:
        print(f"STATUS: ENTER LONG ZONE  ->  BUY {qty} BANKBEES / SELL {qty} SETFNIFBK   (z={z:+.2f} < -2)")
    elif z < EXIT_Z:
        print(f"STATUS: ENTRY-APPROACH  (z={z:+.2f}; LONG only fires below -2)")
    else:
        print(f"STATUS: NEUTRAL  (z={z:+.2f} >= 0; no LONG signal)")
    print("-" * 58)
    print(f"z history (last 60 bars):")
    print("  " + sparkline(zs[-60:]))
    print("  scale: " + "\u2581" + "=-3  " + "\u2583" + "=-2 (enter)  " + "\u2585" +
          "=-0.3  " + "\u2588" + "=+3   (exit LONG at z>=0)")
    return z, qty, pa, pb


def save_png(df, zs, sp):
    x = list(range(len(df)))
    fig, ax = plt.subplots(2, 1, figsize=(12, 7))
    ax[0].plot(x, sp, color="tab:blue", lw=0.8)
    ax[0].set_ylabel("log spread")
    ax[0].axhline(sum(sp[-WINDOW:]) / len(sp[-WINDOW:]), color="k", ls="--", lw=0.6)
    ax[0].grid(alpha=0.3)
    ax[1].plot(x, zs, color="tab:orange", lw=0.8)
    ax[1].axhline(0, color="k", lw=0.6)
    ax[1].axhline(-ENTRY_Z, color="r", ls="--", lw=0.8)
    ax[1].axhline(ENTRY_Z, color="r", ls="--", lw=0.8)
    ax[1].set_ylabel("z-score")
    ax[1].set_xlabel(f"{INTERVAL} bar")
    ax[1].grid(alpha=0.3)
    ax[0].set_title("LONG-only manual indicator (enter z<-2, exit z>=0)")
    plt.tight_layout()
    plt.savefig(PNG, dpi=110)
    plt.close(fig)


def main():
    try:
        df = fetch()
    except Exception as e:
        print(f"fetch error: {e}")
        return
    zs, sp = compute(df)
    render(df)
    save_png(df, zs, sp)
    print(f"chart saved: {PNG}")
    if ONCE:
        return
    while True:
        try:
            time.sleep(REFRESH_SECS)
            df = fetch()
            zs, sp = compute(df)
            render(df)
            save_png(df, zs, sp)
        except KeyboardInterrupt:
            print("\nstopped")
            break
        except Exception as e:
            print(f"refresh error: {e}")


if __name__ == "__main__":
    main()
