#!/usr/bin/env python3
"""Faithful implementation of the requested insider -> momentum strategy.

Unlike ``optimize_momentum.py``, this script does not optimize the insider
threshold, impose a short confirmation window, substitute a trailing exit, or
force an annual portfolio trade count.

State machine, independently for each stock:

1. A public disclosure of a >= Rs 25 lakh *Market Purchase* by a promoter,
   promoter group, director, or KMP arms the stock.  The watch does not expire.
2. Wait for price to rise at least 10% from the disclosure close and close at a
   new 252-session high, with close > EMA50 > EMA200.
3. Buy the next open.
4. Hold through ordinary dips.  Sell next open only after close <= EMA50 or a
   10% close-confirmed hard stop.  Cap the trade at 126 sessions.
5. A new insider purchase after the entry is required to arm another trade.

Prices are adjusted Yahoo Finance OHLC.  The high, rather than the close, is
used to define the prior high.  Results include 27 bp round-trip delivery
charges; historical bid/ask spread is unavailable and therefore excluded.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf


HERE = Path(__file__).resolve().parent
EVENTS = HERE / "data" / "events.csv"
PRICE_DIR = HERE / "data" / "faithful_prices"
RESULT_DIR = HERE / "data" / "faithful_momentum"
PLOT_DIR = HERE / "plots" / "faithful_momentum"

BASKET = tuple((
    "ADANIPORTS,CHAMBLFERT,MAHSEAMLES,JSWSTEEL,GRASIM,GODREJAGRO,GODREJIND,"
    "APOLLOTYRE,DBCORP,STEL,NCLIND,NRBBEARING,NCC,MANINFRA,APLLTD,JSL,"
    "SURYAROSNI,BAJAJHLDNG,TFCILTD,KRISHANA"
).split(","))
MAJOR = {"Promoters", "Promoter Group", "Director", "Key Managerial Personnel"}

MIN_VALUE = 2_500_000.0
MIN_RISE = 0.10
HIGH_LOOKBACK = 252
STOP = 0.10
MAX_HOLD = 126
COST_RT = 0.0027
RANDOM_TRIALS = 250
RANDOM_SEED = 20261013


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, min_periods=period,
                                   adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, min_periods=period,
                                      adjust=False).mean()
    return 100 - 100 / (1 + gain / loss.replace(0, np.nan))


def load_events() -> pd.DataFrame:
    frame = pd.read_csv(EVENTS, parse_dates=["trade_date", "disclose_ts"])
    mask = (
        frame.personCategory.isin(MAJOR)
        & frame.is_buy
        & frame.is_equity
        & frame.acqMode.eq("Market Purchase")
        & frame.value.ge(MIN_VALUE)
        & frame.symbol.isin(BASKET)
        & frame.disclose_ts.notna()
    )
    frame = frame.loc[mask].copy()
    frame["disclosure_date"] = frame.disclose_ts.dt.normalize()
    # Multiple filings for the same stock/day are one piece of public information.
    frame = (frame.sort_values(["symbol", "disclosure_date", "value"])
             .groupby(["symbol", "disclosure_date"], as_index=False)
             .agg(value=("value", "sum"), trade_date=("trade_date", "min"),
                  acqName=("acqName", "first")))
    return frame


def download_prices() -> tuple[dict[str, pd.DataFrame], list[dict]]:
    PRICE_DIR.mkdir(parents=True, exist_ok=True)
    prices: dict[str, pd.DataFrame] = {}
    audit: list[dict] = []
    for symbol in BASKET:
        path = PRICE_DIR / f"{symbol}.csv"
        if not path.exists():
            raw = yf.download(f"{symbol}.NS", start="2010-01-01", auto_adjust=True,
                              progress=False, threads=False)
            if raw.empty:
                audit.append({"symbol": symbol, "status": "download_failed"})
                continue
            if isinstance(raw.columns, pd.MultiIndex):
                raw.columns = raw.columns.get_level_values(0)
            raw = raw.reset_index()
            raw.columns = [str(column).lower() for column in raw.columns]
            needed = ["date", "open", "high", "low", "close"]
            if not set(needed).issubset(raw.columns):
                audit.append({"symbol": symbol, "status": "missing_ohlc"})
                continue
            raw[needed].to_csv(path, index=False)
        px = (pd.read_csv(path, parse_dates=["date"]).set_index("date")
              .sort_index()[["open", "high", "low", "close"]].dropna())
        cached = HERE / "data" / "bt_prices" / f"{symbol}.csv"
        cross_median = np.nan
        cross_p95 = np.nan
        if cached.exists():
            old = pd.read_csv(cached, parse_dates=["date"]).set_index("date")
            joined = px[["close"]].join(old[["close"]], lsuffix="_fresh",
                                         rsuffix="_cached", how="inner")
            if len(joined):
                diff = (joined.close_fresh / joined.close_cached - 1).abs()
                cross_median = float(diff.median())
                cross_p95 = float(diff.quantile(0.95))
        audit.append({"symbol": symbol, "status": "ok", "rows": len(px),
                      "start": str(px.index.min().date()),
                      "end": str(px.index.max().date()),
                      "cached_close_abs_diff_median": cross_median,
                      "cached_close_abs_diff_p95": cross_p95})
        prices[symbol] = px
    return prices, audit


def simulate_symbol(symbol: str, events: pd.DataFrame,
                    px: pd.DataFrame) -> pd.DataFrame:
    """Run the persistent-watch state machine for one stock."""
    symbol_events = (events.loc[events.symbol.eq(symbol)]
                     .sort_values("disclosure_date").reset_index(drop=True))
    if symbol_events.empty or len(px) <= HIGH_LOOKBACK + 2:
        return pd.DataFrame()

    idx = px.index
    close = px.close.to_numpy(float)
    open_ = px.open.to_numpy(float)
    ema50 = px.close.ewm(span=50, adjust=False).mean().to_numpy(float)
    ema200 = px.close.ewm(span=200, adjust=False).mean().to_numpy(float)
    # Yesterday's rolling maximum of true intraday highs: today's close must
    # actually clear the level that existed before today's session.
    prior_high = px.high.rolling(HIGH_LOOKBACK).max().shift(1).to_numpy(float)

    trades: list[dict] = []
    event_pointer = 0
    earliest_search_i = HIGH_LOOKBACK
    while event_pointer < len(symbol_events):
        event = symbol_events.iloc[event_pointer]
        disclosure_i = int(idx.searchsorted(event.disclosure_date))
        if disclosure_i >= len(idx) - 2:
            break
        search_i = max(disclosure_i, earliest_search_i, HIGH_LOOKBACK)
        reference = float(close[disclosure_i])
        if not np.isfinite(reference) or reference <= 0:
            event_pointer += 1
            continue

        signal_i = None
        for i in range(search_i, len(idx) - 1):
            if (np.isfinite(prior_high[i])
                    and close[i] > prior_high[i]
                    and close[i] >= reference * (1 + MIN_RISE)
                    and close[i] > ema50[i] > ema200[i]):
                signal_i = i
                break
        if signal_i is None:
            break  # the persistent watch remained armed through the data end

        entry_i = signal_i + 1
        entry_price = float(open_[entry_i])
        if not np.isfinite(entry_price) or entry_price <= 0:
            earliest_search_i = entry_i + 1
            continue

        exit_i = min(entry_i + MAX_HOLD, len(idx) - 1)
        exit_reason = "six_month_cap"
        for i in range(entry_i, min(entry_i + MAX_HOLD, len(idx) - 1)):
            if close[i] <= entry_price * (1 - STOP):
                exit_i = i + 1
                exit_reason = "hard_stop_close"
                break
            if close[i] <= ema50[i]:
                exit_i = i + 1
                exit_reason = "ema50_close"
                break
        exit_price = float(open_[exit_i])
        gross = exit_price / entry_price - 1
        trades.append({
            "symbol": symbol,
            "disclosure_date": event.disclosure_date,
            "insider_trade_date": event.trade_date,
            "event_value": float(event.value),
            "reference": reference,
            "signal_date": idx[signal_i],
            "prior_high": float(prior_high[signal_i]),
            "achieved_rise": float(close[signal_i] / reference - 1),
            "entry_i": entry_i,
            "entry_date": idx[entry_i],
            "entry_price": entry_price,
            "exit_i": exit_i,
            "exit_date": idx[exit_i],
            "exit_price": exit_price,
            "exit_reason": exit_reason,
            "hold_sessions": int(exit_i - entry_i),
            "gross": gross,
            "net": gross - COST_RT,
        })

        # The disclosure that armed this entry, and every disclosure known by
        # entry time, has now been consumed.  A later purchase can arm the stock
        # again, including one made while this position is open.
        while (event_pointer < len(symbol_events)
               and symbol_events.iloc[event_pointer].disclosure_date <= idx[entry_i]):
            event_pointer += 1
        earliest_search_i = exit_i + 1

    return pd.DataFrame(trades)


def sleeve_returns(trades: pd.DataFrame, prices: dict[str, pd.DataFrame],
                   start: pd.Timestamp, end: pd.Timestamp) -> pd.Series:
    parts = []
    for symbol, px in prices.items():
        ret = pd.Series(0.0, index=px.index[(px.index >= start) & (px.index <= end)])
        selected = trades[(trades.symbol == symbol)
                          & (trades.entry_date >= start) & (trades.entry_date <= end)]
        for trade in selected.itertuples():
            ei, xi = int(trade.entry_i), int(trade.exit_i)
            dates = px.index[ei:xi + 1]
            dates = dates[(dates >= start) & (dates <= end)]
            if not len(dates):
                continue
            ret.loc[px.index[ei]] += px.close.iloc[ei] / trade.entry_price - 1 - COST_RT / 2
            for i in range(ei + 1, xi):
                if px.index[i] in ret.index:
                    ret.loc[px.index[i]] += px.close.iloc[i] / px.close.iloc[i - 1] - 1
            if px.index[xi] in ret.index:
                ret.loc[px.index[xi]] += trade.exit_price / px.close.iloc[xi - 1] - 1 - COST_RT / 2
        parts.append(ret.rename(symbol))
    return pd.concat(parts, axis=1).fillna(0).mean(axis=1).sort_index()


def metrics(trades: pd.DataFrame, daily: pd.Series,
            start: pd.Timestamp, end: pd.Timestamp) -> dict:
    years = max((end - start).days / 365.25, 1 / 365.25)
    equity = (1 + daily).cumprod()
    sd = daily.std(ddof=1)
    dd = float((equity / equity.cummax() - 1).min()) if len(equity) else np.nan
    cagr = float(equity.iloc[-1] ** (1 / years) - 1) if len(equity) else np.nan
    values = trades.net.to_numpy(float) if len(trades) else np.array([])
    se = float(values.std(ddof=1) / math.sqrt(len(values))) if len(values) > 1 else np.nan
    return {
        "period_start": str(start.date()), "period_end": str(end.date()),
        "trades": int(len(trades)), "trades_per_year_total": len(trades) / years,
        "trades_per_stock_year": len(trades) / years / max(len(BASKET), 1),
        "win_rate": float((values > 0).mean()) if len(values) else np.nan,
        "mean_net": float(values.mean()) if len(values) else np.nan,
        "median_net": float(np.median(values)) if len(values) else np.nan,
        "mean_net_se": se,
        "cagr_equal_weight_sleeves": cagr,
        "sharpe_equal_weight_sleeves": float(daily.mean() / sd * math.sqrt(252))
        if np.isfinite(sd) and sd > 0 else np.nan,
        "max_drawdown_equal_weight_sleeves": dd,
        "calmar_equal_weight_sleeves": cagr / abs(dd) if dd < 0 else np.nan,
        "breakeven_cost_bp_mean_gross": float(trades.gross.mean() * 1e4)
        if len(trades) else np.nan,
    }


def randomized_event_calendar(events: pd.DataFrame,
                              prices: dict[str, pd.DataFrame],
                              rng: np.random.Generator) -> pd.DataFrame:
    """Replace disclosures with random trading dates, count-matched by stock."""
    rows = []
    for symbol, group in events.groupby("symbol"):
        px = prices.get(symbol)
        if px is None or len(px) <= HIGH_LOOKBACK + 2:
            continue
        eligible = px.index[HIGH_LOOKBACK:-2]
        chosen = np.sort(rng.choice(eligible.to_numpy(), size=len(group),
                                    replace=len(group) > len(eligible)))
        for date, source in zip(chosen, group.itertuples()):
            timestamp = pd.Timestamp(date)
            rows.append({"symbol": symbol, "disclosure_date": timestamp,
                         "trade_date": timestamp, "value": float(source.value),
                         "acqName": "matched random catalyst"})
    return pd.DataFrame(rows)


def matched_random_control(events: pd.DataFrame, prices: dict[str, pd.DataFrame],
                           split_date: pd.Timestamp, end: pd.Timestamp,
                           observed_test: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    rng = np.random.default_rng(RANDOM_SEED)
    rows = []
    for trial in range(RANDOM_TRIALS):
        pseudo = randomized_event_calendar(events, prices, rng)
        parts = [simulate_symbol(symbol, pseudo, px) for symbol, px in prices.items()]
        parts = [part for part in parts if not part.empty]
        trial_trades = (pd.concat(parts, ignore_index=True) if parts
                        else pd.DataFrame(columns=["entry_date", "net", "gross"]))
        test = trial_trades[trial_trades.entry_date >= split_date]
        rows.append({
            "trial": trial,
            "test_trades": int(len(test)),
            "test_mean_net": float(test.net.mean()) if len(test) else np.nan,
            "test_median_net": float(test.net.median()) if len(test) else np.nan,
            "test_win_rate": float((test.net > 0).mean()) if len(test) else np.nan,
        })
    control = pd.DataFrame(rows)
    observed_mean = float(observed_test.net.mean())
    observed_median = float(observed_test.net.median())
    comparison = {
        "trials": RANDOM_TRIALS,
        "matched_by": "same number of catalyst dates per stock",
        "observed_test_mean_net": observed_mean,
        "random_median_test_mean_net": float(control.test_mean_net.median()),
        "p_random_mean_ge_observed": float((control.test_mean_net >= observed_mean).mean()),
        "observed_test_median_net": observed_median,
        "random_median_test_median_net": float(control.test_median_net.median()),
        "p_random_median_ge_observed": float((control.test_median_net >= observed_median).mean()),
    }
    return control, comparison


def plot_symbol(symbol: str, trades: pd.DataFrame, events: pd.DataFrame,
                px: pd.DataFrame, split_date: pd.Timestamp) -> None:
    ema50 = px.close.ewm(span=50, adjust=False).mean()
    ema200 = px.close.ewm(span=200, adjust=False).mean()
    fig, (ax, ax2) = plt.subplots(2, 1, figsize=(15, 8.5), sharex=True,
                                  gridspec_kw={"height_ratios": [3, 1]})
    ax.plot(px.index, px.close, color="#333", lw=0.85, label="close")
    ax.plot(px.index, ema50, color="#3b73b9", lw=1.0, label="EMA50")
    ax.plot(px.index, ema200, color="#91651c", lw=1.0, label="EMA200")
    symbol_events = events[events.symbol.eq(symbol)]
    event_y = px.close.reindex(symbol_events.disclosure_date, method="nearest")
    ax.scatter(symbol_events.disclosure_date, event_y, s=20, color="#9ecae1",
               alpha=0.55, label="qualifying insider purchase", zorder=3)
    if len(trades):
        ax.scatter(trades.disclosure_date, trades.reference, marker="D", s=50,
                   color="#fdae61", edgecolor="white", lw=0.5,
                   label="watch armed", zorder=5)
        ax.scatter(trades.entry_date, trades.entry_price, marker="^", s=115,
                   color="#17964b", edgecolor="white", lw=0.5,
                   label="buy next open", zorder=6)
        ax.scatter(trades.exit_date, trades.exit_price, marker="x", s=75,
                   color="#d62728", lw=1.5, label="sell next open", zorder=6)
        for trade in trades.itertuples():
            ax.hlines(trade.reference * (1 + MIN_RISE), trade.disclosure_date,
                      trade.signal_date, color="#8e3a9c", ls="--", lw=1.0,
                      alpha=0.7)
    ax.axvline(split_date, color="black", ls=":", lw=1.1, label="70/30 split")
    ax.set_title(f"{symbol} — persistent insider watch, 52-week-high momentum ({len(trades)} trades)")
    ax.legend(fontsize=8, loc="best", ncol=2)
    ax.grid(alpha=0.22)
    indicator = rsi(px.close)
    ax2.plot(px.index, indicator, color="#555", lw=0.85)
    ax2.axhline(70, color="#d62728", ls="--", lw=0.7)
    ax2.axhline(30, color="#17964b", ls="--", lw=0.7)
    ax2.set_ylim(0, 100); ax2.set_ylabel("RSI14"); ax2.grid(alpha=0.22)
    fig.tight_layout(); fig.savefig(PLOT_DIR / f"{symbol}.png", dpi=150); plt.close(fig)


def plot_audit(trades: pd.DataFrame, daily: pd.Series,
               split_date: pd.Timestamp, test_stats: dict,
               random_control: pd.DataFrame) -> None:
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    equity = (1 + daily).cumprod()
    axes[0, 0].plot(equity.index, equity, color="#263f5c")
    axes[0, 0].axvline(split_date, color="#b3261e", ls="--")
    axes[0, 0].set_title("Equal-weight stock sleeves (27 bp charges; spread excluded)")
    axes[0, 0].set_ylabel("Growth of Rs 1"); axes[0, 0].grid(alpha=0.25)

    by_year = trades.assign(year=trades.entry_date.dt.year).groupby("year").size()
    axes[0, 1].bar(by_year.index.astype(str), by_year.values, color="#5f8fb8")
    axes[0, 1].set_title("Natural trade frequency — no imposed annual cap")
    axes[0, 1].tick_params(axis="x", rotation=45); axes[0, 1].grid(axis="y", alpha=0.25)

    axes[1, 0].hist(trades.net * 100, bins=18, color="#9ecae1", edgecolor="white")
    axes[1, 0].axvline(0, color="black", lw=0.8)
    axes[1, 0].set_title("Trade returns after 27 bp charges")
    axes[1, 0].set_xlabel("Net return (%)"); axes[1, 0].grid(alpha=0.25)

    axes[1, 1].hist(random_control.test_mean_net.dropna() * 100, bins=22,
                    color="#9ecae1", edgecolor="white", label="matched random catalysts")
    axes[1, 1].axvline(test_stats["mean_net"] * 100, color="#b3261e", lw=2,
                       label="actual insider catalysts")
    axes[1, 1].set_title("Untouched-test mean trade return: insider vs random")
    axes[1, 1].set_xlabel("Mean net return (%)")
    axes[1, 1].legend(fontsize=8); axes[1, 1].grid(alpha=0.25)
    fig.suptitle(
        f"Faithful insider-momentum rules | untouched test: {test_stats['trades']} trades, "
        f"median {test_stats['median_net']:.1%}", fontsize=14)
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    fig.savefig(PLOT_DIR / "audit.png", dpi=150); plt.close(fig)


def main() -> None:
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    PLOT_DIR.mkdir(parents=True, exist_ok=True)
    events = load_events()
    prices, audit = download_prices()
    trade_parts = [simulate_symbol(symbol, events, px) for symbol, px in prices.items()]
    trade_parts = [part for part in trade_parts if not part.empty]
    if not trade_parts:
        raise RuntimeError("No trades produced")
    trades = pd.concat(trade_parts, ignore_index=True).sort_values("entry_date")

    all_dates = sorted(set().union(*(set(px.index) for px in prices.values())))
    start = max(events.disclosure_date.min(), pd.Timestamp(all_dates[0]))
    end = pd.Timestamp(all_dates[-1])
    reference = prices["ADANIPORTS"].index[prices["ADANIPORTS"].index >= start]
    split_date = reference[int(0.70 * len(reference))]
    daily = sleeve_returns(trades, prices, start, end)
    train_trades = trades[trades.entry_date < split_date]
    test_trades = trades[trades.entry_date >= split_date]
    train_daily = daily[(daily.index >= start) & (daily.index < split_date)]
    test_daily = daily[daily.index >= split_date]
    full_stats = metrics(trades, daily, start, end)
    train_stats = metrics(train_trades, train_daily, start, split_date - pd.Timedelta(days=1))
    test_stats = metrics(test_trades, test_daily, split_date, end)
    control, control_stats = matched_random_control(events, prices, split_date,
                                                     end, test_trades)

    summary = {
        "interpretation": "persistent watch; frequency generated naturally per stock",
        "rules": {"minimum_market_purchase_rupees": MIN_VALUE,
                  "minimum_rise_from_disclosure": MIN_RISE,
                  "prior_high_sessions": HIGH_LOOKBACK,
                  "trend": "close > EMA50 > EMA200",
                  "entry": "next open", "hard_stop": STOP,
                  "trend_exit": "close <= EMA50, then next open",
                  "maximum_hold_sessions": MAX_HOLD,
                  "round_trip_charge_bp": COST_RT * 1e4,
                  "bid_ask_spread": "not measured"},
        "data": {"source": "Yahoo Finance adjusted OHLC",
                 "symbols_requested": list(BASKET), "symbols_priced": list(prices),
                 "survivorship_bias": "current-symbol basket; unresolved"},
        "split": {"method": "chronological 70/30; parameters fixed, not optimized",
                  "date": str(split_date.date())},
        "full": full_stats, "train": train_stats, "test": test_stats,
        "matched_random_control": control_stats,
        "caveats": [
            "Historical bid/ask spread is unavailable.",
            "The hard stop is close-confirmed and executes next open because intraday stop data are not modeled.",
            "The basket uses current tickers and therefore has survivorship bias.",
        ],
    }
    trades.to_csv(RESULT_DIR / "trades.csv", index=False)
    control.to_csv(RESULT_DIR / "random_control.csv", index=False)
    pd.DataFrame(audit).to_csv(RESULT_DIR / "data_audit.csv", index=False)
    (RESULT_DIR / "summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n")
    for symbol, group in trades.groupby("symbol"):
        plot_symbol(symbol, group, events, prices[symbol], split_date)
    plot_audit(trades, daily, split_date, test_stats, control)
    print(json.dumps(summary, indent=2, allow_nan=False))
    print(f"plots -> {PLOT_DIR}")


if __name__ == "__main__":
    main()
