#!/usr/bin/env python3
"""
patterns.py — pin out the reaction PATTERNS after a major insider buy.

Question: does the price react FAST (days) or drift SLOWLY (months/a year)? And
which stocks/patterns react strongly enough to be tradeable?

For every major-insider market-buy event (>= MIN_VALUE, promoter/director/KMP) we
measure the forward EXCESS return (vs Nifty) at 1,3,5,10,20,60,120,250 trading
days, then classify the shape:

  FAST   : +>=3% within 5 days                      (news reaches price quickly)
  SLOW   : <3% at 5d but +>=5% by 250d              (the year-long drift)
  KNIFE  : <=-5% by 250d                            (kept falling)
  FLAT   : |250d| < 5% and not fast
  FADE   : +>=3% at 5d but ends lower by 250d       (pop then gives back)

Also: time-to-peak (how many trading days until the best point), and a table of
"famous" large caps' behaviour.

Outputs tables + plots/patterns/*.png.
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
from backtest_insider import load_events, load_px, download, rsi  # noqa: E402

H = (1, 3, 5, 10, 20, 60, 120, 250)
MIN_VALUE = 1e7
FAMOUS = ("RELIANCE TCS HDFCBANK ICICIBANK INFY ITC SBIN BHARTIARTL LT AXISBANK "
          "KOTAKBANK HINDUNILVR MARUTI ASIANPAINT BAJFINANCE HCLTECH WIPRO TITAN "
          "SUNPHARMA NESTLEIND ADANIENT ADANIPORTS TATAMOTORS ONGC NTPC POWERGRID "
          "COALINDIA ULTRACEMCO JSWSTEEL TATASTEEL").split()
OUT = HERE / "plots" / "patterns"
OUT.mkdir(parents=True, exist_ok=True)


def bench():
    import yfinance as yf
    b = yf.download("^NSEI", start="2010-01-01", auto_adjust=True, progress=False)["Close"]
    if isinstance(b, pd.DataFrame):
        b = b.iloc[:, 0]
    b = b.dropna()
    return b.index.to_numpy(), b.to_numpy(float)


def fwd(px, bd, bv, d, h):
    idx = px.index.to_numpy()
    close = px["close"].to_numpy(float)
    p = np.searchsorted(idx, np.datetime64(d))
    if p + h >= len(idx):
        return np.nan
    r = close[p + h] / close[p] - 1.0
    d0, d1 = idx[p], idx[p + h]
    j0, j1 = np.searchsorted(bd, d0), np.searchsorted(bd, d1)
    if j0 >= len(bd) or j1 >= len(bd) or bd[j0] != d0 or bd[j1] != d1:
        return np.nan
    return r - (bv[j1] / bv[j0] - 1.0)


def main():
    ev = load_events(MIN_VALUE)
    # use the existing price panel + the famous names (avoid 1,600 downloads)
    panel_syms = [p.stem for p in (HERE / "data" / "panel").glob("*.csv")]
    syms = sorted(set(panel_syms) | set(FAMOUS))
    download(syms)
    bd, bv = bench()

    rows = []
    for s in syms:
        px = load_px(s)
        if px is None:
            continue
        e = ev[ev["symbol"] == s]
        for d in e["d"]:
            rec = {"symbol": s, "d": d}
            for h in H:
                rec[f"r{h}"] = fwd(px, bd, bv, d, h)
            rows.append(rec)
    df = pd.DataFrame(rows).dropna(subset=["r250"])
    print(f"events with full 250d window: {len(df):,} across {df['symbol'].nunique()} symbols")

    # ---- average reaction profile ----
    prof = {h: df[f"r{h}"].mean() for h in H}
    print("\n=== average excess return vs Nifty, by horizon ===")
    for h in H:
        print(f"  +{h:>3}d : {prof[h]*100:6.2f}%   (median {df[f'r{h}'].median()*100:6.2f}%)")

    # ---- classify shapes ----
    def cls(r):
        r5, r250 = r["r5"], r["r250"]
        if r5 >= 0.03 and r250 < 0:
            return "FADE"
        if r5 >= 0.03:
            return "FAST"
        if r250 <= -0.05:
            return "KNIFE"
        if r250 >= 0.05:
            return "SLOW"
        return "FLAT"
    df["pattern"] = df.apply(cls, axis=1)
    counts = df["pattern"].value_counts()
    print("\n=== pattern counts (share) ===")
    for k, v in counts.items():
        print(f"  {k:6} {v:>6}  {v/len(df)*100:5.1f}%")

    # ---- time to peak (trading days) ----
    # recompute a dense cumulative path for a subsample to find the peak day
    # (cheap: reuse r-horizons as the path; peak horizon among H)
    path = df[[f"r{h}" for h in H]]
    df["peak_h"] = [H[i] for i in np.nanargmax(path.to_numpy(), axis=1)]
    print("\n=== time to peak (which horizon has the max return) ===")
    print(df["peak_h"].value_counts().sort_index().to_string())

    # ---- per-symbol speed: median r5 and median r250 ----
    by = df.groupby("symbol").agg(n=("r5", "size"), r5=("r5", "median"),
                                  r20=("r20", "median"), r250=("r250", "median"),
                                  fast=("pattern", lambda x: (x == "FAST").mean()))
    by = by[by["n"] >= 5].sort_values("r5", ascending=False)
    print("\n=== fastest reactors (median +5d, n>=5) ===")
    print(by.head(15).to_string(float_format=lambda x: f"{x:,.3f}"))

    fam = by[by.index.isin(FAMOUS)]
    print("\n=== famous / large caps ===")
    print(fam.to_string(float_format=lambda x: f"{x:,.3f}"))

    # ---- plots ----
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.plot(H, [prof[h]*100 for h in H], "o-", color="#1a9850")
    ax.axhline(0, color="#999", lw=0.8)
    ax.set_xscale("log")
    ax.set_xticks(H); ax.set_xticklabels(H)
    ax.set_xlabel("trading days after the buy"); ax.set_ylabel("mean excess return vs Nifty (%)")
    ax.set_title("Average reaction after a major insider buy — slow, not fast")
    ax.grid(alpha=0.25)
    fig.tight_layout(); fig.savefig(OUT/"car_profile.png", dpi=140); plt.close(fig)

    fig, ax = plt.subplots(figsize=(8, 6))
    colors = {"FAST": "#1a9850", "SLOW": "#4575b4", "KNIFE": "#d73027",
              "FLAT": "#999999", "FADE": "#fdae61"}
    for k, g in df.groupby("pattern"):
        ax.scatter(g["r5"]*100, g["r250"]*100, s=8, alpha=0.35, color=colors[k],
                   label=f"{k} ({len(g)})")
    ax.axhline(0, color="#999", lw=0.7); ax.axvline(0, color="#999", lw=0.7)
    ax.set_xlim(-15, 20); ax.set_ylim(-60, 120)
    ax.set_xlabel("+5-day excess (%)"); ax.set_ylabel("+250-day excess (%)")
    ax.set_title("Reaction shapes: fast pop vs slow drift")
    ax.legend(fontsize=8); ax.grid(alpha=0.2)
    fig.tight_layout(); fig.savefig(OUT/"speed_scatter.png", dpi=140); plt.close(fig)

    counts.plot(kind="bar", color="#4d6475", figsize=(7, 4))
    plt.title("Pattern counts"); plt.tight_layout()
    plt.savefig(OUT/"pattern_counts.png", dpi=140); plt.close()

    print(f"\nplots -> {OUT}")
    df.to_csv(HERE/"data"/"patterns.csv", index=False)


if __name__ == "__main__":
    main()
