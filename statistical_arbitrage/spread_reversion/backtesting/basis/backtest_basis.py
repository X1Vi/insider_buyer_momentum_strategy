#!/usr/bin/env python3
"""WATCH -> BASIS backtest.

The live scanner's WATCH signal (ML v3 XGBoost, probability >= 0.5 on a z < -3
dislocation) is normally traded LONG A / SHORT B as a mean-reversion pairs bet.
That pays full delivery fees on BOTH legs and only earns when the market helps.

This backtest trades the SAME WATCH signal as a market-neutral BASIS trade:
    LONG  the dislocated stock A  (cash/delivery)
    SHORT the market (an equal-weight NIFTY-style index proxy, hedged via a
          single cheap index-futures leg instead of shorting stock B)

Because the index hedge removes market beta, the trade earns whether the market
goes up, down, or (the user's situation) just sits flat — it captures only the
dislocated stock's *relative* recovery. It also cuts fees: one delivery leg +
one futures leg instead of two delivery legs.

New file only; the scanner, its model, and the original backtests are untouched.

Run:
  .venv/bin/python backtesting/basis/backtest_basis.py
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

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
REPO = os.path.dirname(ROOT)
DATA = os.path.join(ROOT, "data")
MODEL_PATH = os.path.join(ROOT, "model_dump.txt")
sys.path.insert(0, REPO)
from reaction import scanner as S  # noqa: E402

CAPITAL = 20000.0
MAX_HOLD = 30
STOP_NOTIONAL_PCT = 0.05        # stop = 5% of the long notional
PROB_MIN = 0.5                  # WATCH threshold (matches scanner THRESH)

# scanner leg config (name, partner, leg_id) — identical to src/bin/scanner.rs
LEGS = [
    ("AXISBANK", "RELIANCE", 0.0),
    ("BAJAJFINSV", "RELIANCE", 1.0),
    ("HDFCBANK", "KOTAKBANK", 4.0),
    ("HINDALCO", "JSWSTEEL", 5.0),
    ("ICICIBANK", "KOTAKBANK", 7.0),
    ("JSWSTEEL", "TATASTEEL", 10.0),
    ("KOTAKBANK", "RELIANCE", 11.0),
    ("NESTLEIND", "ITC", 12.0),
    ("SBIN", "ICICIBANK", 14.0),
    ("TATASTEEL", "TCS", 15.0),
]

# ---- Indian fee model (cash delivery + index futures) ----
BROKERAGE_FLAT, BROKERAGE_PCT, BROKERAGE_MIN = 20.0, 0.001, 5.0
STT_CASH_SELL, STAMP, EXCH_CASH = 0.00025, 0.00003, 0.0000297
SEBI_PCT, IPFT_PCT, GST_PCT = 0.000001, 0.000001, 0.18
STT_FUT_SELL, EXCH_FUT = 0.0002, 0.00002     # futures: STT 0.02% on sell, ~0.002% exchange


def cash_fees(price, qty, side):
    v = price * qty
    brk = max(min(BROKERAGE_FLAT, BROKERAGE_PCT * v), BROKERAGE_MIN)
    stt = v * STT_CASH_SELL if side == "SELL" else 0.0
    stp = v * STAMP if side == "BUY" else 0.0
    e = v * EXCH_CASH; s = v * SEBI_PCT; i = v * IPFT_PCT
    return brk + stt + stp + e + s + i + GST_PCT * (brk + e + s + i)


def fut_fees(notional, side):
    brk = max(min(BROKERAGE_FLAT, BROKERAGE_PCT * notional), BROKERAGE_MIN)
    stt = notional * STT_FUT_SELL if side == "SELL" else 0.0
    stp = notional * STAMP if side == "BUY" else 0.0
    e = notional * EXCH_FUT; s = notional * SEBI_PCT; i = notional * IPFT_PCT
    return brk + stt + stp + e + s + i + GST_PCT * (brk + e + s + i)


def load_closes(name):
    return pd.read_csv(os.path.join(DATA, f"{name}.csv"))["close"].values.astype(float)


def equal_weight_index(names, data):
    """Daily-rebalanced equal-weight index of the universe (NIFTY-style proxy)."""
    n = min(len(v) for v in data.values())
    rets = np.array([data[nm][1:n] / data[nm][:n - 1] - 1.0 for nm in names])
    idx = np.empty(n)
    idx[0] = 1.0
    for t in range(1, n):
        idx[t] = idx[t - 1] * (1.0 + rets[:, t - 1].mean())
    return idx


def simulate_basis(pa, idx, z, entry, qty, hedge_notional):
    """LONG stock A + SHORT index hedge. Returns trade dict or None."""
    if entry + MAX_HOLD >= len(pa):
        return None
    epa = pa[entry]
    fees_in = cash_fees(epa, qty, "BUY") + fut_fees(hedge_notional, "SELL")
    stop = -STOP_NOTIONAL_PCT * hedge_notional
    exit_i, reason = None, None
    for k in range(1, MAX_HOLD + 1):
        t = entry + k
        gross = (pa[t] - epa) * qty - hedge_notional * (idx[t] / idx[entry] - 1.0)
        if gross <= stop:
            exit_i, reason = t, "STOP"
            break
        if z[t] >= 0.0:
            exit_i, reason = t, "ZERO"
            break
    if exit_i is None:
        exit_i, reason = entry + MAX_HOLD, "TIME"
    gross = (pa[exit_i] - epa) * qty - hedge_notional * (idx[exit_i] / idx[entry] - 1.0)
    fees_out = cash_fees(pa[exit_i], qty, "SELL") + fut_fees(hedge_notional, "BUY")
    return {"entry": int(entry), "exit": int(exit_i), "held": exit_i - entry,
            "gross": gross, "fees": fees_in + fees_out, "net": gross - fees_in - fees_out,
            "reason": reason}


def simulate_pairs(pa, pb, z, entry, qty):
    """Old strategy on the SAME WATCH signal: LONG A / SHORT B, both delivery."""
    if entry + MAX_HOLD >= len(pa):
        return None
    epa, epb = pa[entry], pb[entry]
    fees_in = cash_fees(epa, qty, "BUY") + cash_fees(epb, qty, "SELL")
    stop = -STOP_NOTIONAL_PCT * (epa + epb) * qty
    exit_i, reason = None, None
    for k in range(1, MAX_HOLD + 1):
        t = entry + k
        g = (pa[t] - epa) * qty - (pb[t] - epb) * qty
        if g <= stop:
            exit_i, reason = t, "STOP"
            break
        if z[t] >= 0.0:
            exit_i, reason = t, "ZERO"
            break
    if exit_i is None:
        exit_i, reason = entry + MAX_HOLD, "TIME"
    gross = (pa[exit_i] - epa) * qty - (pb[exit_i] - epb) * qty
    fees_out = cash_fees(pa[exit_i], qty, "SELL") + cash_fees(pb[exit_i], qty, "BUY")
    return {"entry": int(entry), "exit": int(exit_i), "held": exit_i - entry,
            "gross": gross, "fees": fees_in + fees_out, "net": gross - fees_in - fees_out,
            "reason": reason}


def main():
    names = sorted(os.path.basename(f)[:-4] for f in glob.glob(os.path.join(DATA, "*.csv")))
    data = {nm: load_closes(nm) for nm in names}
    idx = equal_weight_index(names, data)
    trees = S.parse_model(MODEL_PATH)
    assert len(trees) == 300, "model_dump.txt must have 300 trees"

    basis_trades, pairs_trades, n_watch = [], [], 0
    for leg, partner, leg_id in LEGS:
        pa, pb = data[leg], data[partner]
        n = min(len(pa), len(pb))
        z, beta = S.rbz(pa[:n], pb[:n])
        last_arm = -1
        for nb in range(S.W_BETA + S.W_Z + S.OBS + 1, n + 1):
            sc = S.scan(pa[:n], pb[:n], z, beta, trees, leg_id, nb)
            if sc["watch"] and sc["arm"] is not None and sc["arm"] != last_arm:
                last_arm = sc["arm"]
                n_watch += 1
                e = sc["arm"] + S.OBS
                if e + MAX_HOLD >= n:
                    continue
                qty = max(int(CAPITAL / pa[e]), 1)
                hedge_notional = qty * pa[e]
                qty_pairs = max(int(CAPITAL / (pa[e] + pb[e])), 1)
                b = simulate_basis(pa[:n], idx, z, e, qty, hedge_notional)
                p = simulate_pairs(pa[:n], pb[:n], z, e, qty_pairs)
                if b:
                    basis_trades.append({**b, "leg": leg, "partner": partner})
                if p:
                    pairs_trades.append({**p, "leg": leg, "partner": partner})

    def report(title, trs):
        df = pd.DataFrame(trs)
        print(f"\n=== {title} ===")
        print(f"  WATCH signals: {n_watch}   trades taken: {len(df)}")
        if not len(df):
            print("  (no trades)")
            return df
        net = df["net"].sum(); wins = (df["net"] > 0).mean()
        print(f"  net: Rs {net:+,.0f}   win%: {100*wins:.0f}%   avg: Rs {df['net'].mean():+,.0f}")
        gross = df["gross"].sum()
        fee_share = (100 * df["fees"].sum() / abs(gross)) if gross else 0.0
        print(f"  gross: Rs {gross:+,.0f}   fees: Rs {df['fees'].sum():+,.0f}  "
              f"(fees = {fee_share:.1f}% of |gross|)")
        print(f"  exits: {dict(df['reason'].value_counts())}   avg hold: {df['held'].mean():.1f}d")
        per = df.groupby("leg").agg(n=("net", "size"), net=("net", "sum"),
                                    win=("net", lambda s: (s > 0).mean()))
        for lg, r in per.sort_values("net", ascending=False).iterrows():
            print(f"    {lg:<11} n={int(r['n'])}  net=Rs{r['net']:+8,.0f}  win={100*r['win']:.0f}%")
        return df

    bdf = report("BASIS (LONG stock + SHORT index hedge)", basis_trades)
    pdf = report("PAIRS (old: LONG A / SHORT B, same signals)", pairs_trades)

    # equity curves
    fig, ax = plt.subplots(figsize=(11, 5))
    for df_, lbl, c in ((bdf, "BASIS (long+index hedge)", "tab:green"),
                        (pdf, "PAIRS (old long/short)", "tab:red")):
        if len(df_):
            eq = [CAPITAL] + list(np.cumsum(df_["net"].values) + CAPITAL)
            ax.plot(eq, marker="o", label=f"{lbl}  (net Rs{df_['net'].sum():+,.0f})", color=c, ms=3)
    ax.axhline(CAPITAL, color="k", ls="--", lw=0.8)
    ax.set_title(f"WATCH basis vs pairs — {len(bdf)} basis trades, {len(pdf)} pairs trades")
    ax.set_ylabel("capital Rs"); ax.set_xlabel("trade #"); ax.legend(); ax.grid(alpha=0.3)
    plt.tight_layout()
    out = os.path.join(HERE, "basis_vs_pairs.png")
    plt.savefig(out, dpi=110)
    print(f"\nsaved {out}")
    if len(bdf):
        bdf.to_csv(os.path.join(HERE, "basis_trades.csv"), index=False)
    if len(pdf):
        pdf.to_csv(os.path.join(HERE, "pairs_trades.csv"), index=False)


if __name__ == "__main__":
    main()
