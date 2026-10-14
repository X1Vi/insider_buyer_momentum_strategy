//! HDFCBANK / KOTAKBANK gap tracker (threaded) + replay stress test.
//!
//! Two producer threads update the two stock prices every ~2.5s into shared
//! state; an analyzer computes the log-spread z-score (calibrated from daily
//! 2022-2026) and fires a BUY on the LAGGARD when the gap is extreme (|z|>=3),
//! with the profit margin PRECOMPUTED (expected 5-day follow minus fees)
//! before the trade. Long-only (never shorts).
//!
//! Modes:
//!   tracker --replay backtesting/hdfc_ktak_daily.csv   (stress test)
//!   tracker --live   backtesting/hdfc_ktak_5m.csv      (threaded demo, 2.5s)
//!
//! Calibration (HDFCBANK.NS vs KOTAKBANK.NS, daily 2022-2026):
//!   spread = ln(pa) - 1.1622*ln(pb) + 0.2189 ; rolling-60d z-score.
//!   z>=3 (2022-2026, 5-day hold): 9 signals, ~67% win, avg follow ~2.9%
//!   (~₹12/unit) -> NET +₹5,010 (~₹557/trade) @ ₹15k. Win rate is real but
//!   NOT stable yearly (2024 was 25% win; tiny samples). Same-day exit drops
//!   win rate to ~46%; multi-day holds are higher-win. Filters (leader volume,
//!   index confirmation) nudge 67%->71% on small samples.

use std::collections::VecDeque;
use std::env;
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::Duration;

// ---- calibration ----
const BETA: f64 = 1.1622;
const ALPHA: f64 = -0.2189;
const WINDOW: usize = 60;
const WARMUP: usize = 60; // match rolling-60d calibration
const Z_ENTER: f64 = 3.0;
const Z_EXIT: f64 = 0.0;
const Z_STOP: f64 = 4.5;
const CAPITAL: f64 = 15_000.0;
const FEES: f64 = 35.0; // 2-leg intraday round trip at ~qty20 (Groww MIS)
const FOLLOW_RS_PER_UNIT: f64 = 9.0; // avg 5-day follow at z>=3 (₹/unit)
const HOLD_BARS: usize = 5;
const UPDATE_MS: u64 = 2500;

#[derive(Default, Clone, Copy)]
struct Slot {
    px: f64,
}

#[derive(Default)]
struct Shared {
    a: Slot,
    b: Slot,
}

fn spread(pa: f64, pb: f64) -> f64 {
    pa.ln() - BETA * pb.ln() - ALPHA
}

fn parse_csv(path: &str) -> Vec<(f64, f64)> {
    let txt = std::fs::read_to_string(path).unwrap_or_else(|e| {
        eprintln!("read {path}: {e}");
        std::process::exit(1);
    });
    let mut out = Vec::new();
    for line in txt.lines() {
        let p: Vec<&str> = line.split(',').collect();
        if p.len() < 3 {
            continue;
        }
        let pa: f64 = match p[1].trim().parse() {
            Ok(v) => v,
            Err(_) => continue,
        };
        let pb: f64 = match p[2].trim().parse() {
            Ok(v) => v,
            Err(_) => continue,
        };
        if pa > 0.0 && pb > 0.0 {
            out.push((pa, pb));
        }
    }
    out
}

/// Margin pre-check before entering a trade.
fn margin_precheck(z: f64, pa: f64, pb: f64) -> (String, u64, f64, f64, f64) {
    // z>0 => HDFC stretched expensive => KOTAK is the laggard (buy KOTAK)
    // z<0 => KOTAK stretched expensive => HDFC is the laggard (buy HDFC)
    let (laggard, px) = if z > 0.0 {
        ("KOTAKBANK", pb)
    } else {
        ("HDFCBANK", pa)
    };
    let qty = (CAPITAL / px).max(1.0) as u64;
    let expected_gross = FOLLOW_RS_PER_UNIT * qty as f64;
    let expected_net = expected_gross - FEES;
    let conf = ((z.abs() - Z_ENTER) / (Z_STOP - Z_ENTER) * 100.0).clamp(0.0, 100.0);
    (laggard.to_string(), qty, expected_gross, expected_net, conf)
}

/// Replay stress test: same logic over recorded daily closes.
fn stress(data: &[(f64, f64)]) {
    let mut hist: VecDeque<f64> = VecDeque::with_capacity(WINDOW);
    let (mut n, mut wins) = (0usize, 0usize);
    let (mut gross, mut fees) = (0.0f64, 0.0f64);
    let mut i = 0usize;
    let mut last_sig = -10i64; // keep rolling window CORRECT: advance bar-by-bar, gate non-overlap
    while i < data.len() {
        let (pa, pb) = data[i];
        let s = spread(pa, pb);
        hist.push_back(s);
        if hist.len() > WINDOW {
            hist.pop_front();
        }
        if hist.len() >= WARMUP
            && (i as i64) >= last_sig + HOLD_BARS as i64
            && i + HOLD_BARS < data.len()
        {
            let mean = hist.iter().sum::<f64>() / hist.len() as f64;
            let var =
                hist.iter().map(|x| (x - mean).powi(2)).sum::<f64>() / (hist.len() - 1) as f64;
            let z = (s - mean) / var.sqrt().max(1e-6);
            if z.abs() >= Z_ENTER {
                let f = spread(data[i + HOLD_BARS].0, data[i + HOLD_BARS].1) - s;
                let ok_dir = (z > 0.0 && f < 0.0) || (z < 0.0 && f > 0.0);
                let px_lag = if z > 0.0 { pb } else { pa };
                let qty = (CAPITAL / px_lag).max(1.0) as u64;
                gross += f.abs() * px_lag * qty as f64;
                fees += FEES;
                if ok_dir {
                    wins += 1;
                }
                n += 1;
                last_sig = i as i64;
            }
        }
        i += 1;
    }
    let net = gross - fees;
    println!("\n=== REPLAY STRESS (z>={Z_ENTER}, hold {HOLD_BARS} days, 2-leg fees ₹{FEES}) ===");
    println!("signals: {n}   win rate: {}%", 100 * wins / n.max(1));
    println!(
        "gross ≈ ₹{gross:.0}   fees ≈ ₹{fees:.0}   NET ≈ ₹{net:.0}   (₹{:.0}/trade)",
        net / n.max(1) as f64
    );
}

