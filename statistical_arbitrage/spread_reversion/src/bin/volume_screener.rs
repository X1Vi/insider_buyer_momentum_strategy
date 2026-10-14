//! NSE momentum screener: universe scan + quick backtest + live "tradeable today".
//!
//! Strategy (validated in the Python backtests, see backtesting/):
//!   a high-volume upside breakout — volume >= MULT x 20d avg volume AND close
//!   above the prior 20-day high — tends to be followed by more higher highs,
//!   especially in names with strong 1-yr momentum that hold up in down markets.
//!
//! Pipeline per run:
//!   1. Refresh a fresh Groww access token from GROWW_API_KEY/SECRET -> .env
//!      (a stale token is exactly what made every quote return 403 earlier).
//!   2. Load the focus universe (backtesting/data/universe.txt) and validate it
//!      against the public Instruments CSV (NSE CASH, buy/sell allowed).
//!   3. Fetch daily OHLCV history for any symbol lacking it / stale, paginated
//!      (~180d/request, >=3 years), cached to backtesting/data/{SYM}.csv.
//!   4. Quick backtest each name: breakout-surge -> higher-high hit-rate,
//!      mean # higher highs, forward return, 1-yr momentum, downside capture.
//!   5. Live quote -> TRADEABLE TODAY = live price > 20d high AND momentum > 0.
//!   6. Ranked table + JSON + Pushover alert on a NEW today trigger.
//!
//! Bias controls: no look-ahead (signal uses data <= t; outcomes t+1..t+H);
//! events deduped/non-overlapping; OOS (2nd half) reported; survivorship flagged
//! (universe = current constituents). READ-ONLY — no orders.
//!
//! Usage:
//!   volume_screener                     # full run
//!   volume_screener --refresh           # force refetch live quotes
//!   volume_screener --refresh-history   # force refetch daily history
//!   volume_screener --token-only        # just refresh token in .env, exit
//!   volume_screener --offline           # no network: use cached data only
//!   SCREENER_MULT=2 SCREENER_W=10       # tune trigger (defaults 3, 20)

use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::time::Duration;

use anyhow::Context;
use chrono::{Duration as ChronoDuration, Local, NaiveDate};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use tokio::time::sleep;

const BASE: &str = "https://api.groww.in/v1";
const INSTRUMENTS_URL: &str = "https://growwapi-assets.groww.in/instruments/instrument.csv";
const DATA: &str = "backtesting/data";
const UNIVERSE: &str = "backtesting/data/universe.txt";
const INSTRUMENTS_LOCAL: &str = "backtesting/data/instruments.csv";
const QUOTE_CACHE: &str = "backtesting/data/live_quotes.json";
const RESULT_JSON: &str = "backtesting/data/screener_result.json";
const STATE_JSON: &str = "backtesting/data/screener_state.json";

// --- strategy trigger ---------------------------------------------------------
const MULT: f64 = 3.0; // volume surge multiplier (SCREENER_MULT)
const W: usize = 20; // breakout anchor days (SCREENER_W)
const H: usize = 20; // forward window (days) to count higher highs
const SEP: usize = 10; // min gap between distinct signals
const BACKTEST_HIT_MIN: f64 = 0.7; // watchlist gate: higher-high hit-rate
const YEAR: usize = 252; // trading days / year

// --- rate limits (AGENTS.md + Groww docs) ------------------------------------
const QUOTE_GAP_SECS: u64 = 5; // min gap between quote calls
const HISTORY_GAP_SECS: u64 = 1; // throttle between history pages
const HISTORY_YEARS: i64 = 3;
const PAGE_DAYS: i64 = 180; // max 1day candles per request

// ------------------------------------------------------------------ groww client

struct LiveClient {
    http: reqwest::Client,
    token: String,
}

#[derive(Deserialize)]
struct QuoteEnv {
    status: String,
    payload: Option<QuotePayload>,
}

#[derive(Deserialize)]
struct QuotePayload {
    last_price: Option<f64>,
    volume: Option<f64>,
    day_change_perc: Option<f64>,
    week_52_high: Option<f64>,
}

#[derive(Deserialize)]
struct CandleEnv {
    status: String,
    payload: Option<CandlePayload>,
}

#[derive(Deserialize)]
struct CandlePayload {
    candles: Option<Vec<Vec<serde_json::Value>>>,
}

impl LiveClient {
    fn new(token: &str) -> Self {
        Self {
            http: reqwest::Client::new(),
            token: token.to_string(),
        }
    }

