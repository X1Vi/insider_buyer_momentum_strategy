//! Minimal BTC paper-trading bot — daily bars, Binance data, Pushover alerts.
//!
//! **PAPER TRADING ONLY.** This binary has no exchange credentials and links no
//! order-placing code. `binance.rs` exposes public candle endpoints and nothing
//! else, so it cannot place a trade even if instructed to.
//!
//! Design notes, each one fixing a specific defect in the earlier Hummingbot port:
//!
//! * **Closed bars only.** The old port read `close.iloc[-1]`, which on an
//!   intraday tick is the *forming* daily candle — a signal seen at 08:00 UTC
//!   could vanish by the close. `binance::daily_closed` drops the forming bar.
//! * **State survives restarts.** Entry price is persisted, so a restart while
//!   holding cannot leave the position stop-less.
//! * **Exactly-once per bar.** `already_processed` means running twice in a day
//!   (cron overlap, manual re-run) cannot double-trade.
//! * **Same code as the backtest.** Signals come from `strategy::evaluate`, the
//!   identical function `btc_backtest` replays, so live and tested cannot drift.
//!
//! Usage:
//!   cargo run --release --bin btc_bot -- --once      # one pass, for cron
//!   cargo run --release --bin btc_bot                # poll loop
//!   cargo run --release --bin btc_bot -- --status    # print state, do nothing
//!
//! Env: PUSHOVER_APP_TOKEN, PUSHOVER_USER_KEY (optional — degrades to desktop),
//!      BTC_BOT_SYMBOL (default BTCUSDT), BTC_BOT_CASH (default 1000),
//!      BTC_BOT_POLL_MINS (default 15).

use anyhow::Result;
use spread_reversion::binance::Client;
use spread_reversion::engine::{self, Action};
use spread_reversion::notify;
use spread_reversion::paper::PaperAccount;
use spread_reversion::strategy::{self, Indicators, MIN_BARS};
use tokio::time::{Duration, sleep};
use tracing::{error, info, warn};

const STATE_PATH: &str = "btc_paper_state.json";
const TRADE_LOG: &str = "btc_paper_trades.csv";
const LOG_PATH: &str = "btc_bot.log";
/// Enough history to warm up EMA200 with room to spare.
const HISTORY_BARS: usize = 400;

fn env_or<T: std::str::FromStr>(key: &str, default: T) -> T {
    std::env::var(key)
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(default)
}

/// Warn loudly and exactly once if Pushover cannot possibly work.
///
/// The existing scanner logs a quiet `SKIP: PUSHOVER_APP_TOKEN not set` line to
/// `pushover.log` and carries on, which is why phone alerts have been silently
/// dead. A bot whose whole job is to tell you something should say so at startup.
fn check_pushover() -> bool {
    let token = std::env::var("PUSHOVER_APP_TOKEN").unwrap_or_default();
    let user = std::env::var("PUSHOVER_USER_KEY").unwrap_or_default();
    match (token.trim().is_empty(), user.trim().is_empty()) {
        (false, false) => {
            info!("pushover enabled");
            true
        }
        (true, false) => {
            warn!(
                "PUSHOVER_APP_TOKEN is not set — phone alerts are DISABLED (desktop toast only). \
                 Add it to .env next to PUSHOVER_USER_KEY."
            );
            false
        }
        (false, true) => {
            warn!("PUSHOVER_USER_KEY is not set — phone alerts are DISABLED");
            false
        }
        (true, true) => {
            warn!("no Pushover credentials — phone alerts are DISABLED (desktop toast only)");
            false
        }
    }
}

/// Send to phone (if configured) and desktop, always.
async fn alert(title: &str, body: &str, priority: i32) {
    notify::fire(title, body);
    let delivered = notify::pushover(title, body, priority).await;
    if !delivered {
        info!(title, "pushover not delivered (disabled or rejected)");
    }
}

