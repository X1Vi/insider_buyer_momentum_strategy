# ML v3 WATCH Scanner — Line by Line

File: `src/bin/scanner.rs` (888 lines, as of commit `2cd8770`)

A low-latency, **watch-only** scanner. It loads a trained 300-tree XGBoost model,
replays/receives prices, and computes a `WATCH` probability for 10 stock legs.
It never places orders — a human times the entry after a WATCH signal.

---

## 1. Module docs & imports — lines 1–26

```rust
//! ML v3 WATCH scanner (TUI) — AXISBANK / KOTAKBANK / TATASTEEL.
//! Machine screens (WATCH), human times the entry:
//!   watch for the model's WATCH signal, then wait for lower-low -> rejection
//!   -> upward break before entering. No BUY/SELL triggers — WATCH only.
//! Low latency: rolling computations + XGBoost inference in-process (µs).
//! Usage:
//!   scanner --sim                  replay daily CSVs at 2.5s/bar
//!   scanner (live, needs token)    Groww get_ltp, seeds from CSVs
```

- **L1–8**: Doc comment. Explains the design philosophy: the machine *screens*,
  a human *times* the entry. It's a `--sim` (offline replay) or live (Groww
  quotes) tool. "Low latency" because the model is parsed into Rust structs and
  inferred in-process, no Python.

```rust
use std::collections::HashMap;
use std::sync::Arc;
use std::fs;
use std::io;
use std::time::{Duration, Instant};
```

- **L9–13**: Standard library imports.
  - `HashMap` — cache of last-seen prices for rise alerts.
  - `Arc` — shared `LiveClient` across async tasks.
  - `fs` — read CSV files and the model dump.
  - `io` — stdout for beeps and terminal setup.
  - `Duration`/`Instant` — polling intervals, rise-alert cooldowns.

```rust
use serde::Deserialize;
use sha2::{Digest, Sha256};
```

- **L15–16**: `serde::Deserialize` for the Groww JSON response; `sha2` for the
  API-key login checksum (SHA-256 of `secret + timestamp`).

```rust
use crossterm::event::{self, Event, KeyCode, KeyModifiers};
use crossterm::execute;
use crossterm::terminal::{EnterAlternateScreen, LeaveAlternateScreen, disable_raw_mode, enable_raw_mode};
use ratatui::backend::CrosstermBackend;
use ratatui::layout::{Constraint, Layout};
use ratatui::style::{Color, Modifier, Style};
use ratatui::text::{Line, Span};
use ratatui::widgets::{Block, Borders, List, ListItem, Paragraph};
use ratatui::Terminal;
```

- **L18–26**: TUI stack — `crossterm` for raw-mode/alternate-screen/key events,
  `ratatui` for the terminal UI widgets.

---

## 2. Tuning constants — lines 28–38

```rust
const W_BETA: usize = 252;   // rolling-beta lookback (trading days)
const W_Z: usize = 60;       // rolling z-score mean/std lookback
const Z_ARM: f64 = -3.0;     // "arm" = z dipped below -3
const OBS: usize = 10;       // observation window after the arm
const GATE_ZREC: f64 = 0.5;  // min z-recovery to even consider a leg
const GATE_PX: f64 = 0.02;   // max % above the price low
const THRESH: f64 = 0.5;     // model probability to emit WATCH
const RISE_ALERT_PCT: f64 = 0.005; // alert if a leg rises >=0.5% since last poll
const BASE_SCORE: f64 = -0.2817;   // XGBoost default base_score (logit)
const MODEL_PATH: &str = "backtesting/model_dump.txt";
const BAR_MS: u64 = 2500;    // sim replay speed (ms per bar)
```

- **L28–38**: All hyperparameters. These **must match** the Python training
  script `backtesting/export_model.py` exactly, or features/z-scores computed at
  runtime will diverge from training.
- `BASE_SCORE` = `logit(0.43)` ≈ −0.2817 — XGBoost's additive base margin before
  tree outputs.

---

## 3. Model: structs + parser + inference — lines 40–115

```rust
struct Node {
    feature: i32,
    threshold: f64,
    yes: usize,
    no: usize,
    is_leaf: bool,
    leaf: f64,
}
type Tree = Vec<Node>;
```

- **L42–50**: In-memory representation of one XGBoost tree node.
  - Internal node: `feature` index to test, `threshold` to compare against,
    `yes`/`no` child indices (XGBoost dump uses explicit node ids, not DFS order).
  - Leaf: `is_leaf=true`, `leaf` holds the output contribution.

```rust
fn parse_tail_int(tail: &str, key: &str) -> usize {
    if let Some(p) = tail.find(key) {
        let s = &tail[p + key.len()..];
        let e = s.find(|c: char| !c.is_ascii_digit()).unwrap_or(s.len());
        s[..e].trim().parse().unwrap_or(0)
    } else {
        0
    }
}
```

- **L52–60**: Helper to pull an integer like `yes=3` out of the raw model text:
  find `key`, skip past it, read consecutive digits, parse as `usize`.
  Returns `0` on any failure (defaults to node 0, which would be a bug — but the
  dump is machine-generated so this is safe).

```rust
fn parse_model(path: &str) -> Vec<Tree> {
    let txt = fs::read_to_string(path)
        .unwrap_or_else(|e| { eprintln!("read {path}: {e}"); std::process::exit(1); });
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
```

- **L62–75**: Parse `model_dump.txt` into `Vec<Tree>`.
  - Each tree starts with a `booster[N]:` line → flush the accumulated nodes into
    `trees`, sorted by explicit node id so `t[id]` is valid indexing.
  - Tabs are stripped because leaf lines are indented with tabs in the dump.

