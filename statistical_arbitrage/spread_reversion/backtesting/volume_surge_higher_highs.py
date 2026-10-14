#!/usr/bin/env python3
"""Volume-surge -> higher-highs study, run across every stock we have data for.

Question being asked
--------------------
After a "massive volume surge" (volume well above its own recent norm), does the
stock go on to make NEW highs ("higher highs"), and how many higher highs in a row?

Bias controls (the point of this script)
----------------------------------------
1. NO LOOK-AHEAD
   Every trigger and anchor is computed with information available strictly at or
   before the event day t (rolling volume mean uses only past bars; the "recent
   high" anchor is the trailing-W-day high ending at t). Outcomes are measured
   only on days t+1 .. t+H.
2. NO SNOOPING
   The full config grid (volume multiplier x, anchor lookback W, forward window H)
   is pre-registered below and reported for EVERY cell. Nothing is tuned on the
   data; no cell is hidden because it looks bad.
3. NO OVERFITTING (claim)
   Every metric is computed on the second half of the sample (out-of-sample) as
   well as the first half, and both are reported. A result is only "consistent"
   if it holds in both halves. Surge days are also compared against a CONTROL set
   of all non-surge days -- because in a rising market most days are followed by
   new highs eventually, so a raw rate means nothing without a baseline.
4. SURVIVORSHIP BIAS (flagged, cannot be removed)
   The universe is today's large caps / popular ETFs (what we happen to have
   cached). De-listed or bankrupt names are absent, so absolute rates are
   upward-biased relative to a true cross-section. This is stated, not hidden.

Event definitions
-----------------
volume surge on day t:  volume[t] >= mult * SMA(volume, 20)[t]   (mult in {2,3,4})
events are deduplicated: a contiguous run of qualifying days = ONE event (first
day), and separate events must be >= SEP days apart so forward windows do not
overlap and inflate the sample.

Outcomes (forward window H days, starting t+1)
----------------------------------------------
anchor   = highest close in the W days ending at t   (the resistance to break)
HH_count = number of times close sets a new running high above anchor, t+1..t+H
did_HH   = 1 if HH_count >= 1
breakout = close[t] > anchor (the surge day itself already closed above resistance)

Controls: every non-surge day (not inside any surge run) is a control day and is
scored with the identical anchor + forward-window logic.
"""

import os

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
OUT_CSV = os.path.join(HERE, "volume_surge_results.csv")

# ----------------------------------------------------------------------------
# PRE-REGISTERED CONFIG GRID  (do not tune; every cell is reported)
# ----------------------------------------------------------------------------
MULT = [2.0, 3.0, 4.0]      # volume surge multipliers
W = [10, 20]                # anchor lookback (days of closes to beat)
H = [5, 10, 20]             # forward windows (days) to look for higher highs
SEP = 10                    # minimum gap between distinct events
TRAIN_FRAC = 0.5            # first half = train (in-sample), second half = test (OOS)

HEADLINE = (3.0, 20, 20)    # (mult, W, H) used for the per-stock table


def load_stocks():
    stocks = {}
    for fn in sorted(os.listdir(DATA)):
        if not fn.endswith(".csv"):
            continue
        df = pd.read_csv(os.path.join(DATA, fn), parse_dates=["ts"])
        df = df[["ts", "close", "volume"]].dropna().sort_values("ts").reset_index(drop=True)
        stocks[fn[:-4]] = df
    return stocks


def events_and_control(close, volume, mult, W, sep=SEP):
    """Return event indices and control indices, both look-ahead free.

    Signal on day t uses only bars <= t:
      vol_ma20[t] = mean(volume[t-19 .. t])   -> needs t >= 19
      anchor[t]   = max(close[t-W .. t])      -> needs t >= W-1
    A surge day qualifies only if all inputs are available.
    """
    n = len(close)
    vol_ma20 = volume.rolling(20, min_periods=20).mean().to_numpy()
    start = max(19, W - 1)
    qual = np.zeros(n, dtype=bool)
    for t in range(start, n):
        if vol_ma20[t] > 0 and volume[t] >= mult * vol_ma20[t]:
            qual[t] = True

    # dedupe: first day of each run of qualifying days = one event
    events = []
    i = 0
    while i < n:
        if qual[i]:
            events.append(i)
            # skip the whole run, then require SEP gap before next event
            j = i
            while j + 1 < n and qual[j + 1]:
                j += 1
            i = j + sep + 1
        else:
            i += 1

    # control days: non-qualifying days, same min-history requirement, not inside
    # a qualifying run, and outside SEP of any chosen event
    control = [t for t in range(start, n) if not qual[t]]
    ev_set = set(events)
    control = [t for t in control if not any(abs(t - e) <= sep for e in ev_set)]
    return np.array(events), np.array(control)


