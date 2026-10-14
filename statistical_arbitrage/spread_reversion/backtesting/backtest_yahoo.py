#!/usr/bin/env python3
"""
Minimal backtest + plot (Yahoo Finance): BANKBEES.NS vs SETFNIFBK.NS
Strategy (Pole 2007): spread = ln(PA) - ln(PB); enter |z|>2 (rolling window); exit z crosses 0.
Fees: Groww intraday (MIS) on 4 legs per round trip.
Usage: python backtest_yahoo.py [QTY=100] [WINDOW=6] [INTERVAL=5m] [PERIOD=60d]
"""
import math
import sys
from collections import deque

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import yfinance as yf

PAIR_A, PAIR_B = "BANKBEES.NS", "SETFNIFBK.NS"
QTY      = int(sys.argv[1]) if len(sys.argv) > 1 else 100
WINDOW   = int(sys.argv[2]) if len(sys.argv) > 2 else 6     # 6 x 5m = 30min (mirrors live 60x30s)
INTERVAL = sys.argv[3] if len(sys.argv) > 3 else "5m"
PERIOD   = sys.argv[4] if len(sys.argv) > 4 else "60d"
WARMUP, ENTRY_Z = 5, 2.0
OUT_PNG  = "backtesting/spread_reversion_yahoo.png"

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


def entry_fees(d, pa, pb):
    return (leg_fees(pa, QTY, "BUY") + leg_fees(pb, QTY, "SELL")) if d == "LONG" \
        else (leg_fees(pa, QTY, "SELL") + leg_fees(pb, QTY, "BUY"))


def exit_fees(d, pa, pb):
    return (leg_fees(pa, QTY, "SELL") + leg_fees(pb, QTY, "BUY")) if d == "LONG" \
        else (leg_fees(pa, QTY, "BUY") + leg_fees(pb, QTY, "SELL"))


