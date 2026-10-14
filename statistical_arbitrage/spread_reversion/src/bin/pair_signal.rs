#![forbid(unsafe_code)]
//! pair_signal.rs — minimal intraday BUY / SELL signal tool (SIGNALS ONLY).
//!
//! What it does
//! ------------
//! Watches two ETF pairs and prints, for each, a BUY / SELL / FLAT signal plus a
//! confidence (0-100%):
//!
//!     1. BANKBEES  / SETFNIFBK      (primary)
//!     2. NIFTYBEES / SETFNIF50      (secondary)
//!
//! The rule (trend-aware mean reversion):
//!     spread = ln(price_A) - ln(price_B)                (causal, one per tick)
//!     z      = (spread - rolling_mean) / rolling_std     (backward-looking)
//!     trend  = (EMA_fast(price) - EMA_slow(price)) / price   per leg
//!     z <= -entry AND trend_A >= trend_B  -> BUY  (long A, short B)
//!     z >= +entry AND trend_B >= trend_A  -> SELL (short A, long B)
//!     z crosses 0 -> close   |z| >= stop -> stop out
//! The trend gate keeps us from mean-reverting against the stronger leg.
//! Set PAIR_SIGNAL_TREND=off to disable the gate (plain baseline).
//! All history comes only from ticks already seen — no look-ahead.
//!
//! It does NOT place orders. It only prints / logs signals and writes a small
//! SVG chart. Groww credentials come from env vars (see `fetch_token`).
//!
//! Reused code: `spread_reversion::groww::Client` (token + live quote).
//!
//! Modes (default = live TUI, so plain `cargo run` just works)
//! ----------------------------------------------------------
//!   cargo run                 live full-screen TUI (q / Esc / Ctrl-C quits)
//!   cargo run -- --sim [DIR]  backtest gate off vs on from local CSVs
//!                             (default DIR `backtesting/data`)
//!   cargo run -- --once       fetch one live tick and print it (cron-friendly)
//!   cargo run -- --loop SECS  poll forever, printing each cycle
//!
//! Env (all optional)
//! ------------------
//!   GROWW_ACCESS_TOKEN                 pre-generated token (used if non-empty)
//!   GROWW_API_KEY, GROWW_API_SECRET    else the token is RENEWED each run via
//!                                      the Groww checksum flow
//!   PAIR_SIGNAL_WINDOW  (30)           rolling z-score look-back, in ticks
//!   PAIR_SIGNAL_ENTRY   (2.0)          |z| needed to open
//!   PAIR_SIGNAL_STOP    (3.0)          |z| that forces an exit
//!   PAIR_SIGNAL_DIR     (signals)      where history/signals/SVG are written
//!   PAIR_SIGNAL_GAP_MS  (5000)         pause between Groww calls (rate limit)

use std::collections::HashMap;
use std::fs;
use std::path::{Path, PathBuf};
use std::time::Duration;

use ratatui::Terminal;
use ratatui::backend::CrosstermBackend;
use ratatui::layout::{Constraint, Direction, Layout};
use ratatui::style::{Color, Modifier, Style};
use ratatui::text::{Line, Span};
use ratatui::widgets::{Block, Borders, Paragraph};
use spread_reversion::groww::Client;

/// The pairs we watch, in order. Each entry is (leg A, leg B).
const PAIRS: [(&str, &str); 2] = [("BANKBEES", "SETFNIFBK"), ("NIFTYBEES", "SETFNIF50")];

// ----------------------------------------------------------------- small utils

fn env_str(key: &str, default: &str) -> String {
    std::env::var(key).unwrap_or_else(|_| default.to_string())
}

fn env_f64(key: &str, default: f64) -> f64 {
    std::env::var(key)
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(default)
}

fn env_usize(key: &str, default: usize) -> usize {
    std::env::var(key)
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(default)
}

/// Confidence in the current action, 0-100.
/// Inside the entry zone it scales from the entry threshold up to the stop;
/// outside it reports how close we are to triggering.
fn confidence(z: f64, entry: f64, stop: f64) -> f64 {
    let a = z.abs();
    let span = (stop - entry).max(1e-9);
    if a >= entry {
        (100.0 * (a - entry) / span).clamp(0.0, 100.0)
    } else {
        (100.0 * a / entry).clamp(0.0, 100.0)
    }
}

// ---------------------------------------------------------------------- ticks

/// One observation of all four prices at a point in time. NaN = missing.
#[derive(Clone, Copy)]
struct Tick {
    px: [[f64; 2]; 2], // px[pair][leg]: [0] = leg A, [1] = leg B
}

impl Tick {
    fn empty() -> Self {
        Self {
            px: [[f64::NAN; 2]; 2],
        }
    }
}

// --------------------------------------------------------------------- engine

#[derive(Clone)]
struct Event {
    tick: usize,
    pair: usize,
    kind: &'static str, // BUY | SELL | EXIT | STOP
    z: f64,
    conf: f64,
}

