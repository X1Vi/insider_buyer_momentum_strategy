#!/usr/bin/env python3
"""Honest 70/30 optimization of the insider-gated momentum strategy.

The search is intentionally small and interpretable.  Parameters are selected
on the first 70% of history only; the final 30% is untouched until the robust
training cluster is locked.  The portfolio is long-only, holds one cash stock
at a time, and takes at most two entries per calendar year.

Important limitations:
* cached prices contain only adjusted open/close, so "highest high" means the
  highest close and stops are close-confirmed for next-open execution;
* current tickers only: delisted-name survivorship remains;
* 27 bp delivery charges are included, but historical bid/ask spreads are not;
* a 75 bp total-cost stress is also reported, but is not a spread measurement.
"""
from __future__ import annotations

import json
import math
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.stats import kurtosis, norm, skew, t as student_t, ttest_1samp

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "volume_indicator_studies" / "perform_operations"))
from india_data import detect_and_repair_splits  # noqa: E402

EVENTS = HERE / "data" / "events.csv"
PRICES = HERE / "data" / "bt_prices"
OUT = HERE / "plots" / "momentum_optimized"
RESULTS = HERE / "data" / "momentum_optimized"

BASKET = tuple((
    "ADANIPORTS,CHAMBLFERT,MAHSEAMLES,JSWSTEEL,GRASIM,GODREJAGRO,GODREJIND,"
    "APOLLOTYRE,DBCORP,STEL,NCLIND,NRBBEARING,NCC,MANINFRA,APLLTD,JSL,"
    "SURYAROSNI,BAJAJHLDNG,TFCILTD,KRISHANA"
).split(","))
MAJOR = {"Promoters", "Promoter Group", "Director", "Key Managerial Personnel"}

CHARGE_RT = 0.0027       # 27 bp India delivery reference in repo AGENTS.md
STRESS_COST_RT = 0.0075  # sensitivity only; not a measured spread
STOP = 0.10
MAX_HOLD = 126           # about six trading months
EPISODE_GAP_DAYS = 30
ANNUAL_ENTRY_CAP = 2
RANDOM_TRIALS = 250
SEED = 20261013
ALPHA = 0.05

MIN_VALUES = (2.5e6, 1e7, 5e7)
WATCHES = (30, 60)
HIGH_LOOKBACKS = (20, 50)
MIN_RISES = (0.05, 0.10, 0.15)
MAX_RISES = (0.30, 0.50)
EXIT_RULES = ("ema50", "trail10", "trail15")


@dataclass(frozen=True)
class Config:
    min_value: float
    watch: int
    high_n: int
    min_rise: float
    max_rise: float
    exit_rule: str


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, min_periods=period,
                                   adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, min_periods=period,
                                      adjust=False).mean()
    return 100 - 100 / (1 + gain / loss.replace(0, np.nan))