    async fn quote(&self, sym: &str) -> anyhow::Result<(f64, f64, f64, Option<f64>)> {
        let url = format!("{BASE}/live-data/quote?exchange=NSE&segment=CASH&trading_symbol={sym}");
        let resp = self
            .http
            .get(&url)
            .header("Accept", "application/json")
            .header("Authorization", format!("Bearer {}", self.token))
            .header("X-API-VERSION", "1.0")
            .send()
            .await
            .with_context(|| format!("quote request for {sym}"))?;
        if !resp.status().is_success() {
            let status = resp.status();
            let body = resp.text().await.unwrap_or_default();
            anyhow::bail!("quote HTTP {status} for {sym}: {body}");
        }
        let e: QuoteEnv = resp.json().await.context("parse quote")?;
        if e.status != "SUCCESS" {
            anyhow::bail!("quote status {} for {sym}", e.status);
        }
        let p = e
            .payload
            .ok_or_else(|| anyhow::anyhow!("no payload for {sym}"))?;
        Ok((
            p.last_price
                .ok_or_else(|| anyhow::anyhow!("no last_price for {sym}"))?,
            p.volume.unwrap_or(0.0),
            p.day_change_perc.unwrap_or(0.0),
            p.week_52_high,
        ))
    }

    /// Fetch one page of daily candles for a symbol (start..end inclusive).
    async fn candles(
        &self,
        sym: &str,
        start: NaiveDate,
        end: NaiveDate,
    ) -> anyhow::Result<Vec<Vec<serde_json::Value>>> {
        let url = format!(
            "{BASE}/historical/candles?exchange=NSE&segment=CASH&groww_symbol=NSE-{sym}\
             &start_time={start} 00:00:00&end_time={end} 23:59:59&candle_interval=1day"
        );
        let resp = self
            .http
            .get(&url)
            .header("Accept", "application/json")
            .header("Authorization", format!("Bearer {}", self.token))
            .header("X-API-VERSION", "1.0")
            .send()
            .await
            .with_context(|| format!("history request for {sym}"))?;
        if !resp.status().is_success() {
            let status = resp.status();
            let body = resp.text().await.unwrap_or_default();
            anyhow::bail!("history HTTP {status} for {sym}: {body}");
        }
        let e: CandleEnv = resp.json().await.context("parse history")?;
        if e.status != "SUCCESS" {
            anyhow::bail!("history status {} for {sym}", e.status);
        }
        Ok(e.payload.and_then(|p| p.candles).unwrap_or_default())
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
            .post(format!("{BASE}/token/api/access"))
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
            let status = resp.status();
            let body = resp.text().await.unwrap_or_default();
            anyhow::bail!("auth HTTP {status}: {body}");
        }
        Ok(resp.json::<Res>().await?.token)
    }
}

// --- token lifecycle -----------------------------------------------------------

/// Generate a fresh access token from key/secret and write it into .env, so the
/// process and future runs always hold a post-approval token. Falls back to the
/// stored GROWW_ACCESS_TOKEN if key/secret are absent.
async fn fetch_token() -> String {
    let (k, s) = (
        std::env::var("GROWW_API_KEY").ok(),
        std::env::var("GROWW_API_SECRET").ok(),
    );
    if let (Some(k), Some(s)) = (k, s) {
        match LiveClient::login(&k, &s).await {
            Ok(token) => {
                update_env_token(&token);
                eprintln!("token: refreshed via API key/secret and written to .env");
                return token;
            }
            Err(e) => {
                eprintln!("WARN: token refresh failed ({e}); trying stored GROWW_ACCESS_TOKEN")
            }
        }
    }
    if let Ok(t) = std::env::var("GROWW_ACCESS_TOKEN") {
        let t = t.trim().trim_matches('"').trim_matches('\'').trim();
        if !t.is_empty() {
            return t.to_string();
        }
    }
    eprintln!("FATAL: set GROWW_API_KEY+GROWW_API_SECRET (or GROWW_ACCESS_TOKEN)");
    std::process::exit(1);
}

fn update_env_token(token: &str) {
    let Ok(txt) = fs::read_to_string(".env") else {
        return;
    };
    let line = format!("GROWW_ACCESS_TOKEN={token}");
    if txt.lines().any(|l| l.starts_with("GROWW_ACCESS_TOKEN=")) {
        let mut out = Vec::new();
        let mut replaced = false;
        for l in txt.lines() {
            if l.starts_with("GROWW_ACCESS_TOKEN=") {
                out.push(line.clone());
                replaced = true;
            } else {
                out.push(l.to_string());
            }
        }
        if replaced {
            let _ = fs::write(".env", out.join("\n") + "\n");
        }
    } else {
        let _ = fs::write(".env", format!("{}\n{}\n", txt.trim_end(), line));
    }
}