struct Engine {
    window: usize,
    entry: f64,
    stop: f64,
    spreads: [Vec<f64>; 2], // per pair, one spread per tick (NaN if missing)
    state: [i8; 2],         // 0 flat, +1 long A / short B, -1 short A / long B
    entry_z: [f64; 2],
    last_z: [f64; 2],
    events: Vec<Event>,
    // --- trend awareness: a fast/slow EMA per leg, so the signal knows
    //     which ETF is currently the stronger one. ---
    ema_fast_n: usize,
    ema_slow_n: usize,
    use_trend: bool,
    ema_f: [[f64; 2]; 2], // [pair][leg] fast EMA
    ema_s: [[f64; 2]; 2], // [pair][leg] slow EMA
    trend: [[f64; 2]; 2], // [pair][leg] (fast − slow) / price
    seeded: [[bool; 2]; 2],
}

impl Engine {
    fn new(
        window: usize,
        entry: f64,
        stop: f64,
        ema_fast_n: usize,
        ema_slow_n: usize,
        use_trend: bool,
    ) -> Self {
        let fast = ema_fast_n.max(1);
        let slow = ema_slow_n.max(fast + 1);
        Self {
            window,
            entry,
            stop,
            spreads: [Vec::new(), Vec::new()],
            state: [0, 0],
            entry_z: [0.0, 0.0],
            last_z: [0.0, 0.0],
            events: Vec::new(),
            ema_fast_n: fast,
            ema_slow_n: slow,
            use_trend,
            ema_f: [[0.0; 2]; 2],
            ema_s: [[0.0; 2]; 2],
            trend: [[0.0; 2]; 2],
            seeded: [[false; 2]; 2],
        }
    }

    /// Update one leg's EMAs from a new price and refresh its trend score.
    /// trend > 0 -> leg is above its own recent average (uptrend);
    /// trend < 0 -> downtrend. Normalised by price so legs are comparable.
    fn update_ema(&mut self, p: usize, leg: usize, price: f64) {
        let kf = 2.0 / (self.ema_fast_n as f64 + 1.0);
        let ks = 2.0 / (self.ema_slow_n as f64 + 1.0);
        if !self.seeded[p][leg] {
            self.ema_f[p][leg] = price;
            self.ema_s[p][leg] = price;
            self.seeded[p][leg] = true;
        } else {
            self.ema_f[p][leg] += kf * (price - self.ema_f[p][leg]);
            self.ema_s[p][leg] += ks * (price - self.ema_s[p][leg]);
        }
        self.trend[p][leg] = if price > 0.0 {
            (self.ema_f[p][leg] - self.ema_s[p][leg]) / price
        } else {
            0.0
        };
    }

    /// Causal rolling z-score of the latest spread, using only past values.
    fn z(&self, p: usize) -> Option<f64> {
        let v = &self.spreads[p];
        if v.len() < self.window {
            return None;
        }
        let w = &v[v.len() - self.window..];
        if w.iter().any(|x| !x.is_finite()) {
            return None; // pair had missing prices inside the window
        }
        let mean = w.iter().sum::<f64>() / w.len() as f64;
        let var = w.iter().map(|x| (x - mean).powi(2)).sum::<f64>() / w.len() as f64;
        let sd = var.sqrt();
        if sd < 1e-12 {
            return None;
        }
        Some((v[v.len() - 1] - mean) / sd)
    }

    /// The trend gate: long the spread only when leg A is at least as strong
    /// as leg B; short it only when B is at least as strong as A. The idea is
    /// to mean-revert into the relatively strong leg instead of fighting it.
    /// With `use_trend == false` the gate is disabled (baseline behaviour).
    fn allows_long(&self, p: usize) -> bool {
        !self.use_trend || self.trend[p][0] >= self.trend[p][1]
    }
    fn allows_short(&self, p: usize) -> bool {
        !self.use_trend || self.trend[p][1] >= self.trend[p][0]
    }

    /// True when z wants to act but the trend gate blocks it (for display).
    fn gated(&self, p: usize) -> bool {
        if self.state[p] != 0 {
            return false;
        }
        let z = self.last_z[p];
        (z <= -self.entry && !self.allows_long(p)) || (z >= self.entry && !self.allows_short(p))
    }

    fn decide(&mut self, p: usize, i: usize, z: f64) {
        match self.state[p] {
            0 => {
                if z <= -self.entry && self.allows_long(p) {
                    self.state[p] = 1;
                    self.entry_z[p] = z;
                    self.events.push(Event {
                        tick: i,
                        pair: p,
                        kind: "BUY",
                        z,
                        conf: confidence(z, self.entry, self.stop),
                    });
                } else if z >= self.entry && self.allows_short(p) {
                    self.state[p] = -1;
                    self.entry_z[p] = z;
                    self.events.push(Event {
                        tick: i,
                        pair: p,
                        kind: "SELL",
                        z,
                        conf: confidence(z, self.entry, self.stop),
                    });
                }
            }
            1 if z <= -self.stop || z >= 0.0 => {
                self.state[p] = 0;
                let kind = if z <= -self.stop { "STOP" } else { "EXIT" };
                self.events.push(Event {
                    tick: i,
                    pair: p,
                    kind,
                    z,
                    conf: 100.0,
                });
            }
            -1 if z >= self.stop || z <= 0.0 => {
                self.state[p] = 0;
                let kind = if z >= self.stop { "STOP" } else { "EXIT" };
                self.events.push(Event {
                    tick: i,
                    pair: p,
                    kind,
                    z,
                    conf: 100.0,
                });
            }
            _ => {}
        }
    }

