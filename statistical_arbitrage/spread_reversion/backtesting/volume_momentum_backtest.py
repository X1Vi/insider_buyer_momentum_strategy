#!/usr/bin/env python3
"""Annual momentum + resilience backtest, using OUR strategy filters.

Goal
----
Find stocks/ETFs that (a) keep rising through the year even in harsh markets and
(b) have momentum that actually suits our volume-surge + breakout -> higher-highs
strategy. This is the "which names should the screener watch" stage.

Our filter (from volume_surge_higher_highs.py findings)
--------------------------------------------------------
The only thing that predicted higher highs was a PRICE BREAKOUT (close > 20d high),
not volume per se. So the strategy trigger we backtest here is:
    SIGNAL = (volume[t] >= 3x SMA20(volume)[t])  AND  (close[t] > 20d high)
i.e. a high-volume upside breakout. We keep the volume filter because the user's
strategy is volume-gated; the finding was that volume alone does nothing, but
breakout+volume == breakout.

Bias controls (same discipline as the volume study)
---------------------------------------------------
- No look-ahead: signal + 20d-high anchor use only data <= t; outcomes use t+1..t+H.
- Events deduped, non-overlapping (gap >= 10d).
- Reported per calendar year AND out-of-sample (2nd half) where useful.
- Survivorship: universe is today's large caps/ETFs; de-listed names absent (flagged).
"""

import os
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")

MULT = 3.0          # volume surge multiplier
W = 20              # breakout anchor (days)
H = 20              # forward window (days)
SEP = 10            # min gap between distinct signals

# market proxy per symbol (for downside capture / "harsh market" measure)
PROXY = {
    "SP500": "SP500",
    "MAFANG": "SP500",
}
DEFAULT_PROXY = "SETFNIF50"   # Indian names proxy


def load():
    out = {}
    for fn in sorted(os.listdir(DATA)):
        if not fn.endswith(".csv"):
            continue
        df = pd.read_csv(os.path.join(DATA, fn), parse_dates=["ts"])
        df = df[["ts", "close", "volume"]].dropna().sort_values("ts").reset_index(drop=True)
        out[fn[:-4]] = df
    return out


def monthly_returns(df):
    d = df.set_index("ts")["close"].resample("ME").last().dropna()
    return d.pct_change().dropna()


def breakout_surges(close, volume, mult=MULT, W=W, sep=SEP):
    """Return indices of deduped, non-overlapping breakout-surge signals (no look-ahead)."""
    close = np.asarray(close, dtype=float)
    volume = np.asarray(volume, dtype=float)
    n = len(close)
    vol_ma = pd.Series(volume).rolling(20, min_periods=20).mean().to_numpy()
    hi20 = pd.Series(close).rolling(W, min_periods=W).max().shift(1).to_numpy()
    sig = np.zeros(n, dtype=bool)
    for t in range(W, n):
        if vol_ma[t] > 0 and volume[t] >= mult * vol_ma[t] and close[t] > hi20[t]:
            sig[t] = True
    idx = []
    i = 0
    while i < n:
        if sig[i]:
            idx.append(i)
            j = i
            while j + 1 < n and sig[j + 1]:
                j += 1
            i = j + sep + 1
        else:
            i += 1
    return np.array(idx)


def strategy_stats(close, volume):
    close = np.asarray(close, dtype=float)
    volume = np.asarray(volume, dtype=float)
    idx = breakout_surges(close, volume)
    closes = close
    if len(idx) == 0:
        return pd.Series({"n": 0, "hit": np.nan, "HH2": np.nan, "mean_HH": np.nan,
                          "fwd_ret": np.nan, "win": np.nan})
    did = []
    hh = []
    fwd = []
    for t in idx:
        anchor = float(np.max(closes[t - W:t]))
        cur = max(anchor, float(closes[t]))
        c = 0
        end = min(t + H, len(closes) - 1)
        for k in range(t + 1, end + 1):
            if closes[k] > cur:
                c += 1
                cur = closes[k]
        did.append(int(c >= 1))
        hh.append(c)
        fwd.append(closes[min(t + H, len(closes) - 1)] / closes[t] - 1.0)
    fwd = np.array(fwd)
    return pd.Series({"n": len(idx), "hit": float(np.mean(did)), "HH2": float(np.mean(np.array(hh) >= 2)),
                      "mean_HH": float(np.mean(hh)), "fwd_ret": float(np.mean(fwd)),
                      "win": float(np.mean(fwd > 0))})


