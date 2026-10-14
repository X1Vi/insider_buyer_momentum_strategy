#!/usr/bin/env python3
"""cluster_and_fast.py — two new insider-signal tests on the existing data.

#1 CLUSTER: a major insider market-purchase that completes a cluster of >= K
   distinct major insiders all buying the same stock within W calendar days.
   Literature (Brochet et al.; Indian PIT studies) says clustered purchases are
   more informative than singletons.

#2 FAST: point-in-time "fast reactor" subset.  A stock is armed only if its own
   PRIOR qualifying purchases (outcomes already known before the current
   disclosure) reacted fast (>= +3% excess in 5 sessions) at least `fast_frac`
   of the time.  Entry next open, short hold (1-5 sessions).  No look-ahead:
   the classifier uses past events whose 5-session window closed first.

Rules (repo AGENTS.md):
  * point-in-time: signal = disclosure date, never trade date
  * entry = next session OPEN after the disclosure
  * exit  = close H sessions later (no intrabar stop, so no stop-fill trap)
  * cost  = 27 bp round trip (repo delivery reference); 75 bp small-account shown
  * decisive control = matched random entry dates, same count per stock
  * 70/30 chronological split; pooled + non-overlapping + placebo
"""
from __future__ import annotations

import glob
import json
import math
import os
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = Path(__file__).resolve().parent
EVENTS = HERE / "data" / "events.csv"
PX = HERE / "data" / "bt_prices"
BENCH = Path("/home/null/Documents/development/trading_and_investing/data/"
             "2026-10-12/intl_etf_lag/downloads/IDX_NSEI.csv")
OUT = HERE / "data" / "cluster_fast"
OUT.mkdir(parents=True, exist_ok=True)
ETF_DIR = HERE / "data" / "momentum_etf"
ETF_DIR.mkdir(parents=True, exist_ok=True)

# repo-root findings bundle: <repo>/finding/<date>/
REPORT_DATE = "2026-10-14"
FINDING_DIR = HERE.parents[2] / "finding" / REPORT_DATE

# Indian "momentum" ETFs (Nifty200 Momentum 30 / Nifty500 Momentum 50 families)
MOMENTUM_ETFS = {
    "MOM30_ABSL": "MOMENTUM.NS",     # Aditya Birla SL Nifty200 Momentum 30 (2022-08)
    "MOM30_HDFC": "HDFCMOMENT.NS",   # HDFC Nifty200 Momentum 30 (2023-10)
    "MOM30_MO": "MOMOMENTUM.NS",     # Motilal Oswal Nifty200 Momentum 30 (2025-03)
    "MOM50_MO": "MOMENTUM50.NS",     # Motilal Oswal Nifty500 Momentum 50 (2024-09)
}

MAJOR = {"Promoters", "Promoter Group", "Director", "Key Managerial Personnel"}
COST = 0.0027
COST_SMALL = 0.0075
SPLIT = pd.Timestamp("2023-07-05")
N_PLACEBO = 250
SEED = 20261014
MIN_HISTORY_SESSIONS = 260


def load_events(min_value: float = 0.0) -> pd.DataFrame:
    df = pd.read_csv(EVENTS, parse_dates=["trade_date", "disclose_ts"])
    mask = (
        df.personCategory.isin(MAJOR)
        & df.is_buy & df.is_equity
        & df.acqMode.eq("Market Purchase")
        & df.disclose_ts.notna()
        & df.value.ge(min_value)
        & df.acqName.notna() & df.acqName.ne("-")
    )
    df = df.loc[mask].copy()
    df["d"] = df.disclose_ts.dt.normalize()
    return df.dropna(subset=["d"]).sort_values(["symbol", "d"])


def load_prices() -> dict[str, pd.DataFrame]:
    px: dict[str, pd.DataFrame] = {}
    for path in sorted(glob.glob(str(PX / "*.csv"))):
        sym = Path(path).stem
        d = pd.read_csv(path, parse_dates=["date"]).set_index("date").sort_index()
        d = d[["open", "close"]].replace([np.inf, -np.inf], np.nan).dropna()
        d = d[(d.open > 0) & (d.close > 0)]
        if len(d) > MIN_HISTORY_SESSIONS:
            px[sym] = d
    return px