    fn on_tick(&mut self, i: usize, t: &Tick) {
        for p in 0..PAIRS.len() {
            let a = t.px[p][0];
            let b = t.px[p][1];
            if !(a > 0.0) || !(b > 0.0) {
                self.spreads[p].push(f64::NAN);
                continue;
            }
            self.update_ema(p, 0, a);
            self.update_ema(p, 1, b);
            self.spreads[p].push((a / b).ln());
            if let Some(z) = self.z(p) {
                self.last_z[p] = z;
                self.decide(p, i, z);
            }
        }
    }

    /// Latest readout per pair: (signal, confidence, z).
    fn readout(&self, p: usize) -> (&'static str, f64, f64) {
        let z = self.last_z[p];
        let signal = match self.state[p] {
            1 => "BUY",
            -1 => "SELL",
            _ if z <= -self.entry && self.allows_long(p) => "BUY",
            _ if z >= self.entry && self.allows_short(p) => "SELL",
            _ => "FLAT",
        };
        (signal, confidence(z, self.entry, self.stop), z)
    }
}

// ------------------------------------------------------------------ I/O: CSV

fn parse_f64(s: &str) -> f64 {
    s.trim().parse().unwrap_or(f64::NAN)
}

/// Load `ts,open,high,low,close,volume` and return ts -> close.
fn load_close(path: &Path) -> anyhow::Result<HashMap<String, f64>> {
    let text = fs::read_to_string(path)?;
    let mut out = HashMap::new();
    for line in text.lines().skip(1) {
        let f: Vec<&str> = line.split(',').collect();
        if f.len() >= 5 {
            out.insert(f[0].trim().to_string(), parse_f64(f[4]));
        }
    }
    Ok(out)
}

/// Replay data from four local CSVs (BANKBEES, SETFNIFBK, NIFTYBEES, SETFNIF50).
fn load_sim(dir: &Path) -> anyhow::Result<Vec<Tick>> {
    let a = load_close(&dir.join("BANKBEES.csv"))?;
    let b = load_close(&dir.join("SETFNIFBK.csv"))?;
    let c = load_close(&dir.join("NIFTYBEES.csv")).unwrap_or_default();
    let d = load_close(&dir.join("SETFNIF50.csv")).unwrap_or_default();

    let mut ts: Vec<&String> = a.keys().collect();
    ts.sort();
    let mut ticks = Vec::with_capacity(ts.len());
    for t in ts {
        let mut tick = Tick::empty();
        tick.px[0] = [a[t], *b.get(t).unwrap_or(&f64::NAN)];
        tick.px[1] = [
            *c.get(t).unwrap_or(&f64::NAN),
            *d.get(t).unwrap_or(&f64::NAN),
        ];
        ticks.push(tick);
    }
    Ok(ticks)
}

/// history.csv format: ts,bankbees,setfnifbk,niftybees,setfnif50
fn load_history(path: &Path) -> Vec<(String, Tick)> {
    let Ok(text) = fs::read_to_string(path) else {
        return Vec::new();
    };
    let mut out = Vec::new();
    for line in text.lines().skip(1) {
        let f: Vec<&str> = line.split(',').collect();
        if f.len() < 5 {
            continue;
        }
        let mut t = Tick::empty();
        t.px[0] = [parse_f64(f[1]), parse_f64(f[2])];
        t.px[1] = [parse_f64(f[3]), parse_f64(f[4])];
        out.push((f[0].trim().to_string(), t));
    }
    out
}

fn append_history(path: &Path, ts: &str, t: &Tick) -> std::io::Result<()> {
    let exists = path.exists();
    let mut f = fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(path)?;
    use std::io::Write;
    if !exists {
        writeln!(f, "ts,bankbees,setfnifbk,niftybees,setfnif50")?;
    }
    writeln!(
        f,
        "{ts},{:.4},{:.4},{:.4},{:.4}",
        t.px[0][0], t.px[0][1], t.px[1][0], t.px[1][1]
    )
}

fn append_signals(path: &Path, ts: &str, eng: &Engine, since_tick: usize) -> std::io::Result<()> {
    let exists = path.exists();
    let mut f = fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(path)?;
    use std::io::Write;
    if !exists {
        writeln!(f, "ts,pair,signal,confidence,z")?;
    }
    for e in eng.events.iter().filter(|e| e.tick >= since_tick) {
        writeln!(
            f,
            "{ts},{}/{},{},{:.0},{:+.3}",
            PAIRS[e.pair].0, PAIRS[e.pair].1, e.kind, e.conf, e.z
        )?;
    }
    Ok(())
}

/// Append a readout row for every pair to signals.csv (schedule-friendly log).
fn append_readout(path: &Path, ts: &str, eng: &Engine) -> std::io::Result<()> {
    let exists = path.exists();
    let mut f = fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(path)?;
    use std::io::Write;
    if !exists {
        writeln!(f, "ts,pair,signal,confidence,z")?;
    }
    for p in 0..PAIRS.len() {
        let (sig, conf, z) = eng.readout(p);
        writeln!(
            f,
            "{ts},{}/{},{},{:.0},{:+.3}",
            PAIRS[p].0, PAIRS[p].1, sig, conf, z
        )?;
    }
    Ok(())
}

