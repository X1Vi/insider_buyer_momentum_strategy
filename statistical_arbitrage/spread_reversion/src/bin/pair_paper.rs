#![forbid(unsafe_code)]
//! pair_paper.rs — ₹ capital test of the pair_signal logic (VERBATIM copy).
//!
//! This is a standalone test. It does NOT modify or import `pair_signal.rs`;
//! the signal engine below is copied verbatim from it (same spread, same
//! rolling z-score, same EMA trend gate, same entry/exit rules), so results are
//! directly comparable.
//!
//! What it adds on top of the signal logic: an actual ₹ account.
//!   - start capital (default ₹8,000),
//!   - capital split 50/50 between the two pairs, each pair's position is the
//!     same ±1 ratio position the live tool takes,
//!   - realistic Groww intraday (MIS) costs charged on BOTH legs of the pair
//!     (brokerage + STT + exchange txn + GST + SEBI + stamp),
//!   - reports final ₹ value, total return, max drawdown, Sharpe, trades, fees.
//!
//! Run:
//!   cargo run --bin pair_paper -- [DATA_DIR]
//!   (default DATA_DIR = backtesting/data_15m)

use std::collections::HashMap;
use std::path::{Path, PathBuf};

// ---------------------------------------------------------- config / pairs

const PAIRS: [(&str, &str); 2] = [("BANKBEES", "SETFNIFBK"), ("NIFTYBEES", "SETFNIF50")];
const START_CASH: f64 = 12_000.0; // ₹ default account size
const WINDOW: usize = 30;
const ENTRY: f64 = 2.0;
const STOP: f64 = 3.0;
const EMA_FAST: usize = 9;
const EMA_SLOW: usize = 21;
const BPY: f64 = 6_300.0; // 15-min bars/year = 25 bars/day * 252

/// How we express the ratio signal as actual legs.
#[derive(Clone, Copy, PartialEq)]
enum Mode {
    /// Dollar-neutral pair: long the cheap leg AND short the rich leg (2 legs).
    Pair,
    /// Long only: buy whichever leg is cheap (1 leg).
    Long,
    /// Short only: sell whichever leg is rich (1 leg).
    Short,
}

/// Given a ratio position (-1/0/+1) and a mode, return the per-leg directions.
/// leg A = PAIRS[p].0, leg B = PAIRS[p].1. +1 = long that leg, -1 = short it.
fn leg_dirs(mode: Mode, pos: f64) -> (f64, f64) {
    match (mode, pos) {
        (_, 0.0) => (0.0, 0.0),
        // pos = +1 means A cheap -> long A / short B
        (Mode::Pair, 1.0) => (1.0, -1.0),
        (Mode::Pair, -1.0) => (-1.0, 1.0),
        // Long-only: buy the cheap leg (A when pos=+1, B when pos=-1)
        (Mode::Long, 1.0) => (1.0, 0.0),
        (Mode::Long, -1.0) => (0.0, 1.0),
        // Short-only: sell the rich leg (B when pos=+1, A when pos=-1)
        (Mode::Short, 1.0) => (0.0, -1.0),
        (Mode::Short, -1.0) => (-1.0, 0.0),
        _ => (0.0, 0.0),
    }
}

fn confidence(z: f64, entry: f64, stop: f64) -> f64 {
    let a = z.abs();
    let span = (stop - entry).max(1e-9);
    if a >= entry {
        (100.0 * (a - entry) / span).clamp(0.0, 100.0)
    } else {
        (100.0 * a / entry).clamp(0.0, 100.0)
    }
}

// ---------------------------------------------------------------- ticks / CSV

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

fn parse_f64(s: &str) -> f64 {
    s.trim().parse().unwrap_or(f64::NAN)
}

fn load_close(path: &Path) -> anyhow::Result<HashMap<String, f64>> {
    let text = std::fs::read_to_string(path)?;
    let mut out = HashMap::new();
    for line in text.lines().skip(1) {
        let f: Vec<&str> = line.split(',').collect();
        if f.len() >= 5 {
            out.insert(f[0].trim().to_string(), parse_f64(f[4]));
        }
    }
    Ok(out)
}

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

// -------------------------------------------------------------- engine (verbatim)

#[derive(Clone)]
struct Event {
    tick: usize,
    pair: usize,
    kind: &'static str,
    z: f64,
    conf: f64,
}

