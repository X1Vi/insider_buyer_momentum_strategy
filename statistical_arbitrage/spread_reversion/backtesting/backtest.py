#!/usr/bin/env python3
"""
Minimal backtest + plot: BANKBEES vs SETFNIFBK spread reversion (Pole 2007).
Spread = ln(PA) - ln(PB).  Enter |z|>2 (rolling window), exit z crosses 0.
Fees: Groww intraday (MIS) on 4 legs per round trip.
Data: Groww historical 1-minute candles (max 30 days/request).
"""
import math
import os
import sys
from collections import deque
from datetime import datetime

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from growwapi import GrowwAPI

# ---------------- config ----------------
PAIR_A   = "BANKBEES"
PAIR_B   = "SETFNIFBK"
START    = "2026-08-17 09:15:00"
END      = "2026-08-28 15:30:00"
INTERVAL = "1minute"
WINDOW   = 30      # rolling window in candles (~30 min, mirrors live 60x30s)
WARMUP   = 5
ENTRY_Z  = 2.0
QTY      = 100     # units per leg (change to 19 to mirror live account)
OUT_PNG  = "backtesting/spread_reversion_backtest.png"

# Groww intraday (MIS) fee model
BROKERAGE_FLAT, BROKERAGE_PCT, BROKERAGE_MIN = 20.0, 0.001, 5.0
STT_PCT, STAMP_PCT, EXCH_PCT = 0.00025, 0.00003, 0.0000297
SEBI_PCT, IPFT_PCT, GST_PCT = 0.000001, 0.000001, 0.18


def leg_fees(price, qty, side):
    v = price * qty
    brk = max(min(BROKERAGE_FLAT, BROKERAGE_PCT * v), BROKERAGE_MIN)
    stt = v * STT_PCT if side == "SELL" else 0.0
    stamp = v * STAMP_PCT if side == "BUY" else 0.0
    exch, sebi, ipft = v * EXCH_PCT, v * SEBI_PCT, v * IPFT_PCT
    gst = GST_PCT * (brk + exch + sebi + ipft)
    return brk + stt + stamp + exch + sebi + ipft + gst


def entry_fees(d, pa, pb):
    return (leg_fees(pa, QTY, "BUY") + leg_fees(pb, QTY, "SELL")) if d == "LONG" \
        else (leg_fees(pa, QTY, "SELL") + leg_fees(pb, QTY, "BUY"))


def exit_fees(d, pa, pb):
    return (leg_fees(pa, QTY, "SELL") + leg_fees(pb, QTY, "BUY")) if d == "LONG" \
        else (leg_fees(pa, QTY, "BUY") + leg_fees(pb, QTY, "SELL"))


def load_token():
    tok = os.getenv("GROWW_ACCESS_TOKEN")
    if tok:
        return tok
    for line in open(".env"):
        if line.strip().startswith("GROWW_ACCESS_TOKEN="):
            return line.strip().split("=", 1)[1].strip().strip('"').strip("'")
    sys.exit("FATAL: GROWW_ACCESS_TOKEN not found in env or .env")


def fetch(groww, symbol):
    resp = groww.get_historical_candles(
        exchange="NSE", segment="CASH", groww_symbol=f"NSE-{symbol}",
        start_time=START, end_time=END, candle_interval=INTERVAL,
    )
    out = {}
    for c in resp.get("candles", []):
        out[c[0]] = float(c[4])   # ts -> close
    print(f"  {symbol}: {len(out)} candles  {resp.get('start_time','?')} -> {resp.get('end_time','?')}")
    return out