// ---------------------------------------------------------------- SVG chart

const BUY: &str = "#0a7d22";
const SELL: &str = "#c62828";
const EXIT: &str = "#666666";

fn write_svg(path: &Path, ticks: &[Tick], eng: &Engine) -> std::io::Result<()> {
    let w = 1100.0;
    let panel_h = 260.0;
    let top = 70.0;
    let left = 80.0;
    let right = 130.0;
    let h = top + panel_h * PAIRS.len() as f64 + 30.0;
    let n = ticks.len().max(1);

    let mut s = String::new();
    s.push_str(&format!(
        "<svg xmlns='http://www.w3.org/2000/svg' width='{w}' height='{h}' viewBox='0 0 {w} {h}'>"
    ));
    s.push_str("<rect width='100%' height='100%' fill='#ffffff'/>");
    s.push_str(&format!(
        "<text x='24' y='34' font-family='monospace' font-size='19' fill='#111'>pair_signal — spread + BUY/SELL (signals only, no orders)</text>"
    ));
    // Legend
    s.push_str(&format!(
        "<polygon points='24,52 30,42 36,52' fill='{BUY}'/><text x='42' y='52' font-family='monospace' font-size='13'>BUY</text>"
    ));
    s.push_str(&format!(
        "<polygon points='80,42 86,52 92,42' fill='{SELL}'/><text x='98' y='52' font-family='monospace' font-size='13'>SELL</text>"
    ));
    s.push_str(&format!(
        "<text x='146' y='52' font-family='monospace' font-size='13' fill='{EXIT}'>EXIT/STOP</text>"
    ));

    for p in 0..PAIRS.len() {
        let y0 = top + p as f64 * panel_h;
        let y_bottom = y0 + panel_h - 40.0;
        let y_top = y0 + 24.0;

        // Current readout in the panel title.
        let (sig, conf, z) = eng.readout(p);
        s.push_str(&format!(
            "<text x='{left}' y='{}' font-family='monospace' font-size='15' fill='#111'>{}/{}  |  signal={} conf={:.0}%  z={:+0.2}</text>",
            y0 + 16.0, PAIRS[p].0, PAIRS[p].1, sig, conf, z
        ));

        // Gather finite spread points and their min/max.
        let pts: Vec<(usize, f64)> = eng.spreads[p]
            .iter()
            .enumerate()
            .filter(|(_, v)| v.is_finite())
            .map(|(i, v)| (i, *v))
            .collect();
        if pts.len() < 2 {
            s.push_str(&format!(
                "<text x='{left}' y='{}' font-family='monospace' font-size='13' fill='#888'>(not enough data yet)</text>",
                y0 + 90.0
            ));
            continue;
        }
        let (mn, mx) = pts.iter().fold((f64::MAX, f64::MIN), |(lo, hi), (_, v)| {
            (lo.min(*v), hi.max(*v))
        });
        let span = (mx - mn).max(1e-9);
        let x_of = |i: usize| left + (i as f64 / (n - 1).max(1) as f64) * (w - left - right);
        let y_of = |v: f64| y_bottom - ((v - mn) / span) * (y_bottom - y_top);

        // Frame + axis extremes.
        s.push_str(&format!(
            "<rect x='{left}' y='{y_top}' width='{}' height='{}' fill='#fafafa' stroke='#dddddd'/>",
            w - left - right,
            y_bottom - y_top
        ));
        s.push_str(&format!(
            "<text x='8' y='{}' font-family='monospace' font-size='11' fill='#777'>{mx:.5}</text>",
            y_top + 10.0
        ));
        s.push_str(&format!(
            "<text x='8' y='{}' font-family='monospace' font-size='11' fill='#777'>{mn:.5}</text>",
            y_bottom
        ));

        // Spread line.
        let mut poly = String::new();
        for (i, v) in &pts {
            poly.push_str(&format!("{:.1},{:.1} ", x_of(*i), y_of(*v)));
        }
        s.push_str(&format!(
            "<polyline points='{}' fill='none' stroke='#1a237e' stroke-width='1.4'/>",
            poly.trim()
        ));

        // Signal markers.
        for e in eng.events.iter().filter(|e| e.pair == p && e.tick < n) {
            let x = x_of(e.tick);
            // place the marker at the spread value on that tick when available
            let y = eng.spreads[p]
                .get(e.tick)
                .filter(|v| v.is_finite())
                .map(|v| y_of(*v))
                .unwrap_or(y_bottom);
            match e.kind {
                "BUY" => s.push_str(&format!(
                    "<polygon points='{x:.1},{:.1} {:.1},{:.1} {:.1},{:.1}' fill='{BUY}' stroke='#fff'/>",
                    y - 7.0, x - 6.0, y + 4.0, x + 6.0, y + 4.0
                )),
                "SELL" => s.push_str(&format!(
                    "<polygon points='{x:.1},{:.1} {:.1},{:.1} {:.1},{:.1}' fill='{SELL}' stroke='#fff'/>",
                    y + 7.0, x - 6.0, y - 4.0, x + 6.0, y - 4.0
                )),
                _ => s.push_str(&format!(
                    "<text x='{:.1}' y='{:.1}' font-family='monospace' font-size='13' fill='{EXIT}'>x</text>",
                    x - 4.0, y + 4.0
                )),
            }
        }
    }
    s.push_str("</svg>");
    fs::write(path, s)
}

