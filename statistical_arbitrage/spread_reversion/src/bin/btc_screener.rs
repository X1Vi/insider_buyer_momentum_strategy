//! Watchlist screener — applies the refined rule to each symbol and reports.
//!
//! Semi-automatic by design: it evaluates and alerts, a human decides. It holds
//! no positions and writes no state, so it is safe to run as often as you like.
//!
//! Default watchlist is deliberately narrow — BTCUSDT and THETAUSDT, the two
//! coins that cleared the success bar in the master-table study (net Sharpe
//! above the S&P 500 over their own window, positive in both sample halves).
//!
//! Worth stating plainly: a watchlist chosen *because* those names scored well
//! in the same backtest is a selection-biased universe. Two survivors out of 72
//! coins is roughly what chance produces, and THETA's own halves were 1.07 then
//! 0.49. Override with `BTC_WATCHLIST` to screen a wider, less flattering set.
//!
//! Usage:
//!   cargo run --release --bin btc_screener
//!   cargo run --release --bin btc_screener -- --push        # send a digest
//!   BTC_WATCHLIST=BTCUSDT,ETHUSDT,SOLUSDT cargo run --release --bin btc_screener

use anyhow::Result;
use spread_reversion::binance::Client;
use spread_reversion::notify;
use spread_reversion::strategy::{self, Indicators, MIN_BARS};

const DEFAULT_WATCHLIST: &[&str] = &["BTCUSDT", "THETAUSDT"];
const HISTORY_BARS: usize = 400;

struct Row {
    symbol: String,
    date: String,
    close: f64,
    entry: bool,
    exit: bool,
    detail: strategy::SignalDetail,
    quote_volume_24h: f64,
    error: Option<String>,
}

fn watchlist() -> Vec<String> {
    match std::env::var("BTC_WATCHLIST") {
        Ok(raw) if !raw.trim().is_empty() => raw
            .split(',')
            .map(|s| s.trim().to_uppercase())
            .filter(|s| !s.is_empty())
            .collect(),
        _ => DEFAULT_WATCHLIST.iter().map(|s| s.to_string()).collect(),
    }
}

async fn screen(client: &Client, symbol: &str) -> Row {
    let mut row = Row {
        symbol: symbol.to_string(),
        date: String::new(),
        close: f64::NAN,
        entry: false,
        exit: false,
        detail: strategy::SignalDetail {
            squeezed: false,
            uptrend: false,
            volume_surge: false,
            risk_on: false,
            spread_pct: f64::NAN,
            volume_ratio: None,
            close: f64::NAN,
            ema_mid: f64::NAN,
            ema_slow: f64::NAN,
        },
        quote_volume_24h: f64::NAN,
        error: None,
    };

    let klines = match client.daily_closed(symbol, HISTORY_BARS).await {
        Ok(k) => k,
        Err(e) => {
            row.error = Some(format!("{e:#}"));
            return row;
        }
    };
    if klines.len() < MIN_BARS {
        row.error = Some(format!(
            "only {} closed bars, need {MIN_BARS}",
            klines.len()
        ));
        return row;
    }

    let closes: Vec<f64> = klines.iter().map(|k| k.close).collect();
    let volumes: Vec<f64> = klines.iter().map(|k| k.volume).collect();
    let indicators = Indicators::compute(&closes, &volumes);
    let last = klines.len() - 1;
    let (signal, detail) = strategy::evaluate(&indicators, &closes, &volumes, last);

    row.date = klines[last].date();
    row.close = klines[last].close;
    row.entry = signal.entry;
    row.exit = signal.exit;
    row.detail = detail;
    row
}

#[tokio::main]
async fn main() -> Result<()> {
    dotenvy::dotenv().ok();
    let args: Vec<String> = std::env::args().collect();
    let push = args.iter().any(|a| a == "--push");

    let symbols = watchlist();
    let client = Client::new();

    let mut rows = Vec::new();
    for symbol in &symbols {
        rows.push(screen(&client, symbol).await);
    }

    // One filtered ticker call for the whole watchlist (weight 2, not 80).
    if let Ok(tickers) = client.tickers(&symbols).await {
        for row in &mut rows {
            if let Some(t) = tickers.iter().find(|t| t.symbol == row.symbol) {
                row.quote_volume_24h = t.quote_volume;
            }
        }
    }

    println!("\nSCREENER — refined EMA/volume rule, last CLOSED daily bar");
    println!("{}", "=".repeat(104));
    println!(
        "{:<11} {:<11} {:>12} {:>13} {:>8}  {}",
        "symbol", "bar", "close", "24h vol (M)", "signal", "why"
    );
    println!("{}", "-".repeat(104));

    let mut triggered: Vec<&Row> = Vec::new();
    for row in &rows {
        if let Some(err) = &row.error {
            println!(
                "{:<11} {:<11} {:>12} {:>13} {:>8}  {}",
                row.symbol, "-", "-", "-", "ERROR", err
            );
            continue;
        }
        let signal = if row.entry {
            "ENTRY"
        } else if row.exit {
            "exit"
        } else {
            "-"
        };
        println!(
            "{:<11} {:<11} {:>12.2} {:>13.1} {:>8}  {}",
            row.symbol,
            row.date,
            row.close,
            row.quote_volume_24h / 1e6,
            signal,
            row.detail.describe()
        );
        if row.entry {
            triggered.push(row);
        }
    }
    println!("{}", "=".repeat(104));

    let ok = rows.iter().filter(|r| r.error.is_none()).count();
    println!(
        "{ok}/{} screened · {} entry signal(s)",
        rows.len(),
        triggered.len()
    );
    println!("(screener only — it holds no positions and places no orders)");

    if push {
        let body = if triggered.is_empty() {
            format!(
                "no entry signals\n{}",
                rows.iter()
                    .filter(|r| r.error.is_none())
                    .map(|r| format!("{}: {}", r.symbol, r.detail.describe()))
                    .collect::<Vec<_>>()
                    .join("\n")
            )
        } else {
            triggered
                .iter()
                .map(|r| format!("{} @ {:.2}\n  {}", r.symbol, r.close, r.detail.describe()))
                .collect::<Vec<_>>()
                .join("\n")
        };
        let title = if triggered.is_empty() {
            "Screener: no signals".to_string()
        } else {
            format!("Screener: {} ENTRY signal(s)", triggered.len())
        };
        let priority = if triggered.is_empty() {
            notify::PRIORITY_NORMAL
        } else {
            notify::PRIORITY_HIGH
        };
        notify::fire(&title, &body);
        if !notify::pushover(&title, &body, priority).await {
            eprintln!(
                "note: Pushover not sent — set PUSHOVER_APP_TOKEN in .env \
                 (PUSHOVER_USER_KEY is already present)"
            );
        }
    }
    Ok(())
}