def load_inputs():
    events = pd.read_csv(EVENTS, parse_dates=["trade_date", "disclose_ts"])
    events = events[
        events.personCategory.isin(MAJOR) & events.is_buy & events.is_equity &
        events.symbol.isin(BASKET) & events.disclose_ts.notna()
    ].copy()
    events["d"] = events.disclose_ts.dt.normalize()

    prices: dict[str, pd.DataFrame] = {}
    audit: list[dict] = []
    for symbol in BASKET:
        path = PRICES / f"{symbol}.csv"
        if not path.exists():
            audit.append(dict(check="missing_price", symbol=symbol))
            continue
        frame = pd.read_csv(path, parse_dates=["date"]).set_index("date").sort_index()
        frame = frame.loc[~frame.index.duplicated(keep="last"), ["open", "close"]]
        raw_open, raw_close = frame.open.copy(), frame.close.copy()
        repaired_close, _, close_repairs = detect_and_repair_splits(frame.close)
        repaired_open, _, open_repairs = detect_and_repair_splits(frame.open)
        for field, repairs in (("close", close_repairs), ("open", open_repairs)):
            for repair in repairs:
                audit.append(dict(check="split_repair", symbol=symbol,
                                  field=field, **{k: str(v) for k, v in repair.items()}))
        close_dates = {pd.Timestamp(r["date"]) for r in close_repairs
                       if "repaired" in r["action"] or "reverse split" in r["action"]}
        open_dates = {pd.Timestamp(r["date"]) for r in open_repairs
                      if "repaired" in r["action"] or "reverse split" in r["action"]}
        candidate_dates = {pd.Timestamp(r["date"]) for r in close_repairs + open_repairs}
        if close_dates and close_dates == open_dates:
            # One close-derived scale must be applied to every price field.
            # Repairing open and close independently can manufacture returns.
            scale = repaired_close / raw_close
            frame["close"] = repaired_close
            frame["open"] = raw_open * scale
        elif candidate_dates:
            # An unresolved round-ratio mismatch is often a demerger, not a split
            # (JSL turned ex-JSHL on 2015-11-19).  Do not invent a rescaling;
            # conservatively discard the incomparable pre-action regime.
            trim_date = min(candidate_dates)
            frame = frame.loc[frame.index >= trim_date].copy()
            audit.append(dict(check="corporate_action_trim", symbol=symbol,
                              date=str(trim_date.date()),
                              reason="open/close split detectors disagreed; pre-action history removed"))
        else:
            frame["open"], frame["close"] = raw_open, raw_close
        remaining_jump = frame.close.pct_change(fill_method=None).abs().max()
        audit.append(dict(check="price_series", symbol=symbol, rows=len(frame),
                          start=str(frame.index.min().date()), end=str(frame.index.max().date()),
                          raw_open_changed=bool(not raw_open.equals(frame.open)),
                          raw_close_changed=bool(not raw_close.equals(frame.close)),
                          max_abs_close_return=float(remaining_jump)))
        prices[symbol] = frame.dropna()
    return events, prices, audit