def load_bench() -> pd.Series:
    b = pd.read_csv(BENCH, parse_dates=["Date"]).set_index("Date")["Close"].dropna()
    b.index.name = "date"
    return b.sort_index()


# --------------------------------------------------------------------------- #
def forward(px: pd.DataFrame, signal_date: pd.Timestamp, hold: int,
            cost: float) -> dict | None:
    idx = px.index
    e = idx.searchsorted(signal_date)
    if e < len(idx) and idx[e] == signal_date:
        e += 1                      # entry is the NEXT session after the signal
    if e + hold >= len(idx):
        return None
    entry, ex = float(px.open.iloc[e]), float(px.close.iloc[e + hold])
    if not (np.isfinite(entry) and entry > 0 and np.isfinite(ex)):
        return None
    gross = ex / entry - 1.0
    return dict(entry_i=int(e), exit_i=int(e + hold), entry_date=idx[e],
                exit_date=idx[e + hold], gross=gross, net=gross - cost)


# --------------------------------------------------------------------------- #
def cluster_signals(events: pd.DataFrame, window_days: int, min_insiders: int,
                    min_value_each: float, dedup_days: int) -> pd.DataFrame:
    ev = events[events.value >= min_value_each]
    rows = []
    for sym, g in ev.groupby("symbol"):
        g = g.sort_values("d")
        dates = g.d.to_numpy("datetime64[ns]")
        names = g.acqName.to_numpy()
        last = None
        for i in range(len(g)):
            lo = dates[i] - np.timedelta64(window_days, "D")
            within = [j for j in range(i + 1) if dates[j] >= lo]
            if len(set(names[j] for j in within)) >= min_insiders:
                if last is None or (dates[i] - last) > np.timedelta64(dedup_days, "D"):
                    rows.append((sym, pd.Timestamp(dates[i])))
                    last = dates[i]
    return pd.DataFrame(rows, columns=["symbol", "signal_date"])


def _fast_symbol(px: pd.DataFrame, bench: pd.Series, event_dates: pd.Series,
                 eval_hold: int, fast_thresh: float, fast_frac: float,
                 min_history: int) -> list[pd.Timestamp]:
    """Point-in-time FAST classifier for one stock."""
    idx = px.index
    close = px.close.to_numpy(float)
    bd = bench.index.to_numpy("datetime64[ns]")
    bv = bench.to_numpy(float)
    dates = event_dates.to_numpy("datetime64[ns]")
    known: list[bool] = []
    out = []
    for i in range(len(dates)):
        d_i = dates[i]
        if len(known) >= min_history and (sum(known) / len(known)) >= fast_frac:
            out.append(pd.Timestamp(d_i))
        # evaluate current event's own outcome for FUTURE classifier use
        p = int(idx.searchsorted(pd.Timestamp(d_i)))
        if p + eval_hold >= len(idx):
            known.append(False)
            continue
        d0, d1 = idx[p], idx[p + eval_hold]
        j0, j1 = np.searchsorted(bd, np.datetime64(d0)), np.searchsorted(bd, np.datetime64(d1))
        if j0 >= len(bd) or j1 >= len(bd):
            known.append(False)
            continue
        stock = close[p + eval_hold] / close[p] - 1.0
        mkt = bv[j1] / bv[j0] - 1.0
        # only mark as known if the window closed before the next event's date
        known.append((stock - mkt) >= fast_thresh)
        if i + 1 < len(dates) and idx[p + eval_hold] >= pd.Timestamp(dates[i + 1]):
            # outcome not yet public at the next signal -> drop it from the classifier
            known.pop()
    return out


