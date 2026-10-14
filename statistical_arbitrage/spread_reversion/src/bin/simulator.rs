//! Simulator — separate component: replay stored market data like a live market,
//! run the spread-reversion indicator which outputs a CONFIDENCE SCORE per signal,
//! place trades from that confidence, and benchmark the OPTIMAL UNIVERSAL position %.
//!
//! Build/run:  cargo run --bin simulator -- [args]
//!
//! Args:
//!   --data <file.csv>      stored data (cols: timestamp,pa,pb or pa,pb; header ok)
//!   --bars <n>             bars to simulate (default 2000; all from file if unset)
//!   --start <i>            start replay at bar i
//!   --random-start         start at a random bar
//!   --window <n>           rolling z-score window (default 60)
//!   --capital <₹>          starting capital (default 20000)
//!   --pos-pct <n>          position size % of capital per trade (default 50)
//!   --conf-min <n>         minimum confidence score 0-100 to take a trade (default 0)
//!   --stop-pct <n>         stop loss as % of capital (default 2)
//!   --side <BOTH|LONG|SHORT>  which side to trade (default LONG)
//!   --benchmark            sweep pos-pct and report the optimal universal %
//!
//! Strategy: spread = ln(PA)-ln(PB); enter LONG z<-2 / SHORT z>+2; exit z crosses 0 or stop.
//! Confidence = how far z is beyond the entry threshold (0 at threshold, 100 at 5σ).

use std::collections::VecDeque;

const ENTRY_Z: f64 = 2.0;
const WARMUP: usize = 5;

#[derive(Clone, Copy, PartialEq)]
enum State {
    Flat,
    Long,
    Short,
}

struct Config {
    data: Option<String>,
    bars: usize,
    start: Option<usize>,
    random_start: bool,
    window: usize,
    capital: f64,
    pos_pct: f64,
    conf_min: f64,
    stop_pct: f64,
    side: String,
    benchmark: bool,
}

fn arg(args: &[String], name: &str) -> Option<String> {
    args.iter()
        .position(|a| a == name)
        .and_then(|i| args.get(i + 1))
        .cloned()
}
fn flag(args: &[String], name: &str) -> bool {
    args.iter().any(|a| a == name)
}

fn parse(args: &[String]) -> Config {
    let num = |n: &str, d: f64| arg(args, n).and_then(|s| s.parse().ok()).unwrap_or(d);
    Config {
        data: arg(args, "--data"),
        bars: num("--bars", 2000.0) as usize,
        start: arg(args, "--start").and_then(|s| s.parse().ok()),
        random_start: flag(args, "--random-start"),
        window: num("--window", 60.0) as usize,
        capital: num("--capital", 20000.0),
        pos_pct: num("--pos-pct", 50.0),
        conf_min: num("--conf-min", 0.0),
        stop_pct: num("--stop-pct", 2.0),
        side: arg(args, "--side").unwrap_or_else(|| "LONG".to_string()),
        benchmark: flag(args, "--benchmark"),
    }
}

// ---------------- data ----------------

fn load_data(cfg: &Config) -> Vec<(f64, f64)> {
    if let Some(path) = &cfg.data {
        let txt = std::fs::read_to_string(path).unwrap_or_else(|e| {
            eprintln!("read {path}: {e}");
            std::process::exit(1);
        });
        let mut out = Vec::new();
        for line in txt.lines() {
            let nums: Vec<f64> = line
                .split(|c: char| c == ',' || c == ' ' || c == '\t' || c == ':')
                .filter_map(|t| t.trim().parse::<f64>().ok())
                .collect();
            if nums.len() >= 2 {
                out.push((nums[nums.len() - 2], nums[nums.len() - 1]));
            }
        }
        if out.is_empty() {
            eprintln!("no numeric (pa,pb) rows found in {path}");
            std::process::exit(1);
        }
        out
    } else {
        synthetic(2000)
    }
}

