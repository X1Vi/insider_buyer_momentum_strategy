//! ML v3 WATCH scanner (TUI) — AXISBANK / KOTAKBANK / TATASTEEL.
//! Machine screens (WATCH), human times the entry:
//!   watch for the model's WATCH signal, then wait for lower-low -> rejection
//!   -> upward break before entering. No BUY/SELL triggers — WATCH only.
//! Low latency: rolling computations + XGBoost inference in-process (µs).
//! Usage:
//!   scanner --sim                  replay daily CSVs at 2.5s/bar
//!   scanner (live, needs token)    Groww get_ltp, seeds from CSVs
//!   --sound (or SCANNER_SOUND=1)   enable the RISE-alert beep (off by default)
use std::collections::HashMap;
use std::fs;
use std::io;
use std::sync::Arc;
use std::time::{Duration, Instant};

use serde::Deserialize;
use sha2::{Digest, Sha256};

use crossterm::event::{self, Event, KeyCode, KeyModifiers};
use crossterm::execute;
use crossterm::terminal::{
    EnterAlternateScreen, LeaveAlternateScreen, disable_raw_mode, enable_raw_mode,
};
use ratatui::Terminal;
use ratatui::backend::CrosstermBackend;
use ratatui::layout::{Constraint, Layout};
use ratatui::style::{Color, Modifier, Style};
use ratatui::text::{Line, Span};
use ratatui::widgets::{Block, Borders, List, ListItem, Paragraph};

const W_BETA: usize = 252;
const W_Z: usize = 60;
const Z_ARM: f64 = -3.0;
const OBS: usize = 10;
const GATE_ZREC: f64 = 0.5;
const GATE_PX: f64 = 0.02;
const THRESH: f64 = 0.5; // T2 WATCH threshold
const RISE_ALERT_PCT: f64 = 0.005; // alert when a leg rises >=0.5% since last poll
const BASE_SCORE: f64 = -0.29783444391579905; // logit(T2 mean 0.426086) — XGBoost auto base_score (see backtesting/train_export.py)
const MODEL_PATH: &str = "backtesting/model_dump.txt";
const BAR_MS: u64 = 2500;

// ----------------------------- model -----------------------------

struct Node {
    feature: i32,
    threshold: f64,
    yes: usize,
    no: usize,
    is_leaf: bool,
    leaf: f64,
}
type Tree = Vec<Node>;

fn parse_tail_int(tail: &str, key: &str) -> usize {
    if let Some(p) = tail.find(key) {
        let s = &tail[p + key.len()..];
        let e = s.find(|c: char| !c.is_ascii_digit()).unwrap_or(s.len());
        s[..e].trim().parse().unwrap_or(0)
    } else {
        0
    }
}

fn parse_model(path: &str) -> Vec<Tree> {
    let txt = fs::read_to_string(path).unwrap_or_else(|e| {
        eprintln!("read {path}: {e}");
        std::process::exit(1);
    });
    let mut trees: Vec<Tree> = Vec::new();
    let mut nodes: Vec<(usize, Node)> = Vec::new();
    for raw in txt.lines() {
        let body = raw.trim_start_matches('\t');
        if body.starts_with("booster[") {
            if !nodes.is_empty() {
                nodes.sort_by_key(|(id, _)| *id); // node ids NOT in DFS order — index by explicit id
                trees.push(nodes.drain(..).map(|(_, n)| n).collect());
            }
            continue;
        }
        let mut it = body.splitn(2, ':');
        let id: usize = it.next().unwrap_or("0").trim().parse().unwrap_or(0);
        let rest = it.next().unwrap_or("");
        if rest.starts_with("leaf=") {
            let v: f64 = rest["leaf=".len()..].trim().parse().unwrap_or(0.0);
            nodes.push((
                id,
                Node {
                    feature: -1,
                    threshold: 0.0,
                    yes: 0,
                    no: 0,
                    is_leaf: true,
                    leaf: v,
                },
            ));
        } else {
            let inner = rest.trim_start_matches('[').split(']').next().unwrap_or("");
            let after_f = inner.trim_start_matches('f');
            let (fs, ts) = match after_f.split_once('<') {
                Some(x) => x,
                None => continue,
            };
            let feat: i32 = fs.trim().parse().unwrap_or(-1);
            let thr: f64 = ts.trim().parse().unwrap_or(0.0);
            let tail = rest.split(']').nth(1).unwrap_or("");
            let yes = parse_tail_int(tail, "yes=");
            let no = parse_tail_int(tail, "no=");
            nodes.push((
                id,
                Node {
                    feature: feat,
                    threshold: thr,
                    yes,
                    no,
                    is_leaf: false,
                    leaf: 0.0,
                },
            ));
        }
    }
    if !nodes.is_empty() {
        nodes.sort_by_key(|(id, _)| *id);
        trees.push(nodes.drain(..).map(|(_, n)| n).collect());
    }
    trees
}

fn predict(feats: &[f64], trees: &[Tree]) -> f64 {
    let mut margin = BASE_SCORE;
    for t in trees {
        let mut id = 0usize;
        loop {
            let nd = &t[id];
            if nd.is_leaf {
                margin += nd.leaf;
                break;
            }
            id = if (feats[nd.feature as usize] as f32) < (nd.threshold as f32) {
                nd.yes
            } else {
                nd.no
            };
        }
    }
    1.0 / (1.0 + (-margin).exp())
}

// ----------------------------- signals -----------------------------

fn rolling_beta(la: &[f64], lb: &[f64]) -> (Vec<f64>, Vec<f64>) {
    let n = la.len();
    let mut beta = vec![0.0f64; n];
    let mut alpha = vec![0.0f64; n];
    for i in (W_BETA - 1)..n {
        let s = i + 1 - W_BETA;
        let (mut mx, mut my) = (0.0f64, 0.0f64);
        for j in s..=i {
            mx += lb[j];
            my += la[j];
        }
        mx /= W_BETA as f64;
        my /= W_BETA as f64;
        let (mut sxy, mut sxx) = (0.0f64, 0.0f64);
        for j in s..=i {
            let (dx, dy) = (lb[j] - mx, la[j] - my);
            sxy += dx * dy;
            sxx += dx * dx;
        }
        if sxx > 1e-12 {
            beta[i] = sxy / sxx;
        }
        alpha[i] = my - beta[i] * mx;
    }
    (beta, alpha)
}

fn rolling_mean_std(s: &[f64], w: usize) -> (Vec<f64>, Vec<f64>) {
    let n = s.len();
    let (mut mu, mut sd) = (vec![0.0f64; n], vec![0.0f64; n]);
    for i in (w - 1)..n {
        let s0 = i + 1 - w;
        let m = s[s0..=i].iter().sum::<f64>() / w as f64;
        mu[i] = m;
        let v = s[s0..=i].iter().map(|x| (x - m).powi(2)).sum::<f64>() / (w - 1) as f64;
        sd[i] = v.sqrt();
    }
    (mu, sd)
}

