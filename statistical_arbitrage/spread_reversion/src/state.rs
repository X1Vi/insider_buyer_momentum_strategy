use std::collections::VecDeque;
use std::sync::{Arc, Mutex};
use std::time::Instant;

pub type SharedState = Arc<Mutex<AppState>>;

pub const MAX_EVENTS: usize = 300;
/// Dummy paper-trading trade size (units per leg) — not a real order quantity.
pub const TRADE_QTY: u32 = 100;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Direction {
    /// Long the spread: buy A, short B.
    Long,
    /// Short the spread: short A, buy B.
    Short,
}

#[derive(Debug, Clone)]
pub struct PositionView {
    pub direction: Direction,
    pub entry_spread: f64,
    pub entry_z: f64,
    pub entry_tick: u64,
    pub qty: u32,
    pub buy_symbol: &'static str,
    pub short_symbol: &'static str,
    pub unrealized_pnl: f64,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Level {
    Info,
    Warn,
    Error,
    Entry,
    Exit,
}

#[derive(Debug, Clone)]
pub struct EventLine {
    pub ts: String,
    pub level: Level,
    pub text: String,
}

/// A fresh entry/exit signal, shown as a flash banner and fired as a notification.
#[derive(Debug, Clone)]
pub struct Signal {
    pub title: String,
    pub body: String,
    pub at: Instant,
    pub good: bool,
}

pub struct AppState {
    pub connected: bool,
    pub tick: u64,
    pub price_a: f64,
    pub price_b: f64,
    pub spread: f64,
    pub mean: f64,
    pub std: f64,
    pub z: f64,
    pub history: VecDeque<f64>,
    pub window: usize,
    pub position: Option<PositionView>,
    pub session_pnl: f64,
    pub ledger_pnl: f64,
    pub events: VecDeque<EventLine>,
    pub last_signal: Option<Signal>,
    pub last_error: Option<String>,
}

impl AppState {
    pub fn new(window: usize, ledger_pnl: f64) -> Self {
        Self {
            connected: false,
            tick: 0,
            price_a: 0.0,
            price_b: 0.0,
            spread: 0.0,
            mean: 0.0,
            std: 0.0,
            z: 0.0,
            history: VecDeque::with_capacity(window),
            window,
            position: None,
            session_pnl: 0.0,
            ledger_pnl,
            events: VecDeque::with_capacity(MAX_EVENTS),
            last_signal: None,
            last_error: None,
        }
    }

    pub fn push_event(&mut self, level: Level, text: impl Into<String>) {
        self.events.push_back(EventLine {
            ts: crate::logging::now_hms(),
            level,
            text: text.into(),
        });
        if self.events.len() > MAX_EVENTS {
            self.events.pop_front();
        }
    }

    pub fn signal(&mut self, title: impl Into<String>, body: impl Into<String>, good: bool) {
        self.last_signal = Some(Signal {
            title: title.into(),
            body: body.into(),
            at: Instant::now(),
            good,
        });
    }
}
