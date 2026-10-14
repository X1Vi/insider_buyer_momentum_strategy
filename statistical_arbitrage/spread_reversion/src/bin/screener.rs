//! Two-stage Ross-style momentum screener (READ-ONLY).
//!
//! Stage 1: rank sector/theme ETFs (from backtesting/ross/ross_data/etf/)
//!          by momentum + abnormal volume (RVOL) + breakout, pick the hot sectors.
//! Stage 2: for the hot sectors, rank their constituent stocks
//!          (backtesting/ross/ross_data/stock/) by the same features + low float.
//!
//! Data is cached by backtesting/ross/fetch_data.py (yfinance). This binary only
//! reads the cache and prints candidates — it never places orders. It runs as a
//! separate binary so it can be used alongside the WATCH scanner.
//!
//! Usage:
//!   ./target/release/screener                 # full two-stage run
//!   ./target/release/screener --sector BANK   # only rank this sector's stocks
//!   SCREENER_HOT=1                            # only drill into the hot sector
use std::collections::HashMap;
use std::fs;

const DATA: &str = "backtesting/ross/ross_data";

// sector -> (ETF base name, [stock base names])  (matches fetch_data.py)
const SECTORS: [(&str, &str, &[&str]); 5] = [
    (
        "BANK",
        "BANKBEES",
        &[
            "HDFCBANK",
            "ICICIBANK",
            "KOTAKBANK",
            "SBIN",
            "AXISBANK",
            "INDUSINDBK",
        ],
    ),
    (
        "IT",
        "ITBEES",
        &["TCS", "INFY", "WIPRO", "HCLTECH", "TECHM", "LTIM"],
    ),
    (
        "PHARMA",
        "PHARMABEES",
        &[
            "SUNPHARMA",
            "CIPLA",
            "DRREDDY",
            "DIVISLAB",
            "LUPIN",
            "AUROPHARMA",
        ],
    ),
    (
        "AUTO",
        "AUTOBEES",
        &[
            "MARUTI",
            "TATAMOTORS",
            "M&M",
            "BAJAJ-AUTO",
            "EICHERMOT",
            "TVSMOTOR",
        ],
    ),
    (
        "FMCG",
        "CONSUMBEES",
        &[
            "ITC",
            "HINDUNILVR",
            "NESTLEIND",
            "BRITANNIA",
            "DABUR",
            "MARICO",
        ],
    ),
];

const BK_BARS: usize = 20; // breakout window
const VOL_BARS: usize = 20; // RVOL window

#[derive(Default, Clone)]
struct Candle {
    close: Vec<f64>,
    high: Vec<f64>,
    vol: Vec<f64>,
}

fn read_ohlcv(path: &str) -> Option<Candle> {
    let txt = fs::read_to_string(path).ok()?;
    let mut c = Candle::default();
    for line in txt.lines().skip(1) {
        let f: Vec<&str> = line.split(',').collect();
        if f.len() < 6 {
            continue;
        }
        let high = f[2].trim().parse::<f64>().ok()?;
        let close = f[4].trim().parse::<f64>().ok()?;
        let vol = f[5].trim().parse::<f64>().ok()?;
        c.high.push(high);
        c.close.push(close);
        c.vol.push(vol);
    }
    if c.close.is_empty() { None } else { Some(c) }
}

fn read_fundamentals() -> HashMap<String, f64> {
    let mut m = HashMap::new();
    if let Ok(txt) = fs::read_to_string(format!("{DATA}/fundamentals.csv")) {
        for line in txt.lines().skip(1) {
            let f: Vec<&str> = line.split(',').collect();
            if f.len() >= 2 {
                if let Ok(v) = f[1].trim().parse::<f64>() {
                    m.insert(f[0].trim().to_string(), v);
                }
            }
        }
    }
    m
}

/// Cross-sectional z-score of `x` within `vals`.
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

/// Ross-style features from a candle series (15m): (r1, r8, rvol, breakout_margin).
fn features(c: &Candle) -> (f64, f64, f64, f64) {
    let n = c.close.len();
    if n < BK_BARS + 1 {
        return (0.0, 0.0, 0.0, 0.0);
    }
    // skip trailing incomplete bars (yfinance marks forming bars with volume 0)
    let mut last = n - 1;
    while last > 0 && (c.vol[last] <= 0.0 || c.close[last] <= 0.0) {
        last -= 1;
    }
    if last < BK_BARS {
        return (0.0, 0.0, 0.0, 0.0);
    }
    let px = c.close[last];
    let r1 = px / c.close[last - 1] - 1.0;
    let r8 = px / c.close[last - 8] - 1.0;
    // RVOL: last complete bar volume vs prior window average
    let vmean: f64 = c.vol[last - VOL_BARS..last].iter().sum::<f64>() / VOL_BARS as f64;
    let rvol = if vmean > 0.0 {
        c.vol[last] / vmean
    } else {
        0.0
    };
    // breakout: how far close is above the prior BK_BARS highs
    let rh = c.high[last - BK_BARS..last]
        .iter()
        .cloned()
        .fold(f64::MIN, f64::max);
    let bk = if rh > 0.0 { px / rh - 1.0 } else { 0.0 };
    (r1, r8, rvol, bk)
}

