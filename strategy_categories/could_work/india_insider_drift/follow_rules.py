#!/usr/bin/env python3
"""
follow_rules.py — the rules as specified.

  Signal : a MAJOR insider (promoter/director/KMP) market-BUYS (>= MIN_VALUE).
  Entry  : wait up to ENTRY_DELAY days, then buy at the OPEN (default 2 days).
  Hold   : at least MIN_HOLD days (1 week). KEEP HOLDING while it keeps rising
           with minor dips.
  Exit   : sell once it STARTS DROPPING — the indicator is the 10-day EMA:
           exit at the next open when close crosses BELOW EMA(10).
  Size   : full account, one position at a time (long-only, cash), cost per side.

Outputs pooled metrics, Rs 8,000 / Rs 5,000 account sims, and plots showing the
EMA(10) indicator with the entry/exit markers.
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
from backtest_insider import load_events, load_px, metrics  # noqa: E402

MIN_VALUE = 2.5e6
ENTRY_DELAY = 2          # wait up to 2 days after the buy, then invest
EXIT_EMA = 10            # "starts dropping" indicator
MIN_HOLD = 5             # hold at least 1 week
MAX_HOLD = 60
COST = 0.0075
OOS_START = "2024-01-01"
BASKET = ("DBCORP,STEL,MAHSEAMLES,JINDALSTEL,USHAMART,JSL,SURYAROSNI,NRBBEARING,NCC,"
          "MANINFRA,APLLTD,MANGLMCEM,SHOPERSTOP,GREENPLY,PAISALO,JINDRILL,KRISHANA,"
          "TFCILTD,ADANIPORTS,CHAMBLFERT,GODREJAGRO,GODREJIND,APOLLOTYRE,MRF,"
          "BAJAJHLDNG,JSWSTEEL,GRASIM").split(",")


def trades_for(sym, ev):
    px = load_px(sym)
    if px is None:
        return None, None
    idx = px.index
    c = px["close"].to_numpy(float)
    ema = pd.Series(c, index=idx).ewm(span=EXIT_EMA, adjust=False).mean().to_numpy()
    rows = []
    for t in ev[ev["symbol"] == sym]["d"].to_numpy():
        e0 = np.searchsorted(idx, np.datetime64(t))
        ei = e0 + ENTRY_DELAY                       # wait up to 2 days
        if ei >= len(idx) - MIN_HOLD - 1:
            continue
        entry = px["open"].iloc[ei]
        if not np.isfinite(entry) or entry <= 0:
            continue
        # hold >= MIN_HOLD; exit when close < EMA10; cap at MAX_HOLD
        xi = min(ei + MAX_HOLD, len(idx) - 1)
        for x in range(ei + MIN_HOLD, min(ei + MAX_HOLD, len(idx) - 1)):
            if np.isfinite(ema[x]) and c[x] < ema[x]:      # starts dropping
                xi = x + 1
                break
        exitp = px["open"].iloc[min(xi, len(idx) - 1)]
        if not np.isfinite(exitp):
            continue
        rows.append(dict(entry_date=idx[ei], exit_date=idx[min(xi, len(idx) - 1)],
                         entry_px=float(entry), exit_px=float(exitp),
                         net=exitp / entry - 1.0 - COST))
    if not rows:
        return px, None
    return px, pd.DataFrame(rows)


def account_sim(tr, C):
    cash, cur_exit, taken, eq = float(C), None, [], [float(C)]
    for _, t in tr.sort_values("entry_date").iterrows():
        if cur_exit is not None and t["entry_date"] < cur_exit:
            continue
        n = int(cash // t["entry_px"])
        if n < 1:
            continue
        cash += n * t["entry_px"] * t["net"]
        taken.append(t["net"]); cur_exit = t["exit_date"]; eq.append(cash)
    return np.array(taken), np.array(eq)


def main():
    ev = load_events(MIN_VALUE)
    strats, trs, pxmap = [], [], {}
    for s in BASKET:
        px, tr = trades_for(s, ev)
        if px is None or tr is None:
            continue
        pxmap[s] = px
        trs.append(tr.assign(symbol=s))
        pos = pd.Series(0.0, index=px.index)
        for _, t in tr.iterrows():
            pos.loc[t["entry_date"]:t["exit_date"]] = 1.0
        ret = px["close"].pct_change(fill_method=None).fillna(0.0)
        st = pos.shift(1).fillna(0.0) * ret
        for _, t in tr.iterrows():
            st.loc[t["entry_date"]] -= COST / 2
            st.loc[t["exit_date"]] -= COST / 2
        strats.append(st.rename(s))
    combined = pd.concat(strats, axis=1).mean(axis=1).dropna()
    pooled = pd.concat(trs, ignore_index=True)
    pm = metrics(combined, pooled, (combined != 0).astype(float))
    hold = (pooled["exit_date"] - pooled["entry_date"]).dt.days
    print("=== insider buy -> wait 2d -> hold, exit on close<EMA10 ===")
    print(f"  trades {pm['n']}  win {pm['win']:.2f}  avg net {pm['avg_net']*100:.2f}%  "
          f"Sharpe {pm['sharpe']:.2f}  maxDD {pm['maxdd']*100:.1f}%  "
          f"Calmar {pm['calmar']:.2f}  exposure {pm['exposure']*100:.1f}%")
    print(f"  avg hold {hold.mean():.0f}d (median {hold.median():.0f}, max {hold.max():.0f})")
    oos = pooled[pooled["entry_date"] >= OOS_START]
    if len(oos):
        print(f"  OOS trades {len(oos)}  win {(oos['net']>0).mean():.2f}  "
              f"avg net {oos['net'].mean()*100:.2f}%")

    for C in (8000, 5000):
        taken, eq = account_sim(pooled, C)
        if len(taken) == 0:
            continue
        yrs = (pooled["exit_date"].max() - pooled["entry_date"].min()).days / 365.25
        final = eq[-1]
        dd = (eq / np.maximum.accumulate(eq) - 1).min()
        rng = np.random.default_rng(1)
        per = max(1, round(len(taken) / yrs))
        sims = np.array([np.prod(1 + rng.choice(taken, size=per, replace=True)) - 1
                         for _ in range(5000)])
        print(f"\n  Rs {C:,}: {len(taken)} trades, win {np.mean(taken>0):.2f}, "
              f"final Rs {final:,.0f} ({100*(final/C-1):.0f}%, "
              f"CAGR {100*((final/C)**(1/yrs)-1):.1f}%, maxDD {dd*100:.0f}%)")
        print(f"      year p5 {np.percentile(sims,5)*100:.0f}%  "
              f"p50 {np.percentile(sims,50)*100:.0f}%  "
              f"p95 {np.percentile(sims,95)*100:.0f}%  P(loss)={np.mean(sims<0):.2f}")

    # ---- plots: price + EMA10 + entry/exit ----
    OUT = HERE / "plots" / "rules"
    OUT.mkdir(parents=True, exist_ok=True)
    counts = pooled.groupby("symbol").size().sort_values(ascending=False)
    for s in counts.head(6).index:
        px = pxmap[s]
        tr = pooled[pooled["symbol"] == s]
        ema = px["close"].ewm(span=EXIT_EMA, adjust=False).mean()
        fig, ax = plt.subplots(figsize=(13, 5.5))
        ax.plot(px.index, px["close"].values, color="#333", lw=0.9, label="close")
        ax.plot(px.index, ema.values, color="#4575b4", lw=1.0,
                label=f"EMA({EXIT_EMA}) — exit indicator")
        ax.scatter(tr["entry_date"], px["close"].reindex(tr["entry_date"], method="nearest"),
                   marker="^", s=80, color="#1a9850", edgecolor="white", lw=0.4,
                   label="invest", zorder=4)
        ax.scatter(tr["exit_date"], px["close"].reindex(tr["exit_date"], method="nearest"),
                   marker="x", s=55, color="#d73027", lw=1.1, label="sell", zorder=4)
        ax.set_title(f"{s} — buy after insider, exit when close < EMA10")
        ax.legend(fontsize=8, loc="upper left"); ax.grid(alpha=0.25)
        fig.tight_layout(); fig.savefig(OUT / f"{s}.png", dpi=140); plt.close(fig)
        print(f"  plot -> {(OUT/f'{s}.png').relative_to(HERE)}")


if __name__ == "__main__":
    main()
