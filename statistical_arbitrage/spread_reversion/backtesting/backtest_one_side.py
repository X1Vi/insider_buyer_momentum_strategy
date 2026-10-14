#!/usr/bin/env python3
"""
One-sided (LONG) intraday backtest — any pair of NSE tickers (Yahoo).
ENTER LONG when z < -2 (spread stretched low -> BUY A / SELL B)
EXIT        when z >= 0  OR  stop-loss hit (gross <= -STOP_LOSS_RS)
Position sized from CAPITAL (₹, default 20,000 per trade). Fees: Groww intraday MIS.
Usage: python backtest_one_side.py [capital=20000] [window=6] [stop_loss_rs=400]
                                   [ticker_a=BANKBEES.NS] [ticker_b=SETFNIFBK.NS]
                                   [interval=5m] [period=60d]
Examples:
  python backtest_one_side.py                       # BANKBEES vs SETFNIFBK 5m 60d
  python backtest_one_side.py 20000 6 400 HDFCBANK.NS KOTAKBANK.NS        # intraday
  python backtest_one_side.py 20000 60 400 HDFCBANK.NS KOTAKBANK.NS 1d 3y # daily
"""
import math
import sys
from collections import deque

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import yfinance as yf

CAPITAL     = float(sys.argv[1]) if len(sys.argv) > 1 else 20000.0
WINDOW      = int(sys.argv[2]) if len(sys.argv) > 2 else 6
STOP_LOSS_RS = float(sys.argv[3]) if len(sys.argv) > 3 else 400.0
TICKER_A    = sys.argv[4] if len(sys.argv) > 4 else "BANKBEES.NS"
TICKER_B    = sys.argv[5] if len(sys.argv) > 5 else "SETFNIFBK.NS"
INTERVAL    = sys.argv[6] if len(sys.argv) > 6 else "5m"
PERIOD      = sys.argv[7] if len(sys.argv) > 7 else "60d"
WARMUP, ENTRY_Z = 5, 2.0
LABEL = f"{TICKER_A.removesuffix('.NS')} vs {TICKER_B.removesuffix('.NS')}"
PNG = f"backtesting/backtest_one_side_{LABEL.replace(' vs ', '_')}.png"

BROKERAGE_FLAT, BROKERAGE_PCT, BROKERAGE_MIN = 20.0, 0.001, 5.0
STT_PCT, STAMP_PCT, EXCH_PCT = 0.00025, 0.00003, 0.0000297
SEBI_PCT, IPFT_PCT, GST_PCT = 0.000001, 0.000001, 0.18


def leg_fees(p, q, side):
    v = p * q
    brk = max(min(BROKERAGE_FLAT, BROKERAGE_PCT * v), BROKERAGE_MIN)
    stt = v * STT_PCT if side == "SELL" else 0.0
    stp = v * STAMP_PCT if side == "BUY" else 0.0
    e = v * EXCH_PCT; s = v * SEBI_PCT; i = v * IPFT_PCT
    return brk + stt + stp + e + s + i + GST_PCT * (brk + e + s + i)


def entry_fees(d, pa, pb, q):
    return (leg_fees(pa, q, "BUY") + leg_fees(pb, q, "SELL")) if d == "LONG" \
        else (leg_fees(pa, q, "SELL") + leg_fees(pb, q, "BUY"))


def exit_fees(d, pa, pb, q):
    return (leg_fees(pa, q, "SELL") + leg_fees(pb, q, "BUY")) if d == "LONG" \
        else (leg_fees(pa, q, "BUY") + leg_fees(pb, q, "SELL"))


def gross_pnl(d, epa, epb, pa, pb, q):
    if d == "LONG":
        return (pa - epa) * q - (pb - epb) * q
    return (epa - pa) * q + (pb - epb) * q