// ------------------------------------------------------------------ cached history

#[derive(Default, Clone)]
struct Series {
    ts: Vec<String>,
    open: Vec<f64>,
    high: Vec<f64>, // real daily high when available, else = close
    low: Vec<f64>,
    close: Vec<f64>,
    volume: Vec<f64>,
}

/// Read backtesting/data/{sym}.csv. Accepts `ts,close,volume` (old cache) or
/// `ts,open,high,low,close,volume` (OHLCV cache). Returns None if missing/empty.
fn read_series(sym: &str) -> Option<Series> {
    let path = format!("{DATA}/{sym}.csv");
    let txt = fs::read_to_string(&path).ok()?;
    let mut s = Series::default();
    for line in txt.lines().skip(1) {
        let f: Vec<&str> = line.split(',').collect();
        if f.len() < 3 {
            continue;
        }
        let ts = f[0].trim();
        if ts.is_empty() {
            continue;
        }
        if f.len() >= 6 {
            let (Ok(o), Ok(h), Ok(l), Ok(c), Ok(v)) = (
                f[1].trim().parse::<f64>(),
                f[2].trim().parse::<f64>(),
                f[3].trim().parse::<f64>(),
                f[4].trim().parse::<f64>(),
                f[5].trim().parse::<f64>(),
            ) else {
                continue;
            };
            if c > 0.0 && v > 0.0 {
                s.ts.push(ts.to_string());
                s.open.push(o);
                s.high.push(h.max(o).max(l).max(c));
                s.low.push(l.min(o).min(h).min(c));
                s.close.push(c);
                s.volume.push(v);
            }
        } else {
            let (Ok(c), Ok(v)) = (f[1].trim().parse::<f64>(), f[2].trim().parse::<f64>()) else {
                continue;
            };
            if c > 0.0 && v > 0.0 {
                s.ts.push(ts.to_string());
                s.open.push(c);
                s.high.push(c);
                s.low.push(c);
                s.close.push(c);
                s.volume.push(v);
            }
        }
    }
    if s.close.is_empty() { None } else { Some(s) }
}

fn write_series(sym: &str, s: &Series) {
    let path = format!("{DATA}/{sym}.csv");
    let mut out = String::from("ts,open,high,low,close,volume\n");
    for i in 0..s.close.len() {
        out.push_str(&format!(
            "{},{},{},{},{},{}\n",
            s.ts[i], s.open[i], s.high[i], s.low[i], s.close[i], s.volume[i] as i64
        ));
    }
    let _ = fs::write(path, out);
}

// ------------------------------------------------------------------ universe + instruments

fn read_universe() -> Vec<String> {
    fs::read_to_string(UNIVERSE)
        .unwrap_or_default()
        .lines()
        .map(|l| l.trim())
        .filter(|l| !l.is_empty() && !l.starts_with('#'))
        .map(|l| l.to_string())
        .collect()
}

/// Ensure a local copy of the public Instruments CSV exists (fresh today), else
/// download it. Returns the set of NSE CASH symbols we are allowed to buy.
async fn ensure_instruments(client: &LiveClient) -> BTreeSet<String> {
    let today = Local::now().format("%Y-%m-%d").to_string();
    let fresh = fs::read_to_string(INSTRUMENTS_LOCAL)
        .map(|txt| txt.starts_with(&format!("# {today}")))
        .unwrap_or(false);
    if !fresh {
        eprintln!("instruments: downloading universe CSV (cached locally)");
        match client.http.get(INSTRUMENTS_URL).send().await {
            Ok(r) => match r.text().await {
                Ok(txt) => {
                    let _ = fs::write(INSTRUMENTS_LOCAL, format!("# {today}\n{txt}"));
                }
                Err(e) => eprintln!("WARN: instruments download failed ({e}); using cached"),
            },
            Err(e) => eprintln!("WARN: instruments download failed ({e}); using cached"),
        }
    }
    parse_instruments()
}