fn synthetic(n: usize) -> Vec<(f64, f64)> {
    use std::time::{SystemTime, UNIX_EPOCH};
    let seed = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_secs();
    let mut s = seed;
    let mut rng = move || {
        s = s
            .wrapping_mul(6364136223846793005)
            .wrapping_add(1442695040888963407);
        (s >> 33) as f64 / (1u64 << 31) as f64 - 1.0
    };
    let (mut pa, mut pb) = (500.0f64, 495.0f64);
    let mut out = Vec::with_capacity(n);
    for _ in 0..n {
        let common = 0.0015 * rng(); // shared index move (both track Nifty Bank)
        let da = common + 0.0004 * rng(); // ETF-specific noise
        let db = common + 0.0004 * rng();
        pa *= da.exp();
        pb *= db.exp();
        out.push((pa, pb));
    }
    out
}

// ---------------- fees (Groww intraday MIS) ----------------

fn leg_fees(price: f64, qty: u64, side: &str) -> f64 {
    let v = price * qty as f64;
    let brk = (20.0f64).min(0.001 * v).max(5.0);
    let stt = if side == "SELL" { v * 0.00025 } else { 0.0 };
    let stp = if side == "BUY" { v * 0.00003 } else { 0.0 };
    let e = v * 0.0000297;
    let se = v * 0.000001;
    let ip = v * 0.000001;
    brk + stt + stp + e + se + ip + 0.18 * (brk + e + se + ip)
}

fn entry_fees(dir: &str, pa: f64, pb: f64, q: u64) -> f64 {
    if dir == "LONG" {
        leg_fees(pa, q, "BUY") + leg_fees(pb, q, "SELL")
    } else {
        leg_fees(pa, q, "SELL") + leg_fees(pb, q, "BUY")
    }
}

fn exit_fees(dir: &str, pa: f64, pb: f64, q: u64) -> f64 {
    if dir == "LONG" {
        leg_fees(pa, q, "SELL") + leg_fees(pb, q, "BUY")
    } else {
        leg_fees(pa, q, "BUY") + leg_fees(pb, q, "SELL")
    }
}

fn gross_pnl(dir: &str, epa: f64, epb: f64, pa: f64, pb: f64, q: u64) -> f64 {
    if dir == "LONG" {
        (pa - epa) * q as f64 - (pb - epb) * q as f64
    } else {
        (epa - pa) * q as f64 + (pb - epb) * q as f64
    }
}

// ---------------- indicator confidence ----------------

/// Confidence 0-100: 0 at the |z| = 2 threshold, 100 at |z| = 5.
fn entry_confidence(z: f64) -> f64 {
    let mag = z.abs();
    if mag <= ENTRY_Z {
        return 0.0;
    }
    ((mag - ENTRY_Z) / 3.0 * 100.0).clamp(0.0, 100.0)
}

// ---------------- simulation ----------------

struct Run {
    trades: usize,
    entries: usize,
    gross: f64,
    fees: f64,
    net: f64,
    final_eq: f64,
    max_dd: f64,
    sharpe: f64,
    wins: usize,
    longs: usize,
    shorts: usize,
    avg_conf: f64,
    stops: usize,
}

