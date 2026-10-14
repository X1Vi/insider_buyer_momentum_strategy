#!/usr/bin/env python3
"""
Stress-test backtest of portfolio_trader.py strategy on Yahoo DAILY data 2023-2026.
Replicates: log spread, rolling-window z-score, enter |z|>2, exit on z-cross / stop-loss / take-profit,
₹ portfolio sizing (CAPITAL_USE % of current balance), Groww intraday MIS fees, 4 legs/round trip.
Adaptation: intraday script resets its 60-tick window each day; here the window is N daily closes.
NEW FILE - does not modify any existing code.
"""
import math
import sys
from collections import deque

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import yfinance as yf

PAIR_A, PAIR_B = "BANKBEES.NS", "SETFNIFBK.NS"
START, END = "2023-01-01", "2026-08-29"
WARMUP = 5

# fees (Groww intraday MIS) - identical to portfolio_trader.py
BROKERAGE_FLAT, BROKERAGE_PCT, BROKERAGE_MIN = 20.0, 0.001, 5.0
STT_PCT, STAMP_PCT, EXCH_PCT = 0.00025, 0.00003, 0.0000297
SEBI_PCT, IPFT_PCT, GST_PCT = 0.000001, 0.000001, 0.18


def leg_fees(price, qty, side):
    v = price * qty
    brk = max(min(BROKERAGE_FLAT, BROKERAGE_PCT * v), BROKERAGE_MIN)
    stt = v * STT_PCT if side == "SELL" else 0.0
    stamp = v * STAMP_PCT if side == "BUY" else 0.0
    exch, sebi, ipft = v * EXCH_PCT, v * SEBI_PCT, v * IPFT_PCT
    return brk + stt + stamp + exch + sebi + ipft + GST_PCT * (brk + exch + sebi + ipft)


def entry_fees(d, pa, pb, qty):
    return (leg_fees(pa, qty, "BUY") + leg_fees(pb, qty, "SELL")) if d == "LONG" \
        else (leg_fees(pa, qty, "SELL") + leg_fees(pb, qty, "BUY"))


def exit_fees(d, pa, pb, qty):
    return (leg_fees(pa, qty, "SELL") + leg_fees(pb, qty, "BUY")) if d == "LONG" \
        else (leg_fees(pa, qty, "BUY") + leg_fees(pb, qty, "SELL"))


def gross_pnl(d, epa, epb, pa, pb, qty):
    if d == "LONG":
        return (pa - epa) * qty - (pb - epb) * qty
    return (epa - pa) * qty + (pb - epb) * qty


def compute_qty(portfolio, pa, pb, capital_use):
    return max(int(portfolio * capital_use / (pa + pb)), 1)


def run_backtest(df, window, entry_z, stop_rs, tp_rs, capital_use, portfolio0=400000.0):
    """Returns dict with stats + per-exit portfolio series. stop_rs/tp_rs=None disables."""
    history, pos = deque(maxlen=window), None
    trades, portfolio, total_fees, equity_x, equity_y = [], portfolio0, 0.0, [], []

    for i in range(len(df)):
        pa, pb = df["pa"].iloc[i], df["pb"].iloc[i]
        s = math.log(pa) - math.log(pb)
        history.append(s)
        if len(history) < WARMUP:
            continue
        mean = sum(history) / len(history)
        var = sum((x - mean) ** 2 for x in history) / len(history)
        z = (s - mean) / max(math.sqrt(var), 1e-4)

        if pos is None:
            if z > entry_z:
                pos = {"dir": "SHORT", "pa": pa, "pb": pb, "qty": compute_qty(portfolio, pa, pb, capital_use),
                       "fees_entry": 0.0, "i": i}
            elif z < -entry_z:
                pos = {"dir": "LONG", "pa": pa, "pb": pb, "qty": compute_qty(portfolio, pa, pb, capital_use),
                       "fees_entry": 0.0, "i": i}
        else:
            g = gross_pnl(pos["dir"], pos["pa"], pos["pb"], pa, pb, pos["qty"])
            reason = None
            if stop_rs is not None and g <= -stop_rs:
                reason = "STOP"
            elif tp_rs is not None and g >= tp_rs:
                reason = "TP"
            elif (z >= 0.0) if pos["dir"] == "LONG" else (z <= 0.0):
                reason = "Z"
            if reason:
                fees = entry_fees(pos["dir"], pos["pa"], pos["pb"], pos["qty"]) \
                     + exit_fees(pos["dir"], pa, pb, pos["qty"])
                net = g - fees
                portfolio += net
                total_fees += fees
                trades.append({"dir": pos["dir"], "z": z, "gross": g, "fees": fees, "net": net,
                               "held": i - pos["i"], "in": str(df.index[pos["i"]])[:10],
                               "out": str(df.index[i])[:10], "reason": reason, "qty": pos["qty"]})
                equity_x.append(df.index[i]); equity_y.append(portfolio)
                pos = None

    gross = sum(t["gross"] for t in trades)
    fees = total_fees
    net = gross - fees
    # max drawdown on realized portfolio
    peak, mdd = -1e18, 0.0
    for v in equity_y:
        peak = max(peak, v)
        mdd = max(mdd, (peak - v) / peak if peak else 0)
    return {
        "trades": trades, "n": len(trades), "gross": gross, "fees": fees, "net": net,
        "final": portfolio, "mdd": mdd, "equity_x": equity_x, "equity_y": equity_y,
        "wins": sum(1 for t in trades if t["net"] > 0),
        "params": (window, entry_z, stop_rs, tp_rs, capital_use),
    }