fn std_pop(v: &[f64]) -> f64 {
    if v.is_empty() {
        return 0.0;
    }
    let m = v.iter().sum::<f64>() / v.len() as f64;
    (v.iter().map(|x| (x - m).powi(2)).sum::<f64>() / v.len() as f64).sqrt()
}

fn std_of_diffs(logs: &[f64]) -> f64 {
    if logs.len() < 2 {
        return 0.0;
    }
    let d: Vec<f64> = logs.windows(2).map(|w| w[1] - w[0]).collect();
    std_pop(&d)
}

fn beep() {
    use std::io::Write as _;
    for _ in 0..4 {
        print!("\x07");
        let _ = io::stdout().flush();
    }
}

fn compute_z(pa: &[f64], pb: &[f64]) -> (Vec<f64>, Vec<f64>) {
    let n = pa.len();
    let la: Vec<f64> = pa.iter().map(|x| x.ln()).collect();
    let lb: Vec<f64> = pb.iter().map(|x| x.ln()).collect();
    let (beta, alpha) = rolling_beta(&la, &lb);
    let spread: Vec<f64> = (0..n).map(|i| la[i] - beta[i] * lb[i] - alpha[i]).collect();
    let (mu, sd) = rolling_mean_std(&spread, W_Z);
    let mut z = vec![0.0f64; n];
    for i in (W_BETA + W_Z)..n {
        if sd[i] > 1e-9 {
            z[i] = (spread[i] - mu[i]) / sd[i];
        }
    }
    (z, beta)
}

struct ScanOut {
    z_now: f64, // current z at the live-updated last bar (moves every poll)
    z_sig: f64, // z at the WATCH candidate entry (what the signal was based on)
    zrec: f64,
    pxdist: f64,
    prob: f64,
    watch: bool,
    arm: Option<usize>,
    live_arm: bool,
}

fn scan_leg(pa: &[f64], pb: &[f64], trees: &[Tree], leg_id: f64) -> ScanOut {
    let n = pa.len();
    let mut out = ScanOut {
        z_now: 0.0,
        z_sig: 0.0,
        zrec: 0.0,
        pxdist: 0.0,
        prob: 0.0,
        watch: false,
        arm: None,
        live_arm: false,
    };
    if n < W_BETA + W_Z + OBS {
        return out;
    }
    let (z, beta) = compute_z(pa, pb);
    // find the LATEST arm with a completed observation window (i + OBS < n)
    let mut arm = None;
    for i in (W_BETA + W_Z)..n.saturating_sub(OBS) {
        if z[i] < Z_ARM {
            arm = Some(i); // keep overwriting -> ends at the true latest arm
        }
    }
    let a = match arm {
        Some(x) => x,
        None => return out,
    };
    let e = a + OBS;
    let segz = &z[a..=e];
    let segp = &pa[a..=e];
    let (mut zm, mut dzm) = (f64::INFINITY, 0usize);
    let (mut pmin, mut dpm) = (f64::INFINITY, 0usize);
    for k in 0..segz.len() {
        if segz[k] < zm {
            zm = segz[k];
            dzm = k;
        }
        if segp[k] < pmin {
            pmin = segp[k];
            dpm = k;
        }
    }
    let zrec = z[e] - zm;
    let pxdist = pa[e] / pmin - 1.0;
    out.z_now = if n >= W_BETA + W_Z { z[n - 1] } else { 0.0 };
    out.live_arm = out.z_now < Z_ARM;
    out.z_sig = z[e];
    if !(zrec >= GATE_ZREC.max(0.3 * zm.abs()) && pxdist <= GATE_PX) {
        out.zrec = zrec;
        out.pxdist = pxdist;
        return out;
    }
    // features (order must match training)
    let logs_a: Vec<f64> = pa.iter().map(|x| x.ln()).collect();
    let vf = std_of_diffs(&logs_a[a..a + 6]);
    let vl = std_of_diffs(&logs_a[e - 5..=e]);
    let f: Vec<f64> = vec![
        z[a],
        z[e],
        zm,
        zrec,
        zrec / dzm.max(1) as f64,
        dzm as f64,
        (z[e] - z[a]) / OBS as f64,
        z[e] - z[e - 2],
        pxdist,
        pa[e] / pa[a] - 1.0,
        pa[e] / pa[e - 2] - 1.0,
        pa[e] / pa[e - 3] - 1.0,
        pa[e] / pa[e - 5] - 1.0,
        dpm as f64,
        zrec.max(0.0) * (pa[a] / pmin - 1.0).max(0.0),
        (z[e] - segz[dzm]) / (OBS - dzm).max(1) as f64,
        (pa[e] - segp[dpm]) / (OBS - dpm).max(1) as f64 / pmin.max(1e-9),
        zrec / pxdist.max(1e-4),
        zm.abs(),
        vl / vf.max(1e-9),
        std_pop(&logs_a[e.saturating_sub(19)..=e]),
        beta[e],
        leg_id,
    ];
    let prob = predict(&f, trees);
    out.zrec = zrec;
    out.pxdist = pxdist;
    out.prob = prob;
    out.watch = prob >= THRESH;
    out.arm = Some(a);
    out
}

// ----------------------------- data + UI -----------------------------

struct LegCfg {
    name: &'static str,
    partner: &'static str,
    leg_id: f64,
    conf: &'static str,
    enabled: bool,
}

const LEGS: [LegCfg; 10] = [
    LegCfg {
        name: "AXISBANK",
        partner: "RELIANCE",
        leg_id: 0.0,
        conf: "HIGH",
        enabled: true,
    },
    LegCfg {
        name: "BAJAJFINSV",
        partner: "RELIANCE",
        leg_id: 1.0,
        conf: "MOD",
        enabled: true,
    },
    LegCfg {
        name: "HDFCBANK",
        partner: "KOTAKBANK",
        leg_id: 4.0,
        conf: "HIGH",
        enabled: true,
    },
    LegCfg {
        name: "HINDALCO",
        partner: "JSWSTEEL",
        leg_id: 5.0,
        conf: "HIGH",
        enabled: true,
    },
    LegCfg {
        name: "ICICIBANK",
        partner: "KOTAKBANK",
        leg_id: 7.0,
        conf: "HIGH",
        enabled: true,
    },
    LegCfg {
        name: "JSWSTEEL",
        partner: "TATASTEEL",
        leg_id: 10.0,
        conf: "HIGH",
        enabled: true,
    },
    LegCfg {
        name: "KOTAKBANK",
        partner: "RELIANCE",
        leg_id: 11.0,
        conf: "HIGH",
        enabled: true,
    },
    LegCfg {
        name: "NESTLEIND",
        partner: "ITC",
        leg_id: 12.0,
        conf: "MED",
        enabled: true,
    },
    LegCfg {
        name: "SBIN",
        partner: "ICICIBANK",
        leg_id: 14.0,
        conf: "HIGH",
        enabled: true,
    },
    LegCfg {
        name: "TATASTEEL",
        partner: "TCS",
        leg_id: 15.0,
        conf: "HIGH",
        enabled: true,
    },
];