def evaluate(signals: pd.DataFrame, prices: dict[str, pd.DataFrame], hold: int,
             cost: float, bench: pd.Series, n_placebo: int = N_PLACEBO,
             seed: int = SEED) -> dict:
    trades = []
    by_symbol_sig: dict[str, int] = {}
    for row in signals.itertuples():
        px = prices.get(row.symbol)
        if px is None:
            continue
        f = forward(px, row.signal_date, hold, cost)
        if f is None:
            continue
        trades.append(dict(symbol=row.symbol, signal_date=row.signal_date, **f))
        by_symbol_sig[row.symbol] = by_symbol_sig.get(row.symbol, 0) + 1
    tr = pd.DataFrame(trades)
    if tr.empty:
        return {"n": 0}

    # benchmark-adjusted net (excess vs Nifty over the same entry->exit window)
    bfill = bench.sort_index().ffill()
    b0 = bfill.reindex(tr.entry_date).ffill().to_numpy(float)
    b1 = bfill.reindex(tr.exit_date).ffill().to_numpy(float)
    tr["excess"] = tr.net - (b1 / b0 - 1.0)

    # non-overlapping subset per symbol
    nonover = []
    for sym, g in tr.sort_values("entry_date").groupby("symbol"):
        last_exit = None
        for t in g.itertuples():
            if last_exit is None or t.entry_date > last_exit:
                nonover.append(t)
                last_exit = t.exit_date
    nov = pd.DataFrame(nonover)

    # ---- vectorised equal-weight daily sleeves + matched random placebo ----
    syms = list(by_symbol_sig.keys())
    cal = pd.DatetimeIndex(sorted(set().union(*(set(prices[s].index) for s in syms))))
    arrays = {}
    for s in syms:
        px = prices[s]
        arrays[s] = dict(c=px.close.to_numpy(float), o=px.open.to_numpy(float),
                         g=np.asarray(cal.searchsorted(px.index)),
                         elig=np.arange(MIN_HISTORY_SESSIONS, len(px) - hold - 2))

    def daily_acc(records: list[tuple], n: int) -> np.ndarray:
        acc = np.zeros(len(cal))
        for sym, ei, xi, _net in records:
            a = arrays[sym]
            c, o, g = a["c"], a["o"], a["g"]
            acc[g[ei]] += c[ei] / o[ei] - 1 - cost / 2
            acc[g[ei + 1:xi + 1]] += c[ei + 1:xi + 1] / c[ei:xi] - 1
            acc[g[xi]] -= cost / 2
        return acc / max(n, 1)

    obs_records = [(t.symbol, t.entry_i, t.exit_i, t.net) for t in tr.itertuples()]
    daily = pd.Series(daily_acc(obs_records, len(syms)), index=cal)
    sd = daily.std(ddof=1)
    sharpe = float(daily.mean() / sd * math.sqrt(252)) if sd and sd > 0 else np.nan

    def stats(frame: pd.DataFrame) -> dict:
        v = frame.net.to_numpy(float)
        return dict(n=int(len(v)),
                    win=float((v > 0).mean()) if len(v) else np.nan,
                    mean=float(v.mean()) if len(v) else np.nan,
                    se=float(v.std(ddof=1) / math.sqrt(len(v))) if len(v) > 1 else np.nan,
                    median=float(np.median(v)) if len(v) else np.nan,
                    mean_excess=float(frame.excess.mean()) if len(frame) else np.nan)

    # matched random-entry placebo: same count per symbol, random eligible dates
    rng = np.random.default_rng(seed)
    pooled_means = np.empty(n_placebo)
    sharpes = np.empty(n_placebo)
    for it in range(n_placebo):
        records = []
        for sym, k in by_symbol_sig.items():
            a = arrays[sym]
            elig = a["elig"]
            if len(elig) == 0:
                continue
            picks = rng.choice(elig, size=k, replace=k > len(elig))
            c, o = a["c"], a["o"]
            for ei in picks:
                xi = ei + hold
                records.append((sym, int(ei), int(xi), c[xi] / o[ei] - 1 - cost))
        if not records:
            pooled_means[it] = 0.0; sharpes[it] = 0.0; continue
        pooled_means[it] = float(np.mean([r[3] for r in records]))
        acc = daily_acc(records, len(syms))
        sd2 = acc.std(ddof=1)
        sharpes[it] = acc.mean() / sd2 * math.sqrt(252) if sd2 and sd2 > 0 else 0.0

    obs_mean = float(tr.net.mean())
    # exposure: average fraction of the book holding an open position
    open_days = sum(int(arrays[s]["g"][xi]) - int(arrays[s]["g"][ei]) + 1
                    for s, ei, xi, _ in obs_records)
    exposure = open_days / (len(cal) * max(len(syms), 1))

    # date-jitter placebo: same stock, timing shifted +/- 20 sessions (isolates
    # timing from "the stock/period happened to be good")
    jrng = np.random.default_rng(seed + 1)
    j_mean = np.empty(n_placebo)
    j_sh = np.empty(n_placebo)
    for it in range(n_placebo):
        records = []
        for s, ei, xi, _ in obs_records:
            a = arrays[s]
            if len(a["elig"]) == 0:
                continue
            lo, hi = int(a["elig"][0]), int(a["elig"][-1])
            nei = int(np.clip(ei + int(jrng.integers(-20, 21)), lo, hi))
            records.append((s, nei, nei + hold,
                            a["c"][nei + hold] / a["o"][nei] - 1 - cost))
        if not records:
            j_mean[it] = 0.0; j_sh[it] = 0.0; continue
        j_mean[it] = float(np.mean([r[3] for r in records]))
        acc = daily_acc(records, len(syms))
        sd3 = acc.std(ddof=1)
        j_sh[it] = acc.mean() / sd3 * math.sqrt(252) if sd3 and sd3 > 0 else 0.0

    out = {
        "n": int(len(tr)),
        "n_nonoverlap": int(len(nov)),
        "win": stats(tr)["win"], "mean": stats(tr)["mean"], "se": stats(tr)["se"],
        "median": stats(tr)["median"], "mean_excess": stats(tr)["mean_excess"],
        "sharpe": sharpe,
        "nonoverlap": stats(nov) if len(nov) else {},
        "oos": stats(tr[tr.entry_date >= SPLIT]) if (tr.entry_date >= SPLIT).any() else {},
        "placebo_mean_p": float((pooled_means >= obs_mean).mean()),
        "placebo_sharpe_p": float((sharpes >= sharpe).mean()) if np.isfinite(sharpe) else np.nan,
        "random_mean_median": float(np.median(pooled_means)),
        "random_sharpe_median": float(np.median(sharpes)),
        "placebo_jitter_mean_p": float((j_mean >= obs_mean).mean()),
        "placebo_jitter_sharpe_p": float((j_sh >= sharpe).mean()) if np.isfinite(sharpe) else np.nan,
        "random_jitter_mean_median": float(np.median(j_mean)),
        "exposure": float(exposure),
        "cost_bp": cost * 1e4,
        "hold": hold,
        "_daily": daily,
    }
    return out