def build_screener_state(df):
    """Current-state momentum snapshot for one instrument (latest bar only)."""
    c = df["close"]
    v = df["volume"]
    last = len(df) - 1
    sma50 = c.rolling(50).mean().iloc[last]
    sma200 = c.rolling(200).mean().iloc[last]
    ret20 = c.iloc[last] / c.iloc[max(0, last - 20)] - 1
    ret63 = c.iloc[last] / c.iloc[max(0, last - 63)] - 1
    ret252 = c.iloc[last] / c.iloc[max(0, last - 252)] - 1
    hi252 = c.iloc[max(0, last - 252):last + 1].max()
    dist_hi = c.iloc[last] / hi252 - 1
    vol_ma = v.rolling(20).mean().iloc[last]
    vol_ratio = v.iloc[last] / vol_ma if vol_ma > 0 else np.nan
    hi20_prev = c.rolling(20).max().shift(1).iloc[last]
    breakout = bool(c.iloc[last] > hi20_prev)
    surge = bool(vol_ratio >= MULT)
    return pd.Series({
        "close": c.iloc[last], "sma50": sma50, "sma200": sma200,
        "above50": bool(c.iloc[last] > sma50), "above200": bool(c.iloc[last] > sma200),
        "ret20": ret20, "ret63": ret63, "ret252": ret252,
        "dist_hi": dist_hi, "vol_ratio": vol_ratio,
        "breakout_now": breakout, "surge_now": surge,
    })


