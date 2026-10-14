#!/usr/bin/env python3
"""
MASTER BACKTEST — two-sided (LONG + SHORT) spread reversion, adjustable ₹ portfolio.
Yahoo data. Full metrics: Sharpe, Sortino, MaxDD, CAGR, Calmar, Profit Factor, win rate,
expectancy, max consecutive losses. Graphs: equity, drawdown, spread+z with trade markers.
Writes a markdown report.

Usage:
  python backtest_master.py [capital=10000] [mode=intraday|daily] [window] [entry_z] [stop_rs] [tp_rs]
  mode intraday -> Yahoo 5m, last 60 days (window default 6  = ~30 min)
  mode daily    -> Yahoo daily 2023-2026 (window default 60 = ~3 months)
  stop_rs/tp_rs -> 0 disables (default 0/0)
"""
import math
import sys
from collections import deque
from datetime import datetime

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import yfinance as yf

PAIR_A, PAIR_B = "BANKBEES.NS", "SETFNIFBK.NS"
CAPITAL  = float(sys.argv[1]) if len(sys.argv) > 1 else 20000.0
MODE     = sys.argv[2] if len(sys.argv) > 2 else "intraday"
WINDOW   = int(sys.argv[3]) if len(sys.argv) > 3 else (6 if MODE == "intraday" else 60)
ENTRY_Z  = float(sys.argv[4]) if len(sys.argv) > 4 else 2.0
STOP_RS  = float(sys.argv[5]) if len(sys.argv) > 5 else 0.0
TP_RS    = float(sys.argv[6]) if len(sys.argv) > 6 else 0.0
WARMUP   = 5
PNG      = "backtesting/master_equity.png"
MD       = "backtesting/master_report.md"

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


def qty_for(portfolio, pa, pb):
    return max(int(portfolio / (pa + pb)), 1)


def run(df, window, entry_z, stop_rs, tp_rs):
    h = deque(maxlen=window)
    pos = None
    portfolio = CAPITAL
    trades = []
    equity = []          # mark-to-market portfolio per bar
    spreads, zs = [], []

    for i in range(len(df)):
        pa, pb = df["pa"].iloc[i], df["pb"].iloc[i]
        s = math.log(pa) - math.log(pb)
        spreads.append(s)
        h.append(s)
        if len(h) < WARMUP:
            zs.append(float("nan"))
            equity.append(portfolio)
            continue
        m = sum(h) / len(h)
        v = sum((x - m) ** 2 for x in h) / len(h)
        z = (s - m) / max(math.sqrt(v), 1e-4)
        zs.append(z)

        if pos is None:
            if z > entry_z:
                pos = {"d": "SHORT", "pa": pa, "pb": pb, "q": qty_for(portfolio, pa, pb), "i": i, "z": z}
            elif z < -entry_z:
                pos = {"d": "LONG", "pa": pa, "pb": pb, "q": qty_for(portfolio, pa, pb), "i": i, "z": z}
            equity.append(portfolio)
        else:
            g = gross_pnl(pos["d"], pos["pa"], pos["pb"], pa, pb, pos["q"])
            reason = None
            if stop_rs > 0 and g <= -stop_rs:
                reason = "STOP"
            elif tp_rs > 0 and g >= tp_rs:
                reason = "TP"
            elif (z >= 0.0) if pos["d"] == "LONG" else (z <= 0.0):
                reason = "Z"
            if reason:
                f = entry_fees(pos["d"], pos["pa"], pos["pb"], pos["q"]) \
                    + exit_fees(pos["d"], pa, pb, pos["q"])
                net = g - f
                portfolio += net
                trades.append({"d": pos["d"], "gross": g, "fees": f, "net": net, "q": pos["q"],
                               "held": i - pos["i"], "reason": reason, "z": pos["z"],
                               "in": str(df.index[pos["i"]])[:16], "out": str(df.index[i])[:16]})
                pos = None
                equity.append(portfolio)
            else:
                equity.append(portfolio + g)

    eq = pd.Series(equity, index=df.index)
    return eq, trades, spreads, zs