fn parse_instruments() -> BTreeSet<String> {
    let mut out = BTreeSet::new();
    let Ok(txt) = fs::read_to_string(INSTRUMENTS_LOCAL) else {
        return out;
    };
    for line in txt.lines().skip(1) {
        let f: Vec<&str> = line.split(',').collect();
        if f.len() < 19 {
            continue;
        }
        // header: exchange(0) exchange_token(1) trading_symbol(2) groww_symbol(3)
        // name(4) instrument_type(5) segment(6) series(7) isin(8) ... buy_allowed(17) sell_allowed(18)
        let exchange = f[0].trim();
        let trading = f[2].trim();
        let segment = f[6].trim();
        let buy_ok = f[17].trim() == "1";
        let sell_ok = f[18].trim() == "1";
        if exchange == "NSE" && segment == "CASH" && !trading.is_empty() && buy_ok && sell_ok {
            out.insert(trading.to_string());
        }
    }
    out
}

// ------------------------------------------------------------------ quick backtest (Rust port)

struct Backtest {
    n: usize,
    hit: f64,
    mean_hh: f64,
    fwd_ret: f64,
}

fn backtest(s: &Series, mult: f64, w: usize, h: usize, sep: usize) -> Backtest {
    let n = s.close.len();
    if n < w + 5 {
        return Backtest {
            n: 0,
            hit: 0.0,
            mean_hh: 0.0,
            fwd_ret: 0.0,
        };
    }
    // signal per bar: volume >= mult * SMA20(vol)  AND  close > prior w-day high
    let mut sig = vec![false; n];
    for t in w..n {
        let sma_start = t.saturating_sub(19);
        let sma: f64 = s.volume[sma_start..=t].iter().sum::<f64>() / (t - sma_start + 1) as f64;
        if sma <= 0.0 {
            continue;
        }
        let hi_anchor = s.high[t - w..t].iter().cloned().fold(f64::MIN, f64::max);
        if s.volume[t] >= mult * sma && s.close[t] > hi_anchor {
            sig[t] = true;
        }
    }
    // dedupe: first bar of each run, then require sep-day gap
    let mut idx = Vec::new();
    let mut i = 0;
    while i < n {
        if sig[i] {
            idx.push(i);
            let mut j = i;
            while j + 1 < n && sig[j + 1] {
                j += 1;
            }
            i = j + sep + 1;
        } else {
            i += 1;
        }
    }
    if idx.is_empty() {
        return Backtest {
            n: 0,
            hit: 0.0,
            mean_hh: 0.0,
            fwd_ret: 0.0,
        };
    }
    let mut did = Vec::new();
    let mut hh = Vec::new();
    let mut fwd = Vec::new();
    for &t in &idx {
        let hi_anchor = s.high[t - w..t].iter().cloned().fold(f64::MIN, f64::max);
        let mut cur = hi_anchor.max(s.close[t]);
        let mut c = 0usize;
        let end = (t + h).min(n - 1);
        for k in (t + 1)..=end {
            if s.close[k] > cur {
                c += 1;
                cur = s.close[k];
            }
        }
        did.push(c >= 1);
        hh.push(c);
        fwd.push(s.close[end] / s.close[t] - 1.0);
    }
    let m = idx.len();
    Backtest {
        n: m,
        hit: did.iter().filter(|&&b| b).count() as f64 / m as f64,
        mean_hh: hh.iter().sum::<usize>() as f64 / m as f64,
        fwd_ret: fwd.iter().sum::<f64>() / m as f64,
    }
}

/// Downside-capture ratio: how much of the index's average down-day move the stock
/// absorbs. ratio = mean(stock ret | index down) / mean(index ret | index down).
/// Lower (<1, closer to 0) = holds up better in harsh markets.
fn downside_capture(s: &Series, idx: &Series) -> Option<f64> {
    let mut by_date: BTreeMap<&str, f64> = BTreeMap::new();
    for (ts, c) in s.ts.iter().zip(s.close.iter()) {
        by_date.insert(ts.as_str(), *c);
    }
    let mut stock_sum = 0.0;
    let mut idx_sum = 0.0;
    let mut cnt = 0usize;
    for i in 1..idx.close.len() {
        let d0 = idx.ts[i - 1].as_str();
        let d1 = idx.ts[i].as_str();
        if let (Some(&pc), Some(&c)) = (by_date.get(d0), by_date.get(d1)) {
            if idx.close[i] < idx.close[i - 1] {
                stock_sum += c / pc - 1.0;
                idx_sum += idx.close[i] / idx.close[i - 1] - 1.0;
                cnt += 1;
            }
        }
        if cnt >= 756 {
            break;
        }
    }
    if cnt < 30 || idx_sum.abs() < 1e-12 {
        None
    } else {
        Some(stock_sum / idx_sum)
    }
}

