#!/usr/bin/env python3
"""
NESTLEIND/TATASTEEL — "multiple lower lows + pair z confirmation" entry.
Rule:
  1. Wait for MULTIPLE consecutive LOWER LOWS in NESTLEIND (each new low lower
     than the last, by >= LL_PCT).
  2. Keep waiting while it keeps falling.
  3. BUY when price breaks back ABOVE the lower-low structure AND the pair
     z-score vs TATASTEEL is improving (NESTLEIND strengthening relative to it).
  4. Ride; sell when price turns down from the peak (trailing stop).
Long-only NESTLEIND. Plots price + z with lower lows / buy / sell marked.
"""
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

A, B = "NESTLEIND", "TATASTEEL"
WINDOW, HOLD = 60, 5
CAPITAL = 15000.0
MIN_LL = 2       # require >= this many consecutive lower lows
LL_PCT = 0.005   # a "lower low" must be >= 0.5% below the previous low
BREAK_PCT = 0.01 # buy when price closes >= 1% above the lower-low
TRAIL = 0.05     # sell when price pulls back 5% from the running high


def load(name):
    return pd.read_csv(f"backtesting/data/{name}.csv")["close"].values


def leg_fees(price, qty, side):
    v = price * qty
    brk = max(min(20.0, 0.001 * v), 5.0)
    stt = v * 0.00025 if side == "SELL" else 0.0
    stp = v * 0.00003 if side == "BUY" else 0.0
    e = v * 0.0000297; s = v * 1e-6; i = v * 1e-6
    return brk + stt + stp + e + s + i + 0.18 * (brk + e + s + i)


nestle, tata = load(A), load(B)
n = min(len(nestle), len(tata))
nestle, tata = nestle[:n], tata[:n]

la, lb = np.log(nestle), np.log(tata)
beta, alpha = np.polyfit(lb, la, 1)
sp = la - beta * lb - alpha
mu = pd.Series(sp).rolling(WINDOW).mean().values
sd = pd.Series(sp).rolling(WINDOW).std().values
z = np.zeros(n)
for i in range(n):
    z[i] = (sp[i] - mu[i]) / max(sd[i], 1e-6)

# ---- the rule ----
trades = []
events = []           # (i, kind, price)
ll_marks = []         # lower-low bars
state = "SEARCH"
ll_count, ll_low, ll_i, z_at_low = 0, nestle[0], 0, z[0]
entry_px = entry_i = peak = 0.0

for i in range(n):
    if state == "SEARCH":
        if nestle[i] < ll_low * (1 - LL_PCT):
            ll_count += 1
            ll_low = nestle[i]
            ll_i = i
            z_at_low = z[i]
            ll_marks.append((i, "ll", nestle[i]))
        else:
            # enough lower lows + price breaks back above + pair z improving
            if (ll_count >= MIN_LL
                    and nestle[i] > ll_low * (1 + BREAK_PCT)
                    and z[i] > z_at_low):
                entry_px, entry_i, peak = nestle[i], i, nestle[i]
                state = "HOLD"
                events.append((i, "buy", nestle[i]))
            # else keep searching (ll_low stays as the lowest)
    elif state == "HOLD":
        peak = max(peak, nestle[i])
        if nestle[i] < peak * (1 - TRAIL):
            qty = max(int(CAPITAL / entry_px), 1)
            gross = (nestle[i] - entry_px) * qty
            fees = leg_fees(entry_px, qty, "BUY") + leg_fees(nestle[i], qty, "SELL")
            trades.append({"in": entry_i, "out": i, "bp": entry_px, "sp": nestle[i],
                           "qty": qty, "gross": gross, "fees": fees,
                           "net": gross - fees,
                           "ret": 100 * (nestle[i] / entry_px - 1),
                           "hold": i - entry_i, "ll_count": ll_count,
                           "z_at_low": z_at_low, "z_exit": z[i]})
            events.append((i, "sell", nestle[i]))
            state = "SEARCH"
            ll_count, ll_low, ll_i, z_at_low = 0, nestle[i], i, z[i]

net = sum(t["net"] for t in trades)
wins = sum(1 for t in trades if t["net"] > 0)
print(f"lower-low signals (ll_count>= {MIN_LL} + break + z-confirm): {len(events)//1} buys")
print(f"trades: {len(trades)}  net=₹{net:+.0f} (₹{net/max(len(trades),1):+.0f}/t)  win={100*wins/max(len(trades),1):.0f}%\n")
for t in trades:
    print(f"  buy ₹{t['bp']:.0f} -> sell ₹{t['sp']:.0f}  hold {t['hold']}d  ret {t['ret']:+.1f}%  "
          f"net ₹{t['net']:+.0f}  (used {t['ll_count']} lower lows, z {t['z_at_low']:+.2f}->{t['z_exit']:+.2f})")

# ---- plot ----
dates = np.arange(n)
fig, axes = plt.subplots(2, 1, figsize=(15, 9), sharex=True)
ax = axes[0]
ax.plot(dates, nestle, color="#1f77b4", lw=1.2, label=A)
ax.plot(dates, tata, color="#ff7f0e", lw=1.2, alpha=0.55, label=B)
for i, kind, px in ll_marks:
    ax.scatter(dates[i], px, marker="_", s=40, color="gray", zorder=4)
for i, kind, px in events:
    if kind == "buy":
        ax.axvline(dates[i], color="green", ls="--", lw=0.9, alpha=0.7)
        ax.scatter(dates[i], px, marker="^", s=60, color="green", edgecolors="k", lw=0.5, zorder=6)
    else:
        ax.axvline(dates[i], color="red", ls="--", lw=0.9, alpha=0.7)
        ax.scatter(dates[i], px, marker="v", s=60, color="red", edgecolors="k", lw=0.5, zorder=6)
ax.set_ylabel("Price ₹")
ax.set_title(f"{A} vs {B} — grey _ = lower lows, green ^ = BUY (break above lower lows + z-confirm), "
             f"red v = SELL (trail {TRAIL*100:.0f}%)")
ax.legend(loc="upper left"); ax.grid(alpha=0.3)

ax = axes[1]
ax.plot(dates, z, color="gray", lw=0.8)
ax.axhline(0, color="k", lw=0.7)
ax.axhline(-2, color="g", ls="--", lw=0.8, label="-2")
ax.axhline(2, color="g", ls="--", lw=0.8)
for i, kind, px in events:
    if kind == "buy":
        ax.axvline(dates[i], color="green", ls="--", lw=0.9, alpha=0.7)
        ax.scatter(dates[i], z[i], marker="^", s=50, color="green", edgecolors="k", lw=0.5, zorder=6)
    else:
        ax.axvline(dates[i], color="red", ls="--", lw=0.9, alpha=0.7)
        ax.scatter(dates[i], z[i], marker="v", s=50, color="red", edgecolors="k", lw=0.5, zorder=6)
ax.set_ylabel("z-score vs TATASTEEL"); ax.set_xlabel("trading day (2022-2026)")
ax.set_title("Pair z — buy requires z improving from the lower-low (pair confirming recovery)")
ax.legend(loc="upper left"); ax.grid(alpha=0.3)
plt.tight_layout()
plt.savefig("backtesting/plots/NESTLEIND_TATASTEEL_lowerlows.png", dpi=110)
print("\nsaved backtesting/plots/NESTLEIND_TATASTEEL_lowerlows.png")
