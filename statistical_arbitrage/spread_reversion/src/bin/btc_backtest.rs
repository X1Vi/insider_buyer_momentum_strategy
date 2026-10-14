//! Replay the refined EMA/volume rule over Binance daily klines.
//!
//! This exists because the Python research used yfinance `BTC-USD`, whose
//! volume is aggregated across many venues, while a live bot reads Binance
//! `BTCUSDT` volume — a different series. The rule's `volume > 1.5 x MA20`
//! leg therefore fires on different days. Rather than assume that away, this
//! binary re-runs the rule on the data the bot will actually trade, using the
//! *same* `strategy` and `paper` modules the live bot uses, so a discrepancy
//! can only come from the data and not from a second implementation.
//!
//! Python reference for BTC at 1x (yfinance BTC-USD, 8.1 years, fixed 5% stop):
//!   CAGR 8.21%   Sharpe 1.01   MaxDD -11.7%   18 trades
//!
//! Usage:
//!   cargo run --release --bin btc_backtest
//!   cargo run --release --bin btc_backtest -- --symbol ETHUSDT --years 6
//!   cargo run --release --bin btc_backtest -- --all          (whole watchlist)

use anyhow::Result;
use spread_reversion::binance::{Client, Kline};
use spread_reversion::engine;
use spread_reversion::paper::PaperAccount;
use spread_reversion::strategy::{Indicators, WARMUP_BARS};

const DEFAULT_SYMBOL: &str = "BTCUSDT";
const DEFAULT_YEARS: f64 = 9.0;
const INITIAL_CASH: f64 = 1_000.0;
const PERIODS_PER_YEAR: f64 = 365.0;

/// The coins that cleared the success bar in the master-table study.
const WATCHLIST: &[&str] = &["BTCUSDT", "THETAUSDT"];

#[derive(Debug)]
struct Metrics {
    bars: usize,
    years: f64,
    trades: usize,
    win_rate: f64,
    final_equity: f64,
    cagr: f64,
    sharpe: f64,
    max_drawdown: f64,
    total_fees: f64,
    exposure_pct: f64,
    buy_hold_cagr: f64,
}

fn annualised(equity_curve: &[f64], years: f64) -> (f64, f64, f64) {
    if equity_curve.len() < 3 || years <= 0.0 {
        return (0.0, 0.0, 0.0);
    }
    let returns: Vec<f64> = equity_curve
        .windows(2)
        .map(|w| if w[0] > 0.0 { w[1] / w[0] - 1.0 } else { 0.0 })
        .collect();

    let cagr = (equity_curve[equity_curve.len() - 1] / equity_curve[0]).powf(1.0 / years) - 1.0;

    let mean = returns.iter().sum::<f64>() / returns.len() as f64;
    let variance =
        returns.iter().map(|r| (r - mean).powi(2)).sum::<f64>() / (returns.len() - 1) as f64;
    let sd = variance.sqrt();
    let sharpe = if sd > 0.0 {
        mean / sd * PERIODS_PER_YEAR.sqrt()
    } else {
        0.0
    };

    let mut peak = equity_curve[0];
    let mut max_drawdown = 0.0f64;
    for &value in equity_curve {
        peak = peak.max(value);
        if peak > 0.0 {
            max_drawdown = max_drawdown.min(value / peak - 1.0);
        }
    }
    (cagr, sharpe, max_drawdown)
}

/// Run the rule over `klines`, returning metrics and the closed trades.
fn backtest(symbol: &str, klines: &[Kline]) -> Option<(Metrics, PaperAccount)> {
    if klines.len() <= WARMUP_BARS + 1 {
        return None;
    }
    let closes: Vec<f64> = klines.iter().map(|k| k.close).collect();
    let volumes: Vec<f64> = klines.iter().map(|k| k.volume).collect();
    let dates: Vec<String> = klines.iter().map(|k| k.date()).collect();
    let open_times: Vec<i64> = klines.iter().map(|k| k.open_time).collect();

    // Indicators are computed over the FULL series including the pre-warm-up
    // bars, then trading starts at bar 200 — matching the Python, which seeds
    // the EMAs from bar 0 and only afterwards slices `close.index[200:]`.
    let indicators = Indicators::compute(&closes, &volumes);

    let mut account = PaperAccount::new(symbol, INITIAL_CASH);
    // The same `engine::process_bar` the live bot calls, in a loop. There is no
    // second implementation of the rule anywhere in the tree.
    let (_, equity_curve, bars_in_market) = engine::replay(
        &mut account,
        &indicators,
        &closes,
        &volumes,
        &dates,
        &open_times,
        WARMUP_BARS,
    );

    let bars = equity_curve.len();
    let years = bars as f64 / PERIODS_PER_YEAR;
    let (cagr, sharpe, max_drawdown) = annualised(&equity_curve, years);

    let first_close = closes[WARMUP_BARS];
    let last_close = closes[closes.len() - 1];
    let buy_hold_cagr = (last_close / first_close).powf(1.0 / years) - 1.0;

    let metrics = Metrics {
        bars,
        years,
        trades: account.trades.len(),
        win_rate: account.win_rate().unwrap_or(0.0),
        final_equity: *equity_curve.last().unwrap(),
        cagr: cagr * 100.0,
        sharpe,
        max_drawdown: max_drawdown * 100.0,
        total_fees: account.total_fees,
        exposure_pct: bars_in_market as f64 / bars as f64 * 100.0,
        buy_hold_cagr: buy_hold_cagr * 100.0,
    };
    Some((metrics, account))
}

