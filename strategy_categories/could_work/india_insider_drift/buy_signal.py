#!/usr/bin/env python3
"""buy_signal.py — design & 70/30 backtest of ONE composite BUY signal.

Assumptions (pre-registered before looking at the test period):
  A1 Conviction comes from a cluster: >=2 DISTINCT major insiders buying within 30
     days (each >= Rs10L).  This is the insider ingredient.
  A2 Win probability rises when the stock is already in an uptrend
     (close > EMA50 > EMA200) — the same trend gate that helped the insider work.
  A3 Adding a breakout confirmation (close within 2% of the prior 252-session high)
     raises win rate further but shrinks n.
  A4 The best-validated ingredient (FAST-reactor history) can be layered in.
  A5 The signal is judged on WIN RATE and net mean vs THREE controls: random-entry,
     date-jitter, and a same-gate ("pure momentum") random control.  A high win rate
     that a control also achieves is NOT an edge.

Execution: buy next session OPEN after the signal; exit at CLOSE `hold` sessions
later; cost 27 bp round trip.  Split 70/30 at 2023-07-05: variants are ranked on
TRAIN only; the LOCKED rule is then reported on TEST.
"""
from __future__ import annotations

import json
import math

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import cluster_and_fast as base
import cluster_advantage as ca

FIND = base.FINDING_DIR
COST = base.COST


def gates(px: pd.DataFrame) -> dict:
    c = px.close
    e50 = c.ewm(50, adjust=False).mean()
    e200 = c.ewm(200, adjust=False).mean()
    prior_hi = c.rolling(252).max().shift(1)
    return {
        "trend": ((c > e50) & (e50 > e200)).to_numpy(),
        "brk": (c >= 0.98 * prior_hi).to_numpy(),
    }


def evaluate(signals: pd.DataFrame, prices: dict, hold: int, cost: float,
             gate_names: tuple = (), n_placebo: int = 300,
             seed: int = base.SEED) -> dict:
    gcache: dict[str, dict] = {}

    def G(sym):
        if sym not in gcache:
            gcache[sym] = gates(prices[sym])
        return gcache[sym]

    def pass_gate(sym, i):
        m = G(sym)
        return all(bool(m[g][i]) for g in gate_names)

    trades, by = [], {}
    for row in signals.itertuples():
        px = prices.get(row.symbol)
        if px is None:
            continue
        f = base.forward(px, row.signal_date, hold, cost)
        if f is None:
            continue
        if gate_names and not pass_gate(row.symbol, f["entry_i"]):
            continue
        trades.append(dict(symbol=row.symbol, **f))
        by[row.symbol] = by.get(row.symbol, 0) + 1
    tr = pd.DataFrame(trades)
    if tr.empty:
        return {"n": 0}

    # non-overlapping per symbol
    nov = []
    for s, g in tr.sort_values("entry_date").groupby("symbol"):
        last = None
        for t in g.itertuples():
            if last is None or t.entry_date > last:
                nov.append(t)
                last = t.exit_date
    nov = pd.DataFrame(nov)

    # eligible entry indices (after warm-up) that satisfy the gates
    elig = {}
    for s in by:
        px = prices[s]
        e = np.arange(base.MIN_HISTORY_SESSIONS, len(px) - hold - 2)
        if gate_names and len(e):
            m = G(s)
            mask = np.ones(len(e), bool)
            for gn in gate_names:
                mask &= m[gn][e]
            e = e[mask]
        elig[s] = e

    rng = np.random.default_rng(seed)

    def controls(obs: list[tuple], mode: str, n: int):
        means, wins = np.empty(n), np.empty(n)
        for it in range(n):
            recs = []
            if mode == "random":
                for s, k in by.items():
                    e = elig[s]
                    if len(e) == 0:
                        continue
                    c, o = prices[s].close.to_numpy(float), prices[s].open.to_numpy(float)
                    for ei in rng.choice(e, size=k, replace=k > len(e)):
                        recs.append(c[ei + hold] / o[ei] - 1 - cost)
            else:  # jitter
                for s, ei, xi, _ in obs:
                    e = elig[s]
                    if len(e) == 0:
                        continue
                    cand = int(np.clip(ei + int(rng.integers(-20, 21)), e[0], e[-1]))
                    c, o = prices[s].close.to_numpy(float), prices[s].open.to_numpy(float)
                    recs.append(c[cand + hold] / o[cand] - 1 - cost)
            recs = np.asarray(recs)
            means[it] = recs.mean() if len(recs) else 0.0
            wins[it] = (recs > 0).mean() if len(recs) else 0.0
        return means, wins

    obs = [(t.symbol, t.entry_i, t.exit_i, t.net) for t in tr.itertuples()]
    r_mean, r_win = controls(obs, "random", n_placebo)
    j_mean, j_win = controls(obs, "jitter", n_placebo)

    # equal-weight daily sleeves for Sharpe / drawdown (overlapping allowed)
    syms = list(by)
    cal = pd.DatetimeIndex(sorted(set().union(*(set(prices[s].index) for s in syms))))
    A = {s: dict(c=prices[s].close.to_numpy(float),
                 o=prices[s].open.to_numpy(float),
                 g=np.asarray(cal.searchsorted(prices[s].index))) for s in syms}

    def sleeve(frame):
        a = np.zeros(len(cal))
        for t in frame.itertuples():
            d = A[t.symbol]
            c, o, g = d["c"], d["o"], d["g"]
            a[g[t.entry_i]] += c[t.entry_i] / o[t.entry_i] - 1 - cost / 2
            a[g[t.entry_i + 1:t.exit_i + 1]] += (
                c[t.entry_i + 1:t.exit_i + 1] / c[t.entry_i:t.exit_i] - 1)
            a[g[t.exit_i]] -= cost / 2
        return pd.Series(a / max(len(syms), 1), index=cal)

    def perf(frame):
        if not len(frame):
            return {}
        d = sleeve(frame)
        d = d[(d.index >= frame.entry_date.min()) & (d.index <= frame.exit_date.max())]
        sd = d.std(ddof=1)
        eq = (1 + d).cumprod()
        return dict(sharpe=float(d.mean() / sd * math.sqrt(252)) if sd and sd > 0 else None,
                    maxdd=float((eq / eq.cummax() - 1).min()) if len(eq) else None)

    def st(frame):
        v = frame.net.to_numpy(float)
        base_ = dict(n=int(len(v)), win=float((v > 0).mean()),
                     mean=float(v.mean()), median=float(np.median(v)),
                     se=float(v.std(ddof=1) / math.sqrt(len(v))) if len(v) > 1 else None)
        base_.update(perf(frame))
        return base_

    train = tr[tr.entry_date < base.SPLIT]
    test = tr[tr.entry_date >= base.SPLIT]
    return dict(
        n=len(tr), nonoverlap=len(nov),
        full=st(tr), train=st(train) if len(train) else {}, test=st(test) if len(test) else {},
        p_random_win=float((r_win >= (tr.net > 0).mean()).mean()),
        p_random_mean=float((r_mean >= tr.net.mean()).mean()),
        p_jitter_win=float((j_win >= (tr.net > 0).mean()).mean()),
        p_jitter_mean=float((j_mean >= tr.net.mean()).mean()),
        random_win_median=float(np.median(r_win)),
        random_mean_median=float(np.median(r_mean)),
        _trades=tr, _daily=sleeve(tr),
    )


