//! Live manual-trading indicator (append-only; does not touch the paper-trading engine).
//!
//! Mirrors `indicator_groww.py`:
//!   spread = ln(PA) - ln(PB), rolling z-score.
//!   LONG  when z < -2  -> BUY  BANKBEES / SELL SETFNIFBK   (exit z >= 0)
//!   SHORT when z > +2  -> SELL BANKBEES / BUY  SETFNIFBK   (exit z <= 0)
//! Alerts (desktop + terminal bell) when it is time to enter or exit.
//! MANUAL trading — no orders placed.
//!
//! Run with:  cargo run -- --indicator
//! Env overrides: INDICATOR_REFRESH (1-5s, default 3), INDICATOR_WINDOW (default 60),
//!                INDICATOR_SIDE (BOTH|LONG|SHORT, default BOTH), INDICATOR_CAPITAL (default 10000).

use std::sync::Arc;
use tokio::time::{Duration, interval};
use tracing::{info, warn};

use crate::groww;
use crate::{PAIR_A, PAIR_B};

const ENTRY_Z: f64 = 2.0;
const WARMUP: usize = 5;

#[derive(Clone, Copy, PartialEq)]
enum Side {
    Flat,
    Long,
    Short,
}

fn env_str(key: &str, default: &str) -> String {
    std::env::var(key).unwrap_or_else(|_| default.to_string())
}

pub async fn run(client: Arc<groww::Client>) -> anyhow::Result<()> {
    let refresh_secs: u64 = env_str("INDICATOR_REFRESH", "3")
        .parse()
        .unwrap_or(3)
        .clamp(1, 5);
    let window: usize = env_str("INDICATOR_WINDOW", "60")
        .parse()
        .unwrap_or(60)
        .max(WARMUP);
    let side = env_str("INDICATOR_SIDE", "BOTH");
    let capital: f64 = env_str("INDICATOR_CAPITAL", "10000")
        .parse()
        .unwrap_or(10_000.0);

    info!(side, refresh_secs, window, capital, "indicator started");

    let mut timer = interval(Duration::from_secs(refresh_secs));
    let mut history: Vec<f64> = Vec::with_capacity(window);
    let mut state = Side::Flat;
    let mut entry_z = 0.0f64;
    let mut entry_at = String::new();
    let mut ticks = 0u64;
    let (mut last_a, mut last_b);
    let mut z = 0.0f64;
    let mut spread;

    loop {
        timer.tick().await;
        ticks += 1;

        let (pa, pb) = match fetch_pair(&client).await {
            Ok(p) => p,
            Err(e) => {
                warn!(error = %e, "fetch_failed");
                continue;
            }
        };
        last_a = pa;
        last_b = pb;

        spread = (pa / pb).ln();
        history.push(spread);
        if history.len() > window {
            history.remove(0);
        }

        if history.len() >= WARMUP {
            let mean = history.iter().sum::<f64>() / history.len() as f64;
            let var =
                history.iter().map(|s| (s - mean).powi(2)).sum::<f64>() / history.len() as f64;
            z = (spread - mean) / var.sqrt().max(1e-4);

            let qty = ((capital / (pa + pb)) as u64).max(1);
            match state {
                Side::Flat => {
                    if (side == "BOTH" || side == "SHORT") && z > ENTRY_Z {
                        state = Side::Short;
                        entry_z = z;
                        entry_at = crate::logging::now_hms();
                        let msg = format!(
                            "ENTER SHORT  z={z:+.2}  -> SELL {PAIR_A} / BUY {PAIR_B}  qty~{qty}"
                        );
                        info!(z, "enter_short");
                        crate::notify::fire("INDICATOR: ENTER SHORT", &msg);
                        println!("\n>>> {msg} <<<");
                    } else if (side == "BOTH" || side == "LONG") && z < -ENTRY_Z {
                        state = Side::Long;
                        entry_z = z;
                        entry_at = crate::logging::now_hms();
                        let msg = format!(
                            "ENTER LONG  z={z:+.2}  -> BUY {PAIR_A} / SELL {PAIR_B}  qty~{qty}"
                        );
                        info!(z, "enter_long");
                        crate::notify::fire("INDICATOR: ENTER LONG", &msg);
                        println!("\n>>> {msg} <<<");
                    }
                }
                Side::Long if z >= 0.0 => {
                    let msg = format!("EXIT LONG  z={z:+.2}  (entry z={entry_z:+.2} @ {entry_at})");
                    info!(z, "exit_long");
                    crate::notify::fire("INDICATOR: EXIT LONG", &msg);
                    println!("\n>>> {msg} <<<");
                    state = Side::Flat;
                }
                Side::Short if z <= 0.0 => {
                    let msg =
                        format!("EXIT SHORT  z={z:+.2}  (entry z={entry_z:+.2} @ {entry_at})");
                    info!(z, "exit_short");
                    crate::notify::fire("INDICATOR: EXIT SHORT", &msg);
                    println!("\n>>> {msg} <<<");
                    state = Side::Flat;
                }
                _ => {}
            }
        }

        let state_str = match state {
            Side::Flat => "FLAT",
            Side::Long => "LONG",
            Side::Short => "SHORT",
        };
        println!("\x1b[H\x1b[J");
        println!(
            "=== LIVE {} vs {}  [{}]  refresh={refresh_secs}s window={window} ===",
            PAIR_A,
            PAIR_B,
            crate::logging::now_hms()
        );
        println!(
            "{}={last_a:.2}  {PAIR_B}={last_b:.2}  spread(ln)={spread:.6}  z={z:+.2}",
            PAIR_A
        );
        println!(
            "state: {state_str}  qty~{}  ticks={ticks}  hist={}",
            ((capital / (last_a + last_b)) as u64).max(1),
            history.len()
        );
        let hint = if state == Side::Flat {
            "ENTER SHORT z>+2 | ENTER LONG z<-2 | exit z=0"
        } else {
            "waiting to exit (z should cross 0)"
        };
        println!("[{hint}]");
    }
}

async fn fetch_pair(client: &groww::Client) -> anyhow::Result<(f64, f64)> {
    let a = client.quote(PAIR_A).await?;
    let b = client.quote(PAIR_B).await?;
    Ok((a, b))
}