/// Unique symbols across all legs (fixed fetch set -> constant rate).
fn unique_symbols() -> Vec<&'static str> {
    let mut v: Vec<&'static str> = Vec::new();
    for c in LEGS.iter() {
        if !v.contains(&c.name) {
            v.push(c.name);
        }
        if !v.contains(&c.partner) {
            v.push(c.partner);
        }
    }
    v
}

/// Groww live-data limit: 300 req/min. Keep <=240/min margin.
/// poll_secs = ceil(symbols*60 / 240), min 3s. Override with SCANNER_POLL_SECS.
fn compute_poll_secs() -> u64 {
    if let Ok(v) = std::env::var("SCANNER_POLL_SECS") {
        if let Ok(x) = v.trim().parse::<u64>() {
            return x.max(3);
        }
    }
    let n = unique_symbols().len().max(1);
    (((n * 60) as f64 / 240.0).ceil() as u64).max(3)
}

/// Enable/disable legs before runtime via SCANNER_LEGS=AXISBANK,HDFCBANK,...
fn enabled_from_env() -> Vec<bool> {
    let mut e = vec![true; LEGS.len()];
    if let Ok(v) = std::env::var("SCANNER_LEGS") {
        let list: Vec<String> = v.split(',').map(|x| x.trim().to_string()).collect();
        if !list.is_empty() && list.iter().any(|x| !x.is_empty()) {
            for (k, c) in LEGS.iter().enumerate() {
                e[k] = list.iter().any(|x| *x == c.name);
            }
        }
    }
    e
}

fn load_closes(name: &str) -> Vec<f64> {
    let txt = fs::read_to_string(format!("backtesting/data/{name}.csv")).unwrap_or_else(|e| {
        eprintln!("read {name}: {e}");
        std::process::exit(1);
    });
    txt.lines()
        .skip(1)
        .filter_map(|l| {
            let f: Vec<&str> = l.split(',').collect();
            if f.len() >= 5 {
                f[4].trim().parse::<f64>().ok() // OHLCV: close is column 4
            } else if f.len() >= 2 {
                f[1].trim().parse::<f64>().ok() // legacy ts,close,volume: close is column 1
            } else {
                None
            }
        })
        .collect()
}

/// Return over the last `h` bars (0.0 when not enough history yet).
fn ret_over(prices: &[f64], h: usize) -> f64 {
    if prices.len() > h {
        prices[prices.len() - 1] / prices[prices.len() - 1 - h] - 1.0
    } else {
        0.0
    }
}

/// Cross-sectional z-score of `x` within `vals` (0.0 when degenerate).
fn zscore(vals: &[f64], x: f64) -> f64 {
    let n = vals.len();
    if n == 0 {
        return 0.0;
    }
    let mu = vals.iter().sum::<f64>() / n as f64;
    let var = vals.iter().map(|v| (v - mu).powi(2)).sum::<f64>() / n as f64;
    if var <= 1e-12 {
        0.0
    } else {
        (x - mu) / var.sqrt()
    }
}

/// Momentum for the leg at index `k` across the whole leg universe `all`.
/// Returns (ret_1d, ret_1m, ret_3m, ret_12m, score, trend) where trend is
/// 1.0 (UP) / -1.0 (DOWN) / 0.0 (FLAT) from the cross-sectional score.
fn momentum_for(all: &[&[f64]], k: usize) -> (f64, f64, f64, f64, f64, f64) {
    const HORIZONS: [usize; 6] = [1, 5, 21, 63, 126, 252];
    const WEIGHTS: [f64; 6] = [0.05, 0.10, 0.25, 0.25, 0.20, 0.15];
    let mut score = 0.0;
    for (hi, &h) in HORIZONS.iter().enumerate() {
        let vals: Vec<f64> = all.iter().map(|p| ret_over(p, h)).collect();
        score += WEIGHTS[hi] * zscore(&vals, vals[k]);
    }
    let (r1d, r1m, r3m, r12m) = (
        ret_over(all[k], 1),
        ret_over(all[k], 21),
        ret_over(all[k], 63),
        ret_over(all[k], 252),
    );
    let trend = if score > 0.5 {
        1.0
    } else if score < -0.5 {
        -1.0
    } else {
        0.0
    };
    (r1d, r1m, r3m, r12m, score, trend)
}

/// Equal-weight market proxy index from the given price series (same length).
fn market_index(legs: &[&[f64]]) -> Vec<f64> {
    let n = legs.iter().map(|p| p.len()).min().unwrap_or(0);
    let mut idx = vec![0.0f64; n];
    if n == 0 {
        return idx;
    }
    idx[0] = 1.0;
    for t in 1..n {
        let mut r = 0.0;
        for p in legs {
            r += p[t] / p[t - 1] - 1.0;
        }
        r /= legs.len() as f64;
        idx[t] = idx[t - 1] * (1.0 + r);
    }
    idx
}

/// Market regime from a price series: 1 = risk-on, 0 = neutral, -1 = risk-off.
/// Uses price vs 200-day MA plus 1M/3M momentum.
fn regime(idx: &[f64]) -> i8 {
    let n = idx.len();
    if n < 200 {
        return 0;
    }
    let px = idx[n - 1];
    let ma200: f64 = idx[n - 200..].iter().sum::<f64>() / 200.0;
    let m1 = if n > 21 {
        idx[n - 1] / idx[n - 22] - 1.0
    } else {
        0.0
    };
    let m3 = if n > 63 {
        idx[n - 1] / idx[n - 64] - 1.0
    } else {
        0.0
    };
    let above = px >= ma200;
    if above && (m1 > 0.0 || m3 > 0.0) {
        1
    } else if !above && (m1 < 0.0 || m3 < 0.0) {
        -1
    } else {
        0
    }
}

fn regime_str(r: i8) -> &'static str {
    match r {
        1 => "RISK-ON",
        -1 => "RISK-OFF",
        _ => "neutral",
    }
}

/// Rule-based ETF-pair signal (Pole logic, no ML): rolling z of the spread.
/// Returns (z_now, signal) where signal = 1 long-A / -1 short-A / 0 none.
fn etf_scan(pa: &[f64], pb: &[f64]) -> (f64, i8) {
    let n = pa.len().min(pb.len());
    let (z, _) = compute_z(&pa[..n], &pb[..n]);
    let zz = if n > W_BETA + W_Z { z[n - 1] } else { 0.0 };
    let signal = if zz <= -2.0 {
        1
    } else if zz >= 2.0 {
        -1
    } else {
        0
    };
    (zz, signal)
}

