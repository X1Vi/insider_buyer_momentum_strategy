#!/usr/bin/env python3
"""
insider_drift.py — India insider (PIT) disclosures: fetch, clean, compare, plot.

One file. Pipeline:
    fetch   -> pull NSE PIT disclosures year-by-year into data/raw/pit_YYYY.json
    clean   -> normalise into data/events.csv (one row per disclosure)
    summary -> counts by year / person type / mode; top symbols by buy value
    plot    -> for the most-bought symbols, price line + markers on the days
               insiders actually bought (trade date), coloured by person type
    fwd     -> simple forward-return comparison after buy events (vs benchmark)

Data source: NSE corporate-filings PIT API (free, no auth) — see
data/2026-10-13/DATA_SOURCES.md. Prices via yfinance (needs a venv with yfinance).

Point-in-time note: this script charts the *trade date* (when the insider bought).
For a tradeable signal use the *disclosure* date instead (see PLAN.md).

Research only; not investment advice.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
RAW = DATA / "raw"
PLOTS = HERE / "plots"
EVENTS = DATA / "events.csv"

API = "https://www.nseindia.com/api/corporates-pit"
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept": "application/json",
    "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-insider-trading",
}
YEARS = list(range(2015, 2027))

# "Big party" definition for the signal overlay: a promoter / promoter-group /
# director / KMP holder (a sizeable, well-informed actor), or any transaction worth
# >= BIG_VALUE. Employee/designated-person (ESOP) trades are excluded — they are
# routine, not a signal. Tune BIG_VALUE / the category set as needed.
BIG_VALUE = 1e7                                   # ₹1 crore
BIG_PARTY_CATS = {"Promoters", "Promoter Group", "Director",
                  "Key Managerial Personnel", "Immediate relative"}
EMPLOYEE_CATS = {"Employees/Designated Employees"}

# De-noised signal overlay ("major characters, size, in dips"):
MAJOR_CATS = {"Promoters", "Promoter Group", "Director", "Key Managerial Personnel"}
MIN_VALUE = 1e7        # only "size" trades: >= ₹1 crore
RSI_PERIOD = 14
RSI_DIP = 35           # LONG only when RSI is below this (the stock is in a dip)
RSI_PEAK = 65          # SHORT only when RSI is above this (overbought)


# --------------------------------------------------------------------------- #
# 1. FETCH
# --------------------------------------------------------------------------- #
def fetch_years(years: list[int], sleep: float = 2.0) -> None:
    import requests
    RAW.mkdir(parents=True, exist_ok=True)
    for y in years:
        out = RAW / f"pit_{y}.json"
        if out.exists() and out.stat().st_size > 1000:
            print(f"  {y}: cached ({out.stat().st_size//1024} KB)")
            continue
        r = requests.get(API, params={"index": "equities",
                                      "from_date": f"01-01-{y}", "to_date": f"31-12-{y}",
                                      "symbol": ""}, headers=HEADERS, timeout=60)
        if r.status_code != 200:
            print(f"  {y}: HTTP {r.status_code} — skipped")
            time.sleep(sleep)
            continue
        out.write_bytes(r.content)
        n = len(r.json().get("data", []))
        print(f"  {y}: {n:>6} rows, {len(r.content)//1024} KB -> {out.name}")
        time.sleep(sleep)


# --------------------------------------------------------------------------- #
# 2. CLEAN
# --------------------------------------------------------------------------- #
NUM = ["secAcq", "secVal", "buyValue", "sellValue", "buyQuantity", "sellquantity",
       "afterAcqSharesNo", "befAcqSharesNo"]


def _num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s.astype(str).str.replace(",", "", regex=False), errors="coerce")


def clean() -> pd.DataFrame:
    rows = []
    for f in sorted(RAW.glob("pit_*.json")):
        rows += json.loads(f.read_text()).get("data", [])
    df = pd.DataFrame(rows)
    if df.empty:
        raise SystemExit("no raw data — run --fetch first")

    df["trade_date"] = pd.to_datetime(df["acqfromDt"], format="%d-%b-%Y", errors="coerce")
    df["trade_to"] = pd.to_datetime(df["acqtoDt"], format="%d-%b-%Y", errors="coerce")
    df["intim_date"] = pd.to_datetime(df["intimDt"], format="%d-%b-%Y", errors="coerce")
    df["disclose_ts"] = pd.to_datetime(df["date"], format="%d-%b-%Y %H:%M", errors="coerce")
    # NSE's feed has occasional century typos (e.g. trade date "22-Jul-1922" for
    # 2022). Where the trade date is implausible but the disclosure timestamp is
    # sane, fall back to the disclosure date (they are usually within days).
    plausible = df["trade_date"].between("2015-01-01",
                                         pd.Timestamp.today() + pd.Timedelta(1, unit="D"))
    df.loc[~plausible, "trade_date"] = df.loc[~plausible, "disclose_ts"].dt.normalize()
    for c in NUM:
        if c in df:
            df[c] = _num(df[c])
    df["value"] = df["secVal"]
    df["qty"] = df["secAcq"]
    df["side"] = df["tdpTransactionType"]
    df["is_buy"] = (df["side"] == "Buy") & (df["acqMode"] == "Market Purchase")
    df["is_equity"] = df["secType"].eq("Equity Shares")

    keep = ["symbol", "company", "acqName", "personCategory", "side", "acqMode",
            "trade_date", "trade_to", "intim_date", "disclose_ts", "qty", "value",
            "is_buy", "is_equity", "anex", "did"]
    df = df[[c for c in keep if c in df]].copy()
    df = df[df["symbol"].notna() & (df["symbol"].astype(str).str.strip() != "")]
    df = df.drop_duplicates(subset=["symbol", "acqName", "trade_date", "acqMode",
                                    "qty", "value"])
    df = df.sort_values("trade_date").reset_index(drop=True)
    DATA.mkdir(parents=True, exist_ok=True)
    df.to_csv(EVENTS, index=False)
    print(f"cleaned: {len(df):,} disclosures, {df['symbol'].nunique():,} symbols "
          f"-> {EVENTS}")
    return df


# --------------------------------------------------------------------------- #
# 3. SUMMARY / COMPARE
# --------------------------------------------------------------------------- #
def summary(df: pd.DataFrame) -> None:
    print("\n=== rows by year ===")
    print(df["trade_date"].dt.year.value_counts().sort_index().to_string())
    print("\n=== side ===")
    print(df["side"].value_counts().to_string())
    print("\n=== acquisition mode ===")
    print(df["acqMode"].value_counts().head(10).to_string())
    print("\n=== person category ===")
    print(df["personCategory"].value_counts().head(10).to_string())
    buys = df[df["is_buy"] & df["is_equity"]]
    print(f"\nmarket purchases (equity): {len(buys):,} across "
          f"{buys['symbol'].nunique():,} symbols")
    top = (buys.groupby("symbol")
           .agg(buys=("symbol", "size"), value=("value", "sum"))
           .sort_values("value", ascending=False).head(15))
    print("\n=== top symbols by total insider-buy value (₹) ===")
    print(top.to_string())


def forward_returns(df: pd.DataFrame, symbols: list[str], horizons=(5, 20, 60)) -> None:
    """Mean forward excess return after market-purchase events, measured from the
    DISCLOSURE date (the tradeable, point-in-time trigger), vs the broad Nifty.

    A trade-date version would be look-ahead (insider trade dates are not public
    until the disclosure). Coarse close-to-close first look, not a costed test."""
    import yfinance as yf
    bench = yf.download("^NSEI", start="2015-01-01", auto_adjust=True,
                        progress=False)["Close"]
    if isinstance(bench, pd.DataFrame):
        bench = bench.iloc[:, 0]
    bench = bench.dropna()
    print("\n=== forward EXCESS return after insider market purchases "
          "(from DISCLOSURE date, vs Nifty, gross) ===")
    print(f"{'symbol':12} {'n':>4} " + " ".join(f"{'h'+str(h):>8}" for h in horizons))
    for sym in symbols:
        ev = df[(df["is_buy"]) & (df["symbol"] == sym)]["disclose_ts"].dropna().unique()
        if not len(ev):
            continue
        px = yf.download(f"{sym}.NS", start="2015-01-01", auto_adjust=True,
                         progress=False)["Close"]
        if isinstance(px, pd.DataFrame):
            px = px.iloc[:, 0]
        px = px.dropna()
        if px.empty:
            continue
        cells = []
        for h in horizons:
            rets = []
            for d in pd.to_datetime(ev).normalize():
                pos = px.index.searchsorted(d)
                if pos + h < len(px):
                    r = px.iloc[pos + h] / px.iloc[pos] - 1
                    b = bench.reindex([px.index[pos], px.index[pos + h]]).dropna()
                    if len(b) == 2:
                        r -= (b.iloc[1] / b.iloc[0] - 1)
                    rets.append(r)
            cells.append(f"{np.mean(rets)*100:8.2f}" if rets else f"{'n/a':>8}")
        print(f"{sym:12} {len(ev):>4} " + " ".join(cells))


# --------------------------------------------------------------------------- #
# 4. PLOT
# --------------------------------------------------------------------------- #
def plot_symbol(sym: str, df: pd.DataFrame) -> None:
    import yfinance as yf
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    buys = df[(df["is_buy"]) & (df["is_equity"]) & (df["symbol"] == sym)].dropna(
        subset=["trade_date"])
    if buys.empty:
        return
    px = yf.download(f"{sym}.NS", start=str(buys["trade_date"].min().date()),
                     auto_adjust=True, progress=False)["Close"]
    if isinstance(px, pd.DataFrame):
        px = px.iloc[:, 0]
    px = px.dropna()
    if px.empty:
        print(f"  {sym}: no price data")
        return

    fig, ax = plt.subplots(figsize=(12, 5))
    ax.plot(px.index, px.values, color="#333", lw=1.0, label="close")
    cats = buys["personCategory"].fillna("-").unique()
    colors = plt.cm.tab10(np.linspace(0, 1, max(len(cats), 1)))
    for c, col in zip(cats, colors):
        sub = buys[buys["personCategory"].fillna("-") == c]
        sizes = np.clip(np.log10(sub["value"].fillna(1).clip(lower=1)) * 8, 6, 120)
        ax.scatter(sub["trade_date"], px.reindex(sub["trade_date"], method="nearest"),
                   s=sizes, color=col, alpha=0.7, edgecolor="white", linewidth=0.4,
                   label=f"{c} ({len(sub)})", zorder=3)
    ax.set_title(f"{sym} — insider market purchases (marker size ∝ ₹ value)")
    ax.set_ylabel("price (₹, adjusted)")
    ax.legend(fontsize=8, loc="upper left")
    ax.grid(alpha=0.25)
    fig.tight_layout()
    PLOTS.mkdir(parents=True, exist_ok=True)
    out = PLOTS / f"{sym}_insider_buys.png"
    fig.savefig(out, dpi=140)
    plt.close(fig)
    print(f"  plot -> {out.relative_to(HERE)}")


def _big_mask(ev: pd.DataFrame) -> pd.Series:
    """A 'big party' = promoter/promoter-group/director/KMP/immediate-relative, OR a
    transaction worth >= BIG_VALUE. Employee/ESOP trades are excluded (routine)."""
    cat = ev["personCategory"]
    by_cat = cat.isin(BIG_PARTY_CATS)
    by_val = (ev["value"] >= BIG_VALUE) & ~cat.isin(EMPLOYEE_CATS)
    return by_cat | by_val


def plot_signals(sym: str, df: pd.DataFrame) -> None:
    """Price line + LONG signals (big insider BUY) and SHORT signals (big insider
    SELL), marked on the day of the trade. Per the strategy: a big market purchase
    is a long signal, a big market sale is a short signal."""
    import yfinance as yf
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    ev = df[df["symbol"] == sym].dropna(subset=["trade_date"]).copy()
    if ev.empty:
        return
    big = _big_mask(ev)
    buys = ev[ev["is_buy"] & big]
    sells = ev[(ev["side"] == "Sell") & (ev["acqMode"] == "Market Sale") & big]
    if buys.empty and sells.empty:
        print(f"  {sym}: no big-party events")
        return

    start = str(ev["trade_date"].min().date())
    px = yf.download(f"{sym}.NS", start=start, auto_adjust=True, progress=False)["Close"]
    if isinstance(px, pd.DataFrame):
        px = px.iloc[:, 0]
    px = px.dropna()
    if px.empty:
        print(f"  {sym}: no price data")
        return

    fig, ax = plt.subplots(figsize=(13, 5.5))
    ax.plot(px.index, px.values, color="#333", lw=1.0, label="close", zorder=1)
    if not buys.empty:
        sz = np.clip(np.log10(buys["value"].clip(lower=1)) * 10, 20, 220)
        ax.scatter(buys["trade_date"], px.reindex(buys["trade_date"], method="nearest"),
                   marker="^", s=sz, color="#1a9850", edgecolor="white", linewidth=0.4,
                   label=f"LONG — big insider BUY ({len(buys)})", zorder=3)
    if not sells.empty:
        sz = np.clip(np.log10(sells["value"].clip(lower=1)) * 10, 20, 220)
        ax.scatter(sells["trade_date"], px.reindex(sells["trade_date"], method="nearest"),
                   marker="v", s=sz, color="#d73027", edgecolor="white", linewidth=0.4,
                   label=f"SHORT — big insider SELL ({len(sells)})", zorder=3)
    ax.set_title(f"{sym} — big-party insider signals  "
                 f"(marker size ∝ ₹ value; big = ≥₹1cr or promoter)")
    ax.set_ylabel("price (₹, adjusted)")
    ax.legend(fontsize=8, loc="upper left")
    ax.grid(alpha=0.25)
    fig.tight_layout()
    PLOTS.mkdir(parents=True, exist_ok=True)
    out = PLOTS / f"{sym}_signals.png"
    fig.savefig(out, dpi=140)
    plt.close(fig)
    print(f"  plot -> {out.relative_to(HERE)}")


def rsi(close: pd.Series, period: int = RSI_PERIOD) -> pd.Series:
    """Wilder RSI (no external TA library)."""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    ag = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    al = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = ag / al.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def plot_major_dips(sym: str, df: pd.DataFrame) -> None:
    """De-noised overlay: only MAJOR insiders (promoter/director/KMP), only size
    trades (>= MIN_VALUE), and only in an RSI dip for longs (RSI < RSI_DIP) /
    overbought for shorts (RSI > RSI_PEAK). Writes plots/major_dips/<sym>.png."""
    import yfinance as yf
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    ev = df[df["symbol"] == sym].dropna(subset=["trade_date"]).copy()
    ev = ev[ev["personCategory"].isin(MAJOR_CATS) & (ev["value"] >= MIN_VALUE)]
    if ev.empty:
        print(f"  {sym}: no major size events")
        return
    buys = ev[ev["is_buy"]]
    sells = ev[(ev["side"] == "Sell") & (ev["acqMode"] == "Market Sale")]
    if buys.empty and sells.empty:
        print(f"  {sym}: no major size buy/sell")
        return

    px = yf.download(f"{sym}.NS", start=str(ev["trade_date"].min().date()),
                     auto_adjust=True, progress=False)["Close"]
    if isinstance(px, pd.DataFrame):
        px = px.iloc[:, 0]
    px = px.dropna()
    if px.empty:
        print(f"  {sym}: no price data")
        return
    r = rsi(px)

    def rsi_at(d):
        pos = r.index.searchsorted(pd.Timestamp(d))
        return float(r.iloc[min(pos, len(r) - 1)]) if len(r) else np.nan

    buys = buys.assign(rsi=buys["trade_date"].map(rsi_at))
    sells = sells.assign(rsi=sells["trade_date"].map(rsi_at))
    longs = buys[buys["rsi"] < RSI_DIP]
    shorts = sells[sells["rsi"] > RSI_PEAK]

    fig, (ax, ax2) = plt.subplots(2, 1, figsize=(13, 7.5), sharex=True,
                                  gridspec_kw={"height_ratios": [3, 1]})
    ax.plot(px.index, px.values, color="#333", lw=1.0, zorder=1)
    if not longs.empty:
        sz = np.clip(np.log10(longs["value"].clip(lower=1)) * 12, 30, 260)
        ax.scatter(longs["trade_date"],
                   px.reindex(longs["trade_date"], method="nearest"),
                   marker="^", s=sz, color="#1a9850", edgecolor="white", lw=0.4,
                   label=f"LONG — major buy in RSI dip ({len(longs)})", zorder=3)
    if not shorts.empty:
        sz = np.clip(np.log10(shorts["value"].clip(lower=1)) * 12, 30, 260)
        ax.scatter(shorts["trade_date"],
                   px.reindex(shorts["trade_date"], method="nearest"),
                   marker="v", s=sz, color="#d73027", edgecolor="white", lw=0.4,
                   label=f"SHORT — major sell overbought ({len(shorts)})", zorder=3)
    ax.set_title(f"{sym} — major insider signals in RSI dips  "
                 f"(major = promoter/director/KMP; size ≥ ₹1cr; marker ∝ ₹)")
    ax.set_ylabel("price (₹, adj)")
    ax.legend(fontsize=8, loc="upper left")
    ax.grid(alpha=0.25)
    ax2.plot(r.index, r.values, color="#555", lw=0.8)
    ax2.axhline(RSI_DIP, color="#1a9850", ls="--", lw=0.8)
    ax2.axhline(RSI_PEAK, color="#d73027", ls="--", lw=0.8)
    ax2.set_ylim(0, 100)
    ax2.set_ylabel(f"RSI({RSI_PERIOD})")
    ax2.grid(alpha=0.25)
    fig.tight_layout()
    out = PLOTS / "major_dips" / f"{sym}.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=140)
    plt.close(fig)
    print(f"  plot -> {out.relative_to(HERE)}")


def plot_overview(df: pd.DataFrame) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 3, figsize=(16, 4.5))
    yr = df["trade_date"].dt.year.value_counts().sort_index()
    axes[0].bar(yr.index.astype(str), yr.values, color="#4d6475")
    axes[0].set(title="Disclosures per year", ylabel="count")
    axes[0].tick_params(axis="x", rotation=45)
    side = df["side"].value_counts().head(6)
    axes[1].bar(side.index, side.values, color="#8b3a3a")
    axes[1].set(title="By transaction type")
    axes[1].tick_params(axis="x", rotation=30)
    buys = df[df["is_buy"]]
    cat = buys["personCategory"].value_counts().head(6)
    axes[2].bar(cat.index, cat.values, color="#2f6f4f")
    axes[2].set(title="Market purchases by person type")
    axes[2].tick_params(axis="x", rotation=30)
    for a in axes:
        a.grid(alpha=0.22, axis="y")
    fig.suptitle("India insider (PIT) disclosures — NSE, 2015–2026")
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    PLOTS.mkdir(parents=True, exist_ok=True)
    fig.savefig(PLOTS / "overview.png", dpi=140)
    plt.close(fig)
    print(f"  plot -> {(PLOTS / 'overview.png').relative_to(HERE)}")


# --------------------------------------------------------------------------- #
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--clean", action="store_true")
    ap.add_argument("--summary", action="store_true")
    ap.add_argument("--plot-top", type=int, default=0,
                    help="plot the N symbols with the most insider buys")
    ap.add_argument("--plot", metavar="SYMBOL", action="append", default=[])
    ap.add_argument("--signals", metavar="SYMBOL", action="append", default=[],
                    help="plot big-party LONG/SHORT signals for SYMBOL")
    ap.add_argument("--signals-top", type=int, default=0,
                    help="plot the N symbols with the most big-party events")
    ap.add_argument("--major", metavar="SYMBOL", action="append", default=[],
                    help="plot de-noised major-insider RSI-dip signals for SYMBOL")
    ap.add_argument("--major-top", type=int, default=0,
                    help="plot the N symbols with the most major size events")
    ap.add_argument("--fwd", action="store_true", help="forward-return comparison")
    ap.add_argument("--all", action="store_true", help="fetch+clean+summary+plot-top 6")
    a = ap.parse_args(argv)

    if a.fetch or a.all:
        fetch_years(YEARS)
    if a.clean or a.all:
        df = clean()
    if not (a.clean or a.all) and (a.summary or a.plot_top or a.plot or a.fwd
                                   or a.signals or a.signals_top
                                   or a.major or a.major_top):
        df = pd.read_csv(EVENTS, parse_dates=["trade_date"])
    if a.summary or a.all:
        summary(df)
    if a.plot_top or a.all:
        n = a.plot_top or 6
        buys = df[df["is_buy"] & df["is_equity"]]
        top = (buys.groupby("symbol").size().sort_values(ascending=False)
               .head(n).index.tolist())
        print(f"\nplotting top {n}: {top}")
        plot_overview(df)
        for s in top:
            plot_symbol(s, df)
    for s in a.plot:
        plot_symbol(s, df)
    for s in a.signals:
        plot_signals(s, df)
    if a.signals_top:
        ev = df[df["is_buy"] | ((df["side"] == "Sell") & (df["acqMode"] == "Market Sale"))]
        ev = ev[_big_mask(ev)]
        top = (ev.groupby("symbol").size().sort_values(ascending=False)
               .head(a.signals_top).index.tolist())
        print(f"\nbig-party signal plots (top {a.signals_top}): {top}")
        for s in top:
            plot_signals(s, df)
    for s in a.major:
        plot_major_dips(s, df)
    if a.major_top:
        me = df[df["personCategory"].isin(MAJOR_CATS) & (df["value"] >= MIN_VALUE)]
        top = (me.groupby("symbol").size().sort_values(ascending=False)
               .head(a.major_top).index.tolist())
        print(f"\nmajor-dip plots (top {a.major_top}): {top}")
        for s in top:
            plot_major_dips(s, df)
    if a.signals_top:
        ev = df[df["is_buy"] | ((df["side"] == "Sell") & (df["acqMode"] == "Market Sale"))]
        ev = ev[_big_mask(ev)]
        top = (ev.groupby("symbol").size().sort_values(ascending=False)
               .head(a.signals_top).index.tolist())
        print(f"\nbig-party signal plots (top {a.signals_top}): {top}")
        for s in top:
            plot_signals(s, df)
    if a.fwd:
        buys = df[df["is_buy"] & df["is_equity"]]
        top = buys.groupby("symbol").size().sort_values(ascending=False).head(10).index
        forward_returns(df, list(top))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