def repair_level_shift(s: pd.Series, thresh: float = 0.5) -> pd.Series:
    """Repair a one-sided level error (bad listing print / unrepaired split).

    A single jump > thresh that does not revert is treated as a level error; the
    earlier segment is rescaled to the later, correct level (AGENTS.md split trap).
    """
    r = np.log(s).diff()
    if r.dropna().empty:
        return s
    j = r.abs().idxmax()
    if abs(r.loc[j]) < thresh:
        return s
    pre, post = s.loc[s.index < j], s.loc[s.index >= j]
    if pre.empty or post.empty:
        return s
    ratio = post.median() / pre.median()
    out = s.copy()
    mask = s.index < j
    out.loc[mask] = out.loc[mask] * ratio
    return out


def load_momentum_etfs() -> dict[str, pd.Series]:
    """Daily close series for each Indian momentum ETF (download once, cached)."""
    out: dict[str, pd.Series] = {}
    for name, ticker in MOMENTUM_ETFS.items():
        path = ETF_DIR / f"{ticker.replace('.NS', '')}.csv"
        if not path.exists():
            try:
                import yfinance as yf
                raw = yf.download(ticker, start="2018-01-01", auto_adjust=True,
                                  progress=False, threads=False)
                if raw is None or raw.empty:
                    continue
                if isinstance(raw.columns, pd.MultiIndex):
                    raw.columns = raw.columns.get_level_values(0)
                raw = raw.reset_index().rename(columns={"Date": "date", "Close": "close"})
                raw[["date", "close"]].to_csv(path, index=False)
            except Exception:
                continue
        if path.exists():
            s = pd.read_csv(path, parse_dates=["date"]).set_index("date")["close"].dropna()
            s = s[s > 0].sort_index()
            if len(s) > 30:
                fixed = repair_level_shift(s)
                if float(fixed.pct_change().abs().max()) <= 0.5:
                    out[name] = fixed
                else:
                    print(f"  WARNING: {name} still has a >50% jump after repair; dropped")
    return out


