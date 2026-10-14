#!/usr/bin/env python3
"""
Gap win-rate deep-dive for HDFCBANK/KOTAKBANK (+ BANKBEES/NIFTYBEES as index refs).
Answers: (1) do volume/indicator filters raise win rate? (2) who rises first — index
ETFs or the stocks? (3) same-day exit win rate, (4) the OPPOSITE direction, (5) stability.
"""
import numpy as np
import pandas as pd
import yfinance as yf

BETA, ALPHA = 1.1622, 0.2189   # spread = ln(hdfc) - BETA*ln(kotak) + ALPHA  (calibrated)


def load(t):
    h = yf.Ticker(t).history(start="2022-01-01", end="2026-08-29")
    return h


hdfc, kotak = load("HDFCBANK.NS"), load("KOTAKBANK.NS")
bb, nb = load("BANKBEES.NS"), load("NIFTYBEES.NS")
d = pd.DataFrame({
    "hc": hdfc["Close"], "hv": hdfc["Volume"],
    "kc": kotak["Close"], "kv": kotak["Volume"],
    "bc": bb["Close"], "bv": bb["Volume"],
    "nc": nb["Close"], "nv": nb["Volume"],
}).dropna()
print(f"bars {len(d)}  {d.index.min().date()} -> {d.index.max().date()}")

# ---- gap z-series (correct Rust-equivalent logic) ----
spread = np.log(d["hc"]) - BETA * np.log(d["kc"]) + ALPHA
mu = spread.rolling(60).mean()
sd = spread.rolling(60).std()
z = ((spread - mu) / sd).fillna(0).values
hc, kc = d["hc"].values, d["kc"].values
hv, kv = d["hv"].values, d["kv"].values
bc, nc = d["bc"].values, d["nc"].values


sp = spread.values

def run_signal(hold, mode="laggard", zthr=3.0, filt=None, name=""):
    """mode: 'laggard' (buy stretched-behind), 'leader' (buy stretched-ahead, opposite)."""
    n = win = 0
    gross = 0.0
    last = -10**9
    i = 0
    while i < len(sp):
        if abs(z[i]) >= zthr and i + hold < len(sp) and i >= last + hold:
            f = sp[i + hold] - sp[i]
            if filt is not None and not filt(i):
                i += 1
                continue
            if mode == "laggard":
                # buy the laggard (the cheap leg)
                px_lag = kc[i] if z[i] > 0 else hc[i]
                ok = (z[i] > 0 and f < 0) or (z[i] < 0 and f > 0)
            else:  # leader (opposite): buy the stretched-ahead leg, momentum continuation
                px_lag = hc[i] if z[i] > 0 else kc[i]
                ok = (z[i] > 0 and f > 0) or (z[i] < 0 and f < 0)
            qty = max(15000.0 / px_lag, 1.0)
            gross += abs(f) * px_lag * qty
            if ok:
                win += 1
            n += 1
            last = i
            i += 1
        else:
            i += 1
    fees = 35.0 * n
    net = gross - fees
    return n, 100 * win / max(n, 1), gross, net


def show(title, n, wr, gross, net):
    print(f"  {title:<58} n={n:>3}  win={wr:>4.0f}%  net=₹{net:>+7.0f} (₹{net/max(n,1):+.0f}/t)")