def main():
    stocks = load()
    px = {s: df["close"] for s, df in stocks.items()}

    proxy_series = {s: monthly_returns(stocks[PROXY.get(s, DEFAULT_PROXY)]) for s in stocks}

    print("=" * 100)
    print("ANNUAL MOMENTUM + RESILIENCE BACKTEST  |  our filters: vol>=%.0fx SMA20 AND close>20d high, fwd %dd" % (MULT, H))
    print(f"Instruments: {len(stocks)}  |  proxy for downside capture: SETFNIF50 (Indian), SP500 (US/MAFANG)")
    print("Bias: no look-ahead; deduped non-overlapping signals; year-by-year + OOS; SURVIVORSHIP BIAS present (today's large caps/ETFs).")
    print("=" * 100)

    # ---------------------------------------------------------------- TABLE 1
    print("\nTABLE 1 | TREND + RESILIENCE (rising through harsh markets)")
    hdr = (f"{'symbol':>11} {'years+':>6} {'CAGR%':>7} {'maxDD%':>7} "
           f"{'downCap%':>9} {'upMon%':>7} {'downMon+%':>9} {'20d':>7} {'252d':>7}")
    print(hdr)
    print("-" * 100)
    rows = []
    for s, df in stocks.items():
        c = df["close"]
        yrs = df["ts"].dt.year
        n_years = yrs.nunique()
        pos_years = (c.groupby(yrs).last().pct_change().dropna() > 0).sum() if n_years > 1 else np.nan
        span_years = (df["ts"].iloc[-1] - df["ts"].iloc[0]).days / 365.25
        total = c.iloc[-1] / c.iloc[0] - 1
        cagr = (1 + total) ** (1 / span_years) - 1 if span_years > 0 else np.nan
        dd = (c / c.cummax() - 1).min()
        mr = monthly_returns(df)
        pm = proxy_series[s]
        joined = pd.concat([mr.rename("s"), pm.rename("p")], axis=1).dropna()
        down = joined[joined["p"] < 0]
        down_cap = down["s"].mean() * 12 * 100 if len(down) else np.nan
        up_mon = (mr > 0).mean() * 100
        down_pos = (down["s"] > 0).mean() * 100 if len(down) else np.nan
        last = len(df) - 1
        ret20 = (c.iloc[last] / c.iloc[last - 20] - 1) * 100
        ret252 = (c.iloc[last] / c.iloc[last - 252] - 1) * 100 if last >= 252 else np.nan
        rows.append((s, pos_years, cagr * 100, dd * 100, down_cap, up_mon, down_pos, ret20, ret252))
    for r in sorted(rows, key=lambda x: (x[1] is np.nan, -x[1], -x[2])):
        f = lambda v, w: f"{v:>{w}.1f}" if not pd.isna(v) else f"{'--':>{w}}"
        print(f"{r[0]:>11} {f(r[1],6)} {f(r[2],7)} {f(r[3],7)} {f(r[4],9)} "
              f"{f(r[5],7)} {f(r[6],9)} {f(r[7],7)} {f(r[8],7)}")

    # ---------------------------------------------------------------- TABLE 2
    print("\nTABLE 2 | STRATEGY BACKTEST WITH OUR FILTERS (breakout-surge -> higher highs, fwd %dd)" % H)
    hdr = (f"{'symbol':>11} {'sig':>4} {'hit>=1HH':>9} {'>=2HH':>7} {'mean#HH':>8} "
           f"{'fwdRet%':>9} {'win%':>6} | {'hit[OOS]':>9} {'fwdRet[OOS]%':>12}")
    print(hdr)
    print("-" * 100)
    strat = {}
    for s, df in stocks.items():
        st = strategy_stats(df["close"], df["volume"])
        strat[s] = st
        closes = df["close"].to_numpy()
        half = len(closes) // 2
        c2 = df["close"].iloc[half:]
        v2 = df["volume"].iloc[half:]
        st_oos = strategy_stats(c2, v2)
        def ff(v, w): return f"{v*100:>{w}.1f}" if not pd.isna(v) else f"{'--':>{w}}"
        print(f"{s:>11} {int(st['n']):>4} {ff(st['hit'],9)} {ff(st['HH2'],7)} "
              f"{st['mean_HH']:>8.2f} {ff(st['fwd_ret'],9)} {ff(st['win'],6)} | "
              f"{ff(st_oos['hit'],9)} {ff(st_oos['fwd_ret'],12)}")

    # ---------------------------------------------------------------- TABLE 3
    print("\nTABLE 3 | YEAR-BY-YEAR: breakout-surge signal count / hit-rate / mean fwd-ret%")
    years = sorted(set(df["ts"].dt.year.min() for df in stocks.values()) |
                   set(df["ts"].dt.year.max() for df in stocks.values()))
    years = list(range(min(years), max(years) + 1))
    print(f"{'symbol':>11} " + "".join(f"{y:>5}H" for y in years) + "  |  " +
          "".join(f"{y:>5}R" for y in years))
    print("-" * 100)
    yearly = {}
    for s, df in stocks.items():
        df = df.copy()
        df["year"] = df["ts"].dt.year
        cells_h, cells_r = [], []
        for y in years:
            sub = df[df["year"] == y]
            if len(sub) < W + 5:
                cells_h.append(np.nan); cells_r.append(np.nan); continue
            st = strategy_stats(sub["close"], sub["volume"])
            cells_h.append(st["hit"]); cells_r.append(st["fwd_ret"])
        yearly[s] = (cells_h, cells_r)
        def ff(v, w=5): return f"{100*v:>{w}.0f}" if not pd.isna(v) else f"{'--':>{w}}"
        print(f"{s:>11} " + "".join(ff(v) for v in cells_h) + "  |  " +
              "".join(ff(v) for v in cells_r))

    # ---------------------------------------------------------------- SCREENER
    print("\nSCREENER | CURRENT MOMENTUM STATE (latest bar)")
    hdr = (f"{'symbol':>11} {'close':>9} {'>50':>5} {'>200':>5} {'ret20%':>7} "
           f"{'ret252%':>8} {'distHi%':>8} {'volx':>6} {'bko':>5} {'surge':>6}")
    print(hdr)
    print("-" * 100)
    states = {}
    for s, df in stocks.items():
        st = build_screener_state(df)
        states[s] = st
        ff = lambda v, w: f"{v:>{w}.1f}" if not pd.isna(v) else f"{'--':>{w}}"
        print(f"{s:>11} {st['close']:>9.2f} {str(int(st['above50'])):>5} {str(int(st['above200'])):>5} "
              f"{st['ret20']*100:>7.1f} {ff(st['ret252']*100,8)} {st['dist_hi']*100:>8.1f} "
              f"{st['vol_ratio']:>6.1f} {str(int(st['breakout_now'])):>5} {str(int(st['surge_now'])):>6}")

    # composite: rank by years-positive, downside-capture, strategy hit-rate (OOS)
    print("\nTOP RANKING  (years-positive desc, then OOS strategy hit-rate desc, then downside-capture asc)")
    ranked = []
    for s in stocks:
        r = next(x for x in rows if x[0] == s)
        sy = strat[s]
        st_oos = strategy_stats(stocks[s]["close"].iloc[len(stocks[s]) // 2:],
                                stocks[s]["volume"].iloc[len(stocks[s]) // 2:])
        ranked.append((s, r[1], st_oos["hit"], r[4]))
    ranked.sort(key=lambda x: (-(x[1] if not pd.isna(x[1]) else -9),
                               -(x[2] if not pd.isna(x[2]) else -9),
                               (x[3] if not pd.isna(x[3]) else 999)))
    for s, py, hit, dc in ranked:
        print(f"  {s:>11}: years_positive={py if not pd.isna(py) else '--':>5}  "
              f"OOS hit_rate={100*hit if not pd.isna(hit) else float('nan'):.0f}%  "
              f"downside_capture={dc if not pd.isna(dc) else float('nan'):.0f}%")
    print("\nNOTE: 'hit' = share of breakout-surge signals followed by a higher high within %dd; "
          "OOS = 2nd half of data." % H)


if __name__ == "__main__":
    main()
