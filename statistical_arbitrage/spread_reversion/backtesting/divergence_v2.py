#!/usr/bin/env python3
"""
DIVERGENCE v2 — the corrected BUY + adaptive exit.
Entry (bullish price/z divergence between TWO price lows):
  arm z<-3 -> first swing low (low1) -> a LOWER swing low (low2) where
  the Z-SCORE is HIGHER than at low1  -> BUY.
  (A lower price low with a lower z = no divergence = NO buy = kills the false positive.)
Exit — compare three rules to let big winners run:
  fixed 4% trail | progressive trail (4/6/8/10% as profit grows) | ATR trail.
Also reports MFE (max favorable excursion) to show the fat right tail.
"""
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

WINDOW, Z_ARM, CAPITAL = 60, -3.0, 15000.0
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


def zseries(pa, pb):
    n = len(pa)
    la, lb = np.log(pa), np.log(pb)
    beta, alpha = np.polyfit(lb, la, 1)
    sp = la - beta * lb - alpha
    mu = pd.Series(sp).rolling(WINDOW).mean().values
    sd = pd.Series(sp).rolling(WINDOW).std().values
    z = np.zeros(n)
    for i in range(n):
        z[i] = (sp[i] - mu[i]) / max(sd[i], 1e-6)
    return z, beta


def atr14(c):
    d = np.abs(np.diff(c, prepend=c[0]))
    out = np.zeros(len(c))
    for i in range(len(c)):
        out[i] = d[max(0, i - 13):i + 1].mean()
    return out


def swing_lows(c, L=3):
    is_low = np.zeros(len(c), dtype=bool)
    for i in range(len(c)):
        lft = c[max(0, i - L):i]
        rgt = c[i + 1:min(len(c), i + L + 1)]
        if len(lft) and len(rgt) and c[i] <= lft.min() and c[i] <= rgt.min():
            is_low[i] = True
    return is_low


def run(pa, pb, exit_mode="progressive"):
    z, beta = zseries(pa, pb)
    n = len(pa)
    atr = atr14(pa)
    low = swing_lows(pa)
    state = "ARMED"
    last_low = None              # (price, z) of the most recent swing low
    entry_px = entry_i = peak = 0.0
    trades, buys, sells, marks = [], [], [], []
    arm_i = None
    for i in range(n):
        if state == "ARMED":
            if z[i] < Z_ARM:
                state = "HUNT"
                arm_i = i
                marks.append((i, "arm", pa[i]))
        elif state == "HUNT":
            # reset the hunt when the dislocation heals (z back above -1) so a
            # fresh extreme can re-arm it — otherwise a stale first low blocks
            # later valid setups forever.
            if z[i] > -1.0 or (arm_i is not None and i - arm_i > 150):
                state = "ARMED"
                last_low = None
            elif low[i]:
                px, zi = pa[i], z[i]
                if last_low is None:
                    last_low = (px, zi)
                    marks.append((i, "low1", px))
                elif px < last_low[0]:
                    if zi > last_low[1]:
                        entry_px, entry_i, peak = px, i, px
                        buys.append((i, "buy", px))
                        marks.append((i, "low2", px))
                        state = "HOLD"
                    else:
                        last_low = (px, zi)      # lower price low but z also lower -> no divergence
                        marks.append((i, "low2", px))
        elif state == "HOLD":
            peak = max(peak, pa[i])
            profit = peak / entry_px - 1
            if exit_mode == "fixed":
                level = peak * 0.96
            elif exit_mode == "progressive":
                t = 0.10 if profit >= 0.15 else 0.08 if profit >= 0.10 else 0.06 if profit >= 0.05 else 0.04
                level = peak * (1 - t)
            else:  # atr
                level = peak - max(0.04 * peak, 2.0 * atr[i])
            if pa[i] < level:
                qty = max(int(CAPITAL / entry_px), 1)
                gross = (pa[i] - entry_px) * qty
                fees = leg_fees(entry_px, qty, "BUY") + leg_fees(pa[i], qty, "SELL")
                mfe = 100 * (pa[entry_i:i + 1].max() / entry_px - 1)
                trades.append({"in": entry_i, "out": i, "bp": entry_px, "sp": pa[i],
                               "hold": i - entry_i, "ret": 100 * (pa[i] / entry_px - 1),
                               "mfe": mfe, "net": gross - fees})
                sells.append((i, "sell", pa[i]))
                state = "ARMED"
                last_low = None
    return trades, buys, sells, marks, z, beta