fn rank(
    list: &[(String, Candle)],
    float: Option<&HashMap<String, f64>>,
) -> Vec<(String, f64, f64, f64, f64, f64)> {
    let feats: Vec<(String, (f64, f64, f64, f64))> =
        list.iter().map(|(n, c)| (n.clone(), features(c))).collect();
    let r1: Vec<f64> = feats.iter().map(|f| f.1.0).collect();
    let r8: Vec<f64> = feats.iter().map(|f| f.1.1).collect();
    let rv: Vec<f64> = feats.iter().map(|f| f.1.2).collect();
    let bk: Vec<f64> = feats.iter().map(|f| f.1.3).collect();
    // low-float factor: -ln(float_shares), so smaller float -> larger positive value
    let flog: Vec<f64> = feats
        .iter()
        .map(|(n, _)| match float.and_then(|m| m.get(n)) {
            Some(fs) if *fs > 0.0 => -(*fs).ln(),
            _ => 0.0,
        })
        .collect();
    let mut out = Vec::new();
    for (i, (name, f)) in feats.iter().enumerate() {
        let score = 0.25 * zscore(&r1, f.0)
            + 0.30 * zscore(&r8, f.1)
            + 0.25 * zscore(&rv, f.2)
            + 0.20 * zscore(&bk, f.3)
            + if float.is_some() {
                0.10 * zscore(&flog, flog[i])
            } else {
                0.0
            };
        out.push((
            name.clone(),
            score,
            100.0 * f.0,
            100.0 * f.1,
            f.2,
            100.0 * f.3,
        ));
    }
    out.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));
    out
}

fn main() {
    let only = std::env::args().skip(1).collect::<Vec<_>>();
    let hot_only = std::env::var("SCREENER_HOT")
        .map(|v| v == "1")
        .unwrap_or(false);

    // ---- Stage 1: rank sector ETFs ----
    let mut etf_rows = Vec::new();
    for (sector, etf, _stocks) in SECTORS.iter() {
        let path = format!("{DATA}/etf/{etf}_15m.csv");
        if let Some(c) = read_ohlcv(&path) {
            let f = features(&c);
            etf_rows.push((sector.to_string(), f));
        }
    }
    let r1: Vec<f64> = etf_rows.iter().map(|x| x.1.0).collect();
    let r8: Vec<f64> = etf_rows.iter().map(|x| x.1.1).collect();
    let rv: Vec<f64> = etf_rows.iter().map(|x| x.1.2).collect();
    let bk: Vec<f64> = etf_rows.iter().map(|x| x.1.3).collect();
    let mut scored: Vec<(String, f64, f64, f64, f64, f64)> = etf_rows
        .iter()
        .map(|(s, f)| {
            let score = 0.30 * zscore(&r8, f.1)
                + 0.30 * zscore(&rv, f.2)
                + 0.20 * zscore(&r1, f.0)
                + 0.20 * zscore(&bk, f.3);
            (s.clone(), score, 100.0 * f.0, 100.0 * f.1, f.2, 100.0 * f.3)
        })
        .collect();
    scored.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));

    println!("=== STAGE 1 — SECTOR / THEME ETF MOMENTUM (read-only) ===");
    println!(
        "{:<8} {:>7} {:>8} {:>8} {:>7} {:>8}  RANK",
        "SECTOR", "SCORE", "R_30m", "R_2h", "RVOL", "BRK%"
    );
    for (s, sc, r1p, r8p, rv_, bk_) in &scored {
        println!(
            "{:<8} {:>7.2} {:>+7.2}% {:>+7.2}% {:>7.1}x {:>+7.2}%  {}",
            s, sc, r1p, r8p, rv_, bk_, "HOT"
        );
    }
    // hot sectors = top 2 by score, or all with score > 0.5
    let n_hot = scored
        .len()
        .min(2)
        .max(if scored.iter().any(|s| s.1 > 0.5) {
            2
        } else {
            1
        });
    let hot: Vec<&String> = scored.iter().take(n_hot).map(|s| &s.0).collect();
    println!(
        "\nHOT SECTORS: {}",
        hot.iter()
            .map(|s| s.as_str())
            .collect::<Vec<_>>()
            .join(", ")
    );

    // ---- Stage 2: rank stocks in hot (or requested) sectors ----
    let mut targets: Vec<&str> = Vec::new();
    if let Some(i) = only.iter().position(|a| a == "--sector") {
        if let Some(s) = only.get(i + 1) {
            targets.push(s.as_str());
        }
    } else if hot_only {
        for h in &hot {
            targets.push(h.as_str());
        }
    } else {
        for (sector, _, _) in SECTORS.iter() {
            targets.push(sector);
        }
    }

    let float = read_fundamentals();
    for sec in targets {
        let entry = SECTORS.iter().find(|s| s.0 == sec);
        let (_, _etf, stocks) = match entry {
            Some(e) => e,
            None => {
                println!("\nunknown sector {sec}");
                continue;
            }
        };
        let mut rows = Vec::new();
        for st in *stocks {
            let path = format!("{DATA}/stock/{st}_15m.csv");
            if let Some(c) = read_ohlcv(&path) {
                rows.push((st.to_string(), c));
            }
        }
        println!("\n=== STAGE 2 — {sec} STOCKS ===");
        if rows.is_empty() {
            println!(
                "  no cached data — run:  .venv/bin/python backtesting/ross/fetch_data.py {sec}"
            );
            continue;
        }
        let ranked = rank(&rows, Some(&float));
        println!(
            "{:<12} {:>7} {:>8} {:>8} {:>7} {:>8}",
            "STOCK", "SCORE", "R_30m", "R_2h", "RVOL", "BRK%"
        );
        for (name, sc, r1p, r8p, rv_, bk_) in ranked {
            println!(
                "{:<12} {:>7.2} {:>+7.2}% {:>+7.2}% {:>7.1}x {:>+7.2}%",
                name, sc, r1p, r8p, rv_, bk_
            );
        }
    }
    println!("\nNOTE: read-only — identify candidates, place any trade manually.");
}