```rust
        let mut it = body.splitn(2, ':');
        let id: usize = it.next().unwrap_or("0").trim().parse().unwrap_or(0);
        let rest = it.next().unwrap_or("");
        if rest.starts_with("leaf=") {
            let v: f64 = rest["leaf=".len()..].trim().parse().unwrap_or(0.0);
            nodes.push((id, Node { feature: -1, threshold: 0.0, yes: 0, no: 0, is_leaf: true, leaf: v }));
        } else {
            let inner = rest.trim_start_matches('[').split(']').next().unwrap_or("");
            let after_f = inner.trim_start_matches('f');
            let (fs, ts) = match after_f.split_once('<') { Some(x) => x, None => continue };
            let feat: i32 = fs.trim().parse().unwrap_or(-1);
            let thr: f64 = ts.trim().parse().unwrap_or(0.0);
            let tail = rest.split(']').nth(1).unwrap_or("");
            let yes = parse_tail_int(tail, "yes=");
            let no = parse_tail_int(tail, "no=");
            nodes.push((id, Node { feature: feat, threshold: thr, yes, no, is_leaf: false, leaf: 0.0 }));
        }
    }
    if !nodes.is_empty() {
        nodes.sort_by_key(|(id, _)| *id);
        trees.push(nodes.drain(..).map(|(_, n)| n).collect());
    }
    trees
}
```

- **L76–98**: Per-line parsing:
  - `leaf=0.042` → leaf node with value.
  - `0:[f20<0.019657582] yes=1,no=2,missing=2` → internal node testing
    `feature 20 < threshold`. `missing=` is ignored (we always supply all 23
    features, no NaNs).
- **L94–97**: Flush any remaining nodes after the last `booster` line.

```rust
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
            id = if feats[nd.feature as usize] < nd.threshold { nd.yes } else { nd.no };
        }
    }
    1.0 / (1.0 + (-margin).exp())
}
```

- **L101–115**: XGBoost inference.
  - Start the additive margin at `BASE_SCORE`, walk each tree from node 0 until a
    leaf, accumulate leaf outputs, then apply the **sigmoid** `1/(1+e^-margin)`
    to get a probability in `[0,1]`. This is the model's `P(trade succeeds)`.

---

## 4. Signals: rolling math — lines 117–186

```rust
fn rolling_beta(la: &[f64], lb: &[f64]) -> (Vec<f64>, Vec<f64>) {
    let n = la.len();
    let mut beta = vec![0.0f64; n];
    let mut alpha = vec![0.0f64; n];
    for i in (W_BETA - 1)..n {
        let s = i + 1 - W_BETA;
        let (mut mx, mut my) = (0.0f64, 0.0f64);
        for j in s..=i { mx += lb[j]; my += la[j]; }
        mx /= W_BETA as f64;
        my /= W_BETA as f64;
        let (mut sxy, mut sxx) = (0.0f64, 0.0f64);
        for j in s..=i {
            let (dx, dy) = (lb[j] - mx, la[j] - my);
            sxy += dx * dy;
            sxx += dx * dx;
        }
        if sxx > 1e-12 { beta[i] = sxy / sxx; }
        alpha[i] = my - beta[i] * mx;
    }
    (beta, alpha)
}
```

- **L119–139**: OLS regression of log-price leg A on log-price leg B over the
  last `W_BETA=252` bars, computed by hand (no linear-algebra crate):
  - `beta = Σ(x−x̄)(y−ȳ) / Σ(x−x̄)²` (slope), `alpha = ȳ − beta·x̄` (intercept).
  - Stored per-index so later bars have full 252-bar history. This is the
    hedge ratio β≈1 used to build the spread.

```rust
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
```

- **L141–152**: Rolling mean and **sample** std (÷`w−1`) of the spread over
  `W_Z=60` bars — these normalize the spread into a z-score.

```rust
fn std_pop(v: &[f64]) -> f64 {
    if v.is_empty() { return 0.0; }
    let m = v.iter().sum::<f64>() / v.len() as f64;
    (v.iter().map(|x| (x - m).powi(2)).sum::<f64>() / v.len() as f64).sqrt()
}
```