// -------------------------------------------------------------------- token

/// Resolve a Groww token. By default we RENEW one from
/// GROWW_API_KEY / GROWW_API_SECRET via the checksum flow (the Groww session
/// must be approved for the day). If no key/secret is present we fall back to a
/// pre-generated GROWW_ACCESS_TOKEN. Set PAIR_SIGNAL_ENV_TOKEN=1 to prefer the
/// env token even when key/secret exist.
async fn fetch_token() -> anyhow::Result<String> {
    let prefer_env = std::env::var("PAIR_SIGNAL_ENV_TOKEN")
        .map(|v| !v.is_empty() && v != "0")
        .unwrap_or(false);
    let env_tok = || {
        std::env::var("GROWW_ACCESS_TOKEN")
            .ok()
            .map(|t| {
                t.trim()
                    .trim_matches('"')
                    .trim_matches('\'')
                    .trim()
                    .to_string()
            })
            .filter(|t| !t.is_empty())
    };
    if prefer_env {
        if let Some(t) = env_tok() {
            return Ok(t);
        }
    }
    if let (Ok(k), Ok(s)) = (
        std::env::var("GROWW_API_KEY"),
        std::env::var("GROWW_API_SECRET"),
    ) {
        match Client::login_with_api_key(&k, &s).await {
            Ok(t) => return Ok(t),
            Err(e) => {
                if let Some(t) = env_tok() {
                    eprintln!("WARN: token renew failed ({e}); using GROWW_ACCESS_TOKEN");
                    return Ok(t);
                }
                return Err(e);
            }
        }
    }
    env_tok()
        .ok_or_else(|| anyhow::anyhow!("set GROWW_API_KEY/GROWW_API_SECRET or GROWW_ACCESS_TOKEN"))
}

/// Fetch one tick for all four symbols IN PARALLEL. Failures become NaN.
/// One round = one call per symbol, so each symbol is polled once per cycle.
async fn fetch_tick(client: &Client) -> Tick {
    let (r0, r1, r2, r3) = tokio::join!(
        client.quote(PAIRS[0].0),
        client.quote(PAIRS[0].1),
        client.quote(PAIRS[1].0),
        client.quote(PAIRS[1].1),
    );
    let mut vals = [f64::NAN; 4];
    let syms = [PAIRS[0].0, PAIRS[0].1, PAIRS[1].0, PAIRS[1].1];
    for (i, r) in [r0, r1, r2, r3].into_iter().enumerate() {
        match r {
            Ok(v) => vals[i] = v,
            Err(e) => eprintln!("WARN: quote {} failed: {e}", syms[i]),
        }
    }
    Tick {
        px: [[vals[0], vals[1]], [vals[2], vals[3]]],
    }
}

// ----------------------------------------------------------------------- TUI

/// Restores the terminal on any exit (including early returns / errors).
struct TermGuard;

impl Drop for TermGuard {
    fn drop(&mut self) {
        use std::io::Write;
        crossterm::terminal::disable_raw_mode().ok();
        let mut out = std::io::stdout();
        crossterm::execute!(out, crossterm::terminal::LeaveAlternateScreen).ok();
        let _ = out.flush();
    }
}

fn conf_bar(conf: f64) -> String {
    let filled = ((conf / 100.0 * 20.0).round() as usize).min(20);
    format!("{}{}", "█".repeat(filled), "░".repeat(20 - filled))
}

/// One bordered panel per pair: prices, spread, z, signal, confidence bar.
fn pair_panel(p: usize, eng: &Engine, a: f64, b: f64, ticks: usize) -> Paragraph<'static> {
    let (sig, conf, z) = eng.readout(p);
    let (color, arrow) = match sig {
        "BUY" => (Color::Green, "▲"),
        "SELL" => (Color::Red, "▼"),
        _ => (Color::DarkGray, "•"),
    };
    let spread = eng.spreads[p].last().copied().unwrap_or(f64::NAN);
    let pos = match eng.state[p] {
        1 => "LONG",
        -1 => "SHORT",
        _ => "FLAT",
    };
    let action = match sig {
        "BUY" => format!("long {} / short {}", PAIRS[p].0, PAIRS[p].1),
        "SELL" => format!("short {} / long {}", PAIRS[p].0, PAIRS[p].1),
        _ => "no position — waiting".to_string(),
    };
    let warm = if ticks < eng.window {
        format!("warming up {ticks}/{}", eng.window)
    } else {
        format!("ticks {ticks}")
    };
    let gate = if !eng.use_trend {
        "off".to_string()
    } else if eng.gated(p) {
        "BLOCKED by trend".to_string()
    } else if eng.state[p] != 0 {
        "in position".to_string()
    } else {
        "open".to_string()
    };
    let lines = vec![
        Line::from(format!(
            "  {:<9} {:>9.2}        {:<9} {:>9.2}",
            PAIRS[p].0, a, PAIRS[p].1, b
        )),
        Line::from(format!(
            "  trend  {} {:>+9.5}   {} {:>+9.5}    gate: {gate}",
            PAIRS[p].0, eng.trend[p][0], PAIRS[p].1, eng.trend[p][1]
        )),
        Line::from(format!(
            "  spread(ln) {:>10.6}    z {:>+6.2}    position {:<5}    {warm}",
            spread, z, pos
        )),
        Line::from(vec![Span::styled(
            format!("  SIGNAL  {arrow} {sig}"),
            Style::default().fg(color).add_modifier(Modifier::BOLD),
        )]),
        Line::from(format!("  confidence  {:>5.0}%  {}", conf, conf_bar(conf))),
        Line::from(format!("  action: {action}")),
    ];
    Paragraph::new(lines).block(
        Block::default()
            .borders(Borders::ALL)
            .title(format!(" {}/{} ", PAIRS[p].0, PAIRS[p].1)),
    )
}