struct Engine {
    window: usize,
    entry: f64,
    stop: f64,
    spreads: [Vec<f64>; 2],
    state: [i8; 2],
    entry_z: [f64; 2],
    last_z: [f64; 2],
    events: Vec<Event>,
    ema_fast_n: usize,
    ema_slow_n: usize,
    use_trend: bool,
    ema_f: [[f64; 2]; 2],
    ema_s: [[f64; 2]; 2],
    trend: [[f64; 2]; 2],
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

    fn z(&self, p: usize) -> Option<f64> {
        let v = &self.spreads[p];
        if v.len() < self.window {
            return None;
        }
        let w = &v[v.len() - self.window..];
        if w.iter().any(|x| !x.is_finite()) {
            return None;
        }
        let mean = w.iter().sum::<f64>() / w.len() as f64;
        let var = w.iter().map(|x| (x - mean).powi(2)).sum::<f64>() / w.len() as f64;
        let sd = var.sqrt();
        if sd < 1e-12 {
            return None;
        }
        Some((v[v.len() - 1] - mean) / sd)
    }

    fn allows_long(&self, p: usize) -> bool {
        !self.use_trend || self.trend[p][0] >= self.trend[p][1]
    }
    fn allows_short(&self, p: usize) -> bool {
        !self.use_trend || self.trend[p][1] >= self.trend[p][0]
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
}

// -------------------------------------------------------- Groww cost model

/// Groww intraday (MIS) cost to change the pair position by 1 unit, expressed
/// as a fraction of the pair's ratio notional (both legs combined).
///
/// Components per leg (NSE cash, intraday): brokerage min(₹20, 0.05%) per order,
/// STT 0.025% on the sell, exchange txn 0.00297%, GST 18% on (brokerage+txn),
/// SEBI 0.0001%, stamp 0.003% on the buy.
fn groww_mis_fee_per_turnover(leg_notional: f64) -> f64 {
    let n = leg_notional.max(1.0);
    let brok = (0.0005 * n).min(20.0) / n; // per-order brokerage fraction
    let txn = 0.0000297;
    let gst = 0.18 * (brok + txn);
    let sebi = 0.000001;
    let stamp = 0.00003;
    let stt_sell = 0.00025;
    let buy_leg = brok + txn + gst + sebi + stamp;
    let sell_leg = brok + stt_sell + txn + gst + sebi;
    (buy_leg + sell_leg) / 2.0 // open = buy A + sell B, over the pair notional
}

// ------------------------------------------------------------- capital test

struct Report {
    final_value: f64,
    total_ret: f64,
    max_dd: f64,
    sharpe: f64,
    trades: usize,
    fees_paid: f64,
}

fn run_capital(ticks: &[Tick], use_trend: bool, capital: f64, leverage: f64, mode: Mode) -> Report {
    let mut eng = Engine::new(WINDOW, ENTRY, STOP, EMA_FAST, EMA_SLOW, use_trend);
    let mut pos = vec![[0.0_f64; 2]; ticks.len()];
    for (i, t) in ticks.iter().enumerate() {
        eng.on_tick(i, t);
        pos[i] = [eng.state[0] as f64, eng.state[1] as f64];
    }

    let mut equity = capital;
    let (mut peak, mut max_dd) = (equity, 0.0_f64);
    let (mut fees_paid, mut trades) = (0.0_f64, 0usize);
    let mut rets: Vec<f64> = Vec::new();
    let sleeve = 0.5; // half the account per pair
    let lev = leverage.max(1.0);

    for i in 1..ticks.len() {
        let mut r = 0.0;
        let mut any = false;
        for pr in 0..2 {
            let (a0, b0) = (ticks[i - 1].px[pr][0], ticks[i - 1].px[pr][1]);
            let (a1, b1) = (ticks[i].px[pr][0], ticks[i].px[pr][1]);
            if !(a0 > 0.0 && b0 > 0.0 && a1 > 0.0 && b1 > 0.0) {
                continue;
            }
            any = true;
            let ra = a1 / a0 - 1.0;
            let rb = b1 / b0 - 1.0;
            // Convert the ratio position into actual leg directions for this mode.
            let (da1, db1) = leg_dirs(mode, pos[i][pr]);
            let (da0, db0) = leg_dirs(mode, pos[i - 1][pr]);
            let n_legs = ((da1 != 0.0) as u8 + (db1 != 0.0) as u8) as f64;
            if n_legs == 0.0 {
                continue;
            }
            let w = 1.0 / n_legs; // equal weight per active leg
            // Gross P&L = each leg's return * its direction, weighted.
            let gross = (da1 * ra + db1 * rb) * w * sleeve * lev;
            // Fees are charged per LEG that changes (1 leg for long/short-only,
            // 2 legs for the neutral pair) — this is the "double fee" effect.
            let turn = (da1 - da0).abs() + (db1 - db0).abs();
            if turn > 0.0 {
                trades += 1;
            }
            let leg_notional = equity * sleeve * w * lev;
            let fee_frac = groww_mis_fee_per_turnover(leg_notional);
            let cost = turn * fee_frac * w * sleeve * lev;
            r += gross - cost;
            fees_paid += cost * equity;
        }
        if !any {
            continue;
        }
        equity *= 1.0 + r;
        if equity <= 0.0 {
            equity = 0.0;
            break;
        }
        peak = peak.max(equity);
        max_dd = max_dd.min(equity / peak - 1.0);
        rets.push(r);
    }

    let n = rets.len().max(1) as f64;
    let mean = rets.iter().sum::<f64>() / n;
    let var = rets.iter().map(|x| (x - mean).powi(2)).sum::<f64>() / n;
    let sd = var.sqrt();
    let sharpe = if sd > 0.0 {
        mean / sd * BPY.sqrt()
    } else {
        0.0
    };

    Report {
        final_value: equity,
        total_ret: equity / capital - 1.0,
        max_dd,
        sharpe,
        trades,
        fees_paid,
    }
}

fn main() -> anyhow::Result<()> {
    let mut args = std::env::args().skip(1);
    let data_dir = PathBuf::from(
        args.next()
            .unwrap_or_else(|| "backtesting/data_15m".to_string()),
    );
    let capital: f64 = args
        .next()
        .and_then(|s| s.parse().ok())
        .unwrap_or(START_CASH);
    // Groww intraday (MIS) commonly offers up to 5x. Sweep unless one is given.
    let leverages: Vec<f64> = match args.next().and_then(|s| s.parse::<f64>().ok()) {
        Some(l) => vec![l],
        None => vec![1.0, 2.0, 5.0],
    };

    let ticks = load_sim(&data_dir)?;
    let bars_finite = ticks.iter().filter(|t| t.px[0][0].is_finite()).count();
    println!("=== pair_paper  (verbatim pair_signal logic + ₹ account) ===");
    println!(
        "  data     : {} ({} bars, {} sessions @ 25 bars/day)",
        data_dir.display(),
        ticks.len(),
        bars_finite / 25
    );
    println!("  costs    : Groww intraday MIS (charged per leg)");
    println!("  rule     : window={WINDOW} entry={ENTRY} stop={STOP} ema={EMA_FAST}/{EMA_SLOW}");
    println!("  capital  : ₹{capital:.0}\n");

    println!(
        "  {:>6} {:>5} {:>6} {:>12} {:>11} {:>10} {:>9} {:>8} {:>11}",
        "mode", "lev", "gate", "final ₹", "totRet", "MaxDD", "Sharpe", "trades", "fees ₹"
    );
    let modes = [
        ("pair", Mode::Pair),   // long cheap + short rich, 2 legs (double fees)
        ("long", Mode::Long),   // buy the cheap leg only, 1 leg
        ("short", Mode::Short), // sell the rich leg only, 1 leg
    ];
    for (mlabel, mode) in modes {
        for lev in &leverages {
            for (glabel, use_trend) in [("off", false), ("on", true)] {
                let r = run_capital(&ticks, use_trend, capital, *lev, mode);
                println!(
                    "  {:>6} {:>4.0}x {:>6} {:>12.2} {:>10.2}% {:>9.2}% {:>9.2} {:>8} {:>11.2}",
                    mlabel,
                    lev,
                    glabel,
                    r.final_value,
                    r.total_ret * 100.0,
                    r.max_dd * 100.0,
                    r.sharpe,
                    r.trades,
                    r.fees_paid
                );
            }
        }
    }
    Ok(())
}