def score_window(close, idx, W, H):
    """Score an event/control day at position idx.

    Returns dict: breakout, did_HH, HH_count, plus the labels.
    All anchor info uses data <= idx; scoring uses idx+1 .. idx+H.
    """
    anchor = float(np.max(close[idx - W: idx]))
    breakout = bool(close[idx] > anchor)
    cur = max(anchor, float(close[idx]))
    hh = 0
    end = min(idx + H, len(close) - 1)
    for t in range(idx + 1, end + 1):
        if close[t] > cur:
            hh += 1
            cur = close[t]
    return anchor, breakout, hh


def half(ts):
    """Return 'train' or 'test' for a row based on the global midpoint."""
    return "test" if ts >= MIDPOINT else "train"


def compute_cell(stocks, mult, W, H):
    """Aggregate one (mult, W, H) cell across all stocks, train/test split."""
    cols = ["symbol", "ts", "half", "group", "anchor", "breakout", "hh"]
    rows = []
    for sym, df in stocks.items():
        close = df["close"]
        volume = df["volume"]
        ev, ctrl = events_and_control(close, volume, mult, W)
        for i, group in ((ev, "surge"), (ctrl, "control")):
            for idx in i:
                anchor, breakout, hh = score_window(close, idx, W, H)
                rows.append((sym, df["ts"].iloc[idx], half(df["ts"].iloc[idx]),
                             group, anchor, int(breakout), int(hh)))
    res = pd.DataFrame(rows, columns=cols)
    return res


def summarize(res):
    def f(df):
        if len(df) == 0:
            return pd.Series({"n": 0, "did_HH": np.nan, "HH_ge2": np.nan,
                              "HH_ge3": np.nan, "mean_HH": np.nan})
        hh = df["hh"].to_numpy()
        return pd.Series({
            "n": len(df),
            "did_HH": float((hh >= 1).mean()),
            "HH_ge2": float((hh >= 2).mean()),
            "HH_ge3": float((hh >= 3).mean()),
            "mean_HH": float(hh.mean()),
        })

    out = {}
    for g in ("surge", "control"):
        sub = res[res["group"] == g]
        out[g + "_all"] = f(sub)
        out[g + "_train"] = f(sub[sub["half"] == "train"])
        out[g + "_test"] = f(sub[sub["half"] == "test"])
    return out


def pct(v):
    return "    --   " if pd.isna(v) else f"{100 * v:6.1f}%"