/// Full-screen live view. Updates every fetch cycle; `q` / Esc / Ctrl-C quits.
async fn run_tui(
    client: &Client,
    window: usize,
    entry: f64,
    stop: f64,
    ema_fast_n: usize,
    ema_slow_n: usize,
    use_trend: bool,
    gap_ms: u64,
    dir: &Path,
) -> anyhow::Result<()> {
    use crossterm::event::{self, Event, KeyCode, KeyEventKind, KeyModifiers};
    use std::io::stdout;
    use std::sync::Arc;
    use std::sync::atomic::{AtomicBool, Ordering};

    crossterm::terminal::enable_raw_mode()?;
    crossterm::execute!(stdout(), crossterm::terminal::EnterAlternateScreen)?;
    let _guard = TermGuard;
    let mut terminal = Terminal::new(CrosstermBackend::new(stdout()))?;

    // Keyboard watcher → sets `quit`.
    let quit = Arc::new(AtomicBool::new(false));
    let q2 = quit.clone();
    std::thread::spawn(move || {
        loop {
            if q2.load(Ordering::Relaxed) {
                break;
            }
            if event::poll(Duration::from_millis(150)).unwrap_or(false) {
                if let Ok(Event::Key(k)) = event::read() {
                    if k.kind == KeyEventKind::Press {
                        let ctrl_c = k.modifiers.contains(KeyModifiers::CONTROL)
                            && k.code == KeyCode::Char('c');
                        if ctrl_c || k.code == KeyCode::Char('q') || k.code == KeyCode::Esc {
                            q2.store(true, Ordering::Relaxed);
                            break;
                        }
                    }
                }
            }
        }
    });

    // Warm up from history on disk so we don't restart the rolling window.
    let hist_path = dir.join("history.csv");
    let sig_path = dir.join("signals.csv");
    let hist = load_history(&hist_path);
    let mut eng = Engine::new(window, entry, stop, ema_fast_n, ema_slow_n, use_trend);
    let mut last_a = [f64::NAN; 2];
    let mut last_b = [f64::NAN; 2];
    for (i, (_, t)) in hist.iter().enumerate() {
        eng.on_tick(i, t);
        last_a = [t.px[0][0], t.px[1][0]];
        last_b = [t.px[0][1], t.px[1][1]];
    }
    let mut ticks = hist.len();
    let mut ts = String::from("--");
    let mut log: Vec<String> = Vec::new();

    while !quit.load(Ordering::Relaxed) {
        let (sig_a, conf_a, z_a) = eng.readout(0);
        let (sig_b, conf_b, z_b) = eng.readout(1);
        terminal.draw(|f| {
            let chunks = Layout::default()
                .direction(Direction::Vertical)
                .constraints([
                    Constraint::Length(3),
                    Constraint::Length(9),
                    Constraint::Length(9),
                    Constraint::Min(4),
                    Constraint::Length(1),
                ])
                .split(f.area());

            let header = Paragraph::new(vec![
                Line::from(Span::styled(
                    "PAIR SIGNAL  —  live intraday  (signals only, NO orders)",
                    Style::default().fg(Color::Cyan).add_modifier(Modifier::BOLD),
                )),
                Line::from(format!(
                    "window={window}  entry={entry:.2}  stop={stop:.2}   last update {ts}",
                )),
            ])
            .block(Block::default().borders(Borders::ALL));
            f.render_widget(header, chunks[0]);
            f.render_widget(pair_panel(0, &eng, last_a[0], last_b[0], ticks), chunks[1]);
            f.render_widget(pair_panel(1, &eng, last_a[1], last_b[1], ticks), chunks[2]);

            let max_lines = chunks[3].height.saturating_sub(2) as usize;
            let lines: Vec<Line> = log
                .iter()
                .rev()
                .take(max_lines)
                .rev()
                .map(|s| Line::from(s.clone()))
                .collect();
            let events = Paragraph::new(lines).block(
                Block::default()
                    .borders(Borders::ALL)
                    .title(" recent signals "),
            );
            f.render_widget(events, chunks[3]);

            let prog = format!(
                "  {}/{}  zB={z_a:+.2} ({sig_a} {conf_a:.0}%)   zN={z_b:+.2} ({sig_b} {conf_b:.0}%)   [q] quit",
                PAIRS[0].0, PAIRS[1].0
            );
            f.render_widget(
                Paragraph::new(prog).style(Style::default().fg(Color::DarkGray)),
                chunks[4],
            );
        })?;

        // Fetch a fresh tick and fold it into the engine.
        let tick = fetch_tick(client).await;
        ts = chrono::Local::now().format("%Y-%m-%d %H:%M:%S").to_string();
        let before = eng.events.len();
        eng.on_tick(ticks, &tick);
        ticks += 1;
        last_a = [tick.px[0][0], tick.px[1][0]];
        last_b = [tick.px[0][1], tick.px[1][1]];
        for e in &eng.events[before..] {
            log.push(format!(
                "{ts}  {}/{}  {:<5}  z={:+.2}  conf={:.0}%",
                PAIRS[e.pair].0, PAIRS[e.pair].1, e.kind, e.z, e.conf
            ));
        }
        append_history(&hist_path, &ts, &tick).ok();
        append_signals(&sig_path, &ts, &eng, ticks - 1).ok();

        // Pace the next round (one call per symbol per round).
        tokio::time::sleep(Duration::from_millis(gap_ms)).await;
    }

    quit.store(true, Ordering::Relaxed);
    Ok(())
}

