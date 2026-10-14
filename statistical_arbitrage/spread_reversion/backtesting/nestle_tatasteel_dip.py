#!/usr/bin/env python3
"""
NESTLEIND/TATASTEEL — "lower low" dip strategy.
On a BUY signal in NESTLEIND (pair z<-3, NESTLEIND is the laggard):
  WAIT for a LOWER LOW (a new N-day low), BUY there,
  RIDE the higher-highs, and SELL when price starts moving DOWN from the peak
  (trailing stop below the running high).
Long-only NESTLEIND. Reports trades, win rate, net P&L @ ₹15k vs the baseline.
"""
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

A, B = "NESTLEIND", "TATASTEEL"
WINDOW, Z_ENTER, HOLD = 60, 3.0, 5
CAPITAL = 15000.0
DIP_NDAYS = 20      # a "lower low" = new N-day low after the signal
TRAIL = 0.04        # sell when price pulls back 4% from the running high


def load(name):
    return pd.read_csv(f"backtesting/data/{name}.csv")["close"].values


def leg_fees(price, qty, side):
    v = price * qty
    brk = max(min(20.0, 0.001 * v), 5.0)
    stt = v * 0.00025 if side == "SELL" else 0.0
    stp = v * 0.00003 if side == "BUY" else 0.0
    e = v * 0.0000297; s = v * 1e-6; i = v * 1e-6
    return brk + stt + stp + e + s + i + 0.18 * (brk + e + s + i)


def run(pa, pb, exit_mode):
    """exit_mode: 'baseline' (5d hold) | 'trail' (ride higher highs, trailing stop)."""
    n = len(pa)
    la, lb = np.log(pa), np.log(pb)
    beta, alpha = np.polyfit(lb, la, 1)
    sp = la - beta * lb - alpha
    mu = pd.Series(sp).rolling(WINDOW).mean().values
    sd = pd.Series(sp).rolling(WINDOW).std().values
    z = np.zeros(n)
    for i in range(n):
        z[i] = (sp[i] - mu[i]) / max(sd[i], 1e-6)

    trades = []
    state, entry_px, entry_i, peak = "FLAT", 0.0, 0, 0.0
    last = -10**9
    for i in range(n):
        if state == "FLAT":
            if z[i] < -Z_ENTER and i >= last + HOLD:
                state = "WAIT"
                last = i
        elif state == "WAIT":
            # lower low: new N-day low
            if i >= DIP_NDAYS and pa[i] < pa[i - DIP_NDAYS:i].min():
                entry_px, entry_i, peak = pa[i], i, pa[i]
                state = "HOLD"
        elif state == "HOLD":
            peak = max(peak, pa[i])
            if exit_mode == "baseline":
                exit_now = (i - entry_i >= 5)
            else:
                exit_now = pa[i] < peak * (1 - TRAIL)
            if exit_now:
                qty = max(int(CAPITAL / entry_px), 1)
                gross = (pa[i] - entry_px) * qty
                fees = leg_fees(entry_px, qty, "BUY") + leg_fees(pa[i], qty, "SELL")
                trades.append({"in": entry_i, "out": i, "bp": entry_px, "sp": pa[i],
                               "qty": qty, "gross": gross, "fees": fees,
                               "net": gross - fees,
                               "ret": 100 * (pa[i] / entry_px - 1),
                               "hold": i - entry_i})
                state = "FLAT"
    return trades, beta


def summary(name, trades):
    if not trades:
        print(f"{name}: 0 completed trades")
        return 0.0
    net = sum(t["net"] for t in trades)
    wins = sum(1 for t in trades if t["net"] > 0)
    print(f"{name}: {len(trades)} trades, net=₹{net:+.0f} (₹{net/len(trades):+.0f}/t), "
          f"win={100*wins/len(trades):.0f}%")
    for t in trades:
        print(f"    buy ₹{t['bp']:.0f} -> sell ₹{t['sp']:.0f}  hold {t['hold']}d  "
              f"ret {t['ret']:+.1f}%  net ₹{t['net']:+.0f}")
    return net


nestle, tata = load(A), load(B)
n = min(len(nestle), len(tata))
nestle, tata = nestle[:n], tata[:n]

print("=== BASELINE (z<-3 -> buy NESTLEIND, 5-day hold) ===")
bt, _ = run(nestle, tata, "baseline")
b_net = summary("baseline", bt)