- **L154–158**: Population std (÷`n`) — used for feature 20 (volatility of the
  leg's log returns).

```rust
fn std_of_diffs(logs: &[f64]) -> f64 {
    if logs.len() < 2 { return 0.0; }
    let d: Vec<f64> = logs.windows(2).map(|w| w[1] - w[0]).collect();
    std_pop(&d)
}
```

- **L160–164**: Std of consecutive log-price *differences* = realized vol of
  returns. Used for features `vf`/`vl` (fast vs. late volatility).

```rust
fn beep() {
    use std::io::Write as _;
    for _ in 0..4 {
        print!("\x07");
        let _ = io::stdout().flush();
    }
}
```

- **L166–172**: Fire 4 terminal bells `\x07` — audible alert in the TUI.

```rust
fn compute_z(pa: &[f64], pb: &[f64]) -> (Vec<f64>, Vec<f64>) {
    let n = pa.len();
    let la: Vec<f64> = pa.iter().map(|x| x.ln()).collect();
    let lb: Vec<f64> = pb.iter().map(|x| x.ln()).collect();
    let (beta, alpha) = rolling_beta(&la, &lb);
    let spread: Vec<f64> = (0..n).map(|i| la[i] - beta[i] * lb[i] - alpha[i]).collect();
    let (mu, sd) = rolling_mean_std(&spread, W_Z);
    let mut z = vec![0.0f64; n];
    for i in (W_BETA + W_Z)..n {
        if sd[i] > 1e-9 { z[i] = (spread[i] - mu[i]) / sd[i]; }
    }
    (z, beta)
}
```

- **L174–186**: The core statistic:
  - `spread = log(A) − β·log(B) − α` — the residuals, i.e. the mispricing.
  - `z[i] = (spread[i] − mean) / std` over the 60-bar window.
  - Zeros are kept until `W_BETA + W_Z` bars (both lookbacks filled).
  - Returns z-series **and** β-series (β is a model feature).

---

## 5. Signals: the scan — lines 188–259

```rust
struct ScanOut {
    z_now: f64,      // current z at the live-updated last bar (moves every poll)
    z_sig: f64,      // z at the WATCH candidate entry (what the signal was based on)
    zrec: f64, pxdist: f64, prob: f64,
    watch: bool, arm: Option<usize>, live_arm: bool,
}
```

- **L188–193**: What one scan of one leg returns.
  - `z_now` = z of the *live* last bar (updates every poll),
  - `z_sig` = z at the candidate's observation-end (fixed),
  - `zrec` = z-recovery since the arm's z-min,
  - `pxdist` = how far price has rebounded off its low,
  - `prob` = model probability, `watch` = signal fired,
  - `arm` = index where the setup began, `live_arm` = currently dislocated (z<−3).

```rust
fn scan_leg(pa: &[f64], pb: &[f64], trees: &[Tree], leg_id: f64) -> ScanOut {
    let n = pa.len();
    let mut out = ScanOut { z_now: 0.0, z_sig: 0.0, zrec: 0.0, pxdist: 0.0, prob: 0.0,
        watch: false, arm: None, live_arm: false };
    if n < W_BETA + W_Z + OBS {
        return out;
    }
```

- **L195–201**: Guard: need `252 + 60 + 10` bars minimum before anything is
  computed; otherwise return an empty scan.

```rust
    let (z, beta) = compute_z(pa, pb);
    // find the latest arm with a completed observation window
    let mut arm = None;
    let mut i = W_BETA + W_Z;
    while i + OBS < n {
        if z[i] < Z_ARM { arm = Some(i); i += 5; } else { i += 1; }
    }
    let a = match arm { Some(x) => x, None => return out };
    let e = a + OBS;
```

- **L202–210**: Find the **latest** index where z < −3 ("the arm" — where the
  spread got stretched abnormally low), skipping in steps of 5 past a found arm
  (dilution), and require a full `OBS=10` window to follow it. `e = a+10` is the
  observation end. If no arm → no signal.

```rust
    let segz = &z[a..=e];
    let segp = &pa[a..=e];
    let (mut zm, mut dzm) = (f64::INFINITY, 0usize);
    let (mut pmin, mut dpm) = (f64::INFINITY, 0usize);
    for k in 0..segz.len() {
        if segz[k] < zm { zm = segz[k]; dzm = k; }
        if segp[k] < pmin { pmin = segp[k]; dpm = k; }
    }
    let zrec = z[e] - zm;
    let pxdist = pa[e] / pmin - 1.0;
```

- **L211–220**: Within the 11-bar window (`a..=e`) find:
  - the minimum z (`zm`) and its offset (`dzm`),
  - the minimum price (`pmin`) and its offset (`dpm`).
  - `zrec` = z-recovery from the z-bottom to now,
  - `pxdist` = % price rebound off the low.

```rust
    out.z_now = if n >= W_BETA + W_Z { z[n - 1] } else { 0.0 };
    out.live_arm = out.z_now < Z_ARM;
    out.z_sig = z[e];
    if !(zrec >= GATE_ZREC.max(0.3 * zm.abs()) && pxdist <= GATE_PX) {
        out.zrec = zrec; out.pxdist = pxdist;
        return out;
    }
```

- **L221–227**: Set the display z's, then **gate** the setup:
  - z must have recovered at least `max(0.5, 0.3·|z_min|)` from its bottom,
  - price must have rebounded ≤2% off its low (i.e. still *near* the low —
    a reversal candidate, not already far off).
  - Fail the gate → record metrics but no WATCH.

```rust
    // features (order must match training)
    let logs_a: Vec<f64> = pa.iter().map(|x| x.ln()).collect();
    let vf = std_of_diffs(&logs_a[a..a + 6]);
    let vl = std_of_diffs(&logs_a[e - 5..=e]);
    let f: Vec<f64> = vec![
        z[a], z[e], zm, zrec,
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
    out.zrec = zrec; out.pxdist = pxdist; out.prob = prob;
    out.watch = prob >= THRESH;
    out.arm = Some(a);
    out
}
```

- **L228–259**: Build the **23 features**, index-for-index identical to
  `FEATURES` in `export_model.py`:
  1. `z_arm` — z at arm start
  2. `z_now` — z at obs end
  3. `z_min` — deepest z in window
  4. `z_rec` — z recovery off bottom
  5. `z_rec_speed` — recovery per day since z-bottom
  6. `days_zmin` — where the z-bottom sits
  7. `zslope_win` — z drift per day over the window
  8. `zslope_short` — last-2-day z change
  9. `px_dist_low` — price rebound %
  10–13. `px_ret_arm`, `ret_last2/3/5` — leg-A returns over various horizons
  14. `days_pxlow` — where the price low sits
  15. `div` — z-recovery × price-drop-at-arm interaction
  16. `z_slope_after_min` — recovery slope after z-bottom
  17. `px_slope_after_min` — price recovery slope after low
  18. `div_strength` — recovery per unit of price distance
  19. `drop_depth` — |z_min|
  20. `vol_ratio` — late vol / fast vol
  21. `svol20` — 20-bar realized vol
  22. `beta` — rolling hedge ratio
  23. `leg_id` — one-hot-ish leg identity (a categorical embedded as float).
  - Then `predict()` → `prob`, and `WATCH` iff `prob ≥ 0.5`.

---

## 6. Leg config & data loading — lines 263–321

```rust
struct LegCfg { name: &'static str, partner: &'static str, leg_id: f64, conf: &'static str, enabled: bool }

const LEGS: [LegCfg; 10] = [
    LegCfg { name: "AXISBANK",  partner: "RELIANCE",  leg_id: 0.0,  conf: "HIGH", enabled: true },
    LegCfg { name: "BAJAJFINSV", partner: "RELIANCE",  leg_id: 1.0,  conf: "MOD",  enabled: true },
    LegCfg { name: "HDFCBANK",  partner: "KOTAKBANK", leg_id: 4.0,  conf: "HIGH", enabled: true },
    LegCfg { name: "HINDALCO",  partner: "JSWSTEEL",  leg_id: 5.0,  conf: "HIGH", enabled: true },
    LegCfg { name: "ICICIBANK", partner: "KOTAKBANK", leg_id: 7.0,  conf: "HIGH", enabled: true },
    LegCfg { name: "JSWSTEEL",  partner: "TATASTEEL", leg_id: 10.0, conf: "HIGH", enabled: true },
    LegCfg { name: "KOTAKBANK", partner: "RELIANCE",  leg_id: 11.0, conf: "HIGH", enabled: true },
    LegCfg { name: "NESTLEIND", partner: "ITC",       leg_id: 12.0, conf: "MED",  enabled: true },
    LegCfg { name: "SBIN",      partner: "ICICIBANK", leg_id: 14.0, conf: "HIGH", enabled: true },
    LegCfg { name: "TATASTEEL", partner: "TCS",       leg_id: 15.0, conf: "HIGH", enabled: true },
];
```

- **L263–276**: The 10 screened legs. `leg_id` values must match what
  `export_model.py` learned. `conf` is just a display tag; `enabled` is the
  static default before env overrides.

```rust
/// Unique symbols across all legs (fixed fetch set -> constant rate).
fn unique_symbols() -> Vec<&'static str> {
    let mut v: Vec<&'static str> = Vec::new();
    for c in LEGS.iter() {
        if !v.contains(&c.name) { v.push(c.name); }
        if !v.contains(&c.partner) { v.push(c.partner); }
    }
    v
}
```

- **L278–286**: Deduplicated list of all tickers to fetch (a leg and its partner
  may share a ticker, e.g. RELIANCE) → stable API call count.

```rust
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
```

- **L288–298**: Rate-limit math. With 16 unique symbols, `16·60/240 = 4s`.
  Never below 3s. `SCANNER_POLL_SECS` overrides.

```rust
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
```

- **L300–312**: `SCANNER_LEGS=AXISBANK,HDFCBANK` whitelists which legs run.

```rust
fn load_closes(name: &str) -> Vec<f64> {
    let txt = fs::read_to_string(format!("backtesting/data/{name}.csv"))
        .unwrap_or_else(|e| { eprintln!("read {name}: {e}"); std::process::exit(1); });
    txt.lines()
        .skip(1)
        .filter_map(|l| l.split(',').nth(1).and_then(|v| v.trim().parse::<f64>().ok()))
        .collect()
}
```

- **L314–321**: Read `backtesting/data/{NAME}.csv`, skip the header, take the
  **2nd column** (the `close` column) as the price series. These seeds supply the
  full history that live mode overlays.

---

## 7. TUI state & rendering — lines 323–423

```rust
struct Ui {
    bars: usize,
    total: usize,
    views: Vec<(String, f64, f64, f64, f64, f64, bool)>, // (leg, z_now, z_sig, zrec, pxdist, prob, watch)
    log: Vec<String>,
    enabled: Vec<bool>,
    poll_secs: u64,
    live: bool,
}
```

- **L323–331**: UI state: replay progress (`bars`/`total`), the per-leg view row,
  the event log ring, enabled flags, poll interval, and live/seeded flag.

```rust
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
```

- **L333–343**: Enter/leave raw mode + alternate screen (full-screen TUI).

```rust
fn draw(f: &mut ratatui::Frame, ui: &Ui) {
    let area = f.area();
    let rows = Layout::default().direction(ratatui::layout::Direction::Vertical)
        .constraints([
            Constraint::Length(3),
            Constraint::Length((LEGS.len() + 3) as u16),
            Constraint::Min(4),
            Constraint::Length(1),
        ]).split(area);
```

- **L345–353**: Four vertical sections: header (3 rows), legs table
  (10 + 3 rows), events (fill), footer (1 row).

```rust
    let conn = if ui.live { "● LIVE" } else { "● SEEDED" };
    let conn_style = if ui.live {
        Style::default().fg(Color::Green).add_modifier(Modifier::BOLD)
    } else {
        Style::default().fg(Color::Red).add_modifier(Modifier::BOLD)
    };
    let header = Paragraph::new(vec![
        Line::from(vec![
            Span::styled(" ML v3 WATCH SCANNER ",
                Style::default().fg(Color::Black).bg(Color::Yellow).add_modifier(Modifier::BOLD)),
            Span::raw("  "),
            Span::styled(conn, conn_style),
        ]),
        Line::from(format!(
            " poll {}s   enabled {}/{}   bars {}/{}",
            ui.poll_secs,
            ui.enabled.iter().filter(|e| **e).count(),
            ui.enabled.len(),
            ui.bars,
            ui.total
        )),
    ]).block(Block::default().borders(Borders::BOTTOM));
    f.render_widget(header, rows[0]);
```

- **L355–378**: Header bar: title, green `● LIVE` vs red `● SEEDED`, poll rate,
  enabled count, replay progress.

```rust
    let mut lines = Vec::new();
    lines.push(ListItem::new(Span::styled(
        format!("{:>2}. {:<11} {:<5} {:>10} {:>5}  STATUS", "#", "LEG", "CONF", "z_now", "P"),
        Style::default().fg(Color::Cyan).add_modifier(Modifier::BOLD))));
    for (k, v) in ui.views.iter().enumerate() {
        let (name, z_now, _z_sig, _zrec, _px, prob, watch) = v;
        let on = ui.enabled.get(k).copied().unwrap_or(true);
        let conf = LEGS.get(k).map(|c| c.conf).unwrap_or("");
        let (style, status) = if !on {
            (Style::default().fg(Color::DarkGray), "OFF".to_string())
        } else if *watch {
            (Style::default().fg(Color::Green).add_modifier(Modifier::BOLD), "WATCH".to_string())
        } else {
            (Style::default().fg(Color::Gray), "wait".to_string())
        };
        let line = format!("{:>2}. {:<11} {:<5} {:>10.5} {:>4.0}%  {}",
                           k + 1, name, conf, z_now, prob * 100.0, status);
        lines.push(ListItem::new(Span::styled(line, style)));
    }
    f.render_widget(
        List::new(lines).block(Block::default().borders(Borders::ALL).title("LEGS")),
        rows[1]);
```

- **L380–402**: Legs table. Each row: index, ticker, confidence tag, `z_now`,
  probability %, and status (`WATCH` green / `wait` grey / `OFF` dark grey).

```rust
    let items: Vec<ListItem> = ui.log.iter().rev().take(25)
        .map(|s| {
            let t: String = if s.chars().count() > 100 {
                s.chars().take(100).collect::<String>() + "…"
            } else {
                s.clone()
            };
            let color = if t.contains("WATCH") { Color::Yellow }
                else if t.contains("RISE") { Color::Green }
                else if t.contains("DISLOCATION") { Color::Cyan }
                else { Color::Gray };
            ListItem::new(Span::styled(t, Style::default().fg(color)))
        }).collect();
    f.render_widget(List::new(items).block(Block::default().borders(Borders::ALL).title("EVENTS")), rows[2]);
```

- **L404–418**: Event log — newest 25 entries, truncated to 100 chars,
  colour-coded by keyword (`WATCH` yellow, `RISE` green, `DISLOCATION` cyan).

```rust
    f.render_widget(
        Paragraph::new(" q quit   ·   1..9,0 toggle leg   ·   SCANNER_LEGS subset   ·   SCANNER_POLL_SECS rate"),
        rows[3]);
}
```

- **L420–423**: Footer key hints.

---

## 8. Groww live client — lines 426–475

```rust
struct LiveClient { http: reqwest::Client, token: String }

impl LiveClient {
    fn new(token: &str) -> Self {
        Self { http: reqwest::Client::new(), token: token.to_string() }
    }
    async fn quote(&self, sym: &str) -> anyhow::Result<f64> {
        let url = format!(
            "https://api.groww.in/v1/live-data/quote?exchange=NSE&segment=CASH&trading_symbol={sym}");
        let resp = self.http.get(&url)
            .header("Accept", "application/json")
            .header("Authorization", format!("Bearer {}", self.token))
            .header("X-API-VERSION", "1.0")
            .send().await?;
        if !resp.status().is_success() {
            anyhow::bail!("quote HTTP {}", resp.status());
        }
        #[derive(Deserialize)]
        struct Env { status: String, payload: Option<Payload> }
        #[derive(Deserialize)]
        struct Payload { last_price: Option<f64> }
        let e: Env = resp.json().await?;
        if e.status != "SUCCESS" {
            anyhow::bail!("quote status {}", e.status);
        }
        e.payload.and_then(|p| p.last_price).ok_or_else(|| anyhow::anyhow!("no last_price"))
    }
```

- **L428–454**: The one Groww endpoint the scanner uses — the live quote. GET with
  a bearer token, parse `{status, payload:{last_price}}`, return `last_price`.

```rust
    async fn login(api_key: &str, secret: &str) -> anyhow::Result<String> {
        let ts = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)?
            .as_secs().to_string();
        let checksum: String = Sha256::digest(format!("{secret}{ts}")).iter().map(|b| format!("{b:02x}")).collect();
        #[derive(Serialize)]
        struct Req { key_type: &'static str, checksum: String, timestamp: String }
        #[derive(Deserialize)]
        struct Res { token: String }
        let resp = reqwest::Client::new()
            .post("https://api.groww.in/v1/token/api/access")
            .header("Accept", "application/json")
            .header("Authorization", format!("Bearer {api_key}"))
            .json(&Req { key_type: "approval", checksum, timestamp: ts })
            .send().await?;
        if !resp.status().is_success() {
            anyhow::bail!("auth HTTP {}", resp.status());
        }
        Ok(resp.json::<Res>().await?.token)
    }
}
```

- **L455–475**: Token generation: `checksum = SHA256(secret + unix_seconds)`,
  POST it with `key_type=approval` → returns a fresh access token. This is the
  second (and only other) Groww endpoint allowed by the project rules.

---

## 9. Pushover notifications — lines 477–539

```rust
use serde::Serialize;

/// Append a timestamped line to pushover.log so send outcomes are always visible,
/// even under the TUI (which hides stderr).
fn log_push(line: &str) {
    let ts = chrono::Local::now().format("%Y-%m-%d %H:%M:%S");
    if let Ok(mut f) = std::fs::OpenOptions::new().create(true).append(true).open("pushover.log") {
        use std::io::Write as _;
        let _ = writeln!(f, "[{ts}] {line}");
    }
}
```

- **L477–487**: Append an outcome line to `pushover.log` — the TUI hides stderr,
  so this file is the persistent audit trail.

```rust
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
```

- **L492–508**: Env-driven push client. No/empty env vars → log `SKIP` and return
  `false`, so the scanner still runs headless without Pushover.

```rust
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
```

- **L510–539**: POST a form to Pushover. Every outcome — `OK` / `REJECTED` /
  `SEND ERROR` — is logged to `pushover.log`.

```rust
fn fetch_token() -> String {
    if let Ok(t) = std::env::var("GROWW_ACCESS_TOKEN") {
        let t = t.trim().trim_matches('"').trim_matches('\'').trim();
        if !t.is_empty() { return t.to_string(); }
    }
    let rt = tokio::runtime::Builder::new_current_thread().enable_all().build().unwrap();
    let k = std::env::var("GROWW_API_KEY").ok();
    let s = std::env::var("GROWW_API_SECRET").ok();
    if let (Some(k), Some(s)) = (k, s) {
        if let Ok(t) = rt.block_on(LiveClient::login(&k, &s)) { return t; }
    }
    eprintln!("FATAL: set GROWW_ACCESS_TOKEN or GROWW_API_KEY/GROWW_API_SECRET");
    std::process::exit(1);
}
```

- **L541–554**: Prefer a pre-fetched `GROWW_ACCESS_TOKEN`; else generate one via
  API key/secret; else fatal-exit. Priority matches the project's auth rules.

---

## 10. Live mode — lines 556–744

```rust
fn live_mode(trees: &[Tree], mut terminal: Option<Terminal<CrosstermBackend<io::Stdout>>>, mut enabled: Vec<bool>) {
    dotenvy::dotenv().ok();
    let client = Arc::new(LiveClient::new(&fetch_token()));
    let rt = tokio::runtime::Builder::new_multi_thread().enable_all().build().unwrap();
    let mut seeds: Vec<(Vec<f64>, Vec<f64>)> = LEGS.iter()
        .map(|c| (load_closes(c.name), load_closes(c.partner))).collect();
    let n = seeds.iter().map(|(a, _)| a.len()).min().unwrap_or(0);
    let symbols = unique_symbols();
    let poll_secs = compute_poll_secs();
```

- **L556–564**: Live-mode setup: load `.env`, build a multi-threaded Tokio runtime
  (quote fetches run concurrently), seed every leg from its CSV, and compute the
  poll interval. `n` = shortest history (all legs share a common length).

```rust
    let no_tui = terminal.is_none();
    let mut ui = Ui { bars: n, total: n, views: Vec::new(), log: Vec::new(),
                      enabled: enabled.clone(), poll_secs, live: false };
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
    rt.block_on(pushover(&http, "ML3 — Scanner started",
        &format!("{}/{} symbols live, {} legs enabled, poll {}s. Notifications active.",
                 symbols.len(), symbols.len(), enabled.iter().filter(|e| **e).count(), poll_secs),
        0));
```

- **L566–587**: State:
  - `last_arm` — per leg, the arm we already alerted on (dedup WATCH pushes),
  - `prev_live_arm` — for edge-triggered dislocation alerts,
  - `prev_px` / `last_rise_push` — rise-detection + per-leg 5-min push cooldown.
  - A startup Pushover confirms notifications are wired before anything else.

```rust
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
```

- **L589–607**: Main poll loop. Fire **all** symbol quotes concurrently via
  `tokio::spawn`, collect successes into a map. `ok_count < len` means some
  quotes failed (e.g. auth/rate issues).

```rust
        if ok_count < symbols.len() && !auth_notified {
            if no_tui {
                eprintln!("NOTE: live quotes unavailable ({}/{} fetched) - showing seeded last bar", ok_count, symbols.len());
            }
            auth_notified = true;
        }
        for (k, cfg) in LEGS.iter().enumerate() {
            if let Some(v) = prices.get(cfg.name) { seeds[k].0[n - 1] = *v; }
            if let Some(v) = prices.get(cfg.partner) { seeds[k].1[n - 1] = *v; }
        }
```

- **L609–618**: Warn once if quotes are partially failing. Then **overwrite the
  last bar** of each leg's seeded history with the live price — so the whole
  rolling math runs on history + one live price point.

```rust
        let mut new_views = Vec::new();
        let mut tick_line = String::new();
        for (k, cfg) in LEGS.iter().enumerate() {
            if !enabled[k] {
                new_views.push((cfg.name.to_string(), 0.0, 0.0, 0.0, 0.0, 0.0, false));
                continue;
            }
            let s = scan_leg(&seeds[k].0, &seeds[k].1, trees, cfg.leg_id);
            new_views.push((cfg.name.to_string(), s.z_now, s.z_sig, s.zrec, s.pxdist, s.prob, s.watch));
            tick_line.push_str(&format!(" {} z={:.3} P={:.0}%", cfg.name, s.z_now, s.prob * 100.0));
```

- **L620–630**: Scan every enabled leg (disabled legs render as all-zeros) and
  build the one-line headless summary.

```rust
            // minimal: alert sound when the leg starts rising significantly since last poll
            let px_now = seeds[k].0[n - 1];
            if let Some(pv) = prev_px.get(cfg.name) {
                if px_now >= *pv * (1.0 + RISE_ALERT_PCT) {
                    let rise = 100.0 * (px_now / pv - 1.0);
                    let line = format!("RISE {} STOCK +{rise:.2}% ({px_now:.2} vs {pv:.2})", cfg.name);
                    ui.log.push(line.clone());
                    if no_tui { println!("\x1b[32m{line}\x1b[0m"); }
                    beep();
                    // push on rise too, but at most once per leg per 5 min to avoid spam
                    let now = Instant::now();
                    let cooled = last_rise_push.get(cfg.name)
                        .map_or(true, |t| now.duration_since(*t) > Duration::from_secs(300));
                    if cooled {
                        last_rise_push.insert(cfg.name.to_string(), now);
                        let _ = rt.block_on(pushover(
                            &http, "ML3 — RISE ALERT",
                            &format!("{} +{rise:.2}%  ({px_now:.2} vs {pv:.2})", cfg.name),
                            0,
                        ));
                    }
                }
            }
            prev_px.insert(cfg.name.to_string(), px_now);
```

- **L631–654**: Rise alert — if a leg jumped ≥0.5% since the last poll: beep,
  log, and push (capped at one push per leg per 5 min).

```rust
            if s.live_arm && !prev_live_arm[k] {
                let line = format!("FRESH DISLOCATION on {} STOCK (z_now={:.3} < -3)", cfg.name, s.z_now);
                ui.log.push(line.clone());
                if no_tui { println!("\x1b[36m{line}\x1b[0m"); }
                let _ = rt.block_on(pushover(
                    &http, "ML3 — FRESH DISLOCATION",
                    &format!("{} STOCK  z_now={:.3} < -3  (setup for WATCH)", cfg.name, s.z_now),
                    1,
                ));
            }
            prev_live_arm[k] = s.live_arm;
```

- **L655–665**: Edge-triggered "fresh dislocation" — the moment z_now drops below
  −3 (a potential arm forming). Priority-1 push.

```rust
            if s.watch {
                if let Some(a) = s.arm {
                    if a != last_arm[k] {
                        last_arm[k] = a;
                        let line = format!(
                            "WATCH {} STOCK  (P={:.0}%  z_now={:.3}  px_low={:.2}%)",
                            cfg.name, s.prob * 100.0, s.z_now, s.pxdist * 100.0);
                        ui.log.push(line.clone());
                        if no_tui { println!("\x1b[33m{line}\x1b[0m"); }
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
        ui.live = ok_count > 0;
```

- **L666–686**: The **WATCH signal** — only pushed once per distinct arm
  (`a != last_arm[k]`), telling the human to wait for the upward break.

```rust
        if tick % SUMMARY_EVERY == 0 {
            let watch: Vec<String> = ui.views.iter()
                .enumerate()
                .filter(|(k, v)| v.6 && enabled.get(*k).copied().unwrap_or(true))
                .map(|(_, v)| v.0.clone())
                .collect();
            let watch_txt = if watch.is_empty() { "none".to_string() } else { watch.join(",") };
            let _ = rt.block_on(pushover(
                &http, "ML3 — Status",
                &format!("tick {tick}  {ok_count}/{} live  enabled {}/{}  WATCH: {}",
                         symbols.len(),
                         enabled.iter().filter(|e| **e).count(),
                         enabled.len(),
                         watch_txt),
                0,
            ));
        }
```

- **L688–705**: Every 10 polls, a low-priority status heartbeat listing which
  legs are currently on WATCH.

```rust
        if no_tui {
            if ok_count > 0 {
                println!("[tick {tick}] {ok_count}/{} LIVE |{tick_line}", symbols.len());
            } else if tick % 5 == 0 {
                println!("[tick {tick}] no live prices (seeded) |{tick_line}");
            }
        }
```

- **L707–713**: Headless console output per tick.

```rust
        if let Some(t) = terminal.as_mut() {
            let _ = t.draw(|f| draw(f, &ui));
            // poll keys DURING the sleep window so q/digits are always caught
            let deadline = Instant::now() + Duration::from_secs(poll_secs);
            while Instant::now() < deadline {
                if let Ok(true) = event::poll(Duration::from_millis(50)) {
                    if let Ok(Event::Key(k)) = event::read() {
                        match k.code {
                            KeyCode::Char('q') => { let _ = teardown(t); return; }
                            KeyCode::Char('c') if k.modifiers.contains(KeyModifiers::CONTROL) => {
                                let _ = teardown(t); return;
                            }
                            KeyCode::Char(d) if d.is_ascii_digit() => {
                                let idx = if d == '0' { 9 } else { d as usize - '1' as usize };
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
```

- **L715–743**: TUI loop: redraw, then poll keys *during* the sleep window:
  - `q` / `Ctrl-C` → teardown + exit,
  - `1..9,0` → toggle that leg on/off.
  - Headless simply sleeps the whole poll interval.

---

## 11. main — lines 746–888

```rust
fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let headless = args.iter().any(|a| a == "--headless");
    let live = args.iter().any(|a| a == "--live");
    let trees = parse_model(MODEL_PATH);
    println!("loaded {} trees from {MODEL_PATH}", trees.len());
    let enabled = enabled_from_env();
    if live {
        let terminal = if headless { None } else {
            match setup() { Ok(t) => Some(t), Err(e) => { eprintln!("TUI error: {e}"); None } }
        };
        live_mode(&trees, terminal, enabled);
        return;
    }
```

- **L746–759**: Parse args, load the 300 trees once (shared by all legs), apply
  env overrides. `--live` (+ optional `--headless`) → `live_mode`.

```rust
    // pre-load full history for all legs + partners
    let full: Vec<(Vec<f64>, Vec<f64>)> = LEGS.iter()
        .map(|c| (load_closes(c.name), load_closes(c.partner))).collect();
    let n = full.iter().map(|(a, _)| a.len()).min().unwrap_or(0);

    // --check LEG ARM: print features + prob at a specific arm for verification
    if let Some(pos) = args.iter().position(|a| a == "--check") {
        let leg = args.get(pos + 1).map(|x| x.as_str()).unwrap_or("TATASTEEL");
        let arm: usize = args.get(pos + 2).and_then(|x| x.parse().ok()).unwrap_or(1033);
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
            if segz[k] < zm { zm = segz[k]; dzm = k; }
            if segp[k] < pmin { pmin = segp[k]; dpm = k; }
        }
        let zrec = z[e] - zm;
        let pxdist = pa[e] / pmin - 1.0;
        let logs_a: Vec<f64> = pa.iter().map(|x| x.ln()).collect();
        let vf = std_of_diffs(&logs_a[arm..arm + 6]);
        let vl = std_of_diffs(&logs_a[e - 5..=e]);
        let f: Vec<f64> = vec![
            z[arm], z[e], zm, zrec, zrec / dzm.max(1) as f64, dzm as f64,
            (z[e] - z[arm]) / OBS as f64, z[e] - z[e - 2], pxdist,
            pa[e] / pa[arm] - 1.0, pa[e] / pa[e - 2] - 1.0, pa[e] / pa[e - 3] - 1.0,
            pa[e] / pa[e - 5] - 1.0, dpm as f64,
            zrec.max(0.0) * (pa[arm] / pmin - 1.0).max(0.0),
            (z[e] - segz[dzm]) / (OBS - dzm).max(1) as f64,
            (pa[e] - segp[dpm]) / (OBS - dpm).max(1) as f64 / pmin.max(1e-9),
            zrec / pxdist.max(1e-4), zm.abs(), vl / vf.max(1e-9),
            std_pop(&logs_a[e.saturating_sub(19)..=e]), beta[e], cfg.leg_id,
        ];
        println!("CHECK {}/{} arm={arm} e={e}  prob={}", leg, cfg.partner, predict(&f, &trees));
        println!("features: {:?}", f.iter().map(|x| format!("{:.6}", x)).collect::<Vec<_>>().join(","));
        return;
    }
```

- **L761–804**: The `--check LEG ARM` debug mode — recomputes the exact 23
  features for a specific arm index and prints probability + feature vector, so a
  Python result can be cross-verified against the Rust re-implementation
  (this is the parity check used in `tests/scanner_backtest.rs`).

```rust
    let mut terminal = if headless { None } else {
        match setup() {
            Ok(t) => Some(t), Err(e) => { eprintln!("TUI error: {e}"); std::process::exit(1); }
        }
    };

    let mut ui = Ui { bars: W_BETA + W_Z + OBS + 1, total: n, views: Vec::new(), log: Vec::new(),
                      enabled: enabled.clone(), poll_secs: compute_poll_secs(), live: false };
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
            new_views.push((cfg.name.to_string(), s.z_now, s.z_sig, s.zrec, s.pxdist, s.prob, s.watch));
            if s.watch {
                if let Some(a) = s.arm {
                    if a != last_arm[k] {
                        last_arm[k] = a;
                        let line = format!(
                            "WATCH {} arm_day={} z={:.2} z_rec={:.2} px_low={:.2}% P={:.0}% wait-for-break",
                            cfg.name, a, s.z_sig, s.zrec, s.pxdist * 100.0, s.prob * 100.0);
                        ui.log.push(line.clone());
                        if headless { println!("{line}"); }
                    }
                }
            }
        }
        ui.views = new_views;
        ui.bars += 1;
```

- **L806–842**: **Sim mode** (`--sim`, the default when not `--live`): replay the
  CSVs bar-by-bar. Each iteration grows the window by one bar and re-scans all
  legs; new distinct WATCH arms are logged (and printed in headless).

```rust
        if let Some(t) = terminal.as_mut() {
            let _ = t.draw(|f| draw(f, &ui));
        }

        if terminal.is_none() { continue; }   // headless: run straight through

        let slow = args.iter().any(|a| a == "--slow");
        if slow {
            let deadline = Instant::now() + Duration::from_millis(BAR_MS);
            while Instant::now() < deadline {
                if let Ok(true) = event::poll(Duration::from_millis(20)) {
                    if let Ok(Event::Key(k)) = event::read() {
                        if k.code == KeyCode::Char('q')
                            || (k.code == KeyCode::Char('c') && k.modifiers.contains(KeyModifiers::CONTROL)) {
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
                            || (k.code == KeyCode::Char('c') && k.modifiers.contains(KeyModifiers::CONTROL)) {
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
    if let Some(t) = terminal.as_mut() { let _ = teardown(t); }
    println!("\nWATCH events:\n{}", ui.log.join("\n"));
}
```

- **L844–888**: TUI pacing for sim mode:
  - `--slow` → 2.5s per bar (BAR_MS) so you can watch bars come in.
  - Otherwise loop as fast as possible, only breaking on a keypress.
  - `q`/`Ctrl-C` exits and prints the full WATCH event log.
  - On completion, teardown the TUI and dump the event log to stdout.

---

## Summary of the data flow

```
backtesting/data/*.csv ──┐                 ┌── Groww /v1/live-data/quote (--live)
backtesting/model_dump.txt ── parse_model() │     (overwrites last seeded bar)
                          └──► scan_leg() ◄─┘
                                │ rolling β → spread → z-score
                                │ find arm (z<-3), 10-bar obs window
                                │ gate z-recovery & price-low distance
                                │ 23 features → XGBoost predict → prob
                                ▼
                        prob ≥ 0.5 → WATCH   (TUI row, log, Pushover, beep)
```

The Rust scanner is a **pure re-implementation** of the Python
`export_model.py` feature pipeline + XGBoost, so the live probability is
bit-identical to what backtesting produced. It is explicitly watch-only:
there is no order placement anywhere in the file.