// --------------------------------------------------------------------- main

/// Runtime parameters (from env, with defaults).
#[derive(Clone, Copy)]
struct Params {
    window: usize,
    entry: f64,
    stop: f64,
    ema_fast: usize,
    ema_slow: usize,
    use_trend: bool,
    bpy: f64, // bars per year, for annualising the backtest Sharpe
}

fn print_readout(eng: &Engine, n_ticks: usize) {
    println!(
        "=== pair_signal  window={} entry={:.2} stop={:.2}  ema {}/{}  trend {:<3}  ticks={} ===",
        eng.window,
        eng.entry,
        eng.stop,
        eng.ema_fast_n,
        eng.ema_slow_n,
        if eng.use_trend { "on" } else { "off" },
        n_ticks
    );
    for p in 0..PAIRS.len() {
        let (sig, conf, z) = eng.readout(p);
        let action = match sig {
            "BUY" => format!("-> long {} / short {}", PAIRS[p].0, PAIRS[p].1),
            "SELL" => format!("-> short {} / long {}", PAIRS[p].0, PAIRS[p].1),
            _ if eng.gated(p) => "trend gate blocked".to_string(),
            _ => "(no position)".to_string(),
        };
        println!(
            "  {:<22} z={:+.2}  tA={:+.4} tB={:+.4}  signal={:<4} conf={:>3.0}%  {}",
            format!("{}/{}", PAIRS[p].0, PAIRS[p].1),
            z,
            eng.trend[p][0],
            eng.trend[p][1],
            sig,
            conf,
            action
        );
    }
}

// ------------------------------------------------------------- backtest (sim)

#[derive(Clone, Copy, Default)]
struct BtStats {
    ret: f64,
    sharpe: f64,
    dd: f64,
    trades: usize,
}

/// Replay ticks through the engine and score the long/short spread position.
/// Causal: a position decided at tick i earns tick i+1's return.
fn backtest(ticks: &[Tick], p: &Params, use_trend: bool, fees: f64) -> BtStats {
    let mut eng = Engine::new(p.window, p.entry, p.stop, p.ema_fast, p.ema_slow, use_trend);
    let mut pos: Vec<[f64; 2]> = Vec::with_capacity(ticks.len());
    for (i, t) in ticks.iter().enumerate() {
        eng.on_tick(i, t);
        pos.push([eng.state[0] as f64, eng.state[1] as f64]);
    }
    let mut rets: Vec<f64> = Vec::new();
    for i in 1..ticks.len() {
        for pr in 0..2 {
            let (a0, b0) = (ticks[i - 1].px[pr][0], ticks[i - 1].px[pr][1]);
            let (a1, b1) = (ticks[i].px[pr][0], ticks[i].px[pr][1]);
            if a0 > 0.0 && b0 > 0.0 && a1 > 0.0 && b1 > 0.0 {
                let r = (a1 / b1) / (a0 / b0) - 1.0;
                let turn = (pos[i][pr] - pos[i - 1][pr]).abs();
                rets.push(pos[i - 1][pr] * r - turn * fees);
            }
        }
    }
    let n = rets.len();
    if n < 30 {
        return BtStats::default();
    }
    let mean = rets.iter().sum::<f64>() / n as f64;
    let var = rets.iter().map(|x| (x - mean).powi(2)).sum::<f64>() / n as f64;
    let sd = var.sqrt();
    let sharpe = if sd > 0.0 {
        mean / sd * p.bpy.sqrt()
    } else {
        0.0
    };
    let (mut eq, mut peak, mut dd) = (1.0_f64, 1.0_f64, 0.0_f64);
    for r in &rets {
        eq *= 1.0 + r;
        peak = peak.max(eq);
        dd = dd.min(eq / peak - 1.0);
    }
    let trades = eng
        .events
        .iter()
        .filter(|e| e.kind == "BUY" || e.kind == "SELL")
        .count();
    BtStats {
        ret: eq - 1.0,
        sharpe,
        dd,
        trades,
    }
}

