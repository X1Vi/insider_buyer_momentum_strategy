#!/usr/bin/env python3
"""Standalone scanner backtest + plots.

Replays the scanner's exact signal logic (verbatim copy of scanner.rs /
reaction/scanner.py) over every pair's daily data, simulates the trade,
computes Sharpe and other ratios, and plots each pair's price + signals over
its time range.

Pairs:
  * 10 scanner stock legs   -> ML WATCH signal (XGBoost, prob >= 0.5)
  * ETF pairs               -> rule-based z (|z| > 2), market-neutral
  * S&P via Mirae ETF       -> MAFANG.NS vs S&P 500 index, rule-based z

Run:
  .venv/bin/python backtesting/scanner_backtest_plot.py
"""
import glob
import json
import math
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from reaction import scanner as S  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "backtesting", "data")
MODEL = os.path.join(ROOT, "backtesting", "model_dump.txt")
OUT = os.path.join(ROOT, "backtesting", "plots", "scanner_bt")
os.makedirs(OUT, exist_ok=True)

CAPITAL = 20000.0
MAX_HOLD = 30
STOP_NOTIONAL_PCT = 0.05
PROB_MIN = 0.5
ETF_THRESH = 2.0

# leg_id = alphabetical index over the 18-stock universe the model was trained on
LEG_ID = {"AXISBANK": 0, "BAJAJFINSV": 1, "COALINDIA": 2, "HCLTECH": 3, "HDFCBANK": 4,
          "HINDALCO": 5, "HINDUNILVR": 6, "ICICIBANK": 7, "INDUSINDBK": 8, "ITC": 9,
          "JSWSTEEL": 10, "KOTAKBANK": 11, "NESTLEIND": 12, "RELIANCE": 13, "SBIN": 14,
          "TATASTEEL": 15, "TCS": 16, "WIPRO": 17}

STOCK_LEGS = [
    ("AXISBANK", "RELIANCE"), ("BAJAJFINSV", "RELIANCE"), ("HDFCBANK", "KOTAKBANK"),
    ("HINDALCO", "JSWSTEEL"), ("ICICIBANK", "KOTAKBANK"), ("JSWSTEEL", "TATASTEEL"),
    ("KOTAKBANK", "RELIANCE"), ("NESTLEIND", "ITC"), ("SBIN", "ICICIBANK"),
    ("TATASTEEL", "TCS"),
]
ETF_PAIRS = [("BANKBEES", "SETFNIFBK"), ("NIFTYBEES", "SETFNIF50")]
SP_PAIRS = [("MAFANG", "SP500")]

# ---------------- Indian cash fee model (Groww) ----------------
BROKERAGE_FLAT, BROKERAGE_PCT, BROKERAGE_MIN = 20.0, 0.001, 5.0
STT_PCT, STAMP_PCT, EXCH_PCT = 0.00025, 0.00003, 0.0000297
SEBI_PCT, IPFT_PCT, GST_PCT = 0.000001, 0.000001, 0.18


def leg_fees(price, qty, side):
    v = price * qty
    brk = max(min(BROKERAGE_FLAT, BROKERAGE_PCT * v), BROKERAGE_MIN)
    stt = v * STT_PCT if side == "SELL" else 0.0
    stp = v * STAMP_PCT if side == "BUY" else 0.0
    e = v * EXCH_PCT; s = v * SEBI_PCT; i = v * IPFT_PCT
    return brk + stt + stp + e + s + i + GST_PCT * (brk + e + s + i)


# ---------------- data ----------------
def load(name):
    return pd.read_csv(os.path.join(DATA, f"{name}.csv"))["close"].values.astype(float)


def load_dates(name):
    return pd.read_csv(os.path.join(DATA, f"{name}.csv"))["ts"].values.astype(str)


# ---------------- trade sim (LONG A / SHORT B, pairs mean-reversion) ----------------
def simulate_pair_trade(pa, pb, z, entry):
    """Enter LONG A / SHORT B at `entry`; exit z>=0 / stop / max-hold."""
    if entry + MAX_HOLD >= len(pa):
        return None
    epa, epb = pa[entry], pb[entry]
    qty = max(int(CAPITAL / (epa + epb)), 1)
    stop = -STOP_NOTIONAL_PCT * (epa + epb) * qty
    exit_i, reason = None, None
    for k in range(1, MAX_HOLD + 1):
        t = entry + k
        g = (pa[t] - epa) * qty - (pb[t] - epb) * qty
        if g <= stop:
            exit_i, reason = t, "STOP"; break
        if z[t] >= 0.0:
            exit_i, reason = t, "ZERO"; break
    if exit_i is None:
        exit_i, reason = entry + MAX_HOLD, "TIME"
    gross = (pa[exit_i] - epa) * qty - (pb[exit_i] - epb) * qty
    fees = (leg_fees(epa, qty, "BUY") + leg_fees(epb, qty, "SELL")
            + leg_fees(pa[exit_i], qty, "SELL") + leg_fees(pb[exit_i], qty, "BUY"))
    return {"entry": int(entry), "exit": int(exit_i), "held": exit_i - entry,
            "gross": gross, "fees": fees, "net": gross - fees, "reason": reason, "qty": qty}