/// Compute momentum, harsh-market gate, India+S&P regime, and ETF signals.
/// `legs` = the scanned legs' current price arrays; `etf_pairs` = (A, B, name).
fn compute_overlays(
    legs: &[&[f64]],
    sp500: &[f64],
    etf_pairs: &[(&[f64], &[f64], &str)],
    ui: &mut Ui,
    enabled: &[bool],
) {
    ui.mom = (0..legs.len()).map(|k| momentum_for(legs, k)).collect();
    let mkt = market_index(legs);
    ui.market_regime = regime(&mkt);
    ui.sp_regime = regime(sp500);
    ui.etf = etf_pairs
        .iter()
        .map(|(a, b, name)| {
            let (z, sig) = etf_scan(a, b);
            (name.to_string(), z, sig)
        })
        .collect();
    ui.gate = legs
        .iter()
        .enumerate()
        .map(|(k, p)| {
            if !enabled.get(k).copied().unwrap_or(true) {
                return "OFF".to_string();
            }
            let watch = ui.views.get(k).map(|v| v.6).unwrap_or(false);
            if !watch {
                return "wait".to_string();
            }
            let r1 = ret_over(p, 21);
            let r3 = ret_over(p, 63);
            let risk_off = ui.market_regime < 0 || ui.sp_regime < 0;
            if r3 < -0.08 {
                // falling knife — don't catch
                "SKIP".to_string()
            } else if risk_off {
                if r3 > 0.0 && r1 > 0.0 {
                    // strong confirmation in a harsh market
                    "CONFIRM".to_string()
                } else {
                    "SKIP".to_string()
                }
            } else {
                "WATCH".to_string()
            }
        })
        .collect();
}

struct Ui {
    bars: usize,
    total: usize,
    views: Vec<(String, f64, f64, f64, f64, f64, bool)>, // (leg, z_now, z_sig, zrec, pxdist, prob, watch)
    log: Vec<String>,
    enabled: Vec<bool>,
    poll_secs: u64,
    live: bool,
    mom: Vec<(f64, f64, f64, f64, f64, f64)>, // per leg: (1d, 1m, 3m, 12m, score, trend)
    gate: Vec<String>,                        // per leg: WATCH / SKIP / CONFIRM
    market_regime: i8,
    sp_regime: i8,
    etf: Vec<(String, f64, i8)>, // (pair, z, signal)
}

fn setup() -> io::Result<Terminal<CrosstermBackend<io::Stdout>>> {
    enable_raw_mode()?;
    let mut stdout = io::stdout();
    execute!(stdout, EnterAlternateScreen)?;
    Terminal::new(CrosstermBackend::new(stdout))
}
fn teardown(t: &mut Terminal<CrosstermBackend<io::Stdout>>) -> io::Result<()> {
    disable_raw_mode()?;
    execute!(t.backend_mut(), LeaveAlternateScreen)?;
    Ok(())
}

fn draw(f: &mut ratatui::Frame, ui: &Ui) {
    let area = f.area();
    let etf_h = ui.etf.len() as u16 + 2;
    let rows = Layout::default()
        .direction(ratatui::layout::Direction::Vertical)
        .constraints([
            Constraint::Length(4),
            Constraint::Length((LEGS.len() + 3) as u16),
            Constraint::Length(etf_h),
            Constraint::Min(4),
            Constraint::Length(1),
        ])
        .split(area);

    // header — title + live/seeded status + regime
    let conn = if ui.live { "● LIVE" } else { "● SEEDED" };
    let conn_style = if ui.live {
        Style::default()
            .fg(Color::Green)
            .add_modifier(Modifier::BOLD)
    } else {
        Style::default().fg(Color::Red).add_modifier(Modifier::BOLD)
    };
    let (reg_c, reg_txt) = if ui.market_regime < 0 || ui.sp_regime < 0 {
        (
            Color::Red,
            format!(
                "IND {} / SP {}",
                regime_str(ui.market_regime),
                regime_str(ui.sp_regime)
            ),
        )
    } else if ui.market_regime > 0 {
        (
            Color::Green,
            format!(
                "IND {} / SP {}",
                regime_str(ui.market_regime),
                regime_str(ui.sp_regime)
            ),
        )
    } else {
        (
            Color::Yellow,
            format!(
                "IND {} / SP {}",
                regime_str(ui.market_regime),
                regime_str(ui.sp_regime)
            ),
        )
    };
    let header = Paragraph::new(vec![
        Line::from(vec![
            Span::styled(
                " ML v3 WATCH SCANNER ",
                Style::default()
                    .fg(Color::Black)
                    .bg(Color::Yellow)
                    .add_modifier(Modifier::BOLD),
            ),
            Span::raw("  "),
            Span::styled(conn, conn_style),
            Span::raw("   REGIME: "),
            Span::styled(
                reg_txt,
                Style::default().fg(reg_c).add_modifier(Modifier::BOLD),
            ),
        ]),
        Line::from(format!(
            " poll {}s   enabled {}/{}   bars {}/{}",
            ui.poll_secs,
            ui.enabled.iter().filter(|e| **e).count(),
            ui.enabled.len(),
            ui.bars,
            ui.total
        )),
    ])
    .block(Block::default().borders(Borders::BOTTOM));
    f.render_widget(header, rows[0]);

    // legs — aligned columns, status = harsh-market gate (WATCH/SKIP/CONFIRM)
    let mut lines = Vec::new();
    lines.push(ListItem::new(Span::styled(
        format!(
            "{:>2}. {:<11} {:<5} {:>10} {:>5}  STATUS",
            "#", "LEG", "CONF", "z_now", "P"
        ),
        Style::default()
            .fg(Color::Cyan)
            .add_modifier(Modifier::BOLD),
    )));
    for (k, v) in ui.views.iter().enumerate() {
        let (name, z_now, _z_sig, _zrec, _px, prob, _watch) = v;
        let on = ui.enabled.get(k).copied().unwrap_or(true);
        let conf = LEGS.get(k).map(|c| c.conf).unwrap_or("");
        let g = ui.gate.get(k).map(|s| s.as_str()).unwrap_or("wait");
        let (style, status) = match g {
            "OFF" => (Style::default().fg(Color::DarkGray), "OFF".to_string()),
            "SKIP" => (Style::default().fg(Color::DarkGray), "SKIP".to_string()),
            "CONFIRM" => (
                Style::default()
                    .fg(Color::Cyan)
                    .add_modifier(Modifier::BOLD),
                "CONFIRM".to_string(),
            ),
            "WATCH" => (
                Style::default()
                    .fg(Color::Green)
                    .add_modifier(Modifier::BOLD),
                "WATCH".to_string(),
            ),
            _ if !on => (Style::default().fg(Color::DarkGray), "OFF".to_string()),
            _ => (Style::default().fg(Color::Gray), "wait".to_string()),
        };
        let line = format!(
            "{:>2}. {:<11} {:<5} {:>10.5} {:>4.0}%  {}",
            k + 1,
            name,
            conf,
            z_now,
            prob * 100.0,
            status
        );
        lines.push(ListItem::new(Span::styled(line, style)));
    }

    // split the main row horizontally: LEGS | MOMENTUM
    let cols = Layout::default()
        .direction(ratatui::layout::Direction::Horizontal)
        .constraints([Constraint::Percentage(55), Constraint::Percentage(45)])
        .split(rows[1]);
    f.render_widget(
        List::new(lines).block(Block::default().borders(Borders::ALL).title("LEGS")),
        cols[0],
    );

    // momentum — trend since today / 1 month / 3 months / a year + score
    let mut ml = Vec::new();
    ml.push(ListItem::new(Span::styled(
        format!(
            "{:<11} {:>7} {:>7} {:>7} {:>8} {:>5}  TREND",
            "LEG", "1D", "1M", "3M", "12M", "SCORE"
        ),
        Style::default()
            .fg(Color::Cyan)
            .add_modifier(Modifier::BOLD),
    )));
    for (k, m) in ui.mom.iter().enumerate() {
        let name = LEGS.get(k).map(|c| c.name).unwrap_or("?");
        let (c, arrow) = if m.5 > 0.0 {
            (Color::Green, "▲")
        } else if m.5 < 0.0 {
            (Color::Red, "▼")
        } else {
            (Color::Gray, "—")
        };
        ml.push(ListItem::new(Span::styled(
            format!(
                "{:<11} {:>+6.1}% {:>+6.1}% {:>+6.1}% {:>+7.1}% {:>5.2}  {}",
                name,
                100.0 * m.0,
                100.0 * m.1,
                100.0 * m.2,
                100.0 * m.3,
                m.4,
                arrow
            ),
            Style::default().fg(c),
        )));
    }
    f.render_widget(
        List::new(ml).block(Block::default().borders(Borders::ALL).title("MOMENTUM")),
        cols[1],
    );

    // ETF pairs — proven market-neutral edge (Pole z-score, |z|>2)
    let mut el = Vec::new();
    el.push(ListItem::new(Span::styled(
        format!("{:<20} {:>8}  SIGNAL", "PAIR", "Z"),
        Style::default()
            .fg(Color::Cyan)
            .add_modifier(Modifier::BOLD),
    )));
    for (name, z, sig) in &ui.etf {
        let (c, txt) = match sig {
            1 => (
                Color::Green,
                format!(
                    "LONG {} / SHORT {}",
                    name.split('/').next().unwrap_or(""),
                    name.split('/').nth(1).unwrap_or("")
                ),
            ),
            -1 => (
                Color::Red,
                format!(
                    "SHORT {} / LONG {}",
                    name.split('/').next().unwrap_or(""),
                    name.split('/').nth(1).unwrap_or("")
                ),
            ),
            _ => (Color::Gray, "flat".to_string()),
        };
        el.push(ListItem::new(Span::styled(
            format!("{:<20} {:>7.2}  {}", name, z, txt),
            Style::default().fg(c),
        )));
    }
    f.render_widget(
        List::new(el).block(
            Block::default()
                .borders(Borders::ALL)
                .title("ETF PAIRS (market-neutral)"),
        ),
        rows[2],
    );

    // events — tidy, colour-coded, truncated to one line
    let items: Vec<ListItem> = ui
        .log
        .iter()
        .rev()
        .take(25)
        .map(|s| {
            let t: String = if s.chars().count() > 100 {
                s.chars().take(100).collect::<String>() + "…"
            } else {
                s.clone()
            };
            let color = if t.contains("WATCH") {
                Color::Yellow
            } else if t.contains("RISE") {
                Color::Green
            } else if t.contains("DISLOCATION") {
                Color::Cyan
            } else {
                Color::Gray
            };
            ListItem::new(Span::styled(t, Style::default().fg(color)))
        })
        .collect();
    f.render_widget(
        List::new(items).block(Block::default().borders(Borders::ALL).title("EVENTS")),
        rows[3],
    );

    f.render_widget(
        Paragraph::new(" q quit   ·   1..9,0 toggle leg   ·   SCANNER_LEGS subset   ·   SCANNER_POLL_SECS rate   ·   SKIP=falling-knife/risk-off"),
        rows[4]);
}

