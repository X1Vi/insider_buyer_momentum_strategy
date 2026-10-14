#!/usr/bin/env python3
"""
trend_variants.py — test the TREND_OVERLAY_PLAN variants (insider bias + price action).

Variants (entry = price action, exit = trend rule):
  A  insider + breakout(20d high) within 5 days  + exit on 10d-low   (V1)
  B  insider + above 200DMA & RSI>50 within 20d  + exit on 50DMA      (V2)
  C  insider + pullback (RSI 40-50, above 50DMA) + exit on 10d-low    (V3)
  D  FAST-reactor stocks only, breakout within 5d + exit on 10d-low   (V4)

Control: random trigger dates, SAME entry/exit pipeline (placebo). A variant that
does not beat its control is dead.

Reports pooled Sharpe / CAGR / maxDD / Calmar / win / avg net / hold, IS/OOS, and
a Rs 8,000 account estimate.
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from backtest_insider import load_events, load_px, download, metrics, rsi  # noqa: E402

MIN_VALUE, COST, MAX_HOLD, OOS_START = 2.5e6, 0.0075, 250, "2024-01-01"
BASKET = ("DBCORP,STEL,MAHSEAMLES,JINDALSTEL,USHAMART,JSL,SURYAROSNI,NRBBEARING,NCC,"
          "MANINFRA,APLLTD,MANGLMCEM,SHOPERSTOP,GREENPLY,PAISALO,JINDRILL,KRISHANA,"
          "TFCILTD").split(",")


def prep(px):
    idx = px.index
    c = px["close"].to_numpy(float)
    s = pd.Series(c, index=idx)
    return dict(idx=idx, close=c,
                hi20=s.rolling(20).max().shift(1).to_numpy(),
                lo10=s.rolling(10).min().shift(1).to_numpy(),
                sma200=s.rolling(200).mean().to_numpy(),
                sma50=s.rolling(50).mean().to_numpy(),
                rsi=rsi(px["close"]).to_numpy())


def simulate(px, P, triggers, entry, exit_, watch, cost=COST):
    idx, close = P["idx"], P["close"]
    trades = []
    for t in triggers:
        start = np.searchsorted(idx, np.datetime64(t))
        ei = None
        for e in range(start, min(start + watch, len(idx) - 2)):
            if entry == "breakout":
                ok = e > 0 and np.isfinite(P["hi20"][e]) and close[e] > P["hi20"][e]
            elif entry == "above200":
                ok = (np.isfinite(P["sma200"][e]) and close[e] > P["sma200"][e]
                      and np.isfinite(P["rsi"][e]) and P["rsi"][e] > 50)
            elif entry == "pullback":
                ok = (np.isfinite(P["sma50"][e]) and close[e] > P["sma50"][e]
                      and np.isfinite(P["rsi"][e]) and 40 <= P["rsi"][e] <= 50)
            else:
                ok = True
            if ok:
                ei = e + 1
                break
        if ei is None or ei >= len(idx) - 2:
            continue
        entry_px = px["open"].iloc[ei]
        if not np.isfinite(entry_px) or entry_px <= 0:
            continue
        xi = min(ei + MAX_HOLD, len(idx) - 1)
        for x in range(ei + 1, min(ei + MAX_HOLD, len(idx) - 1)):
            if exit_ == "donchian10":
                if np.isfinite(P["lo10"][x]) and close[x] < P["lo10"][x]:
                    xi = x + 1
                    break
            elif exit_ == "ma50":
                if np.isfinite(P["sma50"][x]) and close[x] < P["sma50"][x]:
                    xi = x + 1
                    break
        exit_px = px["open"].iloc[min(xi, len(idx) - 1)]
        if not np.isfinite(exit_px):
            continue
        trades.append(dict(entry_date=idx[ei], exit_date=idx[min(xi, len(idx) - 1)],
                           net=exit_px / entry_px - 1.0 - cost))
    if not trades:
        return None
    tr = pd.DataFrame(trades)
    pos = pd.Series(0.0, index=idx)
    for t in trades:
        pos.loc[t["entry_date"]:t["exit_date"]] = 1.0
    ret = px["close"].pct_change(fill_method=None).fillna(0.0)
    strat = pos.shift(1).fillna(0.0) * ret
    for t in trades:
        strat.loc[t["entry_date"]] -= cost / 2
        strat.loc[t["exit_date"]] -= cost / 2
    return strat, tr


def run_variant(ev, syms, entry, exit_, watch, placebo=False, seed=3):
    rng = np.random.default_rng(seed)
    strats, trs = [], []
    for s in syms:
        px = load_px(s)
        if px is None:
            continue
        P = prep(px)
        trig = ev[ev["symbol"] == s]["d"].to_numpy()
        if placebo:
            if len(trig) == 0:
                continue
            trig = P["idx"][rng.integers(200, len(P["idx"]) - 300, size=len(trig))]
        r = simulate(px, P, trig, entry, exit_, watch)
        if r is None:
            continue
        strats.append(r[0].rename(s)); trs.append(r[1])
    if not strats:
        return None
    combined = pd.concat(strats, axis=1).mean(axis=1).dropna()
    pooled = pd.concat(trs, ignore_index=True)
    pm = metrics(combined, pooled, (combined != 0).astype(float))
    hold = (pooled["exit_date"] - pooled["entry_date"]).dt.days.mean()
    oos = pooled[pooled["entry_date"] >= OOS_START]
    pm["hold"] = hold
    pm["oos_n"] = len(oos)
    pm["oos_net"] = oos["net"].mean() if len(oos) else np.nan
    return pm, pooled


def main():
    ev = load_events(MIN_VALUE)
    download(BASKET)
    # FAST basket from patterns.csv
    fast = []
    pcsv = HERE / "data" / "patterns.csv"
    if pcsv.exists():
        p = pd.read_csv(pcsv)
        g = p.groupby("symbol")["pattern"].agg(n="size", fast=lambda x: (x == "FAST").mean())
        fast = g[(g["n"] >= 5) & (g["fast"] >= 0.30)].index.tolist()
    print(f"FAST basket ({len(fast)}): {fast}")

    variants = [
        ("A  breakout5 + 10dlow", BASKET, "breakout", "donchian10", 5),
        ("B  >200DMA&RSI50 + 50DMA", BASKET, "above200", "ma50", 20),
        ("C  pullback + 10dlow", BASKET, "pullback", "donchian10", 30),
        ("D  FAST breakout5 + 10dlow", fast or BASKET, "breakout", "donchian10", 5),
    ]
    hdr = (f"{'variant':30}{'trades':>7}{'win':>6}{'net':>7}{'sharpe':>7}"
           f"{'maxdd':>7}{'calmar':>7}{'hold':>6}{'OOSn':>6}{'OOSnet':>8}")
    print("\n" + hdr); print("-" * len(hdr))
    out = {}
    for label, syms, entry, exit_, watch in variants:
        r = run_variant(ev, syms, entry, exit_, watch)
        ctl = run_variant(ev, syms, entry, exit_, watch, placebo=True)
        if r is None:
            print(f"{label:30}  no trades"); continue
        pm, pooled = r
        print(f"{label:30}{pm['n']:>7}{pm['win']:>6.2f}{pm['avg_net']*100:>7.2f}"
              f"{pm['sharpe']:>7.2f}{pm['maxdd']*100:>7.1f}{pm['calmar']:>7.2f}"
              f"{pm['hold']:>6.0f}{pm['oos_n']:>6}{pm['oos_net']*100:>8.2f}")
        if ctl:
            print(f"{'    (random-entry control)':30}{ctl[0]['n']:>7}{ctl[0]['win']:>6.2f}"
                  f"{ctl[0]['avg_net']*100:>7.2f}{ctl[0]['sharpe']:>7.2f}"
                  f"{ctl[0]['maxdd']*100:>7.1f}{ctl[0]['calmar']:>7.2f}"
                  f"{ctl[0]['hold']:>6.0f}{ctl[0]['oos_n']:>6}{ctl[0]['oos_net']*100:>8.2f}")
        out[label] = (pm, ctl[0] if ctl else None)
    print("\n(if a variant's Sharpe <= its control's Sharpe, the insider signal adds nothing)")


if __name__ == "__main__":
    main()