def ml_watch_trades(pa, pb, leg_id):
    """Replay the scanner's ML WATCH logic bar-by-bar; return entry bars."""
    n = min(len(pa), len(pb)); pa, pb = pa[:n], pb[:n]
    z, beta = S.rbz(pa, pb)
    trees = S.parse_model(MODEL)
    entries, last_arm = [], -1
    for nb in range(S.W_BETA + S.W_Z + S.OBS + 1, n + 1):
        sc = S.scan(pa, pb, z, beta, trees, leg_id, nb)
        if sc["watch"] and sc["arm"] is not None and sc["arm"] != last_arm:
            last_arm = sc["arm"]
            entries.append(sc["arm"] + S.OBS)
    trades, open_till = [], -1
    for e in entries:
        if e < open_till:
            continue
        tr = simulate_pair_trade(pa, pb, z, e)
        if tr:
            tr["leg"], tr["partner"] = None, None
            trades.append(tr)
            open_till = tr["exit"]
    return pa, pb, z, trades


def rule_trades(pa, pb, thr=ETF_THRESH):
    """Rule-based market-neutral pair: enter |z|>2, exit z crosses 0."""
    n = min(len(pa), len(pb)); pa, pb = pa[:n], pb[:n]
    z, _ = S.rbz(pa, pb)
    trades, pos = [], None
    for t in range(S.W_BETA + S.W_Z + 1, n):
        if pos is None:
            if z[t] <= -thr:
                pos = 1; e = t
            elif z[t] >= thr:
                pos = -1; e = t
        else:
            done = False
            if pos == 1 and z[t] >= 0.0:
                done = True
            elif pos == -1 and z[t] <= 0.0:
                done = True
            elif t - e >= MAX_HOLD:
                done = True
            if done:
                epa, epb = pa[e], pb[e]
                qty = max(int(CAPITAL / (epa + epb)), 1)
                if pos == 1:
                    g = (pa[t] - epa) * qty - (pb[t] - epb) * qty
                else:
                    g = (epa - pa[t]) * qty - (epb - pb[t]) * qty
                fees = (leg_fees(epa, qty, "BUY") + leg_fees(epb, qty, "SELL")
                        + leg_fees(pa[t], qty, "SELL") + leg_fees(pb[t], qty, "BUY"))
                trades.append({"entry": int(e), "exit": int(t), "held": t - e,
                               "gross": g, "fees": fees, "net": g - fees, "reason": "R",
                               "qty": qty})
                pos = None
    return pa, pb, z, trades


# ---------------- metrics ----------------
def metrics(pa, pb, dates, trades):
    if not trades:
        return {"n": 0, "net": 0.0, "win": 0.0, "avg": 0.0,
                "sharpe": 0.0, "mdd": 0.0, "pf": 0.0,
                "equity": np.full(len(pa), CAPITAL), "dates": dates}
    n = len(pa)
    daily = np.zeros(n)
    for tr in trades:
        e, x = tr["entry"], tr["exit"]
        qty, epa, epb = tr["qty"], pa[e], pb[e]
        for t in range(e, x + 1):
            g = (pa[t] - epa) * qty - (pb[t] - epb) * qty
            daily[t] += g
        daily[x] -= tr["fees"]
    eq = CAPITAL + np.cumsum(daily)
    ret = np.diff(eq) / eq[:-1]
    sharpe = float(np.mean(ret) / np.std(ret) * math.sqrt(252)) if len(ret) and np.std(ret) > 0 else 0.0
    peak = np.maximum.accumulate(eq)
    mdd = float(np.max((peak - eq) / peak)) if len(eq) else 0.0
    nets = np.array([t["net"] for t in trades])
    wins = nets[nets > 0]; losses = nets[nets <= 0]
    pf = (wins.sum() / abs(losses.sum())) if len(losses) and losses.sum() != 0 else float("inf")
    return {
        "n": len(trades), "net": float(nets.sum()), "win": float((nets > 0).mean()),
        "avg": float(nets.mean()), "sharpe": sharpe, "mdd": mdd,
        "pf": pf if math.isfinite(pf) else float("inf"),
        "equity": eq, "dates": dates,
    }