/// Process the most recent closed bar. Returns true if the account changed.
async fn step(client: &Client, account: &mut PaperAccount, symbol: &str) -> Result<bool> {
    let klines = client.daily_closed(symbol, HISTORY_BARS).await?;
    if klines.len() < MIN_BARS {
        warn!(
            bars = klines.len(),
            need = MIN_BARS,
            "not enough history yet"
        );
        return Ok(false);
    }

    let last = klines.len() - 1;
    let bar = &klines[last];
    if account.already_processed(bar.open_time) {
        return Ok(false);
    }

    let closes: Vec<f64> = klines.iter().map(|k| k.close).collect();
    let volumes: Vec<f64> = klines.iter().map(|k| k.volume).collect();
    let dates: Vec<String> = klines.iter().map(|k| k.date()).collect();
    let open_times: Vec<i64> = klines.iter().map(|k| k.open_time).collect();
    let indicators = Indicators::compute(&closes, &volumes);

    // Exactly the function `btc_backtest` replays. Live and tested cannot drift.
    let outcome = engine::process_bar(
        account,
        &indicators,
        &closes,
        &volumes,
        &dates,
        &open_times,
        last,
    );

    // Persist the fill and the "bar seen" mark in one atomic write, so they can
    // never disagree after a crash.
    account.mark_processed(outcome.bar_open_time);
    account.save()?;

    let date = &outcome.date;
    match &outcome.action {
        Action::Entered(position) => {
            info!(
                symbol, date = %date, price = position.entry_price,
                qty = position.quantity, "PAPER ENTRY"
            );
            alert(
                &format!("PAPER ENTRY {symbol}"),
                &format!(
                    "{date}  bought at {:.2}\nqty {:.6}  stop {:.2} (-5%)\n{}\nequity {:.2}",
                    position.entry_price,
                    position.quantity,
                    position.stop_ref_price * (1.0 - strategy::STOP_LOSS_PCT),
                    outcome.detail.describe(),
                    outcome.equity
                ),
                notify::PRIORITY_HIGH,
            )
            .await;
        }
        Action::Exited(trade) => {
            PaperAccount::append_trade_csv(TRADE_LOG, trade).ok();
            info!(
                symbol, date = %date, price = trade.exit_price, pnl = trade.pnl,
                reason = trade.exit_reason.label(), "PAPER EXIT"
            );
            alert(
                &format!("PAPER EXIT {symbol} ({})", trade.exit_reason.label()),
                &format!(
                    "{date}  sold at {:.2}\nP&L {:+.2} ({:+.2}%)\nheld since {}\nequity {:.2}",
                    trade.exit_price, trade.pnl, trade.return_pct, trade.entry_date, outcome.equity
                ),
                notify::PRIORITY_HIGH,
            )
            .await;
        }
        Action::Hold => {
            info!(
                symbol, date = %date, close = outcome.close,
                flat = account.is_flat(),
                detail = %outcome.detail.describe(),
                "no action"
            );
        }
    }
    Ok(outcome.action.changed())
}

fn print_status(account: &PaperAccount, last_price: Option<f64>) {
    let price = last_price.unwrap_or(0.0);
    println!("symbol            {}", account.symbol);
    println!("cash              {:.2}", account.cash);
    match &account.position {
        Some(p) => {
            println!(
                "position          LONG {:.6} @ {:.2} since {} (stop {:.2})",
                p.quantity,
                p.entry_price,
                p.entry_date,
                p.entry_price * (1.0 - strategy::STOP_LOSS_PCT)
            );
            if price > 0.0 {
                println!("unrealised        {:+.2}", account.unrealised_pnl(price));
            }
        }
        None => println!("position          FLAT"),
    }
    println!("realised P&L      {:+.2}", account.realised_pnl);
    println!("fees paid         {:.2}", account.total_fees);
    println!("closed trades     {}", account.trades.len());
    if let Some(rate) = account.win_rate() {
        println!("win rate          {rate:.1}%");
    }
    if price > 0.0 {
        let equity = account.equity(price);
        println!(
            "equity            {:.2}  ({:+.2}% from {:.0})",
            equity,
            (equity / account.initial_cash - 1.0) * 100.0,
            account.initial_cash
        );
    }
}