fn print_report(symbol: &str, klines: &[Kline], metrics: &Metrics, account: &PaperAccount) {
    println!("\n{}", "=".repeat(78));
    println!("{symbol}  —  refined EMA/volume rule on Binance daily klines");
    println!("{}", "=".repeat(78));
    println!(
        "window          {} -> {}  ({} closed bars after {WARMUP_BARS}-bar warm-up, {:.1} years)",
        klines[WARMUP_BARS].date(),
        klines[klines.len() - 1].date(),
        metrics.bars,
        metrics.years
    );
    println!("costs           0.10% fee + 0.05% slippage per side, 20% of equity per trade");
    println!("stop            5% FIXED from entry (evaluated on the close)");
    println!();
    println!("  CAGR                {:>9.2}%", metrics.cagr);
    println!("  Sharpe              {:>9.2}", metrics.sharpe);
    println!("  Max drawdown        {:>9.2}%", metrics.max_drawdown);
    println!("  Trades              {:>9}", metrics.trades);
    println!("  Win rate            {:>9.1}%", metrics.win_rate);
    println!("  Time in market      {:>9.1}%", metrics.exposure_pct);
    println!("  Total fees paid     {:>9.2}", metrics.total_fees);
    println!(
        "  Final equity        {:>9.2}   (from {INITIAL_CASH:.0})",
        metrics.final_equity
    );
    println!();
    println!(
        "  Buy & hold CAGR     {:>9.2}%   <- the honest comparison",
        metrics.buy_hold_cagr
    );

    if symbol == DEFAULT_SYMBOL {
        println!();
        println!(
            "  Python reference (yfinance BTC-USD, 8.1y): CAGR 8.21%  Sharpe 1.01  MaxDD -11.7%  18 trades"
        );
        println!("  Differences are expected: Binance BTCUSDT volume is single-venue, the");
        println!("  yfinance series aggregates across venues, so the 1.5x volume leg differs.");
    }

    if !account.trades.is_empty() {
        println!("\n  last {} trades:", account.trades.len().min(8));
        println!(
            "  {:<12} {:<12} {:>10} {:>10} {:>9} {:>10}",
            "entry", "exit", "in", "out", "pnl%", "reason"
        );
        for trade in account.trades.iter().rev().take(8).rev() {
            println!(
                "  {:<12} {:<12} {:>10.2} {:>10.2} {:>8.2}% {:>10}",
                trade.entry_date,
                trade.exit_date,
                trade.entry_price,
                trade.exit_price,
                trade.return_pct,
                trade.exit_reason.label()
            );
        }
    }
}

#[tokio::main]
async fn main() -> Result<()> {
    let args: Vec<String> = std::env::args().collect();
    let flag = |name: &str| -> Option<String> {
        args.iter()
            .position(|a| a == name)
            .and_then(|i| args.get(i + 1))
            .cloned()
    };

    let years: f64 = flag("--years")
        .and_then(|v| v.parse().ok())
        .unwrap_or(DEFAULT_YEARS);
    let min_bars = (years * PERIODS_PER_YEAR) as usize + WARMUP_BARS;

    let symbols: Vec<String> = if args.iter().any(|a| a == "--all") {
        WATCHLIST.iter().map(|s| s.to_string()).collect()
    } else {
        vec![flag("--symbol").unwrap_or_else(|| DEFAULT_SYMBOL.to_string())]
    };

    let client = Client::new();
    println!(
        "fetching up to {min_bars} closed daily bars per symbol from Binance (public, no key)"
    );

    let mut summary: Vec<(String, Metrics)> = Vec::new();
    for symbol in &symbols {
        let klines = match client.daily_closed(symbol, min_bars).await {
            Ok(k) => k,
            Err(e) => {
                eprintln!("{symbol}: fetch failed: {e:#}");
                continue;
            }
        };
        match backtest(symbol, &klines) {
            Some((metrics, account)) => {
                print_report(symbol, &klines, &metrics, &account);
                summary.push((symbol.clone(), metrics));
            }
            None => eprintln!(
                "{symbol}: only {} bars, need > {}",
                klines.len(),
                WARMUP_BARS + 1
            ),
        }
    }

    if summary.len() > 1 {
        println!("\n{}", "=".repeat(78));
        println!("SUMMARY");
        println!("{}", "=".repeat(78));
        println!(
            "{:<12} {:>8} {:>8} {:>9} {:>8} {:>12}",
            "symbol", "CAGR%", "Sharpe", "MaxDD%", "trades", "B&H CAGR%"
        );
        for (symbol, m) in &summary {
            println!(
                "{:<12} {:>8.2} {:>8.2} {:>9.2} {:>8} {:>12.2}",
                symbol, m.cagr, m.sharpe, m.max_drawdown, m.trades, m.buy_hold_cagr
            );
        }
    }
    Ok(())
}