/// Backtest both the plain pair signal (gate off) and the trend-gated version
/// (gate on) on local data, and write a chart of the gated run.
fn run_backtest(data_dir: &Path, out_dir: &Path, p: &Params) -> anyhow::Result<()> {
    let ticks = load_sim(data_dir)?;
    println!(
        "=== BACKTEST  {} bars from {} ===",
        ticks.len(),
        data_dir.display()
    );
    println!(
        "  window={} entry={:.2} stop={:.2}  ema {}/{}  (gate = ETF trend agreement)",
        p.window, p.entry, p.stop, p.ema_fast, p.ema_slow
    );
    println!(
        "  {:>10} {:>6} {:>9} {:>9} {:>9} {:>8}",
        "fees/side", "gate", "Sharpe", "totRet", "MaxDD", "trades"
    );
    for bp in [0.0_f64, 1.8, 4.5, 13.5] {
        for (label, use_trend) in [("off", false), ("on", true)] {
            let s = backtest(&ticks, p, use_trend, bp / 1e4);
            println!(
                "  {:>8.1}bp {:>6} {:>9.2} {:>8.2}% {:>8.2}% {:>8}",
                bp,
                label,
                s.sharpe,
                s.ret * 100.0,
                s.dd * 100.0,
                s.trades
            );
        }
    }
    // Chart of the default (gated) run.
    let mut eng = Engine::new(
        p.window,
        p.entry,
        p.stop,
        p.ema_fast,
        p.ema_slow,
        p.use_trend,
    );
    for (i, t) in ticks.iter().enumerate() {
        eng.on_tick(i, t);
    }
    let svg = out_dir.join("pair_signals_backtest.svg");
    write_svg(&svg, &ticks, &eng)?;
    println!("  svg -> {}", svg.display());
    Ok(())
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    let args: Vec<String> = std::env::args().skip(1).collect();
    dotenvy::dotenv().ok();
    let dir = PathBuf::from(env_str("PAIR_SIGNAL_DIR", "signals"));
    fs::create_dir_all(&dir)?;

    let p = Params {
        window: env_usize("PAIR_SIGNAL_WINDOW", 30).max(3),
        entry: env_f64("PAIR_SIGNAL_ENTRY", 2.0),
        stop: env_f64("PAIR_SIGNAL_STOP", 3.0),
        ema_fast: env_usize("PAIR_SIGNAL_EMA_FAST", 9),
        ema_slow: env_usize("PAIR_SIGNAL_EMA_SLOW", 21),
        use_trend: !matches!(
            env_str("PAIR_SIGNAL_TREND", "on")
                .to_ascii_lowercase()
                .as_str(),
            "off" | "0" | "false" | "no"
        ),
        bpy: env_f64("PAIR_SIGNAL_BPY", 252.0),
    };
    let p = Params {
        stop: p.stop.max(p.entry + 1e-6),
        ..p
    };

    // ---- BACKTEST: replay local CSVs, no credentials needed -----------------
    if let Some(i) = args.iter().position(|a| a == "--sim" || a == "--backtest") {
        let data_dir = PathBuf::from(
            args.get(i + 1)
                .filter(|s| !s.starts_with("--"))
                .cloned()
                .unwrap_or_else(|| "backtesting/data".to_string()),
        );
        return run_backtest(&data_dir, &dir, &p);
    }

    // ---- LIVE: token + quotes ----------------------------------------------
    let gap_ms = env_usize("PAIR_SIGNAL_GAP_MS", 5000) as u64;
    let loop_secs = args.iter().position(|a| a == "--loop").map(|i| {
        args.get(i + 1)
            .and_then(|v| v.parse::<u64>().ok())
            .unwrap_or(30)
    });
    let want_once = args.iter().any(|a| a == "--once");
    let want_tui = args.iter().any(|a| a == "--tui") || (!want_once && loop_secs.is_none());

    let token = fetch_token().await?;
    let client = Client::new(&token);
    let hist_path = dir.join("history.csv");
    let sig_path = dir.join("signals.csv");

    // Default (no args) = full-screen TUI; q / Esc / Ctrl-C quits.
    if want_tui && !want_once {
        return run_tui(
            &client,
            p.window,
            p.entry,
            p.stop,
            p.ema_fast,
            p.ema_slow,
            p.use_trend,
            gap_ms,
            &dir,
        )
        .await;
    }

    loop {
        let ts = chrono::Local::now().format("%Y-%m-%d %H:%M:%S").to_string();
        let tick = fetch_tick(&client).await;

        // Persist this tick, then recompute state over the full history.
        append_history(&hist_path, &ts, &tick)?;
        let hist = load_history(&hist_path);
        let mut eng = Engine::new(
            p.window,
            p.entry,
            p.stop,
            p.ema_fast,
            p.ema_slow,
            p.use_trend,
        );
        for (i, (_, t)) in hist.iter().enumerate() {
            eng.on_tick(i, t);
        }
        append_signals(&sig_path, &ts, &eng, hist.len().saturating_sub(1))?;
        append_readout(&sig_path, &ts, &eng)?;

        let ticks: Vec<Tick> = hist.iter().map(|(_, t)| *t).collect();
        let svg = dir.join("pair_signals.svg");
        write_svg(&svg, &ticks, &eng)?;

        print_readout(&eng, hist.len());
        println!("  svg -> {}", svg.display());

        if want_once {
            break;
        }
        tokio::time::sleep(Duration::from_secs(loop_secs.unwrap_or(30))).await;
    }
    Ok(())
}