def fast_dates(ev: pd.DataFrame, prices: dict, bench) -> pd.DataFrame:
    rows = []
    for sym, px in prices.items():
        g = ev[ev.symbol == sym]
        if g.empty:
            continue
        for d in base._fast_symbol(px, bench, g.d, 5, 0.03, 0.5, 2):
            rows.append((sym, d))
    return pd.DataFrame(rows, columns=["symbol", "signal_date"])


def main() -> None:
    events = base.load_events()
    prices = base.load_prices()
    bench = base.load_bench()
    ev = events[events.symbol.isin(prices)]

    cl = ca.cluster_events(ev, 30, 2, 1e6, 20)[["symbol", "signal_date"]]
    cl_prom = ca.cluster_events(ev, 30, 2, 1e6, 20)
    cl_prom = cl_prom[cl_prom.promoter][["symbol", "signal_date"]]
    fast = fast_dates(ev, prices, bench)
    cl_fast = cl.merge(fast, on=["symbol", "signal_date"])[["symbol", "signal_date"]]

    variants = {
        "V1_cluster": (cl, 20, ()),
        "V2_cluster_trend": (cl, 20, ("trend",)),
        "V3_cluster_trend_brk": (cl, 20, ("trend", "brk")),
        "V4_cluster_fast_trend": (cl_fast, 20, ("trend",)),
        "V5_cluster_trend_h60": (cl, 60, ("trend",)),
        "V6_promoter_trend": (cl_prom, 20, ("trend",)),
        "V7_fast_trend": (fast, 20, ("trend",)),
    }
    print(f"cluster={len(cl)}  cluster∩fast={len(cl_fast)}  fast={len(fast)}  "
          f"cluster(signals)/priced...\n")
    hdr = (f"{'variant':26}{'n':>5}{'win':>6}{'mean':>8}{'Sh':>6}{'DD':>7}{'trN':>5}{'trWin':>7}"
           f"{'teN':>5}{'teWin':>7}{'teMean':>8}{'teSh':>6}{'randW':>7}{'jitW':>7}")
    print(hdr); print("-" * len(hdr))
    res = {}
    cells = []
    for name, (sig, hold, gn) in variants.items():
        r = evaluate(sig, prices, hold, COST, gn)
        res[name] = r
        if not r.get("n"):
            print(f"{name:26}  no trades")
            continue
        cells.append((name, r["p_random_win"]))
        f, tr, te = r["full"], r["train"], r["test"]
        print(f"{name:26}{f['n']:>5}{f['win']:>6.3f}{f['mean']*100:>7.2f}%"
              f"{(f.get('sharpe') or 0):>6.2f}{(f.get('maxdd') or 0)*100:>6.1f}%"
              f"{tr.get('n',0):>5}{tr.get('win',float('nan')):>7.3f}"
              f"{te.get('n',0):>5}{te.get('win',float('nan')):>7.3f}"
              f"{te.get('mean',float('nan'))*100:>7.2f}%{(te.get('sharpe') or 0):>6.2f}"
              f"{r['p_random_win']:>7.3f}{r['p_jitter_win']:>7.3f}")

    # ---- lock the rule on TRAIN only (max train win with n_train>=60) ----
    eligible = [(n, res[n]["train"].get("win", 0), res[n]["train"].get("n", 0))
                for n in res if res[n].get("n") and res[n].get("train", {}).get("n", 0) >= 60]
    eligible.sort(key=lambda x: -x[1])
    print("\nTRAIN ranking (win rate, n_train>=60):")
    for n, w, k in eligible:
        print(f"  {n:26} train win={w:.3f} n={k}")
    locked = eligible[0][0] if eligible else None
    if locked:
        r = res[locked]
        print(f"\nLOCKED rule (best train): {locked}")
        print(f"  TEST: n={r['test']['n']} win={r['test']['win']:.3f} "
              f"mean={r['test']['mean']*100:+.2f}% median={r['test']['median']*100:+.2f}%")
        print(f"  controls (full): random win={r['random_win_median']:.3f} "
              f"p(win)={r['p_random_win']:.3f}  jitter p(win)={r['p_jitter_win']:.3f}")

    pvals = [c[1] for c in cells]
    passed = base.bh_fdr(pvals)
    print("\nFDR (BH 5%) on p(random win >= observed win):")
    for (nm, pv), ok in zip(cells, passed):
        print(f"  {nm:26} p={pv:.3f}  {'PASS' if ok else 'fail'}")

    # ---- plots + JSON ----
    FIND.mkdir(parents=True, exist_ok=True)
    plots = FIND / "plots"
    plots.mkdir(exist_ok=True)
    try:
        fig, ax = plt.subplots(figsize=(12, 6))
        for key, color in (("V5_cluster_trend_h60", "#17964b"),
                           ("V3_cluster_trend_brk", "#8e3a9c"),
                           ("V1_cluster", "#4d6475")):
            d = res.get(key, {}).get("_daily")
            if d is None:
                continue
            eq = (1 + d).cumprod()
            ax.plot(eq.index, eq, color=color, lw=1.6, label=f"{key} (n={res[key]['n']})")
        nb = bench.reindex(res["V5_cluster_trend_h60"]["_daily"].index, method="ffill").dropna()
        nb = nb / nb.iloc[0]
        ax.plot(nb.index, nb, ls="--", color="#888", lw=1.1, label="NIFTY buy&hold")
        ax.axvline(base.SPLIT, color="black", ls=":", lw=1.0, label="70/30 split")
        ax.set_title("Single-BUY composites (27 bp), growth of 1 — vs Nifty")
        ax.set_ylabel("growth of Rs 1"); ax.grid(alpha=0.25); ax.legend(fontsize=8)
        fig.tight_layout(); fig.savefig(plots / "buy_signal_equity.png", dpi=150); plt.close(fig)

        names = [n for n in res if res[n].get("n")]
        full_win = [res[n]["full"]["win"] for n in names]
        test_win = [res[n]["test"].get("win", np.nan) for n in names]
        x = np.arange(len(names))
        fig, ax = plt.subplots(figsize=(13, 5.5))
        ax.bar(x - 0.2, full_win, width=0.4, label="full", color="#4d6475")
        ax.bar(x + 0.2, test_win, width=0.4, label="test (OOS)", color="#9ecae1")
        ax.axhline(0.5, color="k", lw=0.8, ls="--")
        ax.set_xticks(x); ax.set_xticklabels(names, rotation=30, ha="right", fontsize=8)
        ax.set_ylabel("win rate"); ax.set_title("Win rate by composite (dashed = coin flip)")
        ax.legend(); ax.grid(axis="y", alpha=0.25)
        fig.tight_layout(); fig.savefig(plots / "buy_signal_winrate.png", dpi=150); plt.close(fig)
    except Exception as exc:  # plotting must never break the run
        print(f"plot warning: {exc}")

    for v in res.values():
        v.pop("_trades", None); v.pop("_daily", None)
    (FIND / "buy_signal.json").write_text(
        json.dumps({"variants": res, "locked": locked,
                    "fdr": dict(cells=[c[0] for c in cells], pvals=pvals, passed=passed)},
                   indent=2, default=float) + "\n")
    print(f"\nwrote {FIND / 'buy_signal.json'}  and plots/")


if __name__ == "__main__":
    raise SystemExit(main())
