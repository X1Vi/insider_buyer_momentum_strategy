#!/usr/bin/env python3
"""
momentum_entry.py — catch momentum after an insider buy.

Rules:
  Signal : major insider (promoter/director/KMP) market-BUYS (>= MIN_VALUE).
  Entry  : within WATCH days of the buy, buy the next open after price
           BREAKS ITS HIGHEST HIGH (new HI_N-day high close) AND
           close > EMA(50) > EMA(200)   (both EMAs BELOW the price = uptrend) AND
           price has risen at least MIN_RISE from its disclosure-date close.
  Stop   : hard stop-loss SL below entry (and EMA50 acts as a trail).
  Exit   : after close falls back to / below EMA(50), or confirms the stop,
           sell at the next open; otherwise exit at MAX_HOLD.
  Plot   : price + EMA50 + EMA200 + insider-buy/disclosure markers + the MIN_RISE
           confirmation level + our entry/exit, RSI below.

Run:  volume_indicator_studies/.venv/bin/python momentum_entry.py
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from backtest_insider import load_events, load_px  # noqa: E402

MIN_VALUE = 2.5e6
WATCH = 60          # look for the breakout within this many days of the buy
HI_N = 20           # "highest high" lookback
MIN_RISE = 0.10     # require +10% from disclosure-date close before investing
SL = 0.10           # stop-loss 10%
MAX_HOLD = 126       # about six trading months
COST = 0.0075
BASKET = ("ADANIPORTS,CHAMBLFERT,MAHSEAMLES,JSWSTEEL,GRASIM,GODREJAGRO,GODREJIND,"
          "APOLLOTYRE,DBCORP,STEL,NCLIND,NRBBEARING,NCC,MANINFRA,APLLTD,JSL,"
          "SURYAROSNI,BAJAJHLDNG,TFCILTD,KRISHANA").split(",")


def rsi(s, p=14):
    d = s.diff()
    ag = d.clip(lower=0).ewm(alpha=1 / p, min_periods=p, adjust=False).mean()
    al = (-d.clip(upper=0)).ewm(alpha=1 / p, min_periods=p, adjust=False).mean()
    return 100 - 100 / (1 + ag / al.replace(0, np.nan))


def signals(sym, ev, px):
    idx = px.index
    close = px["close"].to_numpy(float)
    open_ = px["open"].to_numpy(float)
    hi = px["close"].rolling(HI_N).max().shift(1).to_numpy()
    ema50 = px["close"].ewm(span=50, adjust=False).mean().to_numpy()
    ema200 = px["close"].ewm(span=200, adjust=False).mean().to_numpy()
    ent = np.zeros(len(idx), bool); ex = np.zeros(len(idx), bool)
    confirmations = []
    next_allowed = -1
    for t in ev[ev["symbol"] == sym]["d"].sort_values().to_numpy():
        start = np.searchsorted(idx, np.datetime64(t))
        if start >= len(idx):
            continue
        reference = close[start]
        if not np.isfinite(reference) or reference <= 0:
            continue
        rise_level = reference * (1 + MIN_RISE)
        ei = None
        for e in range(start, min(start + WATCH, len(idx) - 2)):
            if e > 0 and np.isfinite(hi[e]) and close[e] > hi[e] \
                    and np.isfinite(ema50[e]) and np.isfinite(ema200[e]) \
                    and close[e] > ema50[e] > ema200[e] \
                    and close[e] >= rise_level:
                ei = e + 1; break
        if ei is None or ei >= len(idx) - 2 or ei <= next_allowed:
            continue
        entry = open_[ei]
        if not np.isfinite(entry) or entry <= 0:
            continue
        ent[ei] = True
        xi = min(ei + MAX_HOLD, len(idx) - 1)
        for x in range(ei, min(ei + MAX_HOLD, len(idx) - 1)):
            if close[x] <= entry * (1 - SL):          # hard stop
                xi = x + 1; break                     # close confirms; next open
            if np.isfinite(ema50[x]) and close[x] < ema50[x]:   # EMA50 catches up
                xi = x + 1; break                     # close confirms; next open
        ex[xi] = True
        next_allowed = xi
        confirmations.append(dict(
            disclosure_date=idx[start], signal_date=idx[ei - 1],
            entry_date=idx[ei], reference=reference, rise_level=rise_level,
            achieved_rise=close[ei - 1] / reference - 1,
        ))
    return ent, ex, confirmations


def main():
    ev = load_events(MIN_VALUE)
    trs, strats, pxmap = [], [], {}
    for s in BASKET:
        px = load_px(s)
        if px is None or len(px) < 250:
            continue
        ent, ex, confirmations = signals(s, ev, px)
        if ent.sum() == 0:
            continue
        pxmap[s] = (px, ent, ex, confirmations)
        trades = []
        for ei in np.where(ent)[0]:
            xi = int(np.where(ex[ei:])[0][0] + ei)
            r = px["open"].iloc[xi] / px["open"].iloc[ei] - 1 - COST
            trades.append(dict(symbol=s, entry_date=px.index[ei],
                               exit_date=px.index[xi], net=r))
        if trades:
            trs.append(pd.DataFrame(trades))
        pos = pd.Series(0.0, index=px.index)
        for t in trades:
            pos.loc[t["entry_date"]:t["exit_date"]] = 1.0
        st = pos.shift(1).fillna(0.0) * px["close"].pct_change(fill_method=None).fillna(0.0)
        for t in trades:
            st.loc[t["entry_date"]] -= COST / 2
            st.loc[t["exit_date"]] -= COST / 2
        strats.append(st.rename(s))
    if not trs:
        print("no trades"); return
    pooled = pd.concat(trs, ignore_index=True)
    combined = pd.concat(strats, axis=1, sort=True).mean(axis=1).dropna()
    eq = (1 + combined).cumprod()
    ret = combined
    yrs = (eq.index[-1] - eq.index[0]).days / 365.25
    cagr = eq.iloc[-1] ** (1 / yrs) - 1
    dd = (eq / eq.cummax() - 1).min()
    hold = (pooled["exit_date"] - pooled["entry_date"]).dt.days
    print("=== momentum entry: insider buy -> minimum rise -> breakout, EMA trend, stop, exit<EMA50 ===")
    print(f"  minimum rise before entry: {MIN_RISE:.0%} from disclosure-date close")
    print(f"  trades {len(pooled)} ({len(pooled)/yrs:.1f}/yr)  win {(pooled['net']>0).mean():.2f}  "
          f"avg net {pooled['net'].mean()*100:.2f}%  median {pooled['net'].median()*100:.2f}%")
    print(f"  avg hold {hold.mean():.0f}d (median {hold.median():.0f}, max {hold.max():.0f})")
    print(f"  portfolio: CAGR {100*cagr:.2f}%  vol {100*ret.std()*np.sqrt(252):.1f}%  "
          f"Sharpe {ret.mean()/ret.std()*np.sqrt(252):.2f}  maxDD {100*dd:.1f}%  "
          f"Calmar {cagr/abs(dd):.2f}")

    OUT = HERE / "plots" / "momentum_cap"
    OUT.mkdir(parents=True, exist_ok=True)
    counts = pooled.groupby("symbol").size().sort_values(ascending=False)
    for s in counts.head(6).index:
        px, ent, ex, confirmations = pxmap[s]
        fig, (ax, ax2) = plt.subplots(2, 1, figsize=(13, 7.5), sharex=True,
                                      gridspec_kw={"height_ratios": [3, 1]})
        ax.plot(px.index, px["close"], color="#333", lw=0.9, label="close")
        ax.plot(px.index, px["close"].ewm(span=50, adjust=False).mean(),
                color="#4575b4", lw=1.0, label="EMA(50)")
        ax.plot(px.index, px["close"].ewm(span=200, adjust=False).mean(),
                color="#8c6d31", lw=1.1, label="EMA(200)")
        buys = ev[ev["symbol"] == s]
        ax.scatter(buys["trade_date"], px["close"].reindex(buys["trade_date"], method="nearest"),
                   marker="o", s=16, color="#9ecae1", alpha=0.55,
                   label="insider trade date", zorder=3)
        disclosure_dates = pd.DatetimeIndex([c["disclosure_date"] for c in confirmations])
        ax.scatter(disclosure_dates,
                   px["close"].reindex(disclosure_dates, method="nearest"),
                   marker="D", s=34, color="#fdae61", edgecolor="white", lw=0.4,
                   label="public disclosure (selected)", zorder=4)
        for i, c in enumerate(confirmations):
            ax.hlines(c["rise_level"], c["disclosure_date"], c["signal_date"],
                      color="#7b3294", ls="--", lw=1.2, alpha=0.9,
                      label=f"+{MIN_RISE:.0%} momentum threshold" if i == 0 else None,
                      zorder=2)
        ax.scatter(px.index[ent], px["open"][ent], marker="^", s=110, color="#1a9850",
                   edgecolor="white", lw=0.5, label="invest next open", zorder=5)
        ax.scatter(px.index[ex], px["open"][ex], marker="x", s=70, color="#d73027",
                   lw=1.3, label="sell", zorder=5)
        ax.set_title(f"{s} — require +{MIN_RISE:.0%} rise, then breakout with EMA50 > EMA200")
        ax.legend(fontsize=8, loc="upper left"); ax.grid(alpha=0.25)
        r = rsi(px["close"])
        ax2.plot(px.index, r, color="#555", lw=0.9)
        ax2.axhline(70, color="#d73027", ls="--", lw=0.7)
        ax2.axhline(30, color="#1a9850", ls="--", lw=0.7)
        ax2.set_ylim(0, 100); ax2.set_ylabel("RSI(14)"); ax2.grid(alpha=0.25)
        fig.tight_layout(); fig.savefig(OUT / f"{s}.png", dpi=140); plt.close(fig)
        print(f"  plot -> {(OUT/f'{s}.png').relative_to(HERE)}")

        # A focused view makes a rare trade and its confirmation threshold legible.
        c = confirmations[-1]
        ei = px.index.get_indexer([c["entry_date"]])[0]
        if ei < 0:
            continue
        later_exits = np.where(ex & (np.arange(len(ex)) >= ei))[0]
        if not len(later_exits):
            continue
        xi = int(later_exits[0])
        lo = max(0, px.index.get_loc(c["disclosure_date"]) - 60)
        hi_zoom = min(len(px), xi + 41)
        z = px.iloc[lo:hi_zoom]
        fig, (ax, ax2) = plt.subplots(2, 1, figsize=(12, 7), sharex=True,
                                      gridspec_kw={"height_ratios": [3, 1]})
        ax.plot(z.index, z["close"], color="#333", lw=1.25, label="close")
        ax.plot(z.index, px["close"].ewm(span=50, adjust=False).mean().iloc[lo:hi_zoom],
                color="#4575b4", lw=1.2, label="EMA(50)")
        ax.plot(z.index, px["close"].ewm(span=200, adjust=False).mean().iloc[lo:hi_zoom],
                color="#8c6d31", lw=1.2, label="EMA(200)")
        ax.scatter(c["disclosure_date"], c["reference"], marker="D", s=75,
                   color="#fdae61", edgecolor="white", lw=0.6,
                   label="public disclosure", zorder=5)
        ax.hlines(c["rise_level"], c["disclosure_date"], c["signal_date"],
                  color="#7b3294", ls="--", lw=2,
                  label=f"required +{MIN_RISE:.0%} rise", zorder=3)
        ax.scatter(c["signal_date"], px.loc[c["signal_date"], "close"], marker="*",
                   s=150, color="#7b3294", edgecolor="white", lw=0.6,
                   label=f"confirmed +{c['achieved_rise']:.1%}", zorder=6)
        ax.scatter(c["entry_date"], px.loc[c["entry_date"], "open"], marker="^",
                   s=140, color="#1a9850", edgecolor="white", lw=0.6,
                   label="invest next open", zorder=6)
        ax.scatter(px.index[xi], px["open"].iloc[xi], marker="x", s=90,
                   color="#d73027", lw=1.6, label="sell", zorder=6)
        ax.set_title(f"{s} — momentum confirmation before entry")
        ax.legend(fontsize=9, loc="best"); ax.grid(alpha=0.25)
        rz = rsi(px["close"]).iloc[lo:hi_zoom]
        ax2.plot(rz.index, rz, color="#555", lw=1.0)
        ax2.axhline(70, color="#d73027", ls="--", lw=0.7)
        ax2.axhline(30, color="#1a9850", ls="--", lw=0.7)
        ax2.set_ylim(0, 100); ax2.set_ylabel("RSI(14)"); ax2.grid(alpha=0.25)
        fig.tight_layout()
        fig.savefig(OUT / f"{s}_latest.png", dpi=150)
        plt.close(fig)
        print(f"  zoom -> {(OUT/f'{s}_latest.png').relative_to(HERE)}")


if __name__ == "__main__":
    main()