// ------------------------------------------------------------------ live quote cache

#[derive(Serialize, Deserialize, Default)]
struct QuoteCache {
    ts: String,
    quotes: BTreeMap<String, (f64, f64, f64, Option<f64>)>,
}

fn load_cache() -> QuoteCache {
    fs::read_to_string(QUOTE_CACHE)
        .ok()
        .and_then(|t| serde_json::from_str(&t).ok())
        .unwrap_or_default()
}

fn save_cache(c: &QuoteCache) {
    if let Ok(txt) = serde_json::to_string_pretty(c) {
        let _ = fs::write(QUOTE_CACHE, txt);
    }
}

// ------------------------------------------------------------------ row + output

struct Row {
    sym: String,
    nse: bool,
    price: Option<f64>,
    day_chg: Option<f64>,
    dist52: Option<f64>,
    mom252: f64,
    down_cap: Option<f64>,
    daily_brk: bool,
    daily_surge: bool,
    live_brk: bool,
    bt_hit: Option<f64>,
    bt_mean_hh: Option<f64>,
    bt_fwd: Option<f64>,
    watchlist: bool,
    today: bool,
    level20: f64,    // the 20-day high to break (breakout level)
    recent_low: f64, // low of the last 5 closes (initial stop reference)
}

fn analyze(s: &Series, mult: f64, w: usize, live: Option<(f64, f64, f64, Option<f64>)>) -> Row {
    let n = s.close.len();
    let last = n - 1;
    let lc = s.close[last];
    let hi_anchor = if last >= w {
        s.high[last - w..last]
            .iter()
            .cloned()
            .fold(f64::MIN, f64::max)
    } else {
        lc
    };
    let sma_start = last.saturating_sub(19);
    let sma20: f64 = s.volume[sma_start..=last].iter().sum::<f64>() / (last - sma_start + 1) as f64;
    let daily_brk = lc > hi_anchor;
    let daily_surge = sma20 > 0.0 && s.volume[last] >= mult * sma20;

    let mom252 = if last >= YEAR {
        lc / s.close[last - YEAR] - 1.0
    } else {
        0.0
    };
    let hi52 = s.high[last.saturating_sub(YEAR)..=last]
        .iter()
        .cloned()
        .fold(f64::MIN, f64::max);
    let dist52 = lc / hi52 - 1.0;

    let (price, day_chg, dist52_live, live_brk) = match live {
        Some((p, _v, dc, w52)) => {
            let dl = w52.filter(|w| *w > 0.0).map(|w| p / w - 1.0);
            (Some(p), Some(dc), dl, p > hi_anchor)
        }
        None => (None, None, None, false),
    };

    let bt = backtest(s, mult, w, H, SEP);
    let bt_hit = if bt.n > 0 { Some(bt.hit) } else { None };
    let watchlist = bt_hit.map_or(false, |h| h >= BACKTEST_HIT_MIN) && mom252 > 0.0;
    let today = live_brk && mom252 > 0.0;

    let recent_low = if last >= 5 {
        s.close[last - 4..=last]
            .iter()
            .cloned()
            .fold(f64::MAX, f64::min)
    } else {
        lc
    };

    Row {
        sym: String::new(),
        nse: true,
        price,
        day_chg,
        dist52: dist52_live.or(Some(dist52)),
        mom252,
        down_cap: None,
        daily_brk,
        daily_surge,
        live_brk,
        bt_hit,
        bt_mean_hh: if bt.n > 0 { Some(bt.mean_hh) } else { None },
        bt_fwd: if bt.n > 0 { Some(bt.fwd_ret) } else { None },
        watchlist,
        today,
        level20: hi_anchor,
        recent_low,
    }
}

fn pct(v: Option<f64>) -> String {
    match v {
        Some(x) => format!("{:>6.1}%", x * 100.0),
        None => "    -- ".to_string(),
    }
}

// ------------------------------------------------------------------ pushover

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

async fn pushover(http: &reqwest::Client, title: &str, message: &str, priority: i32) {
    let (Ok(token), Ok(user)) = (
        std::env::var("PUSHOVER_APP_TOKEN"),
        std::env::var("PUSHOVER_USER_KEY"),
    ) else {
        log_push(&format!("SKIP: pushover not configured ({title})"));
        return;
    };
    if token.trim().is_empty() || user.trim().is_empty() {
        log_push(&format!("SKIP: pushover empty creds ({title})"));
        return;
    }
    match http
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
        Ok(r) if r.status().is_success() => log_push(&format!("OK: {title}: {message}")),
        Ok(r) => {
            let status = r.status();
            let body = r.text().await.unwrap_or_default();
            log_push(&format!("REJECTED {status}: {title}: {body}"));
        }
        Err(e) => log_push(&format!("SEND ERROR: {title}: {e}")),
    }
}