def fmt(r):
    w, e, s, tp, cu = r["params"]
    return (f"win={w:>3} z={e:<3} stop={str(s) if s is not None else 'off':>4} "
            f"tp={str(tp) if tp is not None else 'off':>4} cu={cu:<4} "
            f"n={r['n']:>3}  gross=₹{r['gross']:>+9.0f}  fees=₹{r['fees']:>7.0f}  "
            f"net=₹{r['net']:>+9.0f}  final=₹{r['final']:>8.0f}  mdd={r['mdd']*100:>4.1f}%  "
            f"win%={100*r['wins']/r['n'] if r['n'] else 0:>3.0f}")


def main():
    print(f"=== stress backtest {PAIR_A} vs {PAIR_B}  daily  {START} -> {END} ===")
    a = yf.Ticker(PAIR_A).history(start=START, end=END)
    b = yf.Ticker(PAIR_B).history(start=START, end=END)
    df = a["Close"].rename("pa").to_frame().join(b["Close"].rename("pb"), how="inner").dropna()
    print(f"  aligned daily bars: {len(df)}  {df.index.min().date()} -> {df.index.max().date()}")
    print(f"  price range: {PAIR_A} {df['pa'].min():.2f}-{df['pa'].max():.2f}  "
          f"{PAIR_B} {df['pb'].min():.2f}-{df['pb'].max():.2f}")

    # ---- base config (portfolio_trader defaults) ----
    base = run_backtest(df, window=60, entry_z=2.0, stop_rs=100.0, tp_rs=None, capital_use=0.5)
    print(f"\n=== BASE (portfolio_trader defaults, portfolio=₹5000) ===")
    print(f"  {fmt(base)}")
    print("  trades (first 25):")
    for t in base["trades"][:25]:
        print(f"    {t['in']} -> {t['out']}  {t['dir']:5} qty={t['qty']:>2} held={t['held']:>2}d  "
              f"{t['reason']:>4}  gross=₹{t['gross']:+8.0f}  fees=₹{t['fees']:6.0f}  net=₹{t['net']:+8.0f}")

    # ---- stress grid ----
    grid = []
    for window in (20, 60, 120):
        for entry_z in (2.0, 2.5, 3.0):
            for stop_rs in (None, 50.0, 100.0):
                for tp_rs in (None, 100.0, 250.0):
                    grid.append(run_backtest(df, window, entry_z, stop_rs, tp_rs, 0.5))

    grid.sort(key=lambda r: r["net"], reverse=True)
    print(f"\n=== STRESS GRID (portfolio=₹5000, cu=0.5): {len(grid)} configs, sorted by net ===")
    print("  " + " ".join(f"{'w':>3} {'z':>3} {'stop':>4} {'tp':>4} {'cu':>4} {'n':>3} "
                          f"{'gross':>9} {'fees':>7} {'net':>9} {'final':>8} {'mdd':>5} {'win%':>4}".split()))
    for r in grid:
        print("  " + fmt(r))

    # top/bottom summary
    print("\n=== BEST 3 ===")
    for r in grid[:3]:
        print("  " + fmt(r))
    print("=== WORST 3 ===")
    for r in grid[-3:]:
        print("  " + fmt(r))

    # ---- plot equity curves ----
    picks = [base,
             grid[0],                          # best
             grid[-1],                         # worst
             run_backtest(df, 60, 2.0, None, None, 0.5),   # no SL/TP
             run_backtest(df, 60, 2.0, 100.0, None, 0.5)]  # SL only
    plt.figure(figsize=(13, 6))
    labels = ["base(w60,z2,SL100,TPoff)", "best", "worst", "noSL/noTP", "SL100 only"]
    for r, lab in zip(picks, labels):
        plt.plot(r["equity_x"], r["equity_y"], label=f"{lab} -> ₹{r['final']:.0f} (mdd {r['mdd']*100:.0f}%)")
    plt.axhline(5000, color="k", ls="--", lw=0.8)
    plt.title("Portfolio equity (₹5000 start) — stress grid highlights, 2023-2026 daily")
    plt.ylabel("portfolio ₹"); plt.legend(fontsize=8); plt.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig("backtesting/portfolio_stress_yahoo.png", dpi=110)
    print("\nplot saved: backtesting/portfolio_stress_yahoo.png")


if __name__ == "__main__":
    main()