// ----------------------------- groww live -----------------------------

struct LiveClient {
    http: reqwest::Client,
    token: String,
}

impl LiveClient {
    fn new(token: &str) -> Self {
        Self {
            http: reqwest::Client::new(),
            token: token.to_string(),
        }
    }
    async fn quote(&self, sym: &str) -> anyhow::Result<f64> {
        let url = format!(
            "https://api.groww.in/v1/live-data/quote?exchange=NSE&segment=CASH&trading_symbol={sym}"
        );
        let resp = self
            .http
            .get(&url)
            .header("Accept", "application/json")
            .header("Authorization", format!("Bearer {}", self.token))
            .header("X-API-VERSION", "1.0")
            .send()
            .await?;
        if !resp.status().is_success() {
            anyhow::bail!("quote HTTP {}", resp.status());
        }
        #[derive(Deserialize)]
        struct Env {
            status: String,
            payload: Option<Payload>,
        }
        #[derive(Deserialize)]
        struct Payload {
            last_price: Option<f64>,
        }
        let e: Env = resp.json().await?;
        if e.status != "SUCCESS" {
            anyhow::bail!("quote status {}", e.status);
        }
        e.payload
            .and_then(|p| p.last_price)
            .ok_or_else(|| anyhow::anyhow!("no last_price"))
    }
    async fn login(api_key: &str, secret: &str) -> anyhow::Result<String> {
        let ts = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)?
            .as_secs()
            .to_string();
        let checksum: String = Sha256::digest(format!("{secret}{ts}"))
            .iter()
            .map(|b| format!("{b:02x}"))
            .collect();
        #[derive(Serialize)]
        struct Req {
            key_type: &'static str,
            checksum: String,
            timestamp: String,
        }
        #[derive(Deserialize)]
        struct Res {
            token: String,
        }
        let resp = reqwest::Client::new()
            .post("https://api.groww.in/v1/token/api/access")
            .header("Accept", "application/json")
            .header("Authorization", format!("Bearer {api_key}"))
            .json(&Req {
                key_type: "approval",
                checksum,
                timestamp: ts,
            })
            .send()
            .await?;
        if !resp.status().is_success() {
            anyhow::bail!("auth HTTP {}", resp.status());
        }
        Ok(resp.json::<Res>().await?.token)
    }
}

use serde::Serialize;

/// Append a timestamped line to pushover.log so send outcomes are always visible,
/// even under the TUI (which hides stderr).
fn log_push(line: &str) {
    let ts = chrono::Local::now().format("%Y-%m-%d %H:%M:%S");
    if let Ok(mut f) = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open("pushover.log")
    {
        use std::io::Write as _;
        let _ = writeln!(f, "[{ts}] {line}");
    }
}

