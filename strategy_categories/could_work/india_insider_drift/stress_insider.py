#!/usr/bin/env python3
"""
stress_insider.py — stress-test the insider-purchase event study.

Runs the traps AGENTS.md warns about on a RANDOM sample of the universe (to avoid
the top-frequency selection of the first look). All returns are market-adjusted
(excess vs Nifty). Core is numpy for speed.

Batteries
  B1 baseline   mean excess CAR at +1/+5/+20/+60, from DISCLOSURE close
  B2 timing     same, but entered at the NEXT-DAY OPEN after disclosure (tradeable)
  B3 placebo    random in-sample dates, same symbols -> null distribution + p
  B4 subperiod  mean +20d CAR by event year
  B5 value      only buys >= 10 lakh (the regulatory disclosure trigger)
  B6 cluster    collapse same-symbol events within 5 days to one
  B7 cost       net CAR at 27 bp and 75 bp round trip
  B8 selection  random-universe sample vs the top-frequency names

Writes data/stress_results.json. See REPORT.md for the write-up.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
EVENTS = HERE / "data" / "events.csv"
PANEL = HERE / "data" / "panel"
BENCH = "^NSEI"
HORIZONS = (1, 5, 20, 60)
MAXH = max(HORIZONS)
RNG_SEED = 42


def load_events() -> pd.DataFrame:
    df = pd.read_csv(EVENTS, parse_dates=["disclose_ts", "trade_date"])
    df = df[(df["is_buy"]) & (df["is_equity"])].dropna(subset=["disclose_ts"]).copy()
    df["d"] = df["disclose_ts"].dt.normalize()
    return df


def pick_sample(df: pd.DataFrame, n: int, seed: int = RNG_SEED) -> list[str]:
    elig = df.groupby("symbol").size()
    elig = elig[elig >= 2].index.to_numpy()
    return list(np.random.default_rng(seed).choice(elig, size=min(n, len(elig)),
                                                   replace=False))


def download_panel(symbols: list[str], chunk: int = 50) -> None:
    import yfinance as yf
    PANEL.mkdir(parents=True, exist_ok=True)
    todo = [s for s in symbols if not (PANEL / f"{s}.csv").exists()]
    print(f"panel: {len(symbols)-len(todo)} cached, {len(todo)} to fetch")
    for i in range(0, len(todo), chunk):
        batch = todo[i:i + chunk]
        data = yf.download(" ".join(f"{s}.NS" for s in batch), start="2015-01-01",
                           auto_adjust=True, progress=False, group_by="ticker",
                           threads=True)
        saved = 0
        for s in batch:
            try:
                sub = data[f"{s}.NS"].dropna()
            except Exception:
                continue
            if sub.empty:
                continue
            sub = sub.reset_index()
            sub.columns = [str(c).lower() for c in sub.columns]
            sub[["date", "open", "close"]].to_csv(PANEL / f"{s}.csv", index=False)
            saved += 1
        print(f"  batch {i//chunk}: {len(batch)} tickers, {saved} saved")
        time.sleep(1.0)


def load_panel(symbols: list[str]) -> dict[str, dict]:
    out = {}
    for s in symbols:
        p = PANEL / f"{s}.csv"
        if not p.exists():
            continue
        df = pd.read_csv(p, parse_dates=["date"]).sort_values("date")
        if len(df) <= MAXH + 2:
            continue
        out[s] = dict(dates=df["date"].to_numpy(),
                      open=df["open"].to_numpy(float),
                      close=df["close"].to_numpy(float))
    return out


def bench_arrays(sym: str = BENCH) -> tuple[np.ndarray, np.ndarray]:
    import yfinance as yf
    b = yf.download(sym, start="2015-01-01", auto_adjust=True, progress=False)["Close"]
    if isinstance(b, pd.DataFrame):
        b = b.iloc[:, 0]
    b = b.dropna()
    return b.index.to_numpy(), b.to_numpy(float)


def _excess(px: dict, bd: np.ndarray, bv: np.ndarray, d, h: int, timing: str) -> float:
    dates = px["dates"]
    pos = np.searchsorted(dates, np.datetime64(d))
    if pos >= len(dates):
        return np.nan
    if timing == "next_open":
        if pos + 1 >= len(dates):
            return np.nan
        ei, entry = pos + 1, px["open"][pos + 1]
    else:
        ei, entry = pos, px["close"][pos]
    xi = ei + h
    if xi >= len(dates) or not np.isfinite(entry) or entry <= 0:
        return np.nan
    r = px["close"][xi] / entry - 1.0
    d0, d1 = dates[ei], dates[xi]
    j0, j1 = np.searchsorted(bd, d0), np.searchsorted(bd, d1)
    if j0 >= len(bd) or j1 >= len(bd) or bd[j0] != d0 or bd[j1] != d1:
        return np.nan
    return r - (bv[j1] / bv[j0] - 1.0)


def cars(events: pd.DataFrame, panel: dict, bd, bv, timing: str,
         horizons=HORIZONS) -> dict[int, np.ndarray]:
    out = {h: [] for h in horizons}
    syms, ds = events["symbol"].to_numpy(), events["d"].to_numpy()
    for sym, d in zip(syms, ds):
        px = panel.get(sym)
        if px is None:
            continue
        for h in horizons:
            r = _excess(px, bd, bv, d, h, timing)
            if np.isfinite(r):
                out[h].append(r)
    return {h: np.asarray(v) for h, v in out.items()}


def summarise(arr: np.ndarray) -> dict:
    if len(arr) == 0:
        return dict(n=0, mean=np.nan, se=np.nan, t=np.nan, hit=np.nan)
    m = float(arr.mean())
    se = float(arr.std(ddof=1) / np.sqrt(len(arr))) if len(arr) > 1 else np.nan
    return dict(n=int(len(arr)), mean=m, se=se,
                t=float(m / se) if se else np.nan, hit=float((arr > 0).mean()))


def per_event_cars(events: pd.DataFrame, panel: dict, bd, bv, timing: str,
                   h: int) -> pd.DataFrame:
    rows = []
    for sym, d in zip(events["symbol"].to_numpy(), events["d"].to_numpy()):
        px = panel.get(sym)
        if px is None:
            continue
        r = _excess(px, bd, bv, d, h, timing)
        if np.isfinite(r):
            rows.append((sym, r))
    return pd.DataFrame(rows, columns=["symbol", "car"])


def cluster_t(events, panel, bd, bv, timing, h):
    """Collapse to one obs per symbol, then t across symbols — the honest n when
    many events share a symbol (repo trap: overlapping events counted as independent)."""
    pe = per_event_cars(events, panel, bd, bv, timing, h)
    g = pe.groupby("symbol")["car"].mean()
    if len(g) < 2:
        return dict(events=len(pe), symbols=len(g), mean=np.nan, se=np.nan, t=np.nan)
    se = float(g.std(ddof=1) / np.sqrt(len(g)))
    return dict(events=int(len(pe)), symbols=int(len(g)), mean=float(g.mean()),
                se=se, t=float(g.mean() / se))


def placebo(events: pd.DataFrame, panel: dict, bd, bv, timing: str,
            B: int = 100, seed: int = RNG_SEED) -> dict:
    rng = np.random.default_rng(seed)
    obs = {h: summarise(cars(events, panel, bd, bv, timing, (h,))[h])["mean"]
           for h in HORIZONS}
    null = {h: [] for h in HORIZONS}
    base = events[["symbol"]].copy()
    for _ in range(B):
        fake_d = np.empty(len(base), dtype="datetime64[ns]")
        for i, sym in enumerate(base["symbol"].to_numpy()):
            px = panel.get(sym)
            fake_d[i] = (px["dates"][rng.integers(0, len(px["dates"]) - MAXH - 1)]
                         if px is not None else np.datetime64("NaT"))
        fake = pd.DataFrame({"symbol": base["symbol"], "d": fake_d}).dropna(subset=["d"])
        c = cars(fake, panel, bd, bv, timing, HORIZONS)
        for h in HORIZONS:
            if len(c[h]):
                null[h].append(c[h].mean())
    p, mean_null = {}, {}
    for h in HORIZONS:
        arr = np.asarray(null[h])
        p[h] = float((np.abs(arr) >= abs(obs[h])).mean()) if len(arr) else np.nan
        mean_null[h] = float(arr.mean()) if len(arr) else np.nan
    return dict(obs=obs, p=p, mean_null=mean_null)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--placebo", type=int, default=100)
    ap.add_argument("--fetch", action="store_true")
    a = ap.parse_args(argv)

    df = load_events()
    sample = pick_sample(df, a.n)
    print(f"universe: {df['symbol'].nunique()} symbols, {len(df):,} buy events; "
          f"sample {len(sample)}")
    if a.fetch:
        download_panel(sample)
    panel = load_panel(sample)
    print(f"panel: {len(panel)} symbols with prices")
    if not panel:
        print("no panel — run with --fetch"); return 1
    bd, bv = bench_arrays()
    ev = df[df["symbol"].isin(panel)].copy()
    print(f"events on panel: {len(ev):,}")

    res = dict(universe=int(df["symbol"].nunique()), sample_symbols=len(sample),
               panel_symbols=len(panel), events_on_panel=int(len(ev)))

    def table(title, c):
        print(f"\n=== {title} ===")
        print(f"{'h':>3} {'n':>6} {'mean%':>8} {'se%':>6} {'t':>6} {'hit':>5}")
        rows = {}
        for h in sorted(c.keys()):
            s = summarise(c[h]); rows[str(h)] = s
            print(f"{h:>3} {s['n']:>6} {s['mean']*100:8.3f} {s['se']*100:6.3f} "
                  f"{s['t']:6.2f} {s['hit']:5.2f}")
        return rows

    res["B1_disclosure_close"] = table("B1 from disclosure close",
                                       cars(ev, panel, bd, bv, "close"))
    res["B2_next_open"] = table("B2 tradeable — next-day open",
                                cars(ev, panel, bd, bv, "next_open"))

    print(f"\n=== B3 placebo ({a.placebo} shuffles, next-day open) ===")
    pl = placebo(ev, panel, bd, bv, "next_open", a.placebo)
    res["B3_placebo"] = pl
    for h in HORIZONS:
        print(f"  h={h:>2}: observed {pl['obs'][h]*100:6.3f}%  "
              f"placebo-mean {pl['mean_null'][h]*100:6.3f}%  p={pl['p'][h]:.3f}")

    print("\n=== B4 subperiod (+20d, next-day open) ===")
    sub = {}
    for y, g in ev.groupby(ev["d"].dt.year):
        cy = cars(g, panel, bd, bv, "next_open", (20,))[20]
        if len(cy):
            sub[int(y)] = dict(n=len(cy), mean=float(cy.mean()))
            print(f"  {y}: n={len(cy):>5}  +20d {cy.mean()*100:6.3f}%")
    res["B4_subperiod_h20"] = sub

    big = ev[ev["value"] >= 1_000_000]
    res["B5_big_buys"] = table(f"B5 buys >= 10L (n_events={len(big):,})",
                               cars(big, panel, bd, bv, "next_open"))

    cl = ev.sort_values("d").copy()
    cl["gap"] = cl.groupby("symbol")["d"].diff().dt.days
    cl = cl[(cl["gap"].isna()) | (cl["gap"] > 5)]
    res["B6_clustered"] = table(f"B6 clustered (n={len(cl):,})",
                                cars(cl, panel, bd, bv, "next_open"))

    print("\n=== B7 net of cost (next-day open) ===")
    c = cars(ev, panel, bd, bv, "next_open", (20, 60))
    for h in (20, 60):
        g = c[h]
        res[f"B7_net_h{h}"] = {f"{bp}bp": float((g - bp / 1e4).mean())
                               for bp in (0, 27, 75)}
        print(f"  h={h}: gross {g.mean()*100:.3f}%  net@27bp {(g.mean()-0.0027)*100:.3f}%"
              f"  net@75bp {(g.mean()-0.0075)*100:.3f}%")

    print("\n=== B8 selection: top-frequency names ===")
    top = df.groupby("symbol").size().sort_values(ascending=False).head(10).index
    evtop = df[df["symbol"].isin(top) & df["symbol"].isin(panel)]
    if len(evtop):
        res["B8_top10"] = table(f"top-10 frequency (n={len(evtop):,})",
                                cars(evtop, panel, bd, bv, "next_open", (20,)))
    else:
        print("  none of the top-10 in panel")

    print("\n=== B9 cluster-robust t (one obs per symbol) ===")
    res["B9_cluster"] = {}
    for h in (20, 60):
        ct = cluster_t(ev, panel, bd, bv, "next_open", h)
        res["B9_cluster"][str(h)] = ct
        print(f"  h={h}: events={ct['events']} symbols={ct['symbols']} "
              f"mean {ct['mean']*100:.3f}%  se {ct['se']*100:.3f}%  t={ct['t']:.2f}")

    print("\n=== B10 benchmark sensitivity (vs Nifty Midcap 150) ===")
    try:
        bd2, bv2 = bench_arrays("^NSEMDCP50")
        if len(bd2):
            res["B10_midcap"] = table("vs ^NSEMDCP50 (next-day open)",
                                      cars(ev, panel, bd2, bv2, "next_open"))
        else:
            print("  ^NSEMDCP50 unavailable")
    except Exception as e:
        print(f"  benchmark fetch failed: {e}")

    (HERE / "data" / "stress_results.json").write_text(json.dumps(res, indent=2,
                                                                  default=float))
    print(f"\nwrote {HERE/'data'/'stress_results.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
