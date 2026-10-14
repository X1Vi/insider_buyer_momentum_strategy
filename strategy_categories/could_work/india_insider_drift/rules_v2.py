#!/usr/bin/env python3
"""
rules_v2.py — few trades, long holds, stop-loss, RSI + EMA200, vectorbt.

Rules (as requested):
  Signal : major insider (promoter/director/KMP) market-BUYS (>= MIN_VALUE).
  ONE TRADE PER EPISODE: after we exit, we only re-enter on a NEW insider buy.
  Entry  : 2 trading days after the buy, at the open.
  Hold   : up to 6 months (126 trading days).
  Exit   : the EARLIEST of
             - stop-loss: close <= entry*(1 - SL)        (drawdown stop)
             - downturn : close < EMA(EXIT_EMA)          ("starts going down")
             - 6 months reached.
  Plot   : price + EMA(200) + entries/exits, and RSI(14) underneath.
  Backtest: vectorbt Portfolio.from_signals.

Run with the venv that has vectorbt + yfinance:
  volume_indicator_studies/.venv/bin/python rules_v2.py
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd
import vectorbt as vbt
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from backtest_insider import load_events, load_px  # noqa: E402

MIN_VALUE = 2.5e6
ENTRY_DELAY = 2
MAX_HOLD = 126            # ~6 months
MIN_HOLD = 20             # hold ~1 month before a trend exit can fire (minor dips ignored)
EXIT_EMA = 50             # "starts going down" (slower = fewer whipsaws)
SL = 0.15                 # stop-loss 15% from entry (the drawdown stop)
COST = 0.0075             # round trip
OOS_START = "2024-01-01"
BASKET = ("ADANIPORTS,CHAMBLFERT,MAHSEAMLES,JSWSTEEL,GRASIM,GODREJAGRO,GODREJIND,"
          "APOLLOTYRE,DBCORP,STEL,NCLIND,NRBBEARING,NCC,MANINFRA,APLLTD,JSL,"
          "SURYAROSNI,BAJAJHLDNG").split(",")


def rsi(s, p=14):
    d = s.diff()
    ag = d.clip(lower=0).ewm(alpha=1 / p, min_periods=p, adjust=False).mean()
    al = (-d.clip(upper=0)).ewm(alpha=1 / p, min_periods=p, adjust=False).mean()
    return 100 - 100 / (1 + ag / al.replace(0, np.nan))


def build_signals(sym, ev, px):
    """Return (entries, exits) boolean Series for one symbol, one trade per episode."""
    idx = px.index
    close = px["close"].to_numpy(float)
    open_ = px["open"].to_numpy(float)
    ema = px["close"].ewm(span=EXIT_EMA, adjust=False).mean().to_numpy()
    entries = np.zeros(len(idx), bool)
    exits = np.zeros(len(idx), bool)
    next_allowed = -1
    for t in ev[ev["symbol"] == sym]["d"].sort_values().to_numpy():
        e0 = np.searchsorted(idx, np.datetime64(t))
        ei = e0 + ENTRY_DELAY
        if ei >= len(idx) - 1 or ei <= next_allowed:
            continue                                   # already holding / too soon
        entry = open_[ei]
        if not np.isfinite(entry) or entry <= 0:
            continue
        entries[ei] = True
        # find exit: stop-loss can fire any time; trend exit only after MIN_HOLD
        xi = min(ei + MAX_HOLD, len(idx) - 1)
        for x in range(ei + 1, min(ei + MAX_HOLD, len(idx) - 1)):
            if close[x] <= entry * (1 - SL):                       # stop-loss
                xi = x; break
            if x >= ei + MIN_HOLD and np.isfinite(ema[x]) and close[x] < ema[x]:
                xi = x; break                                      # downturn
        exits[xi] = True
        next_allowed = xi                              # no re-entry until after exit
    return pd.Series(entries, index=idx), pd.Series(exits, index=idx)


def main():
    ev = load_events(MIN_VALUE)
    all_trades, strats, pxmap = [], [], {}
    for s in BASKET:
        px = load_px(s)
        if px is None or len(px) < 250:
            continue
        ent, ex = build_signals(s, ev, px)
        if ent.sum() == 0:
            continue
        pxmap[s] = px
        pf = vbt.Portfolio.from_signals(px["close"], ent, ex, fees=COST / 2,
                                        freq="1D", init_cash=100_000)
        tr = pf.trades.records_readable
        if len(tr):
            tr = tr.assign(symbol=s)
            all_trades.append(tr)
        strats.append(pf.value() / 100_000.0)
    if not all_trades:
        print("no trades"); return
    trades = pd.concat(all_trades, ignore_index=True)
    combined = pd.concat(strats, axis=1).mean(axis=1).dropna()

    print("=== insider buy -> 2d -> hold <=6m, exit on drop/stop ===")
    print(f"  symbols {len(strats)}  trades {len(trades)}  "
          f"({len(trades)/((combined.index[-1]-combined.index[0]).days/365.25):.1f}/yr)")
    pnl = trades["PnL"].to_numpy()
    print(f"  win rate {np.mean(pnl>0):.2f}  avg PnL Rs {pnl.mean():,.0f}  "
          f"median Rs {np.median(pnl):,.0f}")
    hold = (pd.to_datetime(trades["Exit Timestamp"]) -
            pd.to_datetime(trades["Entry Timestamp"])).dt.days
    print(f"  avg hold {hold.mean():.0f}d (median {hold.median():.0f}, "
          f"max {hold.max():.0f})")
    # combined equity metrics
    ret = combined.pct_change().dropna()
    yrs = (combined.index[-1] - combined.index[0]).days / 365.25
    cagr = combined.iloc[-1] ** (1 / yrs) - 1
    dd = (combined / combined.cummax() - 1).min()
    sharpe = ret.mean() / ret.std() * np.sqrt(252)
    print(f"  portfolio: total {100*(combined.iloc[-1]-1):.1f}%  CAGR {100*cagr:.2f}%  "
          f"vol {100*ret.std()*np.sqrt(252):.1f}%  Sharpe {sharpe:.2f}  "
          f"maxDD {100*dd:.1f}%  Calmar {cagr/abs(dd):.2f}")

    # Rs 8,000 / 5,000 (one position at a time, sequential, from our trades)
    rets = trades["Return"].to_numpy()
    ent_dates = pd.to_datetime(trades["Entry Timestamp"])
    ex_dates = pd.to_datetime(trades["Exit Timestamp"])
    for C in (8000, 5000):
        order = np.argsort(ent_dates.values)
        cash, cur, taken, eq = float(C), None, [], [float(C)]
        for i in order:
            if cur is not None and ent_dates.iloc[i] < cur:
                continue
            cash *= (1 + rets[i])          # vectorbt Return is already net of fees
            taken.append(rets[i]); cur = ex_dates.iloc[i]; eq.append(cash)
        eq = np.array(eq)
        print(f"  Rs {C:,}: {len(taken)} trades  final Rs {eq[-1]:,.0f} "
              f"({100*(eq[-1]/C-1):.0f}%, maxDD {100*(eq/np.maximum.accumulate(eq)-1).min():.0f}%)")

    # ---- plots ----
    OUT = HERE / "plots" / "rules_v2"
    OUT.mkdir(parents=True, exist_ok=True)
    counts = trades.groupby("symbol").size().sort_values(ascending=False)
    for s in counts.head(6).index:
        px = pxmap[s]
        ent, ex = build_signals(s, ev, px)
        fig, (ax, ax2) = plt.subplots(2, 1, figsize=(13, 7.5), sharex=True,
                                      gridspec_kw={"height_ratios": [3, 1]})
        ax.plot(px.index, px["close"], color="#333", lw=0.9, label="close")
        ax.plot(px.index, px["close"].ewm(span=200, adjust=False).mean(),
                color="#8c6d31", lw=1.0, label="EMA(200)")
        ax.plot(px.index, px["close"].ewm(span=EXIT_EMA, adjust=False).mean(),
                color="#4575b4", lw=1.0, label=f"EMA({EXIT_EMA}) exit")
        ax.scatter(px.index[ent], px["close"][ent], marker="^", s=110,
                   color="#1a9850", edgecolor="white", lw=0.5, label="invest", zorder=4)
        ax.scatter(px.index[ex], px["close"][ex], marker="x", s=70,
                   color="#d73027", lw=1.3, label="sell", zorder=4)
        ax.set_title(f"{s} — {int(ent.sum())} trades total (one per insider episode)")
        ax.legend(fontsize=8, loc="upper left"); ax.grid(alpha=0.25)
        r = rsi(px["close"])
        ax2.plot(px.index, r, color="#555", lw=0.9)
        ax2.axhline(70, color="#d73027", ls="--", lw=0.7)
        ax2.axhline(30, color="#1a9850", ls="--", lw=0.7)
        ax2.set_ylim(0, 100); ax2.set_ylabel("RSI(14)"); ax2.grid(alpha=0.25)
        fig.tight_layout(); fig.savefig(OUT / f"{s}.png", dpi=140); plt.close(fig)
        print(f"  plot -> {(OUT/f'{s}.png').relative_to(HERE)}")


if __name__ == "__main__":
    main()