/// Threaded live demo: two producer threads, 2.5s updates, analyzer on main.
fn live(a_series: Vec<f64>, b_series: Vec<f64>) {
    let shared = Arc::new(Mutex::new(Shared::default()));

    let s1 = shared.clone();
    thread::spawn(move || {
        for px in a_series {
            {
                let mut g = s1.lock().unwrap();
                g.a = Slot { px };
            }
            thread::sleep(Duration::from_millis(UPDATE_MS));
        }
    });

    let s2 = shared.clone();
    thread::spawn(move || {
        for px in b_series {
            {
                let mut g = s2.lock().unwrap();
                g.b = Slot { px };
            }
            thread::sleep(Duration::from_millis(UPDATE_MS));
        }
    });

    let mut hist: VecDeque<f64> = VecDeque::with_capacity(WINDOW);
    let mut state = "FLAT";
    let mut entry_z = 0.0f64;
    let mut held = 0usize;
    let mut tick = 0u64;

    println!("=== LIVE tracker: HDFCBANK vs KOTAKBANK gap (threads, {UPDATE_MS}ms) ===");
    loop {
        thread::sleep(Duration::from_millis(UPDATE_MS));
        tick += 1;
        let (pa, pb) = {
            let g = shared.lock().unwrap();
            (g.a.px, g.b.px)
        };
        if pa <= 0.0 || pb <= 0.0 {
            continue;
        }
        let s = spread(pa, pb);
        hist.push_back(s);
        if hist.len() > WINDOW {
            hist.pop_front();
        }
        if hist.len() < WARMUP {
            println!(
                "[tick {tick}] warmup {}/{}  HDFC={pa:.2} KOTAK={pb:.2}",
                hist.len(),
                WINDOW
            );
            continue;
        }
        let mean = hist.iter().sum::<f64>() / hist.len() as f64;
        let var = hist.iter().map(|x| (x - mean).powi(2)).sum::<f64>() / hist.len() as f64;
        let z = (s - mean) / var.sqrt().max(1e-6);

        match state {
            "FLAT" => {
                if z.abs() >= Z_ENTER {
                    let (lag, qty, g, net, conf) = margin_precheck(z, pa, pb);
                    println!(
                        "\n>>> SIGNAL: BUY {lag}  qty={qty} @ ₹{px:.2}\n\
                         >>>   expected gross ≈ ₹{g:.0}  - fees ₹{FEES}  =  NET ≈ ₹{net:.0}\n\
                         >>>   confidence {conf:.0}%  (z={z:+.2}, stop at |z|>={Z_STOP})\n",
                        px = if z > 0.0 { pb } else { pa }
                    );
                    state = "POSITION";
                    entry_z = z;
                    held = 0;
                } else {
                    println!("[{tick}] FLAT  z={z:+.2}  HDFC={pa:.2} KOTAK={pb:.2}");
                }
            }
            "POSITION" => {
                held += 1;
                let exit = if entry_z > 0.0 {
                    z <= Z_EXIT
                } else {
                    z >= Z_EXIT
                };
                if exit || z.abs() >= Z_STOP || held >= HOLD_BARS {
                    let why = if exit {
                        "reverted to mean"
                    } else if z.abs() >= Z_STOP {
                        "STOP"
                    } else {
                        "hold window done"
                    };
                    println!("\n>>> EXIT position  ({why})  z={z:+.2}  held {held} ticks\n");
                    state = "FLAT";
                } else {
                    println!("[{tick}] HOLDING (long the laggard)  z={z:+.2}  held {held}");
                }
            }
            _ => {}
        }
    }
}

fn main() {
    let args: Vec<String> = env::args().skip(1).collect();
    let mode = args.first().map(|s| s.as_str()).unwrap_or("--live");
    let path = args
        .get(1)
        .map(|s| s.as_str())
        .unwrap_or("backtesting/hdfc_ktak_5m.csv");

    let data = parse_csv(path);
    if data.is_empty() {
        eprintln!("no data in {path}");
        std::process::exit(1);
    }
    println!("loaded {} bars from {path}", data.len());

    if mode == "--replay" {
        stress(&data);
    } else {
        let a: Vec<f64> = data.iter().map(|&(pa, _)| pa).collect();
        let b: Vec<f64> = data.iter().map(|&(_, pb)| pb).collect();
        live(a, b);
    }
}