def series_stats(ret: pd.Series, label: str) -> dict:
    ret = ret.dropna()
    if len(ret) < 20 or ret.std(ddof=1) == 0:
        return {"label": label, "n": int(len(ret))}
    eq = (1 + ret).cumprod()
    years = len(ret) / 252
    return {
        "label": label, "n": int(len(ret)),
        "total": float(eq.iloc[-1] - 1),
        "cagr": float(eq.iloc[-1] ** (1 / years) - 1),
        "vol": float(ret.std(ddof=1) * math.sqrt(252)),
        "sharpe": float(ret.mean() / ret.std(ddof=1) * math.sqrt(252)),
        "maxdd": float((eq / eq.cummax() - 1).min()),
    }


def momentum_etf_comparison(strategy_daily: pd.Series,
                            etfs: dict[str, pd.Series]) -> list[dict]:
    """Pairwise compare strategy sleeves vs buy&hold momentum ETF on overlap."""
    rows = []
    for name, px in etfs.items():
        w0 = max(px.index.min(), strategy_daily.index.min())
        w1 = min(px.index.max(), strategy_daily.index.max())
        cal = strategy_daily.index[(strategy_daily.index >= w0)
                                   & (strategy_daily.index <= w1)]
        if len(cal) < 20:
            continue
        s_ret = strategy_daily.reindex(cal).fillna(0.0)
        e_ret = px.reindex(cal, method="ffill").pct_change(fill_method=None).fillna(0.0)
        for tag, ret in (("STRATEGY", s_ret), (f"BUY&HOLD {name}", e_ret)):
            row = series_stats(ret, tag)
            row["peer"] = name
            row["window"] = f"{cal.min().date()}..{cal.max().date()}"
            rows.append(row)
    return rows


def plot_oos_equity(dailies: dict[str, pd.Series], etfs: dict[str, pd.Series],
                    split: pd.Timestamp, path: Path) -> None:
    fig, ax = plt.subplots(figsize=(12, 6.5))
    for key, daily in dailies.items():
        d = daily[daily.index >= split]
        if len(d) < 5:
            continue
        eq = (1 + d).cumprod()
        ax.plot(eq.index, eq, lw=1.6, label=f"strategy: {key}")
    for name, px in etfs.items():
        d = px[px.index >= split]
        if len(d) < 5:
            continue
        eq = d / d.iloc[0]
        ax.plot(eq.index, eq, ls="--", lw=1.2, alpha=0.8, label=f"buy&hold {name}")
    ax.axhline(1.0, color="#999", lw=0.8)
    ax.axvline(split, color="black", ls=":", lw=1.0)
    ax.set_title("Out-of-sample (from 2023-07-05): insider strategies vs momentum ETFs / Nifty")
    ax.set_ylabel("growth of 1"); ax.grid(alpha=0.25); ax.legend(fontsize=8, ncol=2)
    fig.tight_layout(); fig.savefig(path, dpi=150); plt.close(fig)


def print_comparison(title: str, rows: list[dict]) -> None:
    print(f"\n-- {title} vs momentum ETFs (pairwise overlap) --")
    hdr = (f"{'portfolio':34}{'window':24}{'total':>9}{'CAGR':>8}"
           f"{'vol':>7}{'Sharpe':>8}{'maxDD':>8}")
    print(hdr); print("-" * len(hdr))
    for r in rows:
        if "cagr" not in r:
            continue
        print(f"{r['label']:34}{r['window']:24}{r['total']*100:>8.1f}%"
              f"{r['cagr']*100:>7.1f}%{r['vol']*100:>6.1f}%"
              f"{r['sharpe']:>8.2f}{r['maxdd']*100:>7.1f}%")


def bh_fdr(pvals: list[float], q: float = 0.05) -> list[bool]:
    p = np.asarray(pvals, float)
    n = len(p)
    order = np.argsort(p)
    passed = np.zeros(n, bool)
    thresh = q * (np.arange(1, n + 1) / n)
    sorted_p = p[order]
    below = sorted_p <= thresh
    if below.any():
        k = np.max(np.nonzero(below)[0])
        passed[order[:k + 1]] = True
    return passed.tolist()