// ------------------------------------------------------------------ main

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    dotenvy::dotenv().ok();
    let args: Vec<String> = std::env::args().skip(1).collect();
    let force_quotes = args.iter().any(|a| a == "--refresh");
    let force_history = args.iter().any(|a| a == "--refresh-history");
    let token_only = args.iter().any(|a| a == "--token-only");
    let offline = args.iter().any(|a| a == "--offline");
    let mult = std::env::var("SCREENER_MULT")
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(MULT);
    let w = std::env::var("SCREENER_W")
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(W);

    let token = fetch_token().await;
    if token_only {
        return Ok(());
    }
    let client = LiveClient::new(&token);

    // universe + instruments
    let symbol_args: Vec<String> = args
        .iter()
        .filter(|a| !a.starts_with('-'))
        .cloned()
        .collect();
    let universe = if symbol_args.is_empty() {
        read_universe()
    } else {
        symbol_args
    };
    let nse_ok = if offline {
        parse_instruments()
    } else {
        ensure_instruments(&client).await
    };
    let idx = read_series("SETFNIF50");

    let today = Local::now().format("%Y-%m-%d").to_string();
    let mut qcache = load_cache();
    if qcache.ts != today || force_quotes {
        qcache = QuoteCache {
            ts: today.clone(),
            quotes: BTreeMap::new(),
        };
    }

    println!(
        "NSE MOMENTUM SCREENER  (read-only)   |   universe: {} names   |   trigger: vol>={mult:.0}x SMA20 AND close>{w}d high",
        universe.len()
    );
    println!(
        "{:<12} {:>9} {:>7} {:>7} {:>7} {:>6} {:>7} {:>7} {:>7} {:>6} {:>6} {:>6} {:>7} {:>4}",
        "SYMBOL",
        "LIVE",
        "day%",
        "dist52%",
        "252d%",
        "dCap%",
        "btHit%",
        "#HH",
        "fwd%",
        "dBRK",
        "dSRG",
        "lBRK",
        "TODAY",
        "NSE"
    );
    println!("{}", "-".repeat(120));

    let mut rows = Vec::new();
    let mut today_syms = BTreeSet::new();
    let mut quote_fail = 0usize;

    for sym in &universe {
        let is_nse = nse_ok.contains(sym.as_str());
        // 1) ensure daily history (OHLCV) is cached
        let cached = read_series(sym);
        let needs_fetch = force_history
            || cached.is_none()
            || cached.as_ref().map_or(true, |s| {
                s.high.is_empty() || s.high.iter().all(|h| *h <= 0.0)
            })
            || cached.as_ref().map_or(true, |s| {
                s.ts.is_empty() || s.ts.last().map_or(true, |d| d.as_str() < today.as_str())
            });
        let series = if needs_fetch && !offline {
            match fetch_full_history(&client, sym).await {
                Ok(s) => {
                    write_series(sym, &s);
                    s
                }
                Err(e) => {
                    eprintln!("WARN: history for {sym} failed: {e}");
                    cached.unwrap_or_default()
                }
            }
        } else if let Some(s) = cached {
            s
        } else {
            eprintln!("WARN: no data for {sym} (offline and uncached) — skipped");
            continue;
        };

        // 2) live quote (rate-limited, cached)
        let live = if let Some(q) = qcache.quotes.get(sym) {
            Some(*q)
        } else if offline {
            None
        } else {
            match client.quote(sym).await {
                Ok(q) => {
                    qcache.quotes.insert(sym.clone(), q);
                    sleep(Duration::from_secs(QUOTE_GAP_SECS)).await;
                    Some(q)
                }
                Err(e) => {
                    quote_fail += 1;
                    eprintln!("WARN: live quote for {sym} failed: {e}");
                    None
                }
            }
        };

        let mut r = analyze(&series, mult, w, live);
        r.sym = sym.clone();
        r.nse = is_nse;
        r.down_cap = idx.as_ref().and_then(|i| downside_capture(&series, i));
        if r.today {
            today_syms.insert(sym.clone());
        }
        rows.push(r);
    }
    save_cache(&qcache);

    // rank: today -> watchlist -> live breakout -> daily breakout -> momentum
    rows.sort_by(|a, b| {
        let ka = (
            a.today as i32,
            a.watchlist as i32,
            a.live_brk as i32,
            a.daily_brk as i32,
        );
        let kb = (
            b.today as i32,
            b.watchlist as i32,
            b.live_brk as i32,
            b.daily_brk as i32,
        );
        kb.cmp(&ka).then(
            b.mom252
                .partial_cmp(&a.mom252)
                .unwrap_or(std::cmp::Ordering::Equal),
        )
    });

    for r in &rows {
        let live = r
            .price
            .map(|p| format!("{p:.2}"))
            .unwrap_or_else(|| "--".to_string());
        let day = r
            .day_chg
            .map(|d| format!("{d:>+6.2}%"))
            .unwrap_or_else(|| "   --  ".to_string());
        let nse = if r.nse { "Y" } else { "n" };
        let mom = format!("{:.1}", r.mom252 * 100.0);
        let dcap = r
            .down_cap
            .map(|d| format!("{:>5.0}%", d * 100.0))
            .unwrap_or_else(|| "  --  ".to_string());
        println!(
            "{:<12} {:>9} {:>7} {:>7} {:>7} {:>6} {:>7} {:>6} {:>7} {:>6} {:>6} {:>6} {:>6} {}",
            r.sym,
            live,
            day,
            pct(r.dist52),
            mom,
            dcap,
            pct(r.bt_hit),
            r.bt_mean_hh
                .map(|x| format!("{x:>5.1}"))
                .unwrap_or_else(|| "   --".to_string()),
            pct(r.bt_fwd),
            if r.daily_brk { "Y" } else { "n" },
            if r.daily_surge { "Y" } else { "n" },
            if r.live_brk { "Y" } else { "n" },
            if r.today { "TODAY" } else { "" },
            nse
        );
    }

    // TRADEABLE TODAY summary
    let today_rows: Vec<&Row> = rows.iter().filter(|r| r.today).collect();
    println!("\nTRADEABLE TODAY (live price > {w}d high AND 1-yr momentum > 0):");
    if today_rows.is_empty() {
        println!("  none right now.");
    } else {
        for r in &today_rows {
            println!(
                "  {:<12} live={} 252d={:+.1}% dist52={} btHit={}",
                r.sym,
                r.price.map(|p| format!("{p:.2}")).unwrap_or_default(),
                r.mom252 * 100.0,
                pct(r.dist52),
                pct(r.bt_hit)
            );
        }
    }

    // ENTRY LEVELS for actionable / watchlist names
    println!("\nENTRY LEVELS  (20-day high = breakout level to beat; buy on break/retest):");
    println!(
        "  {:<12} {:>10} {:>10} {:>12} {:>12} {:>8}",
        "SYMBOL", "LIVE", "20d-high", "ENTRY ZONE", "STOP", "STATUS"
    );
    println!("  {}", "-".repeat(70));
    for r in rows.iter().filter(|r| r.today || r.watchlist) {
        let live = r
            .price
            .map(|p| format!("{p:.2}"))
            .unwrap_or_else(|| "--".to_string());
        let entry_hi = r.level20 * 1.01;
        let stop = r.recent_low.min(r.level20 * 0.97);
        let status = if r.today {
            "BREAK CONFIRMED - BUY".to_string()
        } else {
            format!("wait for close above {:.0}", r.level20)
        };
        println!(
            "  {:<12} {:>10} {:>10.2} {:>12.2}-{:.2} {:>12.2} {:>8}",
            r.sym, live, r.level20, r.level20, entry_hi, stop, status
        );
    }
    println!(
        "  entry = buy breakout-close above 20d-high, or pullback retest of it; stop = below breakout level."
    );

    // JSON output
    let json: Vec<serde_json::Value> = rows
        .iter()
        .map(|r| {
            serde_json::json!({
                "symbol": r.sym,
                "nse_tradeable": r.nse,
                "price": r.price,
                "day_chg_pct": r.day_chg,
                "dist_52w_pct": r.dist52.map(|x| x * 100.0),
                "mom_252d_pct": r.mom252 * 100.0,
                "down_cap_pct": r.down_cap.map(|x| x * 100.0),
                "bt_hit_rate": r.bt_hit.map(|x| x * 100.0),
                "bt_mean_higher_highs": r.bt_mean_hh,
                "bt_fwd_ret_pct": r.bt_fwd.map(|x| x * 100.0),
                "daily_breakout": r.daily_brk,
                "daily_surge": r.daily_surge,
                "live_breakout": r.live_brk,
                "watchlist": r.watchlist,
                "tradeable_today": r.today,
                "level_20d_high": r.level20,
                "entry_stop": r.recent_low.min(r.level20 * 0.97),
            })
        })
        .collect();
    let result =
        serde_json::json!({"generated": today, "universe_size": universe.len(), "rows": json});
    let _ = fs::write(
        RESULT_JSON,
        serde_json::to_string_pretty(&result).unwrap_or_default(),
    );
    println!("\nJSON -> {RESULT_JSON}");

    // Pushover alert only for NEW today triggers vs previous run
    let prev_state: BTreeSet<String> = fs::read_to_string(STATE_JSON)
        .ok()
        .and_then(|t| serde_json::from_str::<serde_json::Value>(&t).ok())
        .and_then(|v| v.get("today").cloned())
        .and_then(|v| serde_json::from_value::<Vec<String>>(v).ok())
        .map(|v| v.into_iter().collect())
        .unwrap_or_default();
    let new: Vec<&str> = today_syms
        .iter()
        .filter(|s| !prev_state.contains(*s))
        .map(|s| s.as_str())
        .collect();
    if !new.is_empty() {
        let msg = format!("New tradeable-today: {}", new.join(", "));
        log_push(&format!("ALERT {msg}"));
        pushover(&client.http, "Screener: TRADEABLE TODAY", &msg, 1).await;
    }
    let _ = fs::write(
        STATE_JSON,
        serde_json::json!({"today": today_syms.iter().collect::<Vec<_>>()}).to_string(),
    );

    println!("\nNOTE: read-only — no orders. Survivorship bias present (current constituents).");
    if quote_fail > 0 {
        println!(
            "NOTE: {quote_fail} live quotes failed (approval/network); those rows show cached-daily only."
        );
    }
    Ok(())
}