/// Send a push notification via Pushover. Reads PUSHOVER_APP_TOKEN / PUSHOVER_USER_KEY
/// from the environment; no-ops (returns false) if not set so the scanner still runs
/// headless. Every outcome is logged to pushover.log.
async fn pushover(http: &reqwest::Client, title: &str, message: &str, priority: i32) -> bool {
    let Ok(token) = std::env::var("PUSHOVER_APP_TOKEN") else {
        log_push("SKIP: PUSHOVER_APP_TOKEN not set");
        return false;
    };
    if token.trim().is_empty() {
        log_push("SKIP: PUSHOVER_APP_TOKEN empty");
        return false;
    }
    let Ok(user) = std::env::var("PUSHOVER_USER_KEY") else {
        log_push("SKIP: PUSHOVER_USER_KEY not set");
        return false;
    };
    if user.trim().is_empty() {
        log_push("SKIP: PUSHOVER_USER_KEY empty");
        return false;
    }

    let resp = match http
        .post("https://api.pushover.net/1/messages.json")
        .form(&[
            ("token", token.trim().to_string()),
            ("user", user.trim().to_string()),
            ("title", title.to_string()),
            ("message", message.to_string()),
            ("priority", priority.to_string()),
        ])
        .send()
        .await
    {
        Ok(r) => r,
        Err(e) => {
            log_push(&format!("SEND ERROR: {title}: {e}"));
            eprintln!("pushover send error: {e}");
            return false;
        }
    };
    if resp.status().is_success() {
        log_push(&format!("OK: {title}: {message}"));
        true
    } else {
        let status = resp.status();
        let body = resp.text().await.unwrap_or_default();
        log_push(&format!("REJECTED {status}: {title}: {body}"));
        eprintln!("pushover rejected {status}: {body}");
        false
    }
}

fn fetch_token() -> String {
    if let Ok(t) = std::env::var("GROWW_ACCESS_TOKEN") {
        let t = t.trim().trim_matches('"').trim_matches('\'').trim();
        if !t.is_empty() {
            return t.to_string();
        }
    }
    let rt = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .unwrap();
    let k = std::env::var("GROWW_API_KEY").ok();
    let s = std::env::var("GROWW_API_SECRET").ok();
    if let (Some(k), Some(s)) = (k, s) {
        if let Ok(t) = rt.block_on(LiveClient::login(&k, &s)) {
            return t;
        }
    }
    eprintln!("FATAL: set GROWW_ACCESS_TOKEN or GROWW_API_KEY/GROWW_API_SECRET");
    std::process::exit(1);
}