def save_finding_bundle(dailies: dict[str, pd.Series], etfs: dict[str, pd.Series],
                        results: dict, tests: dict[str, dict],
                        save_dir: Path, split: pd.Timestamp) -> None:
    """Write plots + machine-readable stats into <repo>/finding/<date>/."""
    plots = save_dir / "plots"
    plots.mkdir(parents=True, exist_ok=True)
    primary = [("cluster_W30_K2_V10L_h20", "#17964b", "clusters (W30,K2,>=Rs10L, hold 20d)"),
               ("fast_H3_frac50_n2_h3", "#d62728", "FAST reactors (frac>=.5,n>=2, hold 3d)")]

    # full-period equity for each primary signal vs Nifty
    for key, color, title in primary:
        daily = dailies.get(key)
        if daily is None or daily.empty:
            continue
        fig, ax = plt.subplots(figsize=(12, 6))
        eq = (1 + daily).cumprod()
        ax.plot(eq.index, eq, color=color, lw=1.7, label=f"{key} (equal-weight sleeves)")
        nb = etfs.get("NIFTY")
        if nb is not None:
            nb = nb.reindex(eq.index, method="ffill").dropna()
            nb = nb / nb.iloc[0]
            ax.plot(nb.index, nb, ls="--", color="#888", lw=1.2, label="NIFTY buy&hold")
        ax.axvline(split, color="black", ls=":", lw=1.0, label="70/30 split")
        ax.axhline(1.0, color="#bbb", lw=0.8)
        ax.set_title(f"{title} — growth of 1 (27 bp charges)")
        ax.set_ylabel("growth of Rs 1"); ax.grid(alpha=0.25); ax.legend(fontsize=9)
        fig.tight_layout(); fig.savefig(plots / f"equity_{key}.png", dpi=150); plt.close(fig)

    # OOS comparison vs momentum ETFs / Nifty
    plot_oos_equity({k: v for k, v in primary_dailies(dailies, primary)},
                    etfs, split, plots / "oos_vs_momentum_etf.png")

    # bar chart: mean net per trade and Sharpe across all cells
    names = list(tests.keys())
    means = [tests[n].get("mean", np.nan) * 100 for n in names]
    sharpes = [tests[n].get("sharpe", np.nan) for n in names]
    fig, axes = plt.subplots(1, 2, figsize=(14, 5.5))
    axes[0].bar(range(len(names)), means, color="#4d6475")
    axes[0].set_title("Mean net per trade (%)"); axes[0].axhline(0, color="k", lw=0.8)
    axes[1].bar(range(len(names)), sharpes, color="#9ecae1")
    axes[1].set_title("Portfolio Sharpe"); axes[1].axhline(0, color="k", lw=0.8)
    for ax in axes:
        ax.set_xticks(range(len(names)))
        ax.set_xticklabels(names, rotation=90, fontsize=7); ax.grid(axis="y", alpha=0.25)
    fig.tight_layout(); fig.savefig(plots / "cells_mean_sharpe.png", dpi=150); plt.close(fig)

    # daily equity CSVs for the primaries
    for key, _, _ in primary:
        daily = dailies.get(key)
        if daily is not None and not daily.empty:
            daily.rename("daily_return").to_csv(save_dir / f"daily_equity_{key}.csv")

    # markdown stats table
    rows = ["| cell | n | mean net | median | win | Sharpe | OOS n | OOS mean | "
            "random p | jitter p | exposure |",
            "|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|"]
    for n in names:
        t = tests[n]
        o = t.get("oos", {})
        rows.append(
            f"| {n} | {t.get('n')} | {t.get('mean', float('nan'))*100:+.2f}% | "
            f"{t.get('median', float('nan'))*100:+.2f}% | {t.get('win', float('nan')):.3f} | "
            f"{t.get('sharpe', float('nan')):.3f} | {o.get('n', '-')} | "
            f"{o.get('mean', float('nan'))*100:+.2f}% | {t.get('placebo_mean_p', float('nan')):.3f} | "
            f"{t.get('placebo_jitter_mean_p', float('nan')):.3f} | {t.get('exposure',0)*100:.2f}% |")
    (save_dir / "stats_table.md").write_text(
        f"# Stats — insider clusters & FAST reactors ({REPORT_DATE})\n\n"
        f"Cost 27 bp round trip; split {split.date()}; universe 215 current tickers.\n\n"
        + "\n".join(rows) + "\n")
    (save_dir / "results.json").write_text(
        json.dumps(results, indent=2, default=float) + "\n")


def primary_dailies(dailies, primary):
    return [(k, dailies.get(k)) for k, _, _ in primary if dailies.get(k) is not None]