print("\n=== 1. BASELINE + FILTERS (z>=3, 5-day hold, long the laggard) ===")
show("baseline", *run_signal(5, "laggard"))
# volume filter: laggard volume surge (vol5/vol20 > 1.2) at signal
show("laggard vol surge >1.2", *run_signal(5, "laggard", filt=lambda i: kv[i] / np.mean(kv[max(0, i-20):i+1]) > 1.2))
show("laggard vol surge >1.5", *run_signal(5, "laggard", filt=lambda i: kv[i] / np.mean(kv[max(0, i-20):i+1]) > 1.5))
# leader volume high (gap driven by heavy leader volume)
show("leader vol >1.2", *run_signal(5, "laggard", filt=lambda i: hv[i] / np.mean(hv[max(0, i-20):i+1]) > 1.2))
# both above 20d SMA (uptrend context)
sma20_h = pd.Series(hc).rolling(20).mean().values
sma20_k = pd.Series(kc).rolling(20).mean().values
show("both > SMA20", *run_signal(5, "laggard", filt=lambda i: hc[i] > sma20_h[i] and kc[i] > sma20_k[i]))
# laggard still below its 20d high (hasn't caught up) AND vol surge
hi20_h = pd.Series(hc).rolling(20).max().values
hi20_k = pd.Series(kc).rolling(20).max().values
show("laggard < 20d high + vol>1.2",
     *run_signal(5, "laggard", filt=lambda i: (kc[i] < hi20_k[i] and kv[i] / np.mean(kv[max(0, i-20):i+1]) > 1.2)
                 or (hc[i] < hi20_h[i] and hv[i] / np.mean(hv[max(0, i-20):i+1]) > 1.2)))
# index confirmation: BANKBEES up over last 3d
ret3_b = np.concatenate([[0], np.diff(bc)]) if False else pd.Series(bc).pct_change(3).values
show("index(BNKBEES)+3d", *run_signal(5, "laggard", filt=lambda i: ret3_b[i] > 0))

print("\n=== 2. HOLD HORIZON (baseline z>=3, laggard) ===")
for hld in (1, 2, 3, 5):
    show(f"hold {hld}d", *run_signal(hld, "laggard"))

print("\n=== 3. OPPOSITE DIRECTION (z>=3, buy the LEADER = stretched-ahead leg) ===")
for hld in (1, 3, 5):
    show(f"buy leader hold {hld}d", *run_signal(hld, "leader"))

print("\n=== 4. STABILITY (baseline 5d, yearly) ===")
years = d.index.year.unique()
for yr in years:
    mask = (d.index.year == yr)
    # subset logic: restrict signals to that year
    def yr_run():
        n = win = 0
        i = 0
        zsub = np.where(mask, z, 0)
        while i < len(spread):
            if abs(zsub[i]) >= 3.0 and i + 5 < len(spread) and mask[i]:
                f = spread[i + 5] - spread[i]
                ok = (zsub[i] > 0 and f < 0) or (zsub[i] < 0 and f > 0)
                if ok:
                    win += 1
                n += 1
                i += 5
            else:
                i += 1
        return n, 100 * win / max(n, 1)
    n, wr = yr_run()
    print(f"  {yr}: signals={n:>3}  win={wr:>4.0f}%")

print("\n=== 5. WHO RISES FIRST? daily-return cross-correlation (leader index t vs stock t+k) ===")
def xcorr(lead, fol, name):
    rl = pd.Series(lead).pct_change().dropna()
    rf = pd.Series(fol).pct_change().dropna()
    out = []
    for k in (0, 1, 2, 3):
        x = rl.iloc[: len(rl) - k] if k else rl
        y = rf.iloc[k:] if k else rf
        n = min(len(x), len(y))
        xa, ya = x.iloc[:n].dropna().values, y.iloc[:n].dropna().values
        m = min(len(xa), len(ya))
        out.append(np.corrcoef(xa[:m], ya[:m])[0, 1])
    print(f"  {name:<28} corr t,t+1..t+3: " + " ".join(f"{c:+.3f}" for c in out))

xcorr(bc, hc, "BANKBEES -> HDFCBANK")
xcorr(bc, kc, "BANKBEES -> KOTAKBANK")
xcorr(nc, hc, "NIFTYBEES -> HDFCBANK")
xcorr(nc, kc, "NIFTYBEES -> KOTAKBANK")
xcorr(hc, kc, "HDFCBANK -> KOTAKBANK")
xcorr(kc, hc, "KOTAKBANK -> HDFCBANK")