# ---------------- plots ----------------
def plot_pair(A, B, pa, pb, z, dates, trades, m, tag):
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 6.5), sharex=True,
                                   gridspec_kw={"height_ratios": [2.4, 1]})
    x = np.arange(len(pa))
    ax1.plot(x, pa, color="#1f77b4", lw=1.1, label=A)
    ax1.plot(x, pb, color="#ff7f0e", lw=1.1, alpha=0.85, label=B)
    for tr in trades:
        e, xb = tr["entry"], tr["exit"]
        ax1.scatter(e, pa[e], marker="^", s=150, color="tab:green", edgecolors="k", lw=0.6, zorder=6)
        ax1.scatter(xb, pa[xb], marker="v", s=150, color="tab:red", edgecolors="k", lw=0.6, zorder=6)
        ax1.annotate(f"{tr['net']:+.0f}", (e, pa[e]), textcoords="offset points",
                     xytext=(0, 10), fontsize=7, fontweight="bold", color="darkgreen")
        ax2.scatter(e, z[e], marker="^", s=110, color="tab:green", edgecolors="k", lw=0.5, zorder=6)
        ax2.scatter(xb, z[xb], marker="v", s=110, color="tab:red", edgecolors="k", lw=0.5, zorder=6)
    ax1.set_ylabel("price"); ax1.grid(alpha=0.25)
    ax1.set_title(f"{A} / {B}  [{tag}]  n={m['n']}  net=Rs{m['net']:+,.0f}  "
                  f"win={100*m['win'] if m['n'] else 0:.0f}%  Sharpe={m['sharpe']:.2f}  "
                  f"PF={m['pf'] if m['n'] else float('nan'):.2f}")
    ax1.legend(loc="upper left", fontsize=8)
    ax2.plot(x, z, color="tab:purple", lw=0.9)
    ax2.axhline(0, color="k", ls=":", lw=0.8)
    ax2.axhline(-ETF_THRESH, color="tab:red", ls="--", lw=1.0)
    ax2.axhline(ETF_THRESH, color="tab:red", ls="--", lw=1.0)
    ax2.set_ylabel("z"); ax2.grid(alpha=0.25)
    step = max(len(pa) // 6, 1)
    ticks = list(range(0, len(pa), step))
    ax2.set_xticks(ticks)
    ax2.set_xticklabels([dates[i][5:] for i in ticks], rotation=30, fontsize=7)
    plt.tight_layout()
    fname = f"{A}_{B}.png"
    plt.savefig(os.path.join(OUT, fname), dpi=110)
    plt.close(fig)
    return fname


def main():
    trees_loaded = len(S.parse_model(MODEL))
    print(f"scanner model: {trees_loaded} trees   universe legs: {len(STOCK_LEGS)}  "
          f"ETF pairs: {len(ETF_PAIRS)}  S&P(Mirae): {len(SP_PAIRS)}")
    print(f"\n{'PAIR':<24}{'n':>3}{'net':>10}{'win%':>6}{'avg':>9}{'Sharpe':>8}{'MaxDD':>7}{'PF':>6}  file")
    rows = []
    for A, B in STOCK_LEGS:
        pa, pb = load(A), load(B)
        dates = load_dates(A)
        pa, pb, z, trades = ml_watch_trades(pa, pb, LEG_ID[A])
        for t in trades:
            t["leg"], t["partner"] = A, B
        m = metrics(pa, pb, dates, trades)
        fn = plot_pair(A, B, pa, pb, z, dates, trades, m, "ML WATCH")
        rows.append((A, B, m, fn))
        print(f"{A+'/'+B:<24}{m['n']:>3}{m['net']:>+10,.0f}{100*m['win'] if m['n'] else 0:>6.0f}"
              f"{m['avg']:>+9,.0f}{m['sharpe']:>8.2f}{m['mdd']:>7.2%}"
              f"{m['pf'] if m['n'] else 0:>6.2f}  {fn}")
    for A, B in ETF_PAIRS + SP_PAIRS:
        pa, pb = load(A), load(B)
        dates = load_dates(A)
        pa, pb, z, trades = rule_trades(pa, pb)
        for t in trades:
            t["leg"], t["partner"] = A, B
        m = metrics(pa, pb, dates, trades)
        fn = plot_pair(A, B, pa, pb, z, dates, trades, m, "rule |z|>2")
        rows.append((A, B, m, fn))
        print(f"{A+'/'+B:<24}{m['n']:>3}{m['net']:>+10,.0f}{100*m['win'] if m['n'] else 0:>6.0f}"
              f"{m['avg']:>+9,.0f}{m['sharpe']:>8.2f}{m['mdd']:>7.2%}"
              f"{m['pf'] if m['n'] else 0:>6.2f}  {fn}")
    print(f"\nplots saved to {OUT}")


if __name__ == "__main__":
    main()