fn simulate(data: &[(f64, f64)], cfg: &Config, pos_pct: f64) -> Run {
    let mut hist: VecDeque<f64> = VecDeque::with_capacity(cfg.window);
    let mut state = State::Flat;
    let mut capital = cfg.capital;
    let (mut epa, mut epb, mut eqty, mut dir) = (0.0f64, 0.0f64, 0u64, String::new());
    let mut stop_rs = 0.0f64;
    let mut equity: Vec<f64> = Vec::with_capacity(data.len());
    let mut r = Run {
        trades: 0,
        entries: 0,
        gross: 0.0,
        fees: 0.0,
        net: 0.0,
        final_eq: 0.0,
        max_dd: 0.0,
        sharpe: 0.0,
        wins: 0,
        longs: 0,
        shorts: 0,
        avg_conf: 0.0,
        stops: 0,
    };

    for &(pa, pb) in data {
        let s = (pa / pb).ln();
        hist.push_back(s);
        if hist.len() > cfg.window {
            hist.pop_front();
        }
        let mut z = 0.0f64;
        if hist.len() >= WARMUP {
            let mean: f64 = hist.iter().sum::<f64>() / hist.len() as f64;
            let var: f64 = hist.iter().map(|x| (x - mean).powi(2)).sum::<f64>() / hist.len() as f64;
            z = (s - mean) / var.sqrt().max(1e-4);
        }

        let mut unreal = 0.0f64;
        match state {
            State::Flat => {
                let conf = entry_confidence(z);
                if conf >= cfg.conf_min {
                    let long_ok = (cfg.side == "BOTH" || cfg.side == "LONG") && z < -ENTRY_Z;
                    let short_ok = (cfg.side == "BOTH" || cfg.side == "SHORT") && z > ENTRY_Z;
                    if long_ok || short_ok {
                        let qty = ((capital * pos_pct / 100.0) / (pa + pb)).max(1.0) as u64;
                        epa = pa;
                        epb = pb;
                        eqty = qty;
                        stop_rs = capital * cfg.stop_pct / 100.0;
                        dir = if long_ok {
                            "LONG".to_string()
                        } else {
                            "SHORT".to_string()
                        };
                        state = if long_ok { State::Long } else { State::Short };
                        r.entries += 1;
                        r.avg_conf += conf;
                        if long_ok { r.longs += 1 } else { r.shorts += 1 }
                    }
                }
            }
            State::Long => {
                unreal = gross_pnl("LONG", epa, epb, pa, pb, eqty);
                if z >= 0.0 || unreal <= -stop_rs {
                    if unreal <= -stop_rs {
                        r.stops += 1
                    }
                    let g = unreal;
                    let f = entry_fees(&dir, epa, epb, eqty) + exit_fees(&dir, pa, pb, eqty);
                    let net = g - f;
                    r.gross += g;
                    r.fees += f;
                    capital += net;
                    r.trades += 1;
                    if net > 0.0 {
                        r.wins += 1
                    }
                    state = State::Flat;
                }
            }
            State::Short => {
                unreal = gross_pnl("SHORT", epa, epb, pa, pb, eqty);
                if z <= 0.0 || unreal <= -stop_rs {
                    if unreal <= -stop_rs {
                        r.stops += 1
                    }
                    let g = unreal;
                    let f = entry_fees(&dir, epa, epb, eqty) + exit_fees(&dir, pa, pb, eqty);
                    let net = g - f;
                    r.gross += g;
                    r.fees += f;
                    capital += net;
                    r.trades += 1;
                    if net > 0.0 {
                        r.wins += 1
                    }
                    state = State::Flat;
                }
            }
        }
        equity.push(capital + if state == State::Flat { 0.0 } else { unreal });
    }

    r.net = r.gross - r.fees;
    r.final_eq = *equity.last().unwrap_or(&cfg.capital);
    r.avg_conf = if r.entries > 0 {
        r.avg_conf / r.entries as f64
    } else {
        0.0
    };
    let (sharpe, mdd) = eq_metrics(&equity);
    r.sharpe = sharpe;
    r.max_dd = mdd;
    r
}

fn eq_metrics(eq: &[f64]) -> (f64, f64) {
    let mut rets = Vec::new();
    for w in eq.windows(2) {
        if w[0] > 0.0 {
            rets.push((w[1] - w[0]) / w[0]);
        }
    }
    let n = rets.len();
    let mean = if n > 0 {
        rets.iter().sum::<f64>() / n as f64
    } else {
        0.0
    };
    let var = if n > 1 {
        rets.iter().map(|x| (x - mean).powi(2)).sum::<f64>() / (n - 1) as f64
    } else {
        0.0
    };
    let sd = var.sqrt();
    let sharpe = if sd > 0.0 {
        mean / sd * (n as f64).sqrt()
    } else {
        0.0
    };
    let mut peak = f64::MIN;
    let mut mdd = 0.0f64;
    for &v in eq {
        peak = peak.max(v);
        if peak > 0.0 {
            mdd = mdd.max((peak - v) / peak);
        }
    }
    (sharpe, mdd)
}