/// Replay the last `bars` closed bars through the SAME engine the live bot
/// uses, printing every decision.
///
/// A daily bot is undramatic to watch in real time — it wakes, finds no signal,
/// and sleeps. This shows the identical code path making real decisions on real
/// history at a speed you can follow. It touches no state file and places no
/// orders; it is a visualisation, not a second backtest.
async fn replay(client: &Client, symbol: &str, bars: usize, delay_ms: u64) -> Result<()> {
    let need = bars + HISTORY_BARS;
    let klines = client.daily_closed(symbol, need).await?;
    if klines.len() < MIN_BARS + 1 {
        warn!(bars = klines.len(), "not enough history to replay");
        return Ok(());
    }
    let closes: Vec<f64> = klines.iter().map(|k| k.close).collect();
    let volumes: Vec<f64> = klines.iter().map(|k| k.volume).collect();
    let dates: Vec<String> = klines.iter().map(|k| k.date()).collect();
    let open_times: Vec<i64> = klines.iter().map(|k| k.open_time).collect();
    let indicators = Indicators::compute(&closes, &volumes);

    let start = klines.len().saturating_sub(bars).max(strategy::WARMUP_BARS);
    let mut account = PaperAccount::new(symbol, 1_000.0);

    println!(
        "\nREPLAY — {symbol}, {} bars, same engine as the live bot",
        klines.len() - start
    );
    println!("(no state written, no orders — this is a visualisation)\n");
    println!(
        "{:<12} {:>11} {:>9} {:<8} {:>10}  {}",
        "date", "close", "equity", "action", "pnl%", "why"
    );
    println!("{}", "-".repeat(120));

    for i in start..klines.len() {
        let outcome = engine::process_bar(
            &mut account,
            &indicators,
            &closes,
            &volumes,
            &dates,
            &open_times,
            i,
        );
        let (tag, pnl) = match &outcome.action {
            Action::Entered(_) => ("BUY".to_string(), String::new()),
            Action::Exited(t) => (
                format!(
                    "SELL/{}",
                    if t.exit_reason.label() == "stop_loss" {
                        "stop"
                    } else {
                        "sig"
                    }
                ),
                format!("{:+.2}%", t.return_pct),
            ),
            Action::Hold => (
                if account.position.is_some() {
                    "hold".to_string()
                } else {
                    String::new()
                },
                String::new(),
            ),
        };
        // Only narrate bars where something happened, or every 20th bar, so the
        // interesting lines are not buried in a wall of "nothing".
        let notable = outcome.action.changed() || i % 20 == 0;
        if notable {
            println!(
                "{:<12} {:>11.2} {:>9.2} {:<8} {:>10}  {}",
                outcome.date,
                outcome.close,
                outcome.equity,
                tag,
                pnl,
                if outcome.action.changed() {
                    outcome.detail.describe()
                } else {
                    String::new()
                }
            );
        }
        if outcome.action.changed() && delay_ms > 0 {
            sleep(Duration::from_millis(delay_ms)).await;
        }
    }

    let last = *closes.last().unwrap();
    println!("{}", "-".repeat(120));
    println!(
        "closed trades {}  ·  realised {:+.2}  ·  equity {:.2} from 1000 ({:+.2}%)  ·  win rate {:.1}%",
        account.trades.len(),
        account.realised_pnl,
        account.equity(last),
        (account.equity(last) / 1000.0 - 1.0) * 100.0,
        account.win_rate().unwrap_or(0.0),
    );
    Ok(())
}

#[tokio::main]
async fn main() -> Result<()> {
    dotenvy::dotenv().ok();
    let _guard =
        spread_reversion::logging::init_console(LOG_PATH, "btc_bot=info,spread_reversion=info")?;

    let args: Vec<String> = std::env::args().collect();
    let once = args.iter().any(|a| a == "--once");
    let status_only = args.iter().any(|a| a == "--status");
    let replay_bars: Option<usize> = args
        .iter()
        .position(|a| a == "--replay")
        .map(|i| args.get(i + 1).and_then(|v| v.parse().ok()).unwrap_or(400));

    let symbol = std::env::var("BTC_BOT_SYMBOL").unwrap_or_else(|_| "BTCUSDT".to_string());
    let initial_cash: f64 = env_or("BTC_BOT_CASH", 1_000.0);
    let poll_mins: u64 = env_or::<u64>("BTC_BOT_POLL_MINS", 15).clamp(1, 720);

    let mut account = PaperAccount::load_or_new(STATE_PATH, &symbol, initial_cash)?;
    let client = Client::new();

    if let Some(bars) = replay_bars {
        let delay: u64 = env_or("BTC_BOT_REPLAY_MS", 250);
        replay(&client, &symbol, bars, delay).await?;
        return Ok(());
    }

    if status_only {
        let price = client
            .daily_closed(&symbol, 2)
            .await
            .ok()
            .and_then(|k| k.last().map(|b| b.close));
        print_status(&account, price);
        return Ok(());
    }

    let pushover_ok = check_pushover();
    info!(
        symbol,
        initial_cash,
        poll_mins,
        pushover = pushover_ok,
        state = STATE_PATH,
        "BTC paper bot started — PAPER TRADING ONLY, NO REAL ORDERS"
    );
    alert(
        "BTC paper bot started",
        &format!(
            "{symbol} · daily bars · paper only\ncash {:.2} · {} closed trades so far",
            account.cash,
            account.trades.len()
        ),
        notify::PRIORITY_NORMAL,
    )
    .await;

    loop {
        match step(&client, &mut account, &symbol).await {
            Ok(changed) => {
                if changed {
                    info!(realised = account.realised_pnl, "state updated");
                }
            }
            // A failed poll must not kill a long-running bot; the next tick retries.
            Err(e) => error!(error = %format!("{e:#}"), "poll failed"),
        }

        if once {
            break;
        }
        sleep(Duration::from_secs(poll_mins * 60)).await;
    }
    Ok(())
}
