#!/usr/bin/env python3
"""
DIVERGENCE v3 — CAUSAL backtest (ZERO look-ahead).
Entry: arm z<-3 -> confirmed low1 -> confirmed LOWER low2 whose Z is HIGHER than
low1's Z (bullish divergence) -> BUY at the CONFIRMATION bar (L=3 days after the
low, using only information available up to that bar). Focus: BUY signals for a
manual long-term trade. Reports forward returns (5/20/60d) + MFE.
"""
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

WINDOW, Z_ARM, CAPITAL, L = 60, -3.0, 15000.0, 3
WINNING = [
    ("NESTLEIND", "TATASTEEL"), ("AXISBANK", "INDUSINDBK"), ("HDFCBANK", "KOTAKBANK"),
    ("HINDUNILVR", "TATASTEEL"), ("AXISBANK", "BAJAJFINSV"), ("TCS", "HCLTECH"),
    ("RELIANCE", "TATASTEEL"), ("TCS", "WIPRO"), ("NESTLEIND", "HCLTECH"),
]


def load(name):
    return pd.read_csv(f"backtesting/data/{name}.csv")["close"].values


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


def confirmed_swing_low(j, c, L):
    """Causal: bar j is a swing low only once we've SEEN bars j+1..j+L (current bar i=j+L)."""
    lft = c[max(0, j - L):j]
    rgt = c[j + 1:j + L + 1]
    return len(lft) and len(rgt) and c[j] <= lft.min() and c[j] <= rgt.min()


def run_causal(pa, pb):
    z, beta = zseries(pa, pb)
    n = len(pa)
    buys = []
    state = "ARMED"
    last_low = None
    arm_i = None
    for i in range(n):
        # arm / reset (daily, causal)
        if state == "ARMED":
            if z[i] < Z_ARM:
                state = "HUNT"
                arm_i = i
        elif state == "HUNT":
            if z[i] > -1.0 or i - arm_i > 150:
                state = "ARMED"
                last_low = None
        # newly CONFIRMED swing low at bar j = i - L (info only up to bar i)
        j = i - L
        if j >= L and confirmed_swing_low(j, pa, L):
            pj, zj = pa[j], z[j]
            if state == "HUNT":
                if last_low is None:
                    last_low = (pj, zj, j)
                elif pj < last_low[0]:
                    if zj > last_low[1]:
                        # bullish divergence -> BUY at the confirmation bar i (causal)
                        buys.append({"conf_i": i, "conf_px": pa[i],
                                     "low_i": j, "low_px": pj, "low_z": zj,
                                     "prev_z": last_low[1], "prev_low_i": last_low[2]})
                        state = "ARMED"
                        last_low = None
                    else:
                        last_low = (pj, zj, j)
    return buys, z, beta


def enrich(buys, pa, horizons=(5, 20, 60)):
    out = []
    for b in buys:
        r = dict(b)
        r["fwd"], r["mfe60"], r["fwd60win"] = {}, 0.0, None
        i = b["conf_i"]
        for h in horizons:
            if i + h < len(pa):
                r["fwd"][h] = 100 * (pa[i + h] / pa[i] - 1)
        if i + 60 < len(pa):
            r["mfe60"] = 100 * (pa[i:i + 61].max() / pa[i] - 1)
            r["fwd60win"] = pa[i + 60] > pa[i]
        out.append(r)
    return out


def report(A, B):
    pa, pb = load(A), load(B)
    n = min(len(pa), len(pb))
    buys, z, beta = run_causal(pa[:n], pb[:n])
    rows = enrich(buys, pa[:n])
    print(f"\n=== {A}/{B} — CAUSAL divergence BUY signals ===")
    for r in rows:
        f = r["fwd"]
        fwd = " ".join(f"{h}d:{v:+.1f}%" for h, v in f.items())
        print(f"  BUY day {r['conf_i']} @ ₹{r['conf_px']:.0f} "
              f"(confirms low day {r['low_i']} ₹{r['low_px']:.0f}, z {r['prev_z']:+.2f}->{r['low_z']:+.2f})  "
              f"MFE60={r['mfe60']:+.0f}%  [{fwd}]")
    return rows