def summ(A, B, mode):
    pa, pb = load(A), load(B)
    n = min(len(pa), len(pb))
    tr, *_ = run(pa[:n], pb[:n], mode)
    net = sum(t["net"] for t in tr)
    wins = sum(1 for t in tr if t["net"] > 0)
    mfe_avg = np.mean([t["mfe"] for t in tr]) if tr else 0
    return tr, net, wins, mfe_avg


print("=== CORRECTED 2-LOW DIVERGENCE ENTRY — NESTLEIND/TATASTEEL ===")
pa, pb = load("NESTLEIND"), load("TATASTEEL")
n = min(len(pa), len(pb))
for mode in ("fixed", "progressive", "atr"):
    tr, net, wins, mfe = summ("NESTLEIND", "TATASTEEL", mode)
    print(f"\n[{mode} exit]  {len(tr)} trades  net=₹{net:+.0f}  win={100*wins/max(len(tr),1):.0f}%  "
          f"avg MFE={mfe:.0f}%")
    for t in tr:
        print(f"    buy ₹{t['bp']:.0f} -> sell ₹{t['sp']:.0f}  hold {t['hold']}d  "
              f"ret {t['ret']:+.1f}%  MFE {t['mfe']:+.0f}%  net ₹{t['net']:+.0f}")

print("\n=== POOLED ACROSS WINNING PAIRS (by exit) ===")
for mode in ("fixed", "progressive", "atr"):
    alltr = []
    for A, B in WINNING:
        pa, pb = load(A), load(B)
        n = min(len(pa), len(pb))
        tr, *_ = run(pa[:n], pb[:n], mode)
        alltr += tr
    net = sum(t["net"] for t in alltr)
    wins = sum(1 for t in alltr if t["net"] > 0)
    mfe = np.mean([t["mfe"] for t in alltr]) if alltr else 0
    big = sum(1 for t in alltr if t["ret"] > 10)
    print(f"  {mode:<12} {len(alltr):>2} trades  net=₹{net:>+7.0f}  win={100*wins/max(len(alltr),1):.0f}%  "
          f"avgMFE={mfe:.0f}%  trades>10%={big}")

# ---- plot NESTLEIND/TATASTEEL with corrected entry (progressive exit) ----
pa, pb = load("NESTLEIND"), load("TATASTEEL")
n = min(len(pa), len(pb))
tr, buys, sells, marks, z, beta = run(pa[:n], pb[:n], "progressive")
dates = np.arange(n)
fig, axes = plt.subplots(2, 1, figsize=(15, 9), sharex=True)
ax = axes[0]
ax.plot(dates, pa, color="#1f77b4", lw=1.2, label="NESTLEIND")
ax.plot(dates, pb, color="#ff7f0e", lw=1.2, alpha=0.55, label="TATASTEEL")
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
ax.set_title("NESTLEIND/TATASTEEL — corrected 2-low divergence (low1 -> lower low2 with higher z = BUY ^)")
ax.legend(loc="upper left"); ax.grid(alpha=0.3)
ax = axes[1]
ax.plot(dates, z, color="gray", lw=0.8)
ax.axhline(0, color="k", lw=0.7)
ax.axhline(-3, color="g", ls="--", lw=0.8, label="-3 arm")
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
ax.set_title("Pair z — BUY only when low2 price is LOWER but low2 z is HIGHER than low1 (true divergence)")
ax.legend(loc="upper left"); ax.grid(alpha=0.3)
plt.tight_layout()
plt.savefig("backtesting/plots/NESTLEIND_TATASTEEL_divergence_v2.png", dpi=110)
print("\nsaved backtesting/plots/NESTLEIND_TATASTEEL_divergence_v2.png")
