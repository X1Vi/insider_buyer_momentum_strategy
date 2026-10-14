use std::sync::Arc;
use tokio::time::{Duration, interval};
use tracing::{error, info};

use crate::groww;
use crate::state::{Direction, Level, PositionView, SharedState, TRADE_QTY};
use crate::{PAIR_A, PAIR_B};

struct Position {
    direction: Direction,
    entry_spread: f64,
    entry_z: f64,
    entry_tick: u64,
}

pub async fn run(
    client: Arc<groww::Client>,
    state: SharedState,
    interval_secs: u64,
    window: usize,
) {
    let mut timer = interval(Duration::from_secs(interval_secs));
    let mut tick = 0u64;
    let mut history: Vec<f64> = Vec::with_capacity(window);
    let mut position: Option<Position> = None;
    let mut total_pnl = state.lock().unwrap().ledger_pnl;
    let mut summary_counter = 0u64;

    // Send a status summary push every SUMMARY_EVERY_TICKS ticks (~10 min at 30s).
    const SUMMARY_EVERY_TICKS: u64 = 20;

    loop {
        timer.tick().await;
        tick += 1;

        let (price_a, price_b) = match fetch_pair(&client).await {
            Ok(p) => p,
            Err(e) => {
                error!(tick, error = %e, "fetch_failed");
                let mut s = state.lock().unwrap();
                s.connected = false;
                s.last_error = Some(e.to_string());
                s.push_event(Level::Error, format!("fetch failed (tick {tick}): {e}"));
                continue;
            }
        };

        let spread = price_a - price_b;
        history.push(spread);
        if history.len() > window {
            history.remove(0);
        }

        if history.len() < 5 {
            info!(tick, spread, "warming_up");
            let mut s = state.lock().unwrap();
            s.connected = true;
            s.last_error = None;
            s.tick = tick;
            s.price_a = price_a;
            s.price_b = price_b;
            s.spread = spread;
            sync_history(&mut s, &history);
            s.push_event(
                Level::Info,
                format!("warming up ({}/{window}) spread={spread:.4}", history.len()),
            );
            continue;
        }

        let mean = history.iter().sum::<f64>() / history.len() as f64;
        let var = history.iter().map(|s| (s - mean).powi(2)).sum::<f64>() / history.len() as f64;
        let std = var.sqrt().max(0.001);
        let z = (spread - mean) / std;

        // Lock only for the synchronous state updates; drop the guard before the
        // async notify calls below so the future stays Send.
        {
            let mut s = state.lock().unwrap();
            s.connected = true;
            s.last_error = None;
            s.tick = tick;
            s.price_a = price_a;
            s.price_b = price_b;
            s.spread = spread;
            s.mean = mean;
            s.std = std;
            s.z = z;
            sync_history(&mut s, &history);

            match &position {
                None => {
                    if z > 2.0 {
                        position = Some(Position {
                            direction: Direction::Short,
                            entry_spread: spread,
                            entry_z: z,
                            entry_tick: tick,
                        });
                        let msg = format!(
                            "SHORT {PAIR_A} / BUY {PAIR_B}  qty={TRADE_QTY}  z={z:+.2}  spread={spread:.4}"
                        );
                        info!(tick, z, spread, "signal_short_spread");
                        s.push_event(Level::Entry, msg.clone());
                        s.signal("SIGNAL: SHORT spread", msg, true);
                        s.position = position_view(&position);
                    } else if z < -2.0 {
                        position = Some(Position {
                            direction: Direction::Long,
                            entry_spread: spread,
                            entry_z: z,
                            entry_tick: tick,
                        });
                        let msg = format!(
                            "BUY {PAIR_A} / SHORT {PAIR_B}  qty={TRADE_QTY}  z={z:+.2}  spread={spread:.4}"
                        );
                        info!(tick, z, spread, "signal_long_spread");
                        s.push_event(Level::Entry, msg.clone());
                        s.signal("SIGNAL: LONG spread", msg, true);
                        s.position = position_view(&position);
                    } else {
                        info!(tick, z, spread, "idle");
                        s.push_event(Level::Info, format!("idle  z={z:+.3}  spread={spread:.4}"));
                    }
                }
                Some(pos) => {
                    let pnl = match pos.direction {
                        Direction::Long => (spread - pos.entry_spread) * TRADE_QTY as f64,
                        Direction::Short => (pos.entry_spread - spread) * TRADE_QTY as f64,
                    };

                    s.position = position_view(&position).map(|mut p| {
                        p.unrealized_pnl = pnl;
                        p
                    });
                    s.push_event(
                        Level::Info,
                        format!(
                            "hold  pnl=\u{20b9}{pnl:+.2}  z={z:+.3}  ticks={}",
                            tick - pos.entry_tick
                        ),
                    );

                    let should_exit = match pos.direction {
                        Direction::Long => z >= 0.0,
                        Direction::Short => z <= 0.0,
                    };

                    if should_exit {
                        total_pnl += pnl;
                        let dir_str = if matches!(pos.direction, Direction::Long) {
                            "LONG"
                        } else {
                            "SHORT"
                        };
                        info!(tick, pnl, total_pnl, dir = dir_str, "exit");
                        let msg = format!(
                            "EXIT {dir_str}  pnl=\u{20b9}{pnl:+.2}  total_pnl=\u{20b9}{total_pnl:+.2}  held={} ticks",
                            tick - pos.entry_tick
                        );
                        s.push_event(Level::Exit, msg.clone());
                        s.signal("POSITION CLOSED", msg, pnl >= 0.0);
                        s.session_pnl = total_pnl;
                        s.ledger_pnl = total_pnl;
                        s.position = None;
                        position = None;
                    }
                }
            }
        }

        // Async notifications, fired after the guard is released.
        match &position {
            Some(pos) if pos.entry_tick == tick => {
                let (title, body) = match pos.direction {
                    Direction::Short => (
                        "Spread Reversion — SHORT signal",
                        format!(
                            "SHORT {TRADE_QTY} {PAIR_A} / BUY {TRADE_QTY} {PAIR_B}  z={z:+.2}  spread={spread:.4}"
                        ),
                    ),
                    Direction::Long => (
                        "Spread Reversion — LONG signal",
                        format!(
                            "BUY {TRADE_QTY} {PAIR_A} / SHORT {TRADE_QTY} {PAIR_B}  z={z:+.2}  spread={spread:.4}"
                        ),
                    ),
                };
                crate::notify::fire(title, &body);
                crate::notify::pushover(title, &body, crate::notify::PRIORITY_HIGH).await;
            }
            _ => {}
        }
    }
}

fn position_view(position: &Option<Position>) -> Option<PositionView> {
    let pos = position.as_ref()?;
    let (buy_symbol, short_symbol) = match pos.direction {
        Direction::Long => (PAIR_A, PAIR_B),
        Direction::Short => (PAIR_B, PAIR_A),
    };
    Some(PositionView {
        direction: pos.direction,
        entry_spread: pos.entry_spread,
        entry_z: pos.entry_z,
        entry_tick: pos.entry_tick,
        qty: TRADE_QTY,
        buy_symbol,
        short_symbol,
        unrealized_pnl: 0.0,
    })
}

fn sync_history(s: &mut crate::state::AppState, history: &[f64]) {
    s.history.clear();
    s.history.extend(history.iter().copied());
}

async fn fetch_pair(client: &groww::Client) -> anyhow::Result<(f64, f64)> {
    let a = client.quote(PAIR_A).await?;
    let b = client.quote(PAIR_B).await?;
    Ok((a, b))
}