print("=== CAUSAL (no look-ahead): BUY at confirmation, L=3 ===")
all_rows = []
for A, B in WINNING:
    all_rows += report(A, B)

print("\n=== POOLED BUY-SIGNAL FORWARD STATS ===")
for h in (5, 20, 60):
    v = [r["fwd"].get(h) for r in all_rows if h in r["fwd"]]
    if v:
        print(f"  {h}d: avg={np.mean(v):+.1f}%  win={100*np.mean([x>0 for x in v]):.0f}%  (n={len(v)})")
m = [r["mfe60"] for r in all_rows if r["mfe60"]]
if m:
    print(f"  MFE60: avg={np.mean(m):+.0f}%  (n={len(m)})")



def plot_pair(A, B):
    pa, pb = load(A), load(B)
    n = min(len(pa), len(pb)); pa, pb = pa[:n], pb[:n]
    buys, z, beta = run_causal(pa, pb)
    if not buys:
        return None
    dates = np.arange(n)
    fig, axes = plt.subplots(2, 1, figsize=(15, 9), sharex=True)
    ax = axes[0]
    ax.plot(dates, pa, color="#1f77b4", lw=1.2, label=A)
    ax.plot(dates, pb, color="#ff7f0e", lw=1.2, alpha=0.55, label=B)
    for b in buys:
        ax.axvline(dates[b["low_i"]], color="gray", ls=":", lw=0.8, alpha=0.5)
        ax.scatter(dates[b["low_i"]], b["low_px"], marker="_", s=40, color="gray", zorder=4)
        ax.axvline(dates[b["conf_i"]], color="green", ls="--", lw=0.9, alpha=0.7)
        ax.scatter(dates[b["conf_i"]], b["conf_px"], marker="^", s=60, color="green",
                   edgecolors="k", lw=0.5, zorder=6)
        ax.annotate(f"BUY@{b['conf_px']:.0f}", (dates[b["conf_i"]], b["conf_px"]),
                    textcoords="offset points", xytext=(0, 6), ha="center", fontsize=7, color="green")
    ax.set_ylabel("Price ₹")
    ax.set_title(f"{A}/{B} — CAUSAL divergence: grey _ = confirmed low, green ^ = BUY at "
                 f"confirmation ({len(buys)} signals, no look-ahead)")
    ax.legend(loc="upper left"); ax.grid(alpha=0.3)
    ax = axes[1]
    ax.plot(dates, z, color="gray", lw=0.8)
    ax.axhline(0, color="k", lw=0.7)
    ax.axhline(-3, color="g", ls="--", lw=0.8, label="-3 arm")
    for b in buys:
        ax.axvline(dates[b["conf_i"]], color="green", ls="--", lw=0.9, alpha=0.7)
        ax.scatter(dates[b["low_i"]], b["low_z"], marker="o", s=35, color="gray", zorder=5)
        ax.scatter(dates[b["conf_i"]], z[b["conf_i"]], marker="^", s=50, color="green",
                   edgecolors="k", lw=0.5, zorder=6)
    ax.set_ylabel("z-score"); ax.set_xlabel("trading day (2022-2026)")
    ax.set_title("Pair z — BUY after confirmed lower low whose z is HIGHER (bullish divergence)")
    ax.legend(loc="upper left"); ax.grid(alpha=0.3)
    plt.tight_layout()
    path = f"backtesting/plots/{A}_{B}_causal.png"
    plt.savefig(path, dpi=110)
    plt.close(fig)
    return path


# ---- plot every pair that has causal signals ----
print("\n=== CAUSAL PLOTS ===")
for A, B in WINNING:
    path = plot_pair(A, B)
    if path:
        print(f"  {A}/{B}: {path}")