def main():
    a = yf.Ticker(TICKER_A).history(period=PERIOD, interval=INTERVAL, auto_adjust=True)
    b = yf.Ticker(TICKER_B).history(period=PERIOD, interval=INTERVAL, auto_adjust=True)
    df = a["Close"].rename("pa").to_frame().join(b["Close"].rename("pb"), how="inner").dropna()
    print(f"=== {LABEL}  one-sided LONG  {INTERVAL}  bars={len(df)}  "
          f"{df.index.min()} -> {df.index.max()}  capital=₹{CAPITAL:,.0f}  window={WINDOW}  "
          f"stop_loss=₹{STOP_LOSS_RS:,.0f} ===")

    h = deque(maxlen=WINDOW)
    pos = None
    trades = []
    port = CAPITAL

    for i in range(len(df)):
        pa, pb = df["pa"].iloc[i], df["pb"].iloc[i]
        s = math.log(pa) - math.log(pb)
        h.append(s)
        if len(h) < WARMUP:
            continue
        m = sum(h) / len(h)
        v = sum((x - m) ** 2 for x in h) / len(h)
        z = (s - m) / max(math.sqrt(v), 1e-4)

        if pos is None:
            if z < -ENTRY_Z:                       # LONG only
                q = max(int(port / (pa + pb)), 1)
                pos = {"pa": pa, "pb": pb, "q": q, "z": z, "i": i}
        else:
            g = gross_pnl("LONG", pos["pa"], pos["pb"], pa, pb, pos["q"])
            reason = "STOP" if STOP_LOSS_RS > 0 and g <= -STOP_LOSS_RS else ("Z" if z >= 0.0 else None)
            if reason:
                f = entry_fees("LONG", pos["pa"], pos["pb"], pos["q"]) \
                    + exit_fees("LONG", pa, pb, pos["q"])
                net = g - f
                port += net
                trades.append({"gross": g, "fees": f, "net": net, "q": pos["q"],
                               "held": i - pos["i"], "z": pos["z"], "reason": reason,
                               "in": str(df.index[pos["i"]])[5:16], "out": str(df.index[i])[5:16]})
                pos = None

    n = len(trades)
    n_stop = sum(1 for t in trades if t["reason"] == "STOP")
    n_z = n - n_stop
    gross = sum(t["gross"] for t in trades)
    fees = sum(t["fees"] for t in trades)
    net = gross - fees
    wins = [t for t in trades if t["net"] > 0]
    gp = sum(t["net"] for t in wins)
    gl = abs(sum(t["net"] for t in trades if t["net"] < 0))
    days = (df.index[-1] - df.index[0]).days / 30.44
    avg_q = sum(t["q"] for t in trades) / n if n else 0
    net_rets = [t["net"] for t in trades]
    sharpe = (sum(net_rets) / n) / (math.sqrt(sum((x - sum(net_rets) / n) ** 2 for x in net_rets) / n)) \
        * math.sqrt(n) if n > 1 else 0
    # max consecutive losses
    mcl = cur = 0
    for t in trades:
        cur = cur + 1 if t["net"] < 0 else 0
        mcl = max(mcl, cur)

    print(f"\n  trades: {n}   ({n/days:.1f}/month over {days:.1f} months)")
    print(f"  exits: {n_z} by z-cross, {n_stop} by STOP LOSS")
    print(f"  gross: ₹{gross:+.2f}   fees: ₹{fees:.2f}   NET: ₹{net:+.2f}")
    print(f"  gross win%: {100*sum(1 for t in trades if t['gross']>0)/n:.0f}%   "
          f"net win%: {100*len(wins)/n:.0f}%")
    print(f"  avg gross/trade ₹{gross/n:+.2f}   avg fees/trade ₹{fees/n:.2f}   avg net/trade ₹{net/n:+.2f}")
    print(f"  avg win ₹{gp/len(wins) if wins else 0:+.2f}   avg loss ₹{gl/(n-len(wins)) if n-len(wins) else 0:+.2f}")
    print(f"  profit factor: {gp/gl if gl else float('inf'):.2f}   expectancy/trade ₹{net/n:+.2f}")
    print(f"  Sharpe (per trade, ann.): {sharpe:.2f}   max consec losses: {mcl}")
    print(f"  STOP LOSS: ₹{STOP_LOSS_RS:,.0f}/trade = ₹{STOP_LOSS_RS/avg_q:.2f}/unit "
          f"(avg qty {avg_q:.0f})")
    print(f"  final capital: ₹{port:,.2f}  ({100*(port/CAPITAL-1):+.1f}% over {days:.1f} months)")
    print("  recent trades:")
    for t in trades[-12:]:
        print(f"    {t['in']} -> {t['out']}  q={t['q']:>2} held={t['held']:>2}  {t['reason']:>4}  "
              f"gross=₹{t['gross']:+7.0f} fees=₹{t['fees']:5.0f} net=₹{t['net']:+7.0f}")

    # equity plot
    eq = [CAPITAL]
    for t in trades:
        eq.append(eq[-1] + t["net"])
    plt.figure(figsize=(12, 5))
    plt.plot(eq, marker="o", color="tab:green")
    plt.axhline(CAPITAL, color="k", ls="--", lw=0.8)
    plt.title(f"{LABEL} one-sided LONG equity (₹{CAPITAL:,.0f} start) — {n} trades, net ₹{net:+,.0f}")
    plt.ylabel("capital ₹"); plt.xlabel("trade #"); plt.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(PNG, dpi=110)
    print(f"\nplot saved: {PNG}")


if __name__ == "__main__":
    main()
