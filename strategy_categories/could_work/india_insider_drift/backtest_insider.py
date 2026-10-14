#!/usr/bin/env python3
"""
backtest_insider.py — major-insider RSI-dip signal: full backtest.

Signal (tunable):
    LONG when a MAJOR insider (promoter / promoter-group / director / KMP)
    market-BUYS >= MIN_VALUE AND RSI(14) < RSI_DIP.
Entry: next open after the disclosure date (point-in-time). Exit: close after HOLD days.
Long-only, no leverage (cash). Costs charged on both legs.

Selection criterion (better than "volatile"): money = (signals/year) x (edge/signal),
so rank candidates by expected annual net contribution with enough trades and a
tradable price — then confirm out-of-sample.

Reports per symbol and as a pooled equal-sleeve portfolio: n, win, avg net, CAGR,
vol, Sharpe, max drawdown, Calmar, exposure. Then IS/OOS split, Monte-Carlo
(bootstrap) and a random-entry placebo.

Usage:
  python backtest_insider.py --fetch --min-value 2500000 --rsi-dip 40 --hold 20
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
EVENTS = HERE / "data" / "events.csv"
PX = HERE / "data" / "bt_prices"
RESULTS = HERE / "data" / "backtest_results.json"

MAJOR_CATS = {"Promoters", "Promoter Group", "Director", "Key Managerial Personnel"}
RSI_PERIOD = 14
OOS_START = "2024-01-01"


def rsi(close: pd.Series, period: int = RSI_PERIOD) -> pd.Series:
    d = close.diff()
    ag = d.clip(lower=0).ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    al = (-d.clip(upper=0)).ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    return 100 - 100 / (1 + ag / al.replace(0, np.nan))


def load_events(min_value: float) -> pd.DataFrame:
    df = pd.read_csv(EVENTS, parse_dates=["trade_date", "disclose_ts"])
    df = df[df["personCategory"].isin(MAJOR_CATS) & (df["value"] >= min_value)]
    df = df[df["is_buy"] & df["is_equity"]].dropna(subset=["disclose_ts"]).copy()
    df["d"] = df["disclose_ts"].dt.normalize()
    return df


def candidates(df, min_events: int) -> list[str]:
    c = df.groupby("symbol").size()
    return c[c >= min_events].sort_values(ascending=False).index.tolist()


def download(symbols: list[str]) -> None:
    import yfinance as yf
    PX.mkdir(parents=True, exist_ok=True)
    todo = [s for s in symbols if not (PX / f"{s}.csv").exists()]
    print(f"prices: {len(symbols)-len(todo)} cached, {len(todo)} to fetch")
    for i in range(0, len(todo), 40):
        batch = todo[i:i + 40]
        data = yf.download(" ".join(f"{s}.NS" for s in batch), start="2010-01-01",
                           auto_adjust=True, progress=False, group_by="ticker",
                           threads=True)
        for s in batch:
            try:
                sub = data[f"{s}.NS"].dropna()
            except Exception:
                continue
            if sub.empty:
                continue
            sub = sub.reset_index()
            sub.columns = [str(c).lower() for c in sub.columns]
            sub[["date", "open", "close"]].to_csv(PX / f"{s}.csv", index=False)
        print(f"  batch {i//40}: {len(list(PX.glob('*.csv')))} saved")


def load_px(sym: str):
    p = PX / f"{sym}.csv"
    if not p.exists():
        return None
    d = pd.read_csv(p, parse_dates=["date"]).set_index("date").sort_index()
    return d if len(d) > 60 else None


def signals(ev: pd.DataFrame, px: pd.DataFrame, rsi_dip: float) -> pd.DataFrame:
    r = rsi(px["close"])
    sig = ev.dropna(subset=["d"]).copy()
    pos = np.clip(r.index.searchsorted(sig["d"].to_numpy()), 0, len(r) - 1)
    sig["rsi"] = r.to_numpy()[pos]
    return sig[sig["rsi"] < rsi_dip]


def backtest(px: pd.DataFrame, sig: pd.DataFrame, hold: int, cost: float,
             entry: str = "dip", recovery: float = 40.0, ma: int = 0,
             max_wait: int = 40):
    """Long-only. entry='dip' -> buy next open after the signal.
    entry='recovery' -> wait until RSI crosses back ABOVE `recovery`, then buy next
    open (buy the dip *turning*, not the falling knife). `ma`>0 requires close>SMA(ma)
    at entry. Exit at close hold days later."""
    idx = px.index
    close = px["close"]
    r = rsi(close)
    sma = close.rolling(ma).mean() if ma else None
    trades = []
    for d in sig["d"]:
        e = idx.searchsorted(d)
        if e + 1 >= len(idx):
            continue
        if entry == "dip":
            ei = e + 1
        else:  # recovery
            ei = None
            for j in range(e, min(e + max_wait, len(idx) - 1)):
                if np.isfinite(r.iloc[j]) and r.iloc[j] > recovery:
                    ei = j + 1
                    break
            if ei is None:
                continue
        if ei + hold >= len(idx):
            continue
        if sma is not None and not (np.isfinite(sma.iloc[ei])
                                    and close.iloc[ei] > sma.iloc[ei]):
            continue
        entry_p, exit_p = px["open"].iloc[ei], close.iloc[ei + hold]
        if not np.isfinite(entry_p) or entry_p <= 0 or not np.isfinite(exit_p):
            continue
        trades.append(dict(entry_date=idx[ei], exit_date=idx[ei + hold],
                           net=exit_p / entry_p - 1.0 - cost))
    tr = pd.DataFrame(trades)
    pos = pd.Series(0.0, index=idx)
    for t in trades:
        pos.loc[t["entry_date"]:t["exit_date"]] = 1.0
    ret = close.pct_change(fill_method=None).fillna(0.0)
    strat = pos.shift(1).fillna(0.0) * ret
    for t in trades:
        strat.loc[t["entry_date"]] -= cost / 2
        strat.loc[t["exit_date"]] -= cost / 2
    return strat, tr, pos


def metrics(strat: pd.Series, tr: pd.DataFrame, pos: pd.Series) -> dict:
    if tr.empty or strat.std() == 0:
        return dict(n=0, win=np.nan, avg_net=np.nan, cagr=np.nan, vol=np.nan,
                    sharpe=np.nan, maxdd=np.nan, calmar=np.nan, exposure=np.nan)
    eq = (1 + strat).cumprod()
    yrs = (strat.index[-1] - strat.index[0]).days / 365.25
    cagr = eq.iloc[-1] ** (1 / yrs) - 1 if yrs > 0 else np.nan
    vol = strat.std() * np.sqrt(252)
    sharpe = strat.mean() / strat.std() * np.sqrt(252)
    dd = (eq / eq.cummax() - 1).min()
    return dict(n=int(len(tr)), win=float((tr["net"] > 0).mean()),
                avg_net=float(tr["net"].mean()), cagr=float(cagr), vol=float(vol),
                sharpe=float(sharpe), maxdd=float(dd),
                calmar=float(cagr / abs(dd)) if dd else np.nan,
                exposure=float(pos.mean()))


# --------------------------------------------------------------------------- #
def block_bootstrap_sharpe(strat: pd.Series, n: int = 1000, block: int = 20,
                           seed: int = 7) -> dict:
    r = strat.to_numpy()
    rng = np.random.default_rng(seed)
    L = len(r)
    if L < block + 5 or r.std() == 0:
        return {}
    nb = int(np.ceil(L / block))
    sharpes = np.empty(n)
    for i in range(n):
        starts = rng.integers(0, L - block, size=nb)
        s = np.concatenate([r[j:j + block] for j in starts])[:L]
        sharpes[i] = s.mean() / s.std() * np.sqrt(252) if s.std() else 0
    return dict(p05=float(np.percentile(sharpes, 5)),
                p50=float(np.percentile(sharpes, 50)),
                p95=float(np.percentile(sharpes, 95)),
                p_le0=float((sharpes <= 0).mean()))


def placebo_sharpe(px_by_sym: dict, hold: int, cost: float, n_iter: int = 200,
                   seed: int = 11) -> np.ndarray:
    """Random entry dates (same count per symbol) -> distribution of pooled Sharpe."""
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(n_iter):
        parts = []
        for sym, (px, k) in px_by_sym.items():
            if k == 0:
                continue
            idx = px.index
            starts = rng.integers(0, len(idx) - hold - 2, size=k)
            trades = []
            for s in starts:
                e = px["open"].iloc[s]
                x = px["close"].iloc[min(s + hold, len(idx) - 1)]
                if e > 0 and np.isfinite(e) and np.isfinite(x):
                    trades.append((idx[s], idx[min(s + hold, len(idx) - 1)],
                                   x / e - 1 - cost))
            pos = pd.Series(0.0, index=idx)
            for a, b, _ in trades:
                pos.loc[a:b] = 1.0
            ret = px["close"].pct_change(fill_method=None).fillna(0.0)
            st = pos.shift(1).fillna(0.0) * ret
            for a, b, _ in trades:
                st.loc[a] -= cost / 2
                st.loc[b] -= cost / 2
            parts.append(st)
        if parts:
            comb = pd.concat(parts, axis=1).mean(axis=1)
            out.append(comb.mean() / comb.std() * np.sqrt(252) if comb.std() else 0)
    return np.asarray(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--hold", type=int, default=20)
    ap.add_argument("--cost", type=float, default=0.0075)
    ap.add_argument("--min-value", type=float, default=2.5e6)
    ap.add_argument("--rsi-dip", type=float, default=40)
    ap.add_argument("--entry", choices=["dip", "recovery"], default="dip")
    ap.add_argument("--recovery", type=float, default=40.0)
    ap.add_argument("--ma", type=int, default=0, help="require close>SMA(n) at entry")
    ap.add_argument("--variants", action="store_true",
                    help="compare dip/recovery x ma filters and exit")
    ap.add_argument("--min-events", type=int, default=8)
    ap.add_argument("--symbols", type=str, default="")
    ap.add_argument("--pick", type=int, default=8)
    ap.add_argument("--mc", type=int, default=1000)
    a = ap.parse_args(argv)

    ev = load_events(a.min_value)
    cand = ([s.strip() for s in a.symbols.split(",") if s.strip()]
            if a.symbols else candidates(ev, a.min_events))
    print(f"signal: major buy >= Rs{a.min_value:,.0f}, RSI<{a.rsi_dip}, hold {a.hold}, "
          f"cost {a.cost:.4f}")
    print(f"candidates: {len(cand)}")
    if a.fetch:
        download(cand)

    def run_cfg(entry, recovery, ma):
        rows, strats, trade_sets, sig_counts = [], {}, {}, {}
        for s in cand:
            px = load_px(s)
            if px is None:
                continue
            sig = signals(ev[ev["symbol"] == s], px, a.rsi_dip)
            sig_counts[s] = len(sig)
            if sig.empty:
                continue
            strat, tr, pos = backtest(px, sig, a.hold, a.cost, entry, recovery, ma)
            if tr.empty:
                continue
            rows.append(dict(symbol=s, **metrics(strat, tr, pos)))
            strats[s], trade_sets[s] = strat, tr
        if not rows:
            return None
        tab = pd.DataFrame(rows).sort_values("sharpe", ascending=False)
        combined = pd.concat(strats, axis=1).mean(axis=1).dropna()
        pooled = pd.concat(trade_sets.values(), ignore_index=True)
        pm = metrics(combined, pooled, (combined != 0).astype(float))
        return dict(tab=tab, combined=combined, pooled=pooled, pm=pm,
                    strats=strats, trade_sets=trade_sets, sig_counts=sig_counts)

    if a.variants:
        print(f"\n=== variants (pooled, hold {a.hold}, cost {a.cost:.4f}) ===")
        hdr = (f"{'variant':30}{'trades':>7}{'win':>6}{'avg_net':>9}"
               f"{'sharpe':>8}{'maxdd':>8}{'calmar':>8}")
        print(hdr); print("-" * len(hdr))
        for entry, rec, ma in (("dip", 40, 0), ("recovery", 40, 0),
                               ("dip", 40, 200), ("recovery", 40, 200)):
            r = run_cfg(entry, rec, ma)
            label = f"{entry} rsi>{int(rec)} ma{ma}"
            if not r:
                print(f"{label:30}{'no trades':>7}")
                continue
            pm = r["pm"]
            print(f"{label:30}{pm['n']:>7}{pm['win']:>6.2f}"
                  f"{pm['avg_net']*100:>9.2f}{pm['sharpe']:>8.2f}"
                  f"{pm['maxdd']*100:>8.1f}{pm['calmar']:>8.2f}")
        return 0

    res = run_cfg(a.entry, a.recovery, a.ma)
    if not res:
        print("no trades"); return 1
    tab, combined, pooled, pm = res["tab"], res["combined"], res["pooled"], res["pm"]
    strats, trade_sets, sig_counts = res["strats"], res["trade_sets"], res["sig_counts"]
    print(f"\n=== per symbol (entry={a.entry}, ma={a.ma}, hold={a.hold}) ===")
    print(tab[["symbol", "n", "win", "avg_net", "cagr", "vol", "sharpe", "maxdd",
               "calmar", "exposure"]].to_string(index=False,
               float_format=lambda x: f"{x:,.3f}"))
    print("\n=== pooled portfolio (equal sleeve per symbol) ===")
    print(f"  symbols {len(strats)}  trades {pm['n']}  win {pm['win']:.3f}  "
          f"avg net {pm['avg_net']*100:.3f}%  CAGR {pm['cagr']*100:.2f}%  "
          f"vol {pm['vol']*100:.2f}%  Sharpe {pm['sharpe']:.2f}  "
          f"maxDD {pm['maxdd']*100:.1f}%  Calmar {pm['calmar']:.2f}")

    # OOS split on the pooled trades
    oos_tr = pooled[pooled["entry_date"] >= OOS_START]
    print(f"\n=== out-of-sample (entry >= {OOS_START}) ===")
    if len(oos_tr):
        print(f"  trades {len(oos_tr)}  win {(oos_tr['net']>0).mean():.3f}  "
              f"avg net {oos_tr['net'].mean()*100:.3f}%  "
              f"median {oos_tr['net'].median()*100:.3f}%")
    else:
        print("  no OOS trades")

    # Monte Carlo: block-bootstrap Sharpe + random-entry placebo
    mc = block_bootstrap_sharpe(combined, a.mc)
    print(f"\n=== Monte Carlo ({a.mc} block-bootstraps of the portfolio) ===")
    if mc:
        print(f"  Sharpe  p05 {mc['p05']:.2f}  p50 {mc['p50']:.2f}  "
              f"p95 {mc['p95']:.2f}   P(Sharpe<=0)={mc['p_le0']:.3f}")
    px_by_sym = {s: (load_px(s), sig_counts[s]) for s in strats}
    plc = placebo_sharpe(px_by_sym, a.hold, a.cost)
    if len(plc):
        print(f"  random-entry placebo Sharpe: mean {plc.mean():.2f}  "
              f"p95 {np.percentile(plc,95):.2f}  "
              f"P(placebo>=observed)={(plc>=pm['sharpe']).mean():.3f}")

    RESULTS.write_text(json.dumps(dict(params=vars(a), all=tab.to_dict("records"),
                                       pooled=pm, mc=mc, oos_n=int(len(oos_tr))),
                                  indent=2, default=float))
    print(f"\nwrote {RESULTS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