def main() -> None:
    events = load_events()
    prices = load_prices()
    bench = load_bench()
    print(f"major market-purchase events: {len(events):,}  "
          f"priced stocks: {len(prices)}  "
          f"events with prices: {events.symbol.isin(prices).sum():,}")
    ev = events[events.symbol.isin(prices)]

    results: dict = {"cost_bp_primary": COST * 1e4, "split": str(SPLIT.date()),
                     "tests": {}, "momentum_etf_comparison": {}}
    cells = []
    dailies: dict[str, pd.Series] = {}

    # ---- #1 cluster: primary + variants ----
    print("\n================ #1 INSIDER-BUY CLUSTERS ================")
    cluster_cfgs = [
        ("cluster_W30_K2_V10L", dict(window_days=30, min_insiders=2,
                                     min_value_each=1e6, dedup_days=20)),
        ("cluster_W30_K2_V0", dict(window_days=30, min_insiders=2,
                                   min_value_each=0.0, dedup_days=20)),
        ("cluster_W90_K2_V10L", dict(window_days=90, min_insiders=2,
                                     min_value_each=1e6, dedup_days=45)),
        ("cluster_W30_K3_V10L", dict(window_days=30, min_insiders=3,
                                     min_value_each=1e6, dedup_days=20)),
    ]
    for name, cfg in cluster_cfgs:
        sigs = cluster_signals(ev, **cfg)
        for hold in (20,):
            r = evaluate(sigs, prices, hold, COST, bench)
            r["signals"] = int(len(sigs))
            r["cfg"] = cfg
            res = evaluate(sigs, prices, hold, COST_SMALL, bench, n_placebo=1)
            r["mean_at_75bp"] = res.get("mean")
            results["tests"][f"{name}_h{hold}"] = r
            cells.append((f"{name}_h{hold}", r.get("placebo_mean_p", 1.0)))
            dailies[f"{name}_h{hold}"] = r.get("_daily")
            print(f"\n[{name} hold={hold}] signals={len(sigs)} priced-trades={r['n']} "
                  f"non-overlap={r['n_nonoverlap']}")
            if r["n"]:
                print(f"   net mean {r['mean']*100:+.2f}% (SE {r['se']*100:.2f}) "
                      f"median {r['median']*100:+.2f}% win {r['win']:.2f} "
                      f"excess {r['mean_excess']*100:+.2f}%  Sharpe {r['sharpe']:.2f}")
                if r["oos"]:
                    print(f"   OOS (>= {SPLIT.date()}): n={r['oos']['n']} "
                          f"mean {r['oos']['mean']*100:+.2f}% win {r['oos']['win']:.2f}")
                print(f"   random placebo mean {r['random_mean_median']*100:+.2f}% "
                      f"p(mean)={r['placebo_mean_p']:.3f} p(Sharpe)={r['placebo_sharpe_p']:.3f} "
                      f"| jitter placebo mean {r['random_jitter_mean_median']*100:+.2f}% "
                      f"p(mean)={r['placebo_jitter_mean_p']:.3f} p(Sharpe)={r['placebo_jitter_sharpe_p']:.3f} "
                      f"| exposure {r['exposure']*100:.1f}% | mean@75bp {r['mean_at_75bp']*100:+.2f}%")

    # ---- #2 FAST subset (point-in-time) ----
    print("\n================ #2 POINT-IN-TIME FAST REACTORS ================")
    fast_cfgs = [
        ("fast_H3_frac50_n3", dict(min_value=2.5e6, eval_hold=5, fast_thresh=0.03,
                                   fast_frac=0.5, min_history=3)),
        ("fast_H3_frac50_n2", dict(min_value=2.5e6, eval_hold=5, fast_thresh=0.03,
                                   fast_frac=0.5, min_history=2)),
        ("fast_H3_frac34_n2", dict(min_value=2.5e6, eval_hold=5, fast_thresh=0.03,
                                   fast_frac=0.34, min_history=2)),
        ("fast_H5_frac50_n2", dict(min_value=2.5e6, eval_hold=5, fast_thresh=0.03,
                                   fast_frac=0.5, min_history=2)),
    ]
    fast_signals_all = {}
    for name, cfg in fast_cfgs:
        rows = []
        for sym, px in prices.items():
            g = ev[ev.symbol == sym]
            if g.empty:
                continue
            for d in _fast_symbol(px, bench, g.d, cfg["eval_hold"], cfg["fast_thresh"],
                                  cfg["fast_frac"], cfg["min_history"]):
                rows.append((sym, d))
        sigs = pd.DataFrame(rows, columns=["symbol", "signal_date"])
        fast_signals_all[name] = sigs
        hold = 3
        r = evaluate(sigs, prices, hold, COST, bench)
        r["signals"] = int(len(sigs))
        r["cfg"] = {k: v for k, v in cfg.items()}
        res = evaluate(sigs, prices, hold, COST_SMALL, bench, n_placebo=1)
        r["mean_at_75bp"] = res.get("mean")
        results["tests"][f"{name}_h{hold}"] = r
        cells.append((f"{name}_h{hold}", r.get("placebo_mean_p", 1.0)))
        dailies[f"{name}_h{hold}"] = r.get("_daily")
        print(f"\n[{name} hold={hold}] signals={len(sigs)} priced-trades={r['n']} "
              f"non-overlap={r['n_nonoverlap']}")
        if r["n"]:
            print(f"   net mean {r['mean']*100:+.2f}% (SE {r['se']*100:.2f}) "
                  f"median {r['median']*100:+.2f}% win {r['win']:.2f} "
                  f"excess {r['mean_excess']*100:+.2f}%  Sharpe {r['sharpe']:.2f}")
            if r["oos"]:
                print(f"   OOS (>= {SPLIT.date()}): n={r['oos']['n']} "
                      f"mean {r['oos']['mean']*100:+.2f}% win {r['oos']['win']:.2f}")
            print(f"   random placebo mean {r['random_mean_median']*100:+.2f}% "
                  f"p(mean)={r['placebo_mean_p']:.3f} p(Sharpe)={r['placebo_sharpe_p']:.3f} "
                  f"| jitter placebo mean {r['random_jitter_mean_median']*100:+.2f}% "
                  f"p(mean)={r['placebo_jitter_mean_p']:.3f} p(Sharpe)={r['placebo_jitter_sharpe_p']:.3f} "
                  f"| exposure {r['exposure']*100:.1f}% | mean@75bp {r['mean_at_75bp']*100:+.2f}%")

    # ---- FDR over all cells ----
    names = [c[0] for c in cells]
    pvals = [c[1] for c in cells]
    passed = bh_fdr(pvals)
    print("\n================ MULTIPLE TESTING (FDR) ================")
    print(f"cells tested: {len(cells)}   expected raw p<0.05 by chance: {0.05*len(cells):.2f}")
    for nm, pv, ok in zip(names, pvals, passed):
        print(f"  {nm:32} placebo p={pv:.4f}  {'PASS' if ok else 'fail'}")
    results["fdr"] = dict(cells=names, pvals=pvals, passed=passed,
                          expected_by_chance=0.05 * len(cells))

    # ---- momentum ETF comparison (the "just buy momentum" falsification) ----
    print("\n================ MOMENTUM ETF COMPARISON ================")
    etfs = load_momentum_etfs()
    etfs["NIFTY"] = bench            # plain index buy&hold reference
    if not etfs:
        print("no momentum ETF data available")
    else:
        print("benchmarks: " + ", ".join(
            f"{k}={v.index.min().date()}..{v.index.max().date()}" for k, v in etfs.items()))
        primary = [("cluster_W30_K2_V10L_h20", dailies.get("cluster_W30_K2_V10L_h20")),
                   ("fast_H3_frac50_n2_h3", dailies.get("fast_H3_frac50_n2_h3"))]
        for key, daily in primary:
            if daily is None or daily.empty:
                continue
            rows = momentum_etf_comparison(daily, etfs)
            results["momentum_etf_comparison"][key] = rows
            print_comparison(key, rows)
        plot_oos_equity({k: v for k, v in primary if v is not None}, etfs,
                        SPLIT, OUT / "oos_vs_momentum_etf.png")
        print(f"\nplot -> {OUT / 'oos_vs_momentum_etf.png'}")

    # strip non-serialisable daily series
    for test in results["tests"].values():
        test.pop("_daily", None)
    (OUT / "results.json").write_text(json.dumps(results, indent=2, default=float) + "\n")
    print(f"\nwrote {OUT / 'results.json'}")

    # ---- repo-root findings bundle ----
    save_finding_bundle(dailies, etfs, results, results["tests"], FINDING_DIR, SPLIT)
    print(f"findings bundle -> {FINDING_DIR}")


if __name__ == "__main__":
    raise SystemExit(main())