// ---------------- main ----------------

fn report(label: &str, pos_pct: f64, r: &Run, capital: f64) {
    let ret = 100.0 * (r.final_eq / capital - 1.0);
    let (n, longs, shorts, stops) = (r.trades, r.longs, r.shorts, r.stops);
    let (g, f, net, fin, dd, sh, conf) = (
        r.gross,
        r.fees,
        r.net,
        r.final_eq,
        100.0 * r.max_dd,
        r.sharpe,
        r.avg_conf,
    );
    println!(
        "{label:>9} pos={pos_pct:>3.0}%  n={n:>3} (L{longs}/S{shorts}, {stops} stops)  \
         gross=₹{g:.0}  fees=₹{f:.0}  net=₹{net:.0}  final=₹{fin:.0} ({ret:+.1}%)  \
         maxDD={dd:.1}%  sharpe={sh:.2}  conf={conf:.0}"
    );
}

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let cfg = parse(&args);

    let mut data = load_data(&cfg);
    let start = if cfg.random_start {
        use std::time::{SystemTime, UNIX_EPOCH};
        let seed = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_secs();
        (seed as usize) % data.len()
    } else {
        cfg.start.unwrap_or(0).min(data.len().saturating_sub(1))
    };
    if start > 0 {
        data = data[start..].to_vec();
    }
    if data.len() > cfg.bars {
        data.truncate(cfg.bars);
    }
    if data.len() < WARMUP {
        eprintln!("too few bars ({}) for window", data.len());
        std::process::exit(1);
    }

    println!("=== SIMULATOR: BANKBEES vs SETFNIFBK ===");
    println!(
        "data={}  bars={}  start={}  window={}  capital=₹{:.0}  stop={}%  conf_min={}  side={}",
        cfg.data.as_deref().unwrap_or("synthetic"),
        data.len(),
        start,
        cfg.window,
        cfg.capital,
        cfg.stop_pct,
        cfg.conf_min,
        cfg.side
    );

    if cfg.benchmark {
        println!("\n--- benchmark: optimal universal position % ---");
        println!(
            "{:>9} {:>5} {:>10} {:>10} {:>12} {:>8} {:>8} {:>7}",
            "pos%", "trades", "gross₹", "fees₹", "net₹", "final₹", "maxDD%", "sharpe"
        );
        let mut best: Option<(f64, Run)> = None;
        let mut p = 5.0f64;
        while p <= 95.0 {
            let r = simulate(&data, &cfg, p);
            let (g, f, net, fin, dd, sh) = (
                r.gross,
                r.fees,
                r.net,
                r.final_eq,
                100.0 * r.max_dd,
                r.sharpe,
            );
            println!(
                "{p:>7.0}%  {t:>5}  {g:>10.0}  {f:>10.0}  {net:>12.0}  {fin:>12.0}  {dd:>8.1}  {sh:>7.2}",
                t = r.trades
            );
            if r.net > 0.0 {
                if best.as_ref().map(|(_, b)| r.net > b.net).unwrap_or(true) {
                    best = Some((p, r));
                }
            }
            p += 5.0;
        }
        match best {
            Some((p, r)) => {
                println!(
                    "\nOPTIMAL UNIVERSAL % = {p:.0}%  (net ₹{:.0}, final ₹{:.0}, maxDD {:.1}%)",
                    r.net,
                    r.final_eq,
                    100.0 * r.max_dd
                );
            }
            None => println!("\nNo positive-net position % found at any size."),
        }
    } else {
        let r = simulate(&data, &cfg, cfg.pos_pct);
        println!("\n--- single run ---");
        report("run", cfg.pos_pct, &r, cfg.capital);
        println!(
            "win rate (net): {:.0}%  expectancy/trade: ₹{:.2}  avg confidence: {:.0}/100",
            100.0 * r.wins as f64 / r.trades.max(1) as f64,
            r.net / r.trades.max(1) as f64,
            r.avg_conf
        );
        println!("\nTip: run with --benchmark to find the optimal universal position %.");
    }
}
