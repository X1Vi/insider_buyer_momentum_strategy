//! Backtest the scanner's ML logic over ALL historical pairs.
//! No survivorship bias: every stock in backtesting/data/ and every pair is
//! tested. No look-ahead bias: rolling beta/z, candidate gate and features are
//! computed only from data up to the entry bar; the T2 outcome is the label
//! (data after entry).
//! Uses the SAME code as src/bin/scanner.rs (verbatim copies of the model
//! parser, predictor, rolling beta/z and candidate-feature block).
//! Run:  cargo test --release --test scanner_backtest -- --nocapture

use std::collections::HashMap;
use std::fs;

const W_BETA: usize = 252;
const W_Z: usize = 60;
const Z_ARM: f64 = -3.0;
const OBS: usize = 10;
const GATE_ZREC: f64 = 0.5;
const GATE_PX: f64 = 0.02;
const THRESH: f64 = 0.5; // T2 WATCH threshold
const BASE_SCORE: f64 = -0.29783444391579905; // logit(T2 mean 0.426086) — XGBoost auto base_score
const MODEL_PATH: &str = "backtesting/model_dump.txt";
const OUT_CSV: &str = "backtesting/scanner_backtest_results.csv";

const NAMES: [&str; 18] = [
    "AXISBANK",
    "BAJAJFINSV",
    "COALINDIA",
    "HCLTECH",
    "HDFCBANK",
    "HINDALCO",
    "HINDUNILVR",
    "ICICIBANK",
    "INDUSINDBK",
    "ITC",
    "JSWSTEEL",
    "KOTAKBANK",
    "NESTLEIND",
    "RELIANCE",
    "SBIN",
    "TATASTEEL",
    "TCS",
    "WIPRO",
];

// ----------------------------- model (verbatim from scanner.rs) -----------------------------

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

// ----------------------------- signals (verbatim from scanner.rs) -----------------------------

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

/// Score a candidate arm (a) — verbatim feature block from scanner.rs::scan_leg.
/// Returns NaN if the candidate gate fails (not a candidate).
fn score(
    pa: &[f64],
    pb: &[f64],
    z: &[f64],
    beta: &[f64],
    a: usize,
    leg_id: f64,
    trees: &[Tree],
) -> f64 {
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
    if !(zrec >= GATE_ZREC.max(0.3 * zm.abs()) && pxdist <= GATE_PX) {
        return f64::NAN;
    }
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
    predict(&f, trees)
}

fn load_closes(name: &str) -> Vec<f64> {
    let txt = fs::read_to_string(format!("backtesting/data/{name}.csv")).unwrap_or_else(|e| {
        eprintln!("read {name}: {e}");
        std::process::exit(1);
    });
    txt.lines()
        .skip(1)
        .filter_map(|l| {
            l.split(',')
                .nth(1)
                .and_then(|v| v.trim().parse::<f64>().ok())
        })
        .collect()
}

/// T2 target: hit +2% close before -2% close within 10 trading days (label, uses future data).
fn t2_target(ps: &[f64], i: usize) -> i32 {
    let e0 = ps[i];
    for k in 1..=10 {
        if i + k >= ps.len() {
            return 0;
        }
        let c = ps[i + k];
        if c >= e0 * 1.02 {
            return 1;
        }
        if c <= e0 * 0.98 {
            return 0;
        }
    }
    0
}

#[test]
fn scanner_backtest_all_pairs() {
    let data: Vec<Vec<f64>> = NAMES.iter().map(|n| load_closes(n)).collect();
    let trees = parse_model(MODEL_PATH);
    assert_eq!(trees.len(), 300, "model should have 300 trees");

    let mut out = String::from("leg,partner,arm,entry,prob,t2,fwd5,fwd10\n");
    let mut per_leg: HashMap<String, (i64, i64)> = HashMap::new();
    let (mut n_events, mut n_watch) = (0i64, 0i64);

    for a in 0..NAMES.len() {
        for b in (a + 1)..NAMES.len() {
            let pa_full = &data[a];
            let pb_full = &data[b];
            let n = pa_full.len().min(pb_full.len());
            if n < W_BETA + W_Z + OBS + 20 {
                continue;
            }
            let pa = &pa_full[..n];
            let pb = &pb_full[..n];
            let (z, beta) = compute_z(pa, pb);
            let mut i = W_BETA + W_Z;
            while i + OBS + 20 < n {
                if z[i] < Z_ARM {
                    let e = i + OBS;
                    let prob = score(pa, pb, &z, &beta, i, a as f64, &trees);
                    if prob.is_finite() {
                        // candidate passed the gate
                        let t2 = t2_target(pa, e);
                        let f5 = 100.0 * (pa[e + 5] / pa[e] - 1.0);
                        let f10 = 100.0 * (pa[e + 10] / pa[e] - 1.0);
                        out.push_str(&format!(
                            "{},{},{},{},{:.4},{},{:.2},{:.2}\n",
                            NAMES[a], NAMES[b], i, e, prob, t2, f5, f10
                        ));
                        n_events += 1;
                        if prob >= THRESH {
                            n_watch += 1;
                        }
                        let st = per_leg.entry(NAMES[a].to_string()).or_insert((0, 0));
                        st.0 += 1;
                        if t2 == 1 {
                            st.1 += 1;
                        }
                    }
                    i += 5;
                } else {
                    i += 1;
                }
            }
        }
    }

    fs::write(OUT_CSV, &out).expect("write csv");

    let mut legs: Vec<_> = per_leg.into_iter().collect();
    legs.sort_by(|x, y| {
        (y.1.1 as f64 / y.1.0 as f64)
            .partial_cmp(&(x.1.1 as f64 / x.1.0 as f64))
            .unwrap_or(std::cmp::Ordering::Equal)
    });
    println!("\n=== per-leg T2 win rate (ALL pairs, no survivorship) ===");
    for (leg, (n, w)) in legs {
        println!(
            "  {:<12} n={:>4}  T2 win={:>4.0}%",
            leg,
            n,
            100.0 * w as f64 / n as f64
        );
    }
    println!("\nevents={n_events}  watch(prob>=0.5)={n_watch}  wrote {OUT_CSV}");
    assert!(n_events > 0, "expected candidate events");
}
