#!/usr/bin/env python3
"""
Pair gap screener — run the HDFC/KOTAK-style gap strategy (z>=3, 5-day hold, buy the
laggard, dedup non-overlap) across a universe of liquid NSE names, with the
leader-volume filter. Finds pairs where BOTH win rate and trade count hold up.
"""
import numpy as np
import pandas as pd
import yfinance as yf

UNIVERSE = {
    "RELIANCE": "RELIANCE.NS", "HDFCBANK": "HDFCBANK.NS", "ICICIBANK": "ICICIBANK.NS",
    "KOTAKBANK": "KOTAKBANK.NS", "AXISBANK": "AXISBANK.NS", "SBIN": "SBIN.NS",
    "INDUSINDBK": "INDUSINDBK.NS", "INFY": "INFY.NS", "TCS": "TCS.NS",
    "HCLTECH": "HCLTECH.NS", "WIPRO": "WIPRO.NS", "ITC": "ITC.NS",
    "HINDUNILVR": "HINDUNILVR.NS", "NESTLEIND": "NESTLEIND.NS",
    "TATASTEEL": "TATASTEEL.NS", "JSWSTEEL": "JSWSTEEL.NS", "HINDALCO": "HINDALCO.NS",
    "COALINDIA": "COALINDIA.NS", "BAJFINANCE": "BAJFINANCE.NS", "BAJAJFINSV": "BAJAJFINSV.NS",
}
WINDOW, ZTHR, HOLD = 60, 3.0, 5


def load(name, t):
    h = yf.Ticker(t).history(start="2022-01-01", end="2026-08-29")
    if not isinstance(h, pd.DataFrame) or len(h) < 400:
        return None
    return pd.DataFrame({"c": h["Close"], "v": h["Volume"]})


data = {}
for name, t in UNIVERSE.items():
    d = load(name, t)
    if d is not None:
        data[name] = d
print(f"loaded {len(data)} names")


def gap_strategy(pa, va, pb, vb, use_vol_filter=False):
    """Return (signals, win_rate_pct, net_rs_per_trade) for pair A(laggard pool)/B."""
    n = len(pa)
    spread = np.log(pa) - np.log(pb)   # beta fixed at 1.0 for screen; refine later per-pair
    # beta = 1.0 means equal-weight log gap; this is a screen, per-pair OLS comes next
    mu = pd.Series(spread).rolling(WINDOW).mean()
    sd = pd.Series(spread).rolling(WINDOW).std()
    z = ((spread - mu) / sd).values
    sp = spread
    last = -10**9
    n_sig = win = 0
    gross = 0.0
    vola20 = pd.Series(va).rolling(20).mean().values
    volb20 = pd.Series(vb).rolling(20).mean().values
    for i in range(n):
        if abs(z[i]) >= ZTHR and i + HOLD < n and i >= last + HOLD:
            # z>0 => A expensive => B is laggard (buy B); z<0 => buy A
            lag_i = 1 if z[i] > 0 else 0
            lag_v = volb20[i] if lag_i else vola20[i]
            lead_v = vola20[i] if lag_i else volb20[i]
            if use_vol_filter and not (lead_v > 0 and lead_v > 1.2 * (vola20[i] if not lag_i else volb20[i])):
                i += 0
                continue
            f = sp[i + HOLD] - sp[i]
            ok = (z[i] > 0 and f < 0) or (z[i] < 0 and f > 0)
            px_lag = pb[i] if lag_i else pa[i]
            qty = max(15000.0 / px_lag, 1.0)
            gross += abs(f) * px_lag * qty
            if ok:
                win += 1
            n_sig += 1
            last = i
    if n_sig == 0:
        return 0, 0.0, 0.0
    return n_sig, 100 * win / n_sig, (gross - 35 * n_sig) / n_sig


names = list(data.keys())
rows = []
for a in range(len(names)):
    for b in range(a + 1, len(names)):
        A, B = names[a], names[b]
        pa, va = data[A]["c"].values, data[A]["v"].values
        pb, vb = data[B]["c"].values, data[B]["v"].values
        if len(pa) != len(pb):
            continue
        n1, w1, net1 = gap_strategy(pa, va, pb, vb, use_vol_filter=False)
        n2, w2, net2 = gap_strategy(pa, va, pb, vb, use_vol_filter=True)
        rows.append((f"{A}/{B}", n1, w1, net1, n2, w2, net2))

rows.sort(key=lambda r: (-(r[2] if r[1] >= 5 else 0), -r[1]))
print(f"\n{'PAIR':<22} {'base#':>5} {'win%':>5} {'net₹/t':>7} | {'volf#':>5} {'win%':>5} {'net₹/t':>7}")
print("-" * 74)
for r in rows:
    if r[1] >= 5 or r[4] >= 5:
        print(f"{r[0]:<22} {r[1]:>5} {r[2]:>4.0f}% {r[3]:>+7.0f} | {r[4]:>5} {r[5]:>4.0f}% {r[6]:>+7.0f}")