def metrics(eq, trades, dates):
    initial, final = float(eq.iloc[0]), float(eq.iloc[-1])
    years = max((dates[-1] - dates[0]).days / 365.25, 1e-9)
    total_ret = final / initial - 1
    cagr = (final / initial) ** (1 / years) - 1 if final > 0 else -1

    daily = eq.groupby(eq.index.date).last().pct_change().dropna()
    mean_r, std_r = daily.mean(), daily.std()
    sharpe = mean_r / std_r * math.sqrt(252) if std_r and std_r > 0 else 0.0
    dd_std = daily[daily < 0].std()
    sortino = mean_r / dd_std * math.sqrt(252) if dd_std and dd_std > 0 else 0.0

    run_max = eq.cummax()
    mdd = float((eq / run_max - 1).min())
    calmar = cagr / abs(mdd) if mdd < 0 else 0.0
    max_dur = cur = 0
    for flag in (eq < run_max):
        cur = cur + 1 if flag else 0
        max_dur = max(max_dur, cur)

    n = len(trades)
    gross = sum(t["gross"] for t in trades)
    fees = sum(t["fees"] for t in trades)
    net = gross - fees
    wins = [t for t in trades if t["net"] > 0]
    gp_ = sum(t["net"] for t in wins)
    gl_ = abs(sum(t["net"] for t in trades if t["net"] < 0))
    pf = gp_ / gl_ if gl_ else float("inf")
    win_rate = len(wins) / n if n else 0.0
    mcl = cur = 0
    for t in trades:
        cur = cur + 1 if t["net"] < 0 else 0
        mcl = max(mcl, cur)
    months = max((dates[-1] - dates[0]).days / 30.44, 1e-9)

    return {
        "n": n, "gross": gross, "fees": fees, "net": net, "final": final,
        "total_ret": total_ret, "cagr": cagr, "sharpe": sharpe, "sortino": sortino,
        "mdd": mdd, "mdd_dur": max_dur, "calmar": calmar, "pf": pf, "win_rate": win_rate,
        "avg_win": gp_ / len(wins) if wins else 0.0,
        "avg_loss": gl_ / (n - len(wins)) if n - len(wins) else 0.0,
        "expectancy": net / n if n else 0.0, "mcl": mcl, "tpm": n / months,
        "shorts": sum(1 for t in trades if t["d"] == "SHORT"),
        "longs": sum(1 for t in trades if t["d"] == "LONG"),
        "avg_held": sum(t["held"] for t in trades) / n if n else 0,
    }


def fmt(k, v):
    if k in ("total_ret", "cagr", "mdd", "win_rate"):
        return f"{v * 100:.2f}%"
    if k in ("sharpe", "sortino", "calmar", "pf"):
        return f"{v:.2f}"
    if k in ("n", "mdd_dur", "mcl", "shorts", "longs"):
        return f"{v:.0f}"
    if k in ("gross", "fees", "net", "final", "avg_win", "avg_loss", "expectancy"):
        return f"₹{v:,.2f}"
    if k == "tpm":
        return f"{v:.1f}"
    if k == "avg_held":
        return f"{v:.1f}"
    return str(v)