fn live_mode(
    trees: &[Tree],
    mut terminal: Option<Terminal<CrosstermBackend<io::Stdout>>>,
    mut enabled: Vec<bool>,
    sound: bool,
) {
    dotenvy::dotenv().ok();
    let client = Arc::new(LiveClient::new(&fetch_token()));
    let rt = tokio::runtime::Builder::new_multi_thread()
        .enable_all()
        .build()
        .unwrap();
    let mut seeds: Vec<(Vec<f64>, Vec<f64>)> = LEGS
        .iter()
        .map(|c| (load_closes(c.name), load_closes(c.partner)))
        .collect();
    let n = seeds.iter().map(|(a, _)| a.len()).min().unwrap_or(0);
    // align all legs to a common length so index n-1 is each series' TRUE last bar
    for s in seeds.iter_mut() {
        s.0.truncate(n);
        s.1.truncate(n);
    }
    let symbols = unique_symbols();
    let poll_secs = compute_poll_secs();
    // ETF pairs + S&P regime data (daily cached closes)
    let bankbees = load_closes("BANKBEES");
    let setfnifbk = load_closes("SETFNIFBK");
    let niftybees = load_closes("NIFTYBEES");
    let setfnif50 = load_closes("SETFNIF50");
    let sp500 = load_closes("SP500");

    let no_tui = terminal.is_none();
    let mut ui = Ui {
        bars: n,
        total: n,
        views: Vec::new(),
        log: Vec::new(),
        enabled: enabled.clone(),
        poll_secs,
        live: false,
        mom: Vec::new(),
        gate: Vec::new(),
        market_regime: 0,
        sp_regime: 0,
        etf: Vec::new(),
    };
    let mut last_arm = [usize::MAX; LEGS.len()];
    let mut prev_live_arm = [false; LEGS.len()];
    let mut prev_px: HashMap<String, f64> = HashMap::new();
    let mut last_rise_push: HashMap<String, Instant> = HashMap::new();
    let mut auth_notified = false;
    let mut tick: u64 = 0;
    let http = reqwest::Client::new();
    const SUMMARY_EVERY: u64 = 10; // periodic status push every ~10 polls
    if no_tui {
        println!(
            "LIVE WATCH scanner - {} symbols, seeded {n} bars, polling every {poll_secs}s (SCANNER_POLL_SECS to override)",
            symbols.len()
        );
    }
    // startup confirmation push — proves notifications are wired before any signal
    rt.block_on(pushover(
        &http,
        "ML3 — Scanner started",
        &format!(
            "{}/{} symbols live, {} legs enabled, poll {}s. Notifications active.",
            symbols.len(),
            symbols.len(),
            enabled.iter().filter(|e| **e).count(),
            poll_secs
        ),
        0,
    ));

    loop {
        tick += 1;
        // fetch live prices concurrently (non-spamming)
        let (prices, ok_count): (HashMap<String, f64>, usize) = rt.block_on(async {
            let mut handles = Vec::new();
            for sym in symbols.clone() {
                let c = Arc::clone(&client);
                handles.push(tokio::spawn(async move { (sym, c.quote(sym).await) }));
            }
            let mut m = HashMap::new();
            let mut ok = 0usize;
            for h in handles {
                if let Ok((sym, Ok(v))) = h.await {
                    m.insert(sym.to_string(), v);
                    ok += 1;
                }
            }
            (m, ok)
        });

        if ok_count < symbols.len() && !auth_notified {
            if no_tui {
                eprintln!(
                    "NOTE: live quotes unavailable ({}/{} fetched) - showing seeded last bar",
                    ok_count,
                    symbols.len()
                );
            }
            auth_notified = true;
        }
        // build a READ-ONLY working copy: seeds stay pristine, only the per-poll copy
        // has today's live price written into its last bar (never mutates the loaded data)
        let mut work: Vec<(Vec<f64>, Vec<f64>)> = seeds.clone();
        for (k, cfg) in LEGS.iter().enumerate() {
            if let Some(v) = prices.get(cfg.name) {
                work[k].0[n - 1] = *v;
            }
            if let Some(v) = prices.get(cfg.partner) {
                work[k].1[n - 1] = *v;
            }
        }

        // scan + WATCH (only enabled legs)
        let mut new_views = Vec::new();
        let mut tick_line = String::new();
        for (k, cfg) in LEGS.iter().enumerate() {
            if !enabled[k] {
                new_views.push((cfg.name.to_string(), 0.0, 0.0, 0.0, 0.0, 0.0, false));
                continue;
            }
            let s = scan_leg(&work[k].0, &work[k].1, trees, cfg.leg_id);
            new_views.push((
                cfg.name.to_string(),
                s.z_now,
                s.z_sig,
                s.zrec,
                s.pxdist,
                s.prob,
                s.watch,
            ));
            tick_line.push_str(&format!(
                " {} z={:.3} P={:.0}%",
                cfg.name,
                s.z_now,
                s.prob * 100.0
            ));
            // minimal: alert sound when the leg starts rising significantly since last poll
            let px_now = work[k].0[n - 1];
            if let Some(pv) = prev_px.get(cfg.name) {
                if px_now >= *pv * (1.0 + RISE_ALERT_PCT) {
                    let rise = 100.0 * (px_now / pv - 1.0);
                    let line = format!(
                        "RISE {} STOCK +{rise:.2}% ({px_now:.2} vs {pv:.2})",
                        cfg.name
                    );
                    ui.log.push(line.clone());
                    if no_tui {
                        println!("\x1b[32m{line}\x1b[0m");
                    }
                    if sound {
                        beep();
                    }
                    // push on rise too, but at most once per leg per 5 min to avoid spam
                    let now = Instant::now();
                    let cooled = last_rise_push
                        .get(cfg.name)
                        .map_or(true, |t| now.duration_since(*t) > Duration::from_secs(300));
                    if cooled {
                        last_rise_push.insert(cfg.name.to_string(), now);
                        let _ = rt.block_on(pushover(
                            &http,
                            "ML3 — RISE ALERT",
                            &format!("{} +{rise:.2}%  ({px_now:.2} vs {pv:.2})", cfg.name),
                            0,
                        ));
                    }
                }
            }
            prev_px.insert(cfg.name.to_string(), px_now);
            if s.live_arm && !prev_live_arm[k] {
                let line = format!(
                    "FRESH DISLOCATION on {} STOCK (z_now={:.3} < -3)",
                    cfg.name, s.z_now
                );
                ui.log.push(line.clone());
                if no_tui {
                    println!("\x1b[36m{line}\x1b[0m");
                }
                let _ = rt.block_on(pushover(
                    &http,
                    "ML3 — FRESH DISLOCATION",
                    &format!(
                        "{} STOCK  z_now={:.3} < -3  (setup for WATCH)",
                        cfg.name, s.z_now
                    ),
                    1,
                ));
            }
            prev_live_arm[k] = s.live_arm;
            if s.watch {
                if let Some(a) = s.arm {
                    if a != last_arm[k] {
                        last_arm[k] = a;
                        let line = format!(
                            "WATCH {} STOCK  (P={:.0}%  z_now={:.3}  px_low={:.2}%)",
                            cfg.name,
                            s.prob * 100.0,
                            s.z_now,
                            s.pxdist * 100.0
                        );
                        ui.log.push(line.clone());
                        if no_tui {
                            println!("\x1b[33m{line}\x1b[0m");
                        }
                        let _ = rt.block_on(pushover(
                            &http, "ML3 — WATCH SIGNAL",
                            &format!("{} STOCK  P={:.0}%  z_now={:.3}  z_rec={:.2}  px_low={:.2}%  wait-for-break",
                                     cfg.name, s.prob * 100.0, s.z_now, s.zrec, s.pxdist * 100.0),
                            1,
                        ));
                    }
                }
            }
        }
        ui.views = new_views;
        let all_prices: Vec<&[f64]> = work.iter().map(|(pa, _)| pa.as_slice()).collect();
        let etf_pairs: Vec<(&[f64], &[f64], &str)> = vec![
            (&bankbees, &setfnifbk, "BANKBEES/SETFNIFBK"),
            (&niftybees, &setfnif50, "NIFTYBEES/SETFNIF50"),
        ];
        compute_overlays(&all_prices, &sp500, &etf_pairs, &mut ui, &enabled);
        ui.live = ok_count > 0;

        // periodic status push
        if tick % SUMMARY_EVERY == 0 {
            let watch: Vec<String> = ui
                .views
                .iter()
                .enumerate()
                .filter(|(k, v)| v.6 && enabled.get(*k).copied().unwrap_or(true))
                .map(|(_, v)| v.0.clone())
                .collect();
            let watch_txt = if watch.is_empty() {
                "none".to_string()
            } else {
                watch.join(",")
            };
            let _ = rt.block_on(pushover(
                &http,
                "ML3 — Status",
                &format!(
                    "tick {tick}  {ok_count}/{} live  enabled {}/{}  WATCH: {}",
                    symbols.len(),
                    enabled.iter().filter(|e| **e).count(),
                    enabled.len(),
                    watch_txt
                ),
                0,
            ));
        }

        if no_tui {
            if ok_count > 0 {
                println!(
                    "[tick {tick}] {ok_count}/{} LIVE |{tick_line}",
                    symbols.len()
                );
            } else if tick % 5 == 0 {
                println!("[tick {tick}] no live prices (seeded) |{tick_line}");
            }
        }

        if let Some(t) = terminal.as_mut() {
            let _ = t.draw(|f| draw(f, &ui));
            // poll keys DURING the sleep window so q/digits are always caught
            let deadline = Instant::now() + Duration::from_secs(poll_secs);
            while Instant::now() < deadline {
                if let Ok(true) = event::poll(Duration::from_millis(50)) {
                    if let Ok(Event::Key(k)) = event::read() {
                        match k.code {
                            KeyCode::Char('q') => {
                                let _ = teardown(t);
                                return;
                            }
                            KeyCode::Char('c') if k.modifiers.contains(KeyModifiers::CONTROL) => {
                                let _ = teardown(t);
                                return;
                            }
                            KeyCode::Char(d) if d.is_ascii_digit() => {
                                let idx = if d == '0' {
                                    9
                                } else {
                                    d as usize - '1' as usize
                                };
                                if idx < enabled.len() {
                                    enabled[idx] = !enabled[idx];
                                    ui.enabled[idx] = enabled[idx];
                                }
                            }
                            _ => {}
                        }
                    }
                }
                std::thread::sleep(Duration::from_millis(50));
            }
        } else {
            std::thread::sleep(Duration::from_secs(poll_secs));
        }
    }
}

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let headless = args.iter().any(|a| a == "--headless");
    let live = args.iter().any(|a| a == "--live");
    let sound = args.iter().any(|a| a == "--sound")
        || std::env::var("SCANNER_SOUND")
            .map(|v| v == "1")
            .unwrap_or(false);
    let trees = parse_model(MODEL_PATH);
    println!("loaded {} trees from {MODEL_PATH}", trees.len());
    let enabled = enabled_from_env();
    if live {
        let terminal = if headless {
            None
        } else {
            match setup() {
                Ok(t) => Some(t),
                Err(e) => {
                    eprintln!("TUI error: {e}");
                    None
                }
            }
        };
        live_mode(&trees, terminal, enabled, sound);
        return;
    }

    // pre-load full history for all legs + partners
    let full: Vec<(Vec<f64>, Vec<f64>)> = LEGS
        .iter()
        .map(|c| (load_closes(c.name), load_closes(c.partner)))
        .collect();
    let n = full.iter().map(|(a, _)| a.len()).min().unwrap_or(0);
    // ETF pairs + S&P regime data (daily cached closes)
    let bankbees = load_closes("BANKBEES");
    let setfnifbk = load_closes("SETFNIFBK");
    let niftybees = load_closes("NIFTYBEES");
    let setfnif50 = load_closes("SETFNIF50");
    let sp500 = load_closes("SP500");

    // --check LEG ARM: print features + prob at a specific arm for verification
    if let Some(pos) = args.iter().position(|a| a == "--check") {
        let leg = args.get(pos + 1).map(|x| x.as_str()).unwrap_or("TATASTEEL");
        let arm: usize = args
            .get(pos + 2)
            .and_then(|x| x.parse().ok())
            .unwrap_or(1033);
        let cfg = LEGS.iter().find(|c| c.name == leg).expect("unknown leg");
        let pa_full = load_closes(cfg.name);
        let pb_full = load_closes(cfg.partner);
        let e = arm + OBS;
        let pa = &pa_full[..e + 1];
        let pb = &pb_full[..e + 1];
        let (z, beta) = compute_z(pa, pb);
        let segz = &z[arm..=e];
        let segp = &pa[arm..=e];
        let (mut zm, mut dzm) = (f64::INFINITY, 0usize);
        let (mut pmin, mut dpm) = (f64::INFINITY, 0usize);
        for k in 0..segz.len() {
            if segz[k] < zm {
                zm = segz[k];
                dzm = k;
            }
            if segp[k] < pmin {
                pmin = segp[k];
                dpm = k;
            }
        }
        let zrec = z[e] - zm;
        let pxdist = pa[e] / pmin - 1.0;
        let logs_a: Vec<f64> = pa.iter().map(|x| x.ln()).collect();
        let vf = std_of_diffs(&logs_a[arm..arm + 6]);
        let vl = std_of_diffs(&logs_a[e - 5..=e]);
        let f: Vec<f64> = vec![
            z[arm],
            z[e],
            zm,
            zrec,
            zrec / dzm.max(1) as f64,
            dzm as f64,
            (z[e] - z[arm]) / OBS as f64,
            z[e] - z[e - 2],
            pxdist,
            pa[e] / pa[arm] - 1.0,
            pa[e] / pa[e - 2] - 1.0,
            pa[e] / pa[e - 3] - 1.0,
            pa[e] / pa[e - 5] - 1.0,
            dpm as f64,
            zrec.max(0.0) * (pa[arm] / pmin - 1.0).max(0.0),
            (z[e] - segz[dzm]) / (OBS - dzm).max(1) as f64,
            (pa[e] - segp[dpm]) / (OBS - dpm).max(1) as f64 / pmin.max(1e-9),
            zrec / pxdist.max(1e-4),
            zm.abs(),
            vl / vf.max(1e-9),
            std_pop(&logs_a[e.saturating_sub(19)..=e]),
            beta[e],
            cfg.leg_id,
        ];
        println!(
            "CHECK {}/{} arm={arm} e={e}  prob={}",
            leg,
            cfg.partner,
            predict(&f, &trees)
        );
        println!(
            "features: {:?}",
            f.iter()
                .map(|x| format!("{:.6}", x))
                .collect::<Vec<_>>()
                .join(",")
        );
        return;
    }

    let mut terminal = if headless {
        None
    } else {
        match setup() {
            Ok(t) => Some(t),
            Err(e) => {
                eprintln!("TUI error: {e}");
                std::process::exit(1);
            }
        }
    };

    let mut ui = Ui {
        bars: W_BETA + W_Z + OBS + 1,
        total: n,
        views: Vec::new(),
        log: Vec::new(),
        enabled: enabled.clone(),
        poll_secs: compute_poll_secs(),
        live: false,
        mom: Vec::new(),
        gate: Vec::new(),
        market_regime: 0,
        sp_regime: 0,
        etf: Vec::new(),
    };
    let mut last_arm = [usize::MAX; LEGS.len()];

    while ui.bars <= n {
        let mut new_views = Vec::new();
        for (k, cfg) in LEGS.iter().enumerate() {
            if !enabled[k] {
                new_views.push((cfg.name.to_string(), 0.0, 0.0, 0.0, 0.0, 0.0, false));
                continue;
            }
            let (pa_full, pb_full) = &full[k];
            let pa = &pa_full[..ui.bars];
            let pb = &pb_full[..ui.bars];
            let s = scan_leg(pa, pb, &trees, cfg.leg_id);
            new_views.push((
                cfg.name.to_string(),
                s.z_now,
                s.z_sig,
                s.zrec,
                s.pxdist,
                s.prob,
                s.watch,
            ));
            if s.watch {
                if let Some(a) = s.arm {
                    if a != last_arm[k] {
                        last_arm[k] = a;
                        let line = format!(
                            "WATCH {} arm_day={} z={:.2} z_rec={:.2} px_low={:.2}% P={:.0}% wait-for-break",
                            cfg.name,
                            a,
                            s.z_sig,
                            s.zrec,
                            s.pxdist * 100.0,
                            s.prob * 100.0
                        );
                        ui.log.push(line.clone());
                        if headless {
                            println!("{line}");
                        }
                    }
                }
            }
        }
        ui.views = new_views;
        let all_prices: Vec<&[f64]> = full.iter().map(|(pa, _)| &pa[..ui.bars]).collect();
        let etf_pairs: Vec<(&[f64], &[f64], &str)> = vec![
            (&bankbees, &setfnifbk, "BANKBEES/SETFNIFBK"),
            (&niftybees, &setfnif50, "NIFTYBEES/SETFNIF50"),
        ];
        compute_overlays(&all_prices, &sp500, &etf_pairs, &mut ui, &enabled);
        ui.bars += 1;

        if let Some(t) = terminal.as_mut() {
            let _ = t.draw(|f| draw(f, &ui));
        }

        if terminal.is_none() {
            continue;
        } // headless: run straight through

        let slow = args.iter().any(|a| a == "--slow");
        if slow {
            let deadline = Instant::now() + Duration::from_millis(BAR_MS);
            while Instant::now() < deadline {
                if let Ok(true) = event::poll(Duration::from_millis(20)) {
                    if let Ok(Event::Key(k)) = event::read() {
                        if k.code == KeyCode::Char('q')
                            || (k.code == KeyCode::Char('c')
                                && k.modifiers.contains(KeyModifiers::CONTROL))
                        {
                            let _ = teardown(terminal.as_mut().unwrap());
                            println!("\nWATCH events:\n{}", ui.log.join("\n"));
                            return;
                        }
                    }
                }
                std::thread::sleep(Duration::from_millis(20));
            }
        }

        loop {
            match event::poll(Duration::from_millis(1)) {
                Ok(true) => match event::read() {
                    Ok(Event::Key(k)) => {
                        if k.code == KeyCode::Char('q')
                            || (k.code == KeyCode::Char('c')
                                && k.modifiers.contains(KeyModifiers::CONTROL))
                        {
                            let _ = teardown(terminal.as_mut().unwrap());
                            println!("\nWATCH events:\n{}", ui.log.join("\n"));
                            return;
                        }
                    }
                    _ => {}
                },
                Ok(false) => break,
                Err(_) => break,
            }
        }
    }
    if let Some(t) = terminal.as_mut() {
        let _ = teardown(t);
    }
    println!("\nWATCH events:\n{}", ui.log.join("\n"));
}