print("\n=== LOWER-LOW DIP (wait N-day low, ride higher-highs, trail stop) ===")
dt, beta = run(nestle, tata, "trail")
d_net = summary("lower-low dip (trail)", dt)

print(f"\nVERDICT: dip net ₹{d_net:+.0f} vs baseline ₹{b_net:+.0f} -> "
      f"{'INCREASED' if d_net > b_net else 'DECREASED' or 'same' if d_net == b_net else 'DECREASED'}")

# ---- plot ----
n = len(nestle)
la, lb = np.log(nestle), np.log(tata)
bb, aa = np.polyfit(lb, la, 1)
sp = la - bb * lb - aa
mu = pd.Series(sp).rolling(WINDOW).mean().values
sd = pd.Series(sp).rolling(WINDOW).std().values
z = np.zeros(n)
for i in range(n):
    z[i] = (sp[i] - mu[i]) / max(sd[i], 1e-6)

events = []  # (i, kind)
state, last = "FLAT", -10**9
for i in range(n):
    if state == "FLAT":
        if z[i] < -Z_ENTER and i >= last + HOLD:
            state = "WAIT"; last = i; events.append((i, "signal"))
    elif state == "WAIT":
        if i >= DIP_NDAYS and nestle[i] < nestle[i - DIP_NDAYS:i].min():
            events.append((i, "buy")); state = "HOLD"; peak = nestle[i]
    elif state == "HOLD":
        peak = max(peak, nestle[i])
        if nestle[i] < peak * (1 - TRAIL):
            events.append((i, "sell")); state = "FLAT"

dates = np.arange(n)
fig, axes = plt.subplots(2, 1, figsize=(15, 9), sharex=True)
ax = axes[0]
ax.plot(dates, nestle, color="#1f77b4", lw=1.2, label=A)
ax.plot(dates, tata, color="#ff7f0e", lw=1.2, alpha=0.55, label=B)
for i, kind in events:
    if kind == "signal":
        ax.axvline(dates[i], color="gray", ls=":", lw=0.7, alpha=0.5)
    elif kind == "buy":
        ax.axvline(dates[i], color="green", ls="--", lw=0.9, alpha=0.7)
        ax.scatter(dates[i], nestle[i], marker="^", s=55, color="green", edgecolors="k", lw=0.5, zorder=6)
    else:
        ax.axvline(dates[i], color="red", ls="--", lw=0.9, alpha=0.7)
        ax.scatter(dates[i], nestle[i], marker="v", s=55, color="red", edgecolors="k", lw=0.5, zorder=6)
ax.set_ylabel("Price ₹")
ax.set_title(f"{A} vs {B} — grey | = z<-3 signal (wait), green ^ = BUY at lower low, "
             f"red v = SELL when it turns down from the high (trail {TRAIL*100:.0f}%)")
ax.legend(loc="upper left"); ax.grid(alpha=0.3)

ax = axes[1]
ax.plot(dates, z, color="gray", lw=0.8)
ax.axhline(0, color="k", lw=0.7)
ax.axhline(-Z_ENTER, color="g", ls="--", lw=0.8, label="-3")
for i, kind in events:
    if kind == "signal":
        ax.scatter(dates[i], z[i], marker="o", s=30, color="gray", zorder=5)
    elif kind == "buy":
        ax.axvline(dates[i], color="green", ls="--", lw=0.9, alpha=0.7)
        ax.scatter(dates[i], z[i], marker="^", s=45, color="green", edgecolors="k", lw=0.5, zorder=6)
    else:
        ax.axvline(dates[i], color="red", ls="--", lw=0.9, alpha=0.7)
        ax.scatter(dates[i], z[i], marker="v", s=45, color="red", edgecolors="k", lw=0.5, zorder=6)
ax.set_ylabel("z-score"); ax.set_xlabel("trading day (2022-2026)")
ax.set_title("Pair z — signal (o) -> buy at lower low (^) -> sell at trend turn (v)")
ax.legend(loc="upper left"); ax.grid(alpha=0.3)
plt.tight_layout()
plt.savefig("backtesting/plots/NESTLEIND_TATASTEEL_lowerlow.png", dpi=110)
print("\nsaved backtesting/plots/NESTLEIND_TATASTEEL_lowerlow.png")