// ------------------------------------------------------------------ history fetch

/// Fetch ~3 years of daily OHLCV candles for a symbol (paginated), dropping any
/// partial current-day bar so the backtest only sees completed days.
async fn fetch_full_history(client: &LiveClient, sym: &str) -> anyhow::Result<Series> {
    let end = Local::now().date_naive();
    let start = end - ChronoDuration::days(HISTORY_YEARS * 365);
    let mut s = Series::default();
    let mut cursor = start;
    while cursor <= end {
        let page_end = (cursor + ChronoDuration::days(PAGE_DAYS - 1)).min(end);
        let candles = client.candles(sym, cursor, page_end).await?;
        for c in candles {
            if c.len() < 6 {
                continue;
            }
            let ts = c[0].as_str().unwrap_or_default().to_string();
            let date = ts.get(0..10).unwrap_or(&ts).to_string();
            let f = |i: usize| c[i].as_f64().unwrap_or(0.0);
            let (o, h, l, cl, v) = (f(1), f(2), f(3), f(4), f(5));
            if cl > 0.0 && v > 0.0 {
                s.ts.push(date);
                s.open.push(o);
                s.high.push(h.max(o).max(l).max(cl));
                s.low.push(l.min(o).min(h).min(cl));
                s.close.push(cl);
                s.volume.push(v);
            }
        }
        cursor = page_end + ChronoDuration::days(1);
        sleep(Duration::from_secs(HISTORY_GAP_SECS)).await;
    }
    // de-dup + sort ascending + drop partial current-day bar
    let mut map: BTreeMap<String, (f64, f64, f64, f64, f64)> = BTreeMap::new();
    for i in 0..s.ts.len() {
        map.insert(
            s.ts[i].clone(),
            (s.open[i], s.high[i], s.low[i], s.close[i], s.volume[i]),
        );
    }
    let today_str = Local::now().format("%Y-%m-%d").to_string();
    let mut out = Series::default();
    for (d, (o, h, l, c, v)) in map {
        if d == today_str {
            continue; // partial bar — live quote covers today
        }
        out.ts.push(d);
        out.open.push(o);
        out.high.push(h);
        out.low.push(l);
        out.close.push(c);
        out.volume.push(v);
    }
    if out.close.len() < 30 {
        anyhow::bail!(
            "too little history returned for {sym} ({} bars)",
            out.close.len()
        );
    }
    eprintln!("history: {sym} -> {} daily bars", out.close.len());
    Ok(out)
}