def causal_events(events: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    q = events[events.value >= cfg.min_value].sort_values(["symbol", "d", "disclose_ts"])
    kept = []
    for _, group in q.groupby("symbol", sort=False):
        last = None
        for row in group.itertuples():
            if last is not None and (row.d - last).days < EPISODE_GAP_DAYS:
                continue
            kept.append(dict(symbol=row.symbol, d=row.d, value=float(row.value),
                             trade_date=row.trade_date, disclose_ts=row.disclose_ts))
            last = row.d
    return pd.DataFrame(kept)


def build_candidates(events: pd.DataFrame, prices: dict[str, pd.DataFrame],
                     cfg: Config, already_filtered: bool = False) -> pd.DataFrame:
    episode_events = events if already_filtered else causal_events(events, cfg)
    rows = []
    if episode_events.empty:
        return pd.DataFrame()
    for symbol, symbol_events in episode_events.groupby("symbol", sort=False):
        px = prices.get(symbol)
        if px is None or len(px) < 220:
            continue
        idx = px.index
        close = px.close.to_numpy(float)
        high = px.close.rolling(cfg.high_n).max().shift(1).to_numpy()
        ema50 = px.close.ewm(span=50, adjust=False).mean().to_numpy()
        ema200 = px.close.ewm(span=200, adjust=False).mean().to_numpy()
        for event in symbol_events.itertuples():
            start = int(idx.searchsorted(event.d))
            if start >= len(px) - 2:
                continue
            reference = close[start]
            if not np.isfinite(reference) or reference <= 0:
                continue
            signal_i = None
            for i in range(start, min(start + cfg.watch, len(px) - 1)):
                rise = close[i] / reference - 1
                slope_ok = i >= 20 and ema50[i] > ema50[i - 20]
                if (np.isfinite(high[i]) and close[i] > high[i] and
                        close[i] > ema50[i] > ema200[i] and slope_ok and
                        cfg.min_rise <= rise <= cfg.max_rise):
                    signal_i = i
                    break
            if signal_i is None:
                continue
            entry_i = signal_i + 1
            rows.append(dict(
                symbol=symbol, disclosure_date=idx[start],
                disclosed_at=event.disclose_ts, insider_trade_date=event.trade_date,
                event_value=float(event.value), reference=float(reference),
                rise_level=float(reference * (1 + cfg.min_rise)),
                signal_date=idx[signal_i], entry_date=idx[entry_i],
                signal_i=signal_i, entry_i=entry_i,
                achieved_rise=float(close[signal_i] / reference - 1),
            ))
    if not rows:
        return pd.DataFrame()
    out = pd.DataFrame(rows).sort_values(["entry_date", "event_value"], ascending=[True, False])
    return out.drop_duplicates(["symbol", "entry_date"], keep="first").reset_index(drop=True)


def determine_exit(candidate: pd.Series, px: pd.DataFrame, cfg: Config,
                   end: pd.Timestamp) -> dict | None:
    ei = int(candidate.entry_i)
    if ei >= len(px) or px.index[ei] > end:
        return None
    entry = float(px.open.iloc[ei])
    if not np.isfinite(entry) or entry <= 0:
        return None
    close = px.close.to_numpy(float)
    ema50 = px.close.ewm(span=50, adjust=False).mean().to_numpy()
    last_i = min(ei + MAX_HOLD, len(px) - 1, int(px.index.searchsorted(end, side="right") - 1))
    if last_i <= ei:
        return None
    peak = close[ei]
    trigger = "time"
    exit_i = last_i
    forced_close = False
    for i in range(ei, last_i):
        peak = max(peak, close[i])
        stop_hit = close[i] <= entry * (1 - STOP)
        if cfg.exit_rule == "ema50":
            trend_exit = close[i] < ema50[i]
        else:
            trail = 0.10 if cfg.exit_rule == "trail10" else 0.15
            trend_exit = close[i] <= peak * (1 - trail)
        if stop_hit or trend_exit:
            exit_i = i + 1  # close confirms; execute causally at next open
            trigger = "stop" if stop_hit else cfg.exit_rule
            break
    if px.index[exit_i] > end:
        valid = np.where(px.index <= end)[0]
        if not len(valid):
            return None
        exit_i = int(valid[-1])
        forced_close = True
    exit_price = float(px.close.iloc[exit_i] if forced_close else px.open.iloc[exit_i])
    gross = exit_price / entry - 1
    return dict(exit_i=exit_i, exit_date=px.index[exit_i], entry_price=entry,
                exit_price=exit_price, gross=gross, exit_reason=trigger,
                forced_at_boundary=forced_close)


def simulate(candidates: pd.DataFrame, prices: dict[str, pd.DataFrame], cfg: Config,
             start: pd.Timestamp, end: pd.Timestamp, cost: float) -> pd.DataFrame:
    if candidates.empty:
        return pd.DataFrame()
    q = candidates[(candidates.entry_date >= start) & (candidates.entry_date <= end)].copy()
    if q.empty:
        return pd.DataFrame()
    trades = []
    current_exit = pd.Timestamp.min
    entries_by_year: dict[int, int] = {}
    for entry_date, same_day in q.groupby("entry_date", sort=True):
        if entry_date < current_exit or entries_by_year.get(entry_date.year, 0) >= ANNUAL_ENTRY_CAP:
            continue
        # Highest disclosed transaction value is a causal, predeclared tie-breaker.
        candidate = same_day.sort_values("event_value", ascending=False).iloc[0]
        result = determine_exit(candidate, prices[candidate.symbol], cfg, end)
        if result is None:
            continue
        row = candidate.to_dict() | result
        row["net"] = row["gross"] - cost
        trades.append(row)
        current_exit = row["exit_date"]
        entries_by_year[entry_date.year] = entries_by_year.get(entry_date.year, 0) + 1
    return pd.DataFrame(trades)


def daily_returns(trades: pd.DataFrame, prices: dict[str, pd.DataFrame],
                  start: pd.Timestamp, end: pd.Timestamp, cost: float) -> pd.Series:
    calendar = sorted(set().union(*(set(px.index[(px.index >= start) & (px.index <= end)])
                                    for px in prices.values())))
    returns = pd.Series(0.0, index=pd.DatetimeIndex(calendar), dtype=float)
    if trades.empty:
        return returns
    for trade in trades.itertuples():
        px = prices[trade.symbol]
        ei, xi = int(trade.entry_i), int(trade.exit_i)
        if ei >= xi:
            continue
        returns.loc[px.index[ei]] = px.close.iloc[ei] / trade.entry_price - 1 - cost / 2
        for i in range(ei + 1, xi):
            returns.loc[px.index[i]] = px.close.iloc[i] / px.close.iloc[i - 1] - 1
        previous_close = px.close.iloc[xi - 1]
        returns.loc[px.index[xi]] = trade.exit_price / previous_close - 1 - cost / 2
    return returns


def metrics(trades: pd.DataFrame, daily: pd.Series, start: pd.Timestamp,
            end: pd.Timestamp) -> dict:
    years = max((end - start).days / 365.25, 1 / 365.25)
    equity = (1 + daily.fillna(0)).cumprod()
    total = float(equity.iloc[-1] - 1) if len(equity) else 0.0
    cagr = float(equity.iloc[-1] ** (1 / years) - 1) if len(equity) else 0.0
    dd = float((equity / equity.cummax() - 1).min()) if len(equity) else 0.0
    sd = float(daily.std(ddof=1)) if len(daily) > 1 else np.nan
    sharpe = float(daily.mean() / sd * math.sqrt(252)) if sd and sd > 0 else np.nan
    n = len(trades)
    values = trades.net.to_numpy(float) if n else np.array([])
    mean = float(values.mean()) if n else np.nan
    trade_sd = float(values.std(ddof=1)) if n > 1 else np.nan
    se = trade_sd / math.sqrt(n) if n > 1 else np.nan
    critical = float(student_t.ppf(0.975, n - 1)) if n > 1 else np.nan
    test = ttest_1samp(values, 0, alternative="greater") if n > 1 else None
    return dict(
        trades=n, trades_per_year=n / years, total=total, cagr=cagr, max_dd=dd,
        calmar=cagr / abs(dd) if dd < 0 else np.nan, sharpe=sharpe,
        win=float((values > 0).mean()) if n else np.nan,
        mean_net=mean, median_net=float(np.median(values)) if n else np.nan,
        se_net=se, ci_low=mean - critical * se if n > 1 else np.nan,
        ci_high=mean + critical * se if n > 1 else np.nan,
        p_one=float(test.pvalue) if test else np.nan,
        breakeven_cost_bp=float(trades.gross.mean() * 1e4) if n else np.nan,
    )


def fdr_bh(pvalues: pd.Series) -> pd.Series:
    valid = pvalues.dropna().sort_values()
    out = pd.Series(np.nan, index=pvalues.index, dtype=float)
    if valid.empty:
        return out
    adjusted = valid.to_numpy() * len(valid) / np.arange(1, len(valid) + 1)
    adjusted = np.minimum.accumulate(adjusted[::-1])[::-1]
    out.loc[valid.index] = np.clip(adjusted, 0, 1)
    return out


def dsr_probability(daily: pd.Series, trials: int) -> float:
    x = daily.dropna().to_numpy(float)
    if len(x) < 3 or x.std(ddof=1) == 0:
        return np.nan
    sr = x.mean() / x.std(ddof=1)
    gamma = 0.5772156649015329
    expected = (1 / math.sqrt(len(x) - 1)) * (
        (1 - gamma) * norm.ppf(1 - 1 / trials) +
        gamma * norm.ppf(1 - 1 / (trials * math.e)))
    sk = float(skew(x, bias=False))
    ku = float(kurtosis(x, fisher=False, bias=False))
    denom = math.sqrt(max(1e-12, 1 - sk * sr + (ku - 1) * sr * sr / 4))
    return float(norm.cdf((sr - expected) * math.sqrt(len(x) - 1) / denom))


def neighbour_mask(grid: pd.DataFrame, row: pd.Series) -> pd.Series:
    dimensions = [
        ("min_value", MIN_VALUES), ("watch", WATCHES), ("high_n", HIGH_LOOKBACKS),
        ("min_rise", MIN_RISES), ("max_rise", MAX_RISES), ("exit_rule", EXIT_RULES),
    ]
    mask = pd.Series(True, index=grid.index)
    for column, values in dimensions:
        center = values.index(row[column])
        mask &= grid[column].map(values.index).sub(center).abs().le(1)
    return mask


def randomized_events(base: pd.DataFrame, prices: dict[str, pd.DataFrame],
                      start: pd.Timestamp, end: pd.Timestamp,
                      rng: np.random.Generator) -> pd.DataFrame:
    rows = []
    for symbol, group in base.groupby("symbol"):
        px = prices.get(symbol)
        if px is None:
            continue
        dates = px.index[(px.index >= start) & (px.index <= end)]
        if len(dates) < 5:
            continue
        chosen = rng.choice(dates.to_numpy(), size=len(group), replace=len(group) > len(dates))
        for random_date, row in zip(chosen, group.itertuples()):
            d = pd.Timestamp(random_date)
            rows.append(dict(symbol=symbol, d=d, value=float(row.value),
                             trade_date=d, disclose_ts=d))
    if not rows:
        return pd.DataFrame()
    pseudo = pd.DataFrame(rows).sort_values(["symbol", "d"])
    kept = []
    for _, group in pseudo.groupby("symbol", sort=False):
        last = None
        for row in group.itertuples():
            if last is not None and (row.d - last).days < EPISODE_GAP_DAYS:
                continue
            kept.append(row._asdict())
            last = row.d
    return pd.DataFrame(kept)


def random_control(events: pd.DataFrame, prices: dict[str, pd.DataFrame], cfg: Config,
                   start: pd.Timestamp, end: pd.Timestamp, trials: int) -> pd.DataFrame:
    base = causal_events(events[(events.d >= start) & (events.d <= end)], cfg)
    rng = np.random.default_rng(SEED + int(start.year))
    rows = []
    for trial in range(trials):
        pseudo = randomized_events(base, prices, start, end, rng)
        candidates = build_candidates(pseudo, prices, cfg, already_filtered=True)
        trades = simulate(candidates, prices, cfg, start, end, CHARGE_RT)
        daily = daily_returns(trades, prices, start, end, CHARGE_RT)
        rows.append(dict(trial=trial, **metrics(trades, daily, start, end)))
    return pd.DataFrame(rows)


def plot_price_history(symbol: str, trades: pd.DataFrame, px: pd.DataFrame,
                       split_date: pd.Timestamp, cfg: Config) -> None:
    fig, (ax, ax2) = plt.subplots(2, 1, figsize=(14, 8), sharex=True,
                                  gridspec_kw={"height_ratios": [3, 1]})
    ax.plot(px.index, px.close, color="#333", lw=0.9, label="close")
    ax.plot(px.index, px.close.ewm(span=50, adjust=False).mean(),
            color="#4575b4", lw=1.0, label="EMA(50)")
    ax.plot(px.index, px.close.ewm(span=200, adjust=False).mean(),
            color="#8c6d31", lw=1.0, label="EMA(200)")
    for i, trade in enumerate(trades.itertuples()):
        color = "#762a83" if trade.entry_date < split_date else "#c51b7d"
        ax.hlines(trade.rise_level, trade.disclosure_date, trade.signal_date,
                  color=color, ls="--", lw=1.3,
                  label=f"required +{cfg.min_rise:.0%} rise" if i == 0 else None)
    ax.scatter(trades.disclosure_date, trades.reference, marker="D", s=45,
               color="#fdae61", edgecolor="white", lw=0.5,
               label="public disclosure", zorder=5)
    ax.scatter(trades.entry_date, trades.entry_price, marker="^", s=120,
               color="#1a9850", edgecolor="white", lw=0.5,
               label="invest next open", zorder=6)
    ax.scatter(trades.exit_date, trades.exit_price, marker="x", s=80,
               color="#d73027", lw=1.5, label="sell next open", zorder=6)
    ax.axvline(split_date, color="black", ls=":", lw=1.2, label="70/30 split")
    ax.set_title(f"{symbol} — locked momentum rule ({len(trades)} executed trades)")
    ax.legend(fontsize=8, loc="best"); ax.grid(alpha=0.25)
    indicator = rsi(px.close)
    ax2.plot(px.index, indicator, color="#555", lw=0.9)
    ax2.axhline(70, color="#d73027", ls="--", lw=0.7)
    ax2.axhline(30, color="#1a9850", ls="--", lw=0.7)
    ax2.set_ylim(0, 100); ax2.set_ylabel("RSI(14)"); ax2.grid(alpha=0.25)
    fig.tight_layout(); fig.savefig(OUT / f"{symbol}.png", dpi=150); plt.close(fig)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    RESULTS.mkdir(parents=True, exist_ok=True)
    events, prices, audit = load_inputs()
    first_event = events.d.min()
    reference_dates = prices["ADANIPORTS"].index[prices["ADANIPORTS"].index >= first_event]
    cut_i = int(math.floor(0.70 * len(reference_dates)))
    split_date = reference_dates[cut_i]
    sample_start, sample_end = reference_dates[0], max(px.index.max() for px in prices.values())
    train_start, train_end = sample_start, split_date - pd.Timedelta(days=1)
    test_start, test_end = split_date, sample_end

    configs = [Config(v, w, h, lo, hi, ex) for v in MIN_VALUES for w in WATCHES
               for h in HIGH_LOOKBACKS for lo in MIN_RISES for hi in MAX_RISES
               if lo < hi for ex in EXIT_RULES]
    train_cache = {}
    candidate_cache = {}
    rows = []
    for cfg in configs:
        candidates = build_candidates(events, prices, cfg)
        candidate_cache[cfg] = candidates
        trades = simulate(candidates, prices, cfg, train_start, train_end, CHARGE_RT)
        daily = daily_returns(trades, prices, train_start, train_end, CHARGE_RT)
        train_cache[cfg] = (trades, daily)
        rows.append(asdict(cfg) | {f"train_{k}": v for k, v in
                                   metrics(trades, daily, train_start, train_end).items()})
    grid = pd.DataFrame(rows)
    eligible = (grid.train_trades >= 8) & grid.train_trades_per_year.between(0.75, 2.05)
    grid["train_q_bh"] = np.nan
    grid.loc[eligible, "train_q_bh"] = fdr_bh(grid.loc[eligible, "train_p_one"])
    robust_scores, positive_fractions, cluster_sizes = [], [], []
    for _, row in grid.iterrows():
        neighbours = grid[eligible & neighbour_mask(grid, row)]
        robust_scores.append(neighbours.train_cagr.median() if len(neighbours) else np.nan)
        positive_fractions.append(float((neighbours.train_cagr > 0).mean()) if len(neighbours) else np.nan)
        cluster_sizes.append(len(neighbours))
    grid["robust_train_cagr"] = robust_scores
    grid["cluster_positive_fraction"] = positive_fractions
    grid["cluster_size"] = cluster_sizes
    ranked = grid[eligible].sort_values(
        ["robust_train_cagr", "cluster_positive_fraction", "train_ci_low"],
        ascending=False)
    if ranked.empty:
        raise RuntimeError("No configuration met the predeclared frequency/trade-count constraints")
    cluster_center = ranked.iloc[0]
    cluster = grid[eligible & neighbour_mask(grid, cluster_center)].copy()
    cluster["distance_to_cluster_median"] = (
        cluster.train_cagr - cluster.train_cagr.median()).abs()
    selected_row = cluster.sort_values(
        ["distance_to_cluster_median", "train_trades"], ascending=[True, False]).iloc[0]
    selected = Config(selected_row.min_value, int(selected_row.watch), int(selected_row.high_n),
                      selected_row.min_rise, selected_row.max_rise, selected_row.exit_rule)

    selected_candidates = candidate_cache[selected]
    train_trades, train_daily = train_cache[selected]
    test_trades = simulate(selected_candidates, prices, selected, test_start, test_end, CHARGE_RT)
    test_daily = daily_returns(test_trades, prices, test_start, test_end, CHARGE_RT)
    stress_test_trades = simulate(selected_candidates, prices, selected, test_start, test_end,
                                  STRESS_COST_RT)
    stress_test_daily = daily_returns(stress_test_trades, prices, test_start, test_end,
                                      STRESS_COST_RT)
    train_stats = metrics(train_trades, train_daily, train_start, train_end)
    test_stats = metrics(test_trades, test_daily, test_start, test_end)
    stress_stats = metrics(stress_test_trades, stress_test_daily, test_start, test_end)
    trial_count = int(eligible.sum())
    train_stats["dsr_probability"] = dsr_probability(train_daily, trial_count)
    test_stats["dsr_probability"] = dsr_probability(test_daily, trial_count)

    control_train = random_control(events, prices, selected, train_start, train_end, RANDOM_TRIALS)
    control_test = random_control(events, prices, selected, test_start, test_end, RANDOM_TRIALS)
    random_p = float((control_test.cagr >= test_stats["cagr"]).mean())

    sensitivity = []
    for fraction in np.linspace(0.65, 0.75, 11):
        boundary = reference_dates[int(math.floor(fraction * len(reference_dates)))]
        trades = simulate(selected_candidates, prices, selected, boundary, test_end, CHARGE_RT)
        daily = daily_returns(trades, prices, boundary, test_end, CHARGE_RT)
        sensitivity.append(dict(train_fraction=float(fraction), test_start=str(boundary.date()),
                                **metrics(trades, daily, boundary, test_end)))

    # Test metrics for all cells are computed only after the selection is locked.
    test_rows = []
    for cfg in configs:
        trades = simulate(candidate_cache[cfg], prices, cfg, test_start, test_end, CHARGE_RT)
        daily = daily_returns(trades, prices, test_start, test_end, CHARGE_RT)
        test_rows.append({"test_cagr": metrics(trades, daily, test_start, test_end)["cagr"]})
    grid["test_cagr"] = pd.DataFrame(test_rows).test_cagr

    raw_hits = int((grid.loc[eligible, "train_p_one"] < ALPHA).sum())
    fdr_hits = int((grid.loc[eligible, "train_q_bh"] < ALPHA).sum())
    verdict = "dead"
    if (test_stats["ci_low"] > 0 and test_stats["dsr_probability"] >= 0.95 and
            random_p < 0.05 and test_stats["trades"] >= 5):
        verdict = "promising_but_not_fundable_without_spread_and_cross_source_checks"

    all_trades = pd.concat([train_trades.assign(split="train"),
                            test_trades.assign(split="test")], ignore_index=True)
    summary = dict(
        verdict=verdict,
        data=dict(source="cached adjusted yfinance open/close",
                  requested_symbols=list(BASKET), priced_symbols=list(prices),
                  start=str(sample_start.date()), end=str(sample_end.date()),
                  train_start=str(train_start.date()), train_end=str(train_end.date()),
                  test_start=str(test_start.date()), test_end=str(test_end.date()),
                  split="chronological 70/30"),
        execution=dict(entry="next open after close-confirmed signal",
                       exit="next open after close-confirmed exit; time cap at open",
                       annual_entry_cap=ANNUAL_ENTRY_CAP, one_position=True,
                       delivery_charge_bp=CHARGE_RT * 1e4,
                       stress_total_cost_bp=STRESS_COST_RT * 1e4,
                       bid_ask_spread="not measured"),
        search=dict(total_configs=len(configs), eligible_configs=trial_count,
                    raw_p_lt_005=raw_hits, expected_by_chance=ALPHA * trial_count,
                    fdr_q_lt_005=fdr_hits, selected_from="median of robust train neighbourhood"),
        selected_config=asdict(selected), selected_cluster=dict(
            size=len(cluster), mean_train_cagr=float(cluster.train_cagr.mean()),
            median_train_cagr=float(cluster.train_cagr.median()),
            positive_fraction=float((cluster.train_cagr > 0).mean())),
        train=train_stats, test=test_stats, test_75bp_stress=stress_stats,
        random_control=dict(trials=RANDOM_TRIALS,
                            train_median_cagr=float(control_train.cagr.median()),
                            test_median_cagr=float(control_test.cagr.median()),
                            test_p_random_ge_insider=random_p),
        split_start_sensitivity=sensitivity,
        caveats=[
            "highest high is highest close because cached high/low are unavailable",
            "hard stop is close-confirmed and executed next open; intraday stop behaviour is unknown",
            "current-ticker universe has survivorship bias",
            "historical bid/ask spread is unavailable, so no net-positive claim is permitted",
            "no independent second-source price cross-check was available in this run",
            "JSL history before its 2015-11-19 ex-JSHL demerger boundary was removed",
        ],
    )

    grid.to_csv(RESULTS / "grid.csv", index=False)
    all_trades.to_csv(RESULTS / "selected_trades.csv", index=False)
    control_test.to_csv(RESULTS / "random_control_test.csv", index=False)
    pd.DataFrame(audit).to_csv(RESULTS / "data_audit.csv", index=False)
    (RESULTS / "summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n")

    # Diagnostic research plot.
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    shown = grid[eligible & grid.test_cagr.notna()]
    axes[0, 0].scatter(shown.train_cagr * 100, shown.test_cagr * 100,
                       s=14, alpha=0.3, color="#526d82")
    axes[0, 0].scatter([train_stats["cagr"] * 100], [test_stats["cagr"] * 100],
                       s=90, color="#b3261e", label="locked cluster representative")
    axes[0, 0].axhline(0, color="black", lw=0.8); axes[0, 0].axvline(0, color="black", lw=0.8)
    axes[0, 0].set(title="All eligible trials: train vs untouched test",
                   xlabel="Train CAGR (%)", ylabel="Test CAGR (%)")
    axes[0, 0].legend(fontsize=8); axes[0, 0].grid(alpha=0.25)

    combined_daily = pd.concat([train_daily, test_daily]).sort_index()
    axes[0, 1].plot(combined_daily.index, (1 + combined_daily).cumprod(), color="#263f5c")
    axes[0, 1].axvline(split_date, color="#b3261e", ls="--", label="70/30 split")
    axes[0, 1].set(title="Locked rule daily equity (27 bp charges; spread excluded)",
                   ylabel="Growth of ₹1")
    axes[0, 1].legend(fontsize=8); axes[0, 1].grid(alpha=0.25)

    axes[1, 0].hist(control_test.cagr.dropna() * 100, bins=25, color="#9ecae1",
                    edgecolor="white", label=f"random controls (n={RANDOM_TRIALS})")
    axes[1, 0].axvline(test_stats["cagr"] * 100, color="#b3261e", lw=2,
                       label="insider-gated test")
    axes[1, 0].set(title="Matched random-catalyst control on untouched test",
                   xlabel="Test CAGR (%)", ylabel="Trials")
    axes[1, 0].legend(fontsize=8); axes[1, 0].grid(alpha=0.25)

    sens = pd.DataFrame(sensitivity)
    axes[1, 1].plot(sens.train_fraction * 100, sens.cagr * 100, marker="o",
                    color="#263f5c")
    axes[1, 1].axhline(0, color="black", lw=0.8)
    axes[1, 1].set(title="Locked-rule holdout-start sensitivity",
                   xlabel="Training fraction before test (%)", ylabel="Test CAGR (%)")
    axes[1, 1].grid(alpha=0.25)
    fig.suptitle("India insider-gated momentum — honest optimization audit", fontsize=15)
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    fig.savefig(OUT / "audit.png", dpi=150); plt.close(fig)

    for symbol, group in all_trades.groupby("symbol"):
        plot_price_history(symbol, group.sort_values("entry_date"), prices[symbol],
                           split_date, selected)

    print(json.dumps(summary, indent=2, allow_nan=False))
    print(f"plots -> {OUT}")


if __name__ == "__main__":
    main()