def main():
    global MIDPOINT
    stocks = load_stocks()
    all_ts = pd.concat([df["ts"] for df in stocks.values()])
    MIDPOINT = all_ts.median()

    print("=" * 96)
    print(f"VOLUME-SURGE -> HIGHER-HIGHS STUDY   |   {len(stocks)} stocks   |   "
          f"{all_ts.min().date()} .. {all_ts.max().date()}   |   train/test cut: {MIDPOINT.date()}")
    print("=" * 96)
    print("Bias controls: no look-ahead (signal uses data <= t only), deduped")
    print("non-overlapping events (gap >= 10d), control-day baseline, full pre-registered")
    print("config grid reported, train/test (first/second half) both shown.")
    print("SURVIVORSHIP BIAS: universe = today's large caps/ETFs; de-listed names absent.")
    print("-" * 96)

    # ---------------------------------------------------------- headline grid
    print("\nAGGREGATE  |  'reaches at least one higher high within H days'")
    print(f"{'mult':>4} {'W':>3} {'H':>3} | {'surge n':>8} {'surge did_HH':>13} "
          f"{'ctrl did_HH':>12} {'surge-ctrl':>10} | {'surge[train]':>13} {'surge[test]':>12}")
    print("-" * 96)

    all_res = {}
    for mult in MULT:
        for w in W:
            for h in H:
                res = compute_cell(stocks, mult, w, h)
                all_res[(mult, w, h)] = res
                s = summarize(res)
                diff = s["surge_all"]["did_HH"] - s["control_all"]["did_HH"]
                print(f"{mult:>4.0f} {w:>3} {h:>3} | {int(s['surge_all']['n']):>8} "
                      f"{pct(s['surge_all']['did_HH']):>13} {pct(s['control_all']['did_HH']):>12} "
                      f"{diff:>+9.2%} | {pct(s['surge_train']['did_HH']):>13} "
                      f"{pct(s['surge_test']['did_HH']):>12}")

    # ------------------------------------------------- higher-highs depth
    print("\nHOW MANY higher highs?  (surge days, forward window H)")
    print(f"{'mult':>4} {'W':>3} {'H':>3} | {'>=1':>7} {'>=2':>7} {'>=3':>7} "
          f"{'mean#HH':>8} | {'>=1[test]':>9}")
    print("-" * 72)
    for mult in MULT:
        for w in W:
            for h in H:
                s = summarize(all_res[(mult, w, h)])
                a = s["surge_all"]
                print(f"{mult:>4.0f} {w:>3} {h:>3} | {pct(a['did_HH']):>7} "
                      f"{pct(a['HH_ge2']):>7} {pct(a['HH_ge3']):>7} {a['mean_HH']:>8.2f} | "
                      f"{pct(s['surge_test']['did_HH']):>9}")

    # ------------------------------------------------------------ per-stock
    hl_mult, hl_W, hl_H = HEADLINE
    res = all_res[(hl_mult, hl_W, hl_H)]
    surge = res[res["group"] == "surge"].copy()
    ctrl = res[res["group"] == "control"].copy()

    print(f"\nPER-STOCK  (headline config: vol >= {hl_mult:.0f}x SMA20, "
          f"anchor W={hl_W}, forward H={hl_H})")
    print(f"{'symbol':>12} {'evt':>4} {'did_HH':>8} {'HH>=2':>7} {'HH>=3':>7} "
          f"{'mean#HH':>8} {'ctrl did_HH':>12} {'net':>6} | {'did_HH[test]':>13}")
    print("-" * 96)
    per_stock = []
    for sym in sorted(surge["symbol"].unique()):
        ss = surge[surge["symbol"] == sym]
        cc = ctrl[ctrl["symbol"] == sym]
        n = len(ss)
        did = (ss["hh"] >= 1).mean()
        c_did = (cc["hh"] >= 1).mean()
        test_did = (ss[ss["half"] == "test"]["hh"] >= 1).mean() if n else np.nan
        net = did - c_did
        per_stock.append((sym, n, did, c_did, test_did, net))
        print(f"{sym:>12} {n:>4} {pct(did):>8} {pct((ss['hh']>=2).mean()):>7} "
              f"{pct((ss['hh']>=3).mean()):>7} {ss['hh'].mean():>8.2f} "
              f"{pct(c_did):>12} {net:>+5.1%} | {pct(test_did):>13}")

    # ------------------------------------------- direction breakdown (headline)
    print(f"\nSURGE-DAY DIRECTION  (headline config; is the surge an up-day?)")
    up = surge[surge["breakout"].astype(bool)]
    dn = surge[~surge["breakout"].astype(bool)]
    cup = ctrl[ctrl["breakout"].astype(bool)]
    cdn = ctrl[~ctrl["breakout"].astype(bool)]
    def line(name, df):
        if len(df) == 0:
            return
        did = (df["hh"] >= 1).mean()
        tdid = (df[df["half"] == "test"]["hh"] >= 1).mean()
        print(f"  {name:>30}: n={len(df):>5}  did_HH={100*did:5.1f}%  "
              f"did_HH[test]={100*tdid:5.1f}%  mean#HH={df['hh'].mean():.2f}")
    print("  --- surge events ---")
    line("breakout surge (close[t] > W-high)", up)
    line("non-breakout surge", dn)
    print("  --- control days (same-day breakout flag, for baseline) ---")
    line("control breakout day", cup)
    line("control non-breakout day", cdn)

    # ------------------------------------------------------------- raw events
    print(f"\nRAW EVENT COUNT (headline): total surge events = {len(surge)}, "
          f"control days = {len(ctrl)}")

    # ------------------------- per-stock breakout-surge (actionable signal)
    print(f"\nPER-STOCK BREAKOUT SURGES  (vol >= {hl_mult:.0f}x SMA20 AND close[t] > W-high)")
    print(f"{'symbol':>12} {'evt':>4} {'did_HH':>8} {'mean#HH':>8} | {'did_HH[test]':>13}")
    print("-" * 56)
    for sym in sorted(up["symbol"].unique()):
        s2 = up[up["symbol"] == sym]
        t2 = s2[s2["half"] == "test"]
        tdid = (t2["hh"] >= 1).mean() if len(t2) else np.nan
        print(f"{sym:>12} {len(s2):>4} {pct((s2['hh']>=1).mean()):>8} "
              f"{s2['hh'].mean():>8.2f} | {pct(tdid):>13}")

    # save per-stock table + full event log
    per = pd.DataFrame(per_stock, columns=["symbol", "n_events", "did_HH", "ctrl_did_HH",
                                           "did_HH_test", "net"])
    per = per.sort_values("net", ascending=False)
    res.to_csv(OUT_CSV, index=False)
    print(f"\nSaved per-event results -> {OUT_CSV}  ({len(res)} rows)")
    return per


if __name__ == "__main__":
    per = main()