def main():
    print(f"=== backtest {PAIR_A} vs {PAIR_B}  interval={INTERVAL} period={PERIOD} qty={QTY} window={WINDOW} ===")
    a = yf.Ticker(PAIR_A).history(period=PERIOD, interval=INTERVAL, auto_adjust=True)
    b = yf.Ticker(PAIR_B).history(period=PERIOD, interval=INTERVAL, auto_adjust=True)
    print(f"  raw candles: {PAIR_A}={len(a)}  {PAIR_B}={len(b)}")

    df = a["Close"].rename("pa").to_frame().join(b["Close"].rename("pb"), how="inner").dropna()
    if len(df) < WARMUP:
        sys.exit("FATAL: too few aligned candles")
    print(f"  aligned: {len(df)} candles  {df.index.min()} -> {df.index.max()}")

    ts, history, pos, trades = df.index, deque(maxlen=WINDOW), None, []
    zs, spreads = [], []

    for i, t in enumerate(ts):
        pa, pb = df["pa"].iloc[i], df["pb"].iloc[i]
        s = math.log(pa) - math.log(pb)
        spreads.append(s)
        history.append(s)

        if len(history) < WARMUP:
            zs.append(float("nan"))
            continue
        mean = sum(history) / len(history)
        var = sum((x - mean) ** 2 for x in history) / len(history)
        z = (s - mean) / max(math.sqrt(var), 1e-4)
        zs.append(z)

        if pos is None:
            if z > ENTRY_Z:
                pos = {"dir": "SHORT", "pa": pa, "pb": pb, "z": z, "i": i}
            elif z < -ENTRY_Z:
                pos = {"dir": "LONG", "pa": pa, "pb": pb, "z": z, "i": i}
        else:
            exit_now = z >= 0.0 if pos["dir"] == "LONG" else z <= 0.0
            if exit_now:
                g = ((pa - pos["pa"]) * QTY - (pb - pos["pb"]) * QTY) if pos["dir"] == "LONG" \
                    else ((pos["pa"] - pa) * QTY + (pb - pos["pb"]) * QTY)
                f = entry_fees(pos["dir"], pos["pa"], pos["pb"]) + exit_fees(pos["dir"], pa, pb)
                trades.append({"dir": pos["dir"], "z": pos["z"], "entry_i": pos["i"],
                               "exit_i": i, "gross": g, "fees": f, "net": g - f,
                               "held": i - pos["i"], "t_in": ts[pos["i"]], "t_out": t})
                pos = None

    gross = sum(t["gross"] for t in trades)
    fees = sum(t["fees"] for t in trades)
    net = gross - fees
    wins = sum(1 for t in trades if t["net"] > 0)

    print(f"\n=== RESULTS (qty={QTY}, window={WINDOW}) ===")
    print(f"  trades: {len(trades)}  ({sum(1 for t in trades if t['dir']=='SHORT')} SHORT / "
          f"{sum(1 for t in trades if t['dir']=='LONG')} LONG)")
    print(f"  gross: ₹{gross:+.2f}   net(after fees): ₹{net:+.2f}   fees: ₹{fees:.2f}")
    print(f"  win rate (net): {wins}/{len(trades)} = {100*wins/len(trades) if trades else 0:.0f}%")
    if trades:
        print(f"  avg gross/trade ₹{gross/len(trades):+.2f}  avg fees/trade ₹{fees/len(trades):.2f}  "
              f"avg net/trade ₹{net/len(trades):+.2f}  avg held {sum(t['held'] for t in trades)/len(trades):.1f} candles")
        print("  trades:")
        for t in trades:
            print(f"    {str(t['t_in'])[:16]} -> {str(t['t_out'])[:16]}  {t['dir']:5} z={t['z']:+.2f} "
                  f"held={t['held']:>3}  gross=₹{t['gross']:+8.2f}  fees=₹{t['fees']:6.2f}  net=₹{t['net']:+8.2f}")

    # ---- plot ----
    x = list(range(len(ts)))
    fig, axes = plt.subplots(4, 1, figsize=(14, 13), sharex=True)
    axes[0].plot(x, df["pa"], label=PAIR_A, lw=1)
    axes[0].plot(x, df["pb"], label=PAIR_B, lw=1)
    axes[0].set_ylabel("price"); axes[0].legend(loc="best"); axes[0].grid(alpha=0.3)
    axes[0].set_title(f"{PAIR_A} vs {PAIR_B} — spread reversion (qty={QTY}, window={WINDOW}, {INTERVAL})")

    axes[1].plot(x, spreads, color="tab:blue", lw=1, label="log spread")
    for t in trades:
        c = "g" if t["net"] > 0 else "r"
        axes[1].scatter(t["entry_i"], 0, marker="v", color=c, s=45, zorder=3)
        axes[1].scatter(t["exit_i"], 0, marker="^", color=c, s=45, zorder=3)
    axes[1].set_ylabel("log spread"); axes[1].grid(alpha=0.3)

    axes[2].plot(x, zs, color="tab:orange", lw=0.8, label="z-score")
    axes[2].axhline(ENTRY_Z, color="r", ls="--", lw=0.8)
    axes[2].axhline(-ENTRY_Z, color="r", ls="--", lw=0.8)
    axes[2].axhline(0, color="k", lw=0.6)
    axes[2].set_ylabel("z-score"); axes[2].legend(loc="best"); axes[2].grid(alpha=0.3)

    eq, run = [], 0.0
    for t in trades:
        run += t["net"]
        eq.append(run)
    axes[3].plot([t["exit_i"] for t in trades], eq, marker="o", color="tab:green",
                 label=f"net equity (₹{net:+.2f})")
    axes[3].axhline(0, color="k", lw=0.6)
    axes[3].set_ylabel("net ₹"); axes[3].legend(loc="best"); axes[3].grid(alpha=0.3)
    axes[3].set_xlabel(f"{INTERVAL} candle index  {ts[0]} -> {ts[-1]}")

    plt.tight_layout()
    plt.savefig(OUT_PNG, dpi=110)
    print(f"\nplot saved: {OUT_PNG}")


if __name__ == "__main__":
    main()
