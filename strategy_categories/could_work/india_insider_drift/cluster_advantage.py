#!/usr/bin/env python3
"""cluster_advantage.py — can the insider-CLUSTER signal be made more profitable?

Tests conditional cuts / filters on top of the cluster signal:
  * cluster size      (2 vs 3 vs 4 distinct insiders)
  * aggregate value   (sum of the clustered purchases)
  * promoter-only     (all clustered buyers are promoter/promoter group)
  * trend filter      (enter only if close>EMA50>EMA200, or close>SMA200)
  * hold period       (20 vs 60 sessions)

Every variant is judged against a random-entry placebo AND a +/-20-session
date-jitter placebo (both applying the SAME trend filter), plus BH-FDR across the
whole grid.  Point-in-time disclosure dates; next-open entry; cost 27 bp.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

import cluster_and_fast as base

FIND = base.FINDING_DIR


def cluster_events(events: pd.DataFrame, window_days: int, min_insiders: int,
                   min_value_each: float, dedup_days: int) -> pd.DataFrame:
    ev = events[events.value >= min_value_each]
    rows = []
    for sym, g in ev.groupby("symbol"):
        g = g.sort_values("d")
        dts = g.d.to_numpy("datetime64[ns]")
        names = g.acqName.to_numpy()
        cats = g.personCategory.to_numpy()
        vals = g.value.to_numpy()
        last = None
        for i in range(len(g)):
            lo = dts[i] - np.timedelta64(window_days, "D")
            idx = [j for j in range(i + 1) if dts[j] >= lo]
            if len(set(names[j] for j in idx)) >= min_insiders:
                if last is None or (dts[i] - last) > np.timedelta64(dedup_days, "D"):
                    rows.append((sym, pd.Timestamp(dts[i]),
                                 len(set(names[j] for j in idx)),
                                 float(sum(vals[j] for j in idx)),
                                 all(cats[j] in ("Promoters", "Promoter Group") for j in idx)))
                    last = dts[i]
    return pd.DataFrame(rows, columns=["symbol", "signal_date", "n_ins",
                                       "agg_value", "promoter"])


def trend_mask(px: pd.DataFrame, trend: int) -> np.ndarray | None:
    if not trend:
        return None
    c = px.close
    if trend == 50:
        e50 = c.ewm(50, adjust=False).mean()
        e200 = c.ewm(200, adjust=False).mean()
        return ((c > e50) & (e50 > e200)).to_numpy()
    return (c > c.rolling(trend).mean()).to_numpy()


def evaluate_ca(signals: pd.DataFrame, prices: dict[str, pd.DataFrame], hold: int,
                cost: float, trend: int = 0, n_placebo: int = 250,
                seed: int = base.SEED) -> dict:
    trades, by, tcache = [], {}, {}
    for row in signals.itertuples():
        px = prices.get(row.symbol)
        if px is None:
            continue
        f = base.forward(px, row.signal_date, hold, cost)
        if f is None:
            continue
        if trend:
            m = tcache.setdefault(row.symbol, trend_mask(px, trend))
            if not bool(m[f["entry_i"]]):
                continue
        trades.append(dict(symbol=row.symbol, **f))
        by[row.symbol] = by.get(row.symbol, 0) + 1
    tr = pd.DataFrame(trades)
    if tr.empty:
        return {"n": 0}
    syms = list(by)
    cal = pd.DatetimeIndex(sorted(set().union(*(set(prices[s].index) for s in syms))))
    A = {}
    for s in syms:
        px = prices[s]
        elig = np.arange(base.MIN_HISTORY_SESSIONS, len(px) - hold - 2)
        m = tcache.get(s) if trend else None
        if trend and len(elig):
            m = tcache[s]
            elig = elig[m[elig]]
        A[s] = dict(c=px.close.to_numpy(float), o=px.open.to_numpy(float),
                    g=np.asarray(cal.searchsorted(px.index)), elig=elig)

    def acc(records):
        a = np.zeros(len(cal))
        for s, ei, xi, _ in records:
            d = A[s]; c, o, g = d["c"], d["o"], d["g"]
            a[g[ei]] += c[ei] / o[ei] - 1 - cost / 2
            a[g[ei + 1:xi + 1]] += c[ei + 1:xi + 1] / c[ei:xi] - 1
            a[g[xi]] -= cost / 2
        return a / len(syms)

    obs = [(t.symbol, t.entry_i, t.exit_i, t.net) for t in tr.itertuples()]
    daily = pd.Series(acc(obs), index=cal)
    sd = daily.std(ddof=1)
    sharpe = float(daily.mean() / sd * math.sqrt(252)) if sd and sd > 0 else np.nan
    obsmean = float(tr.net.mean())
    rng = np.random.default_rng(seed)
    pm, ps = np.empty(n_placebo), np.empty(n_placebo)
    for it in range(n_placebo):
        recs = []
        for s, k in by.items():
            e = A[s]["elig"]
            if len(e) == 0:
                continue
            c, o = A[s]["c"], A[s]["o"]
            for ei in rng.choice(e, size=k, replace=k > len(e)):
                recs.append((s, int(ei), int(ei + hold), c[ei + hold] / o[ei] - 1 - cost))
        pm[it] = np.mean([r[3] for r in recs]) if recs else 0.0
        a = acc(recs); sd2 = a.std(ddof=1)
        ps[it] = a.mean() / sd2 * math.sqrt(252) if sd2 and sd2 > 0 else 0.0
    jrng = np.random.default_rng(seed + 1)
    jm = np.empty(n_placebo)
    for it in range(n_placebo):
        recs = []
        for s, ei, xi, _ in obs:
            e = A[s]["elig"]
            if len(e) == 0:
                continue
            nei = int(np.clip(ei + int(jrng.integers(-20, 21)), int(e[0]), int(e[-1])))
            c, o = A[s]["c"], A[s]["o"]
            recs.append((s, nei, nei + hold, c[nei + hold] / o[nei] - 1 - cost))
        jm[it] = np.mean([r[3] for r in recs]) if recs else 0.0
    oos = tr[tr.entry_date >= base.SPLIT]
    return dict(n=len(tr),
                mean=obsmean,
                se=float(tr.net.std(ddof=1) / math.sqrt(len(tr))),
                median=float(tr.net.median()),
                win=float((tr.net > 0).mean()),
                sharpe=sharpe,
                oos_n=int(len(oos)),
                oos_mean=float(oos.net.mean()) if len(oos) else np.nan,
                rand_p=float((pm >= obsmean).mean()),
                jitter_p=float((jm >= obsmean).mean()),
                rand_p_sh=float((ps >= sharpe).mean()))


def main() -> None:
    events = base.load_events()
    prices = base.load_prices()
    ev = events[events.symbol.isin(prices)]
    # base cluster universe (K2, each >= Rs10L, 30d window, 20d dedup)
    base_cl = cluster_events(ev, 30, 2, 1e6, 20)

    defs = [
        ("cluster_K2_base_h20", base_cl, 20, 0),
        ("cluster_K2_trend50_h20", base_cl, 20, 50),
        ("cluster_K2_sma200_h20", base_cl, 20, 200),
        ("cluster_K2_trend50_h60", base_cl, 60, 50),
        ("cluster_K3_h20", cluster_events(ev, 30, 3, 1e6, 20), 20, 0),
        ("cluster_K4_h20", cluster_events(ev, 30, 4, 1e6, 20), 20, 0),
        ("cluster_agg50L_h20", base_cl[base_cl.agg_value >= 5e6], 20, 0),
        ("cluster_agg1cr_h20", base_cl[base_cl.agg_value >= 1e7], 20, 0),
        ("cluster_promoter_h20", base_cl[base_cl.promoter], 20, 0),
        ("cluster_promoter_pct_h20", base_cl[base_cl.promoter & (base_cl.agg_value >= 5e6)], 20, 0),
    ]
    print(f"cluster base signals: {len(base_cl)} across {base_cl.symbol.nunique()} stocks\n")
    hdr = (f"{'variant':30}{'n':>5}{'mean':>8}{'med':>7}{'win':>6}{'Sh':>6}"
           f"{'OOSn':>6}{'OOSmean':>9}{'randP':>7}{'jitP':>7}")
    print(hdr); print("-" * len(hdr))
    res = {}
    cells = []
    for name, sig, hold, trend in defs:
        r = evaluate_ca(sig, prices, hold, base.COST, trend)
        res[name] = r
        if r["n"]:
            cells.append((name, r["jitter_p"]))
            print(f"{name:30}{r['n']:>5}{r['mean']*100:>7.2f}%{r['median']*100:>6.2f}%"
                  f"{r['win']:>6.2f}{r['sharpe']:>6.2f}{r['oos_n']:>6}{r['oos_mean']*100:>8.2f}%"
                  f"{r['rand_p']:>7.3f}{r['jitter_p']:>7.3f}")

    pvals = [c[1] for c in cells]
    passed = base.bh_fdr(pvals)
    print("\nFDR (BH 5%) over", len(cells), "variants; expected raw hits by chance:",
          round(0.05 * len(cells), 2))
    for (nm, pv), ok in zip(cells, passed):
        print(f"  {nm:30} jitter p={pv:.3f}  {'PASS' if ok else 'fail'}")

    FIND.mkdir(parents=True, exist_ok=True)
    (FIND / "cluster_advantage.json").write_text(
        json.dumps({"variants": res,
                    "fdr": dict(cells=[c[0] for c in cells], pvals=pvals, passed=passed)},
                   indent=2, default=float) + "\n")
    print(f"\nwrote {FIND / 'cluster_advantage.json'}")


if __name__ == "__main__":
    raise SystemExit(main())