def main():
    token = load_token()
    groww = GrowwAPI(token)
    print(f"=== backtest {PAIR_A} vs {PAIR_B}  {INTERVAL}  {START} -> {END} ===")
    a, b = fetch(groww, PAIR_A), fetch(groww, PAIR_B)

    ts = sorted(set(a) & set(b))
    if len(ts) < WARMUP:
        sys.exit(f"FATAL: only {len(ts)} aligned candles")

    history = deque(maxlen=WINDOW)
    pos = None
    trades = []
    zs, spreads, pays, pbys = [], [], [], []

    for t in ts:
        pa, pb = a[t], b[t]
        s = math.log(pa) - math.log(pb)
        spreads.append(s); pays.append(pa); pbys.append(pb)
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
                pos = {"dir": "SHORT", "pa": pa, "pb": pb, "z": z, "i": len(ts) - 1}
            elif z < -ENTRY_Z:
                pos = {"dir": "LONG", "pa": pa, "pb": pb, "z": z, "i": len(ts) - 1}
        else:
            exit_now = z >= 0.0 if pos["dir"] == "LONG" else z <= 0.0
            if exit_now:
                g = ((pa - pos["pa"]) * QTY - (pb - pos["pb"]) * QTY) if pos["dir"] == "LONG" \
                    else ((pos["pa"] - pa) * QTY + (pb - pos["pb"]) * QTY)
                f = entry_fees(pos["dir"], pos["pa"], pos["pb"]) + exit_fees(pos["dir"], pa, pb)
                trades.append({"dir": pos["dir"], "z": pos["z"], "entry_i": pos["i"],
                               "exit_i": len(ts) - 1, "gross": g, "fees": f, "net": g - f,
                               "held": len(ts) - 1 - pos["i"]})
                pos = None

    gross = sum(t["gross"] for t in trades)
    fees = sum(t["fees"] for t in trades)
    net = gross - fees
    wins = sum(1 for t in trades if t["net"] > 0)
    gross_wins = sum(1 for t in trades if t["gross"] > 0)

    print(f"\n=== RESULTS (qty={QTY}) ===")
    print(f"  candles: {len(ts)}  window={WINDOW}  entry_z=±{ENTRY_Z}")
    print(f"  trades: {len(trades)}  ({len([t for t in trades if t['dir']=='SHORT'])} SHORT / "
          f"{len([t for t in trades if t['dir']=='LONG'])} LONG)")
    print(f"  gross:  ₹{gross:+.2f}   (win rate on gross: {gross_wins}/{len(trades)} = "
          f"{100*gross_wins/len(trades):.0f}%)")
    print(f"  fees:   ₹{fees:.2f}   (₹{fees/len(trades):.2f}/round trip)")
    print(f"  net:    ₹{net:+.2f}   (win rate on net: {wins}/{len(trades)} = "
          f"{100*wins/len(trades):.0f}%)")
    if trades:
        print(f"  avg gross/trade ₹{gross/len(trades):+.2f}  avg net/trade ₹{net/len(trades):+.2f}")
        print(f"  avg held: {sum(t['held'] for t in trades)/len(trades):.1f} candles")
    if pos:
        print(f"  note: {pos['dir']} position still open at end of data (not counted)")

    # ---- plot ----
    x = list(range(len(ts)))
    fig, axes = plt.subplots(4, 1, figsize=(14, 13), sharex=True)
    axes[0].plot(x, pays, label=PAIR_A, lw=1)
    axes[0].plot(x, pbys, label=PAIR_B, lw=1)
    axes[0].set_ylabel("price"); axes[0].legend(loc="best"); axes[0].grid(alpha=0.3)
    axes[0].set_title(f"{PAIR_A} vs {PAIR_B} — spread reversion backtest (qty={QTY})")

    axes[1].plot(x, spreads, color="tab:blue", lw=1, label="log spread")
    for t in trades:
        c = "g" if t["net"] > 0 else "r"
        axes[1].scatter(t["entry_i"], 0, marker="v", color=c, s=40)
        axes[1].scatter(t["exit_i"], 0, marker="^", color=c, s=40)
    axes[1].set_ylabel("log spread"); axes[1].legend(loc="best"); axes[1].grid(alpha=0.3)

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

    axes[3].set_xlabel(f"1-minute candle index ({START[:10]} -> {END[:10]})")
    plt.tight_layout()
    plt.savefig(OUT_PNG, dpi=110)
    print(f"\nplot saved: {OUT_PNG}")


if __name__ == "__main__":
    main()