def main():
    print(f"=== MASTER backtest: {PAIR_A} vs {PAIR_B}  mode={MODE}  capital=₹{CAPITAL:,.0f}  "
          f"window={WINDOW}  entry_z=±{ENTRY_Z}  stop=₹{STOP_RS or 0}  tp=₹{TP_RS or 0} ===")
    a = yf.Ticker(PAIR_A).history(period="60d" if MODE == "intraday" else None,
                                  interval="5m" if MODE == "intraday" else "1d",
                                  start=None if MODE == "intraday" else "2023-01-01",
                                  end=None if MODE == "intraday" else "2026-08-29",
                                  auto_adjust=True)
    b = yf.Ticker(PAIR_B).history(period="60d" if MODE == "intraday" else None,
                                  interval="5m" if MODE == "intraday" else "1d",
                                  start=None if MODE == "intraday" else "2023-01-01",
                                  end=None if MODE == "intraday" else "2026-08-29",
                                  auto_adjust=True)
    df = a["Close"].rename("pa").to_frame().join(b["Close"].rename("pb"), how="inner").dropna()
    print(f"  bars: {len(df)}  {df.index.min()} -> {df.index.max()}")

    eq, trades, spreads, zs = run(df, WINDOW, ENTRY_Z, STOP_RS, TP_RS)
    m = metrics(eq, trades, df.index)

    print(f"\n  trades: {m['n']} ({m['longs']} LONG / {m['shorts']} SHORT, {m['tpm']:.1f}/mo)")
    print(f"  gross ₹{m['gross']:+,.2f}  fees ₹{m['fees']:,.2f}  net ₹{m['net']:+,.2f}  "
          f"final ₹{m['final']:,.2f} ({m['total_ret']*100:+.2f}%)")
    print(f"  Sharpe {m['sharpe']:.2f}  Sortino {m['sortino']:.2f}  MaxDD {m['mdd']*100:.2f}% "
          f"({m['mdd_dur']}d)  CAGR {m['cagr']*100:.2f}%  Calmar {m['calmar']:.2f}")
    print(f"  ProfitFactor {m['pf']:.2f}  net win% {m['win_rate']*100:.0f}%  expectancy ₹{m['expectancy']:,.2f}  "
          f"max consec losses {m['mcl']}")
    for t in trades[-15:]:
        print(f"    {t['in']} -> {t['out']}  {t['d']:5} q={t['q']:>3} {t['reason']:>4}  "
              f"gross ₹{t['gross']:+7.0f}  net ₹{t['net']:+7.0f}")

    # ---- plots ----
    x = list(range(len(df)))
    fig, axes = plt.subplots(4, 1, figsize=(14, 13), sharex=True)
    axes[0].plot(x, df["pa"], label=PAIR_A, lw=0.8)
    axes[0].plot(x, df["pb"], label=PAIR_B, lw=0.8)
    axes[0].set_ylabel("price"); axes[0].legend(fontsize=8); axes[0].grid(alpha=0.3)
    axes[0].set_title(f"MASTER backtest — two-sided, capital ₹{CAPITAL:,.0f}, mode={MODE}, "
                      f"window={WINDOW}, entry_z=±{ENTRY_Z}")

    axes[1].plot(x, spreads, color="tab:blue", lw=0.6, label="log spread")
    axes[1].set_ylabel("log spread"); axes[1].grid(alpha=0.3)

    axes[2].plot(x, zs, color="tab:orange", lw=0.7, label="z-score")
    axes[2].axhline(ENTRY_Z, color="r", ls="--", lw=0.8)
    axes[2].axhline(-ENTRY_Z, color="r", ls="--", lw=0.8)
    axes[2].axhline(0, color="k", lw=0.6)
    axes[2].set_ylabel("z-score"); axes[2].grid(alpha=0.3)

    axes[3].plot(eq.index, eq.values, color="tab:green", lw=1, label=f"equity → ₹{m['final']:,.0f}")
    axes[3].axhline(CAPITAL, color="k", ls="--", lw=0.8)
    axes[3].set_ylabel("portfolio ₹"); axes[3].grid(alpha=0.3)
    axes[3].set_xlabel(f"bar index  {df.index[0]} -> {df.index[-1]}")

    # drawdown subplot for equity
    run_max = eq.cummax()
    dd = (eq / run_max - 1) * 100
    axdd = axes[3].twinx()
    axdd.fill_between(eq.index, dd.values, 0, color="tab:red", alpha=0.35)
    axdd.set_ylabel("drawdown %", color="tab:red")
    axdd.tick_params(axis="y", labelcolor="tab:red")

    plt.tight_layout()
    plt.savefig(PNG, dpi=110)
    print(f"\nplot saved: {PNG}")

    # ---- md report ----
    md = []
    md.append(f"# Master Backtest Report — {PAIR_A} vs {PAIR_B}\n")
    md.append(f"**Data:** Yahoo {MODE}  {df.index[0]} → {df.index[-1]}  ({len(df)} bars)\n")
    md.append(f"**Strategy:** two-sided spread reversion, spread = ln(PA) − ln(PB), rolling z-score; "
              f"enter LONG z<−{ENTRY_Z} / SHORT z>+{ENTRY_Z}; exit z crosses 0, stop ₹{STOP_RS or 'off'}, "
              f"take-profit ₹{TP_RS or 'off'}.\n")
    md.append(f"**Portfolio:** start ₹{CAPITAL:,.0f}, qty = floor(balance / (PA+PB)) per trade.\n")
    md.append(f"**Fees:** Groww intraday (MIS) 4 legs/round trip.\n")
    md.append("\n## Summary\n")
    md.append("| Metric | Value | Metric | Value |")
    md.append("|---|---:|---|---:|")
    rows = [("Trades", "n"), ("LONG / SHORT", None), ("Trades / month", "tpm"), ("Avg hold (bars)", "avg_held"),
            ("Gross P&L", "gross"), ("Fees", "fees"), ("Net P&L", "net"), ("Final portfolio", "final"),
            ("Total return", "total_ret"), ("CAGR", "cagr"), ("Sharpe (daily, ann.)", "sharpe"),
            ("Sortino", "sortino"), ("Max drawdown", "mdd"), ("Max DD duration", "mdd_dur"),
            ("Calmar", "calmar"), ("Profit factor", "pf"), ("Net win rate", "win_rate"),
            ("Avg win", "avg_win"), ("Avg loss", "avg_loss"), ("Expectancy / trade", "expectancy"),
            ("Max consecutive losses", "mcl"), (None, None)]
    # build two-column layout
    pairs = []
    for i in range(0, len(rows), 2):
        r1 = rows[i]
        r2 = rows[i + 1] if i + 1 < len(rows) else (None, None)
        if r1 == (None, None) and r2 == (None, None):
            continue
        pairs.append((r1, r2))

    def cell(l, k):
        if k:
            return fmt(k, m[k])
        if l == "LONG / SHORT":
            return f"{m['longs']} / {m['shorts']}"
        return ""

    for (l1, k1), (l2, k2) in pairs:
        if l2:
            md.append(f"| {l1} | {cell(l1, k1)} | {l2} | {cell(l2, k2)} |")
        else:
            md.append(f"| {l1} | {cell(l1, k1)} |  |  |")

    md.append("\n## Trade list (last 20)\n")
    md.append("| in | out | dir | qty | exit | gross | fees | net |")
    md.append("|---|---|---|---:|---|---:|---:|---:|")
    for t in trades[-20:]:
        md.append(f"| {t['in']} | {t['out']} | {t['d']} | {t['q']} | {t['reason']} "
                  f"| ₹{t['gross']:,.0f} | ₹{t['fees']:,.0f} | ₹{t['net']:,.0f} |")

    md.append("\n## How to read this\n")
    md.append(f"- **Sharpe {m['sharpe']:.2f}** = profit per unit of risk (daily, annualized). >1 good, <0 losing.\n")
    md.append(f"- **Sortino {m['sortino']:.2f}** = like Sharpe but only counts downside moves.\n")
    md.append(f"- **MaxDD {m['mdd']*100:.2f}%** = worst peak-to-trough drop of your balance.\n")
    md.append(f"- **CAGR {m['cagr']*100:.2f}%** = average yearly growth.\n")
    md.append(f"- **Profit factor {m['pf']:.2f}** = total winnings ÷ total losses (>1 profitable).\n")
    md.append(f"- **Expectancy ₹{m['expectancy']:,.2f}** = average ₹ per trade.\n")
    md.append(f"- **Net win rate {m['win_rate']*100:.0f}%** = fraction of trades that made money after fees.\n")
    md.append("\nThe graphs show: prices (top), log spread, z-score with ±entry lines, and portfolio "
              "equity with a red drawdown overlay.\n")

    with open(MD, "w") as f:
        f.write("\n".join(md))
    print(f"report saved: {MD}")


if __name__ == "__main__":
    main()
