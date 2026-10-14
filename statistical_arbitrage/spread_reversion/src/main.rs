mod groww;
mod indicator;
mod ledger;
mod logging;
mod notify;
mod state;
mod trading;
mod tui;

use std::sync::{Arc, Mutex};
use tracing::info;

const PAIR_A: &str = "BANKBEES";
const PAIR_B: &str = "SETFNIFBK";
const FETCH_INTERVAL_SECS: u64 = 30;
const SPREAD_WINDOW: usize = 60;
const LOG_PATH: &str = "spread_reversion.log";

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    dotenvy::dotenv().ok();
    let _log_guard = logging::init(LOG_PATH)?;

    let token = fetch_token().await?;
    let client = Arc::new(groww::Client::new(&token));

    // Indicator mode (live manual-trading signals): cargo run -- --indicator
    if std::env::args().any(|a| a == "--indicator") {
        indicator::run(client).await?;
        return Ok(());
    }

    let ledger_pnl = ledger::replay_total_pnl(LOG_PATH);
    let state: state::SharedState =
        Arc::new(Mutex::new(state::AppState::new(SPREAD_WINDOW, ledger_pnl)));

    info!(
        pair = format!("{PAIR_A}/{PAIR_B}"),
        qty = state::TRADE_QTY,
        window = SPREAD_WINDOW,
        interval_secs = FETCH_INTERVAL_SECS,
        ledger_pnl,
        "paper trading started — NO REAL ORDERS"
    );

    let trading_state = state.clone();
    tokio::spawn(async move {
        trading::run(client, trading_state, FETCH_INTERVAL_SECS, SPREAD_WINDOW).await;
    });

    tui::run(state).await
}

/// Resolve a Groww access token: use GROWW_ACCESS_TOKEN directly if set,
/// otherwise generate one via the API key/secret checksum flow.
async fn fetch_token() -> anyhow::Result<String> {
    if let Ok(token) = std::env::var("GROWW_ACCESS_TOKEN") {
        if !token.is_empty() {
            info!("using GROWW_ACCESS_TOKEN from environment");
            return Ok(token);
        }
    }

    let api_key = std::env::var("GROWW_API_KEY")
        .map_err(|_| anyhow::anyhow!("set GROWW_ACCESS_TOKEN or GROWW_API_KEY/GROWW_API_SECRET"))?;
    let api_secret = std::env::var("GROWW_API_SECRET")
        .map_err(|_| anyhow::anyhow!("set GROWW_ACCESS_TOKEN or GROWW_API_KEY/GROWW_API_SECRET"))?;

    info!("no GROWW_ACCESS_TOKEN set, generating one via API key/secret");
    groww::Client::login_with_api_key(&api_key, &api_secret).await
}
