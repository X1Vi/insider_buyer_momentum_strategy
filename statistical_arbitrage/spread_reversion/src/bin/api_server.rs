//! api_server — a tiny READ-ONLY HTTP API for the insider data, for the React UI.
//!
//! The Rust side does all the work (fetch NSE PIT, fetch Groww prices, compute
//! EMA50/EMA200/RSI). React only GETs JSON and draws.
//!
//! Safety: binds to **127.0.0.1 only**, GET handlers only, no auth/secrets in
//! responses, and no order code. Symbols are length/character capped. NSE PIT
//! and Groww candle data are persisted for 24 hours and spaced by six seconds.
//!
//! Endpoints
//!   GET /health
//!   GET /api/insiders?all=true|false      -> major-insider market buys (pool)
//!   GET /api/series?symbol=AXISBANK&range=10y
//!                                          -> dates, close, ema50, ema200, rsi, buys
//!
//! Run:
//!   cargo run --bin api_server          # http://127.0.0.1:8787

use std::collections::{BTreeMap, HashMap};
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::{SystemTime, UNIX_EPOCH};

use axum::{
    Json, Router,
    extract::{Query, State},
    http::Method,
    routing::get,
};
use chrono::{Datelike, Duration as ChronoDuration, NaiveDate};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use spread_reversion::{groww, insider};
use tokio::sync::Mutex;
use tower_http::cors::{Any, CorsLayer};

const POOL_FILE: &str = concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/backtesting/data/insider_universe.txt"
);
const WINDOW_DAYS: i64 = 550;
/// Only consider buyers within this many days of the newest disclosure (matches
/// the standalone `insider_momentum` tool: last ~2 months of insider activity).
const DEFAULT_RECENT_DAYS: i64 = 60;
/// Window (days) of LIVE filings to pull from the new `-gg` endpoint.
const GG_WINDOW_DAYS: i64 = 60;
const ADDR: &str = "127.0.0.1:8787";
const CACHE_TTL_SECS: i64 = 24 * 60 * 60;
const GROWW_PAGE_DAYS: i64 = 1_000;

#[derive(Clone)]
struct App {
    http: reqwest::Client,
    groww: Option<Arc<groww::Client>>,
    pool: Arc<Vec<String>>,
    cache: Arc<Mutex<Option<Arc<Vec<insider::Record>>>>>,
    cache_dir: Arc<PathBuf>,
    seed_dir: Option<Arc<PathBuf>>,
    /// `symbol:range` -> price result. Only symbols armed by a qualifying buyer
    /// are requested by the watchlist.
    px: Arc<Mutex<HashMap<String, PriceResult>>>,
}

#[derive(Debug, Serialize, Deserialize)]
struct InsiderDiskCache {
    fetched_at: i64,
    start: NaiveDate,
    end: NaiveDate,
    records: Vec<insider::Record>,
}

#[derive(Debug, Deserialize)]
struct RawPitFile {
    #[serde(default)]
    data: Vec<insider::Record>,
}

#[derive(Debug, Serialize, Deserialize)]
struct PriceDiskCache {
    fetched_at: i64,
    source: String,
    bars: Vec<insider::Bar>,
}

#[derive(Clone)]
struct PriceResult {
    bars: Arc<Vec<insider::Bar>>,
    source: String,
    cache_hit: bool,
}

fn unix_now() -> i64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs() as i64)
        .unwrap_or(0)
}

fn fresh(fetched_at: i64) -> bool {
    unix_now().saturating_sub(fetched_at) < CACHE_TTL_SECS
}

fn read_json<T: for<'de> Deserialize<'de>>(path: &Path) -> Option<T> {
    fs::read(path)
        .ok()
        .and_then(|bytes| serde_json::from_slice(&bytes).ok())
}

fn write_json_atomic<T: Serialize>(path: &Path, value: &T) -> anyhow::Result<()> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)?;
    }
    let tmp = path.with_extension("tmp");
    fs::write(&tmp, serde_json::to_vec(value)?)?;
    fs::rename(tmp, path)?;
    Ok(())
}

/// Reuse the complete yearly PIT files produced by the research pipeline. This
/// is a full-universe seed, so it avoids a redundant NSE crawl without changing
/// the meaning of `all=true`.
fn import_raw_pit_cache(
    seed_dir: &Path,
    start: NaiveDate,
    end: NaiveDate,
) -> Option<InsiderDiskCache> {
    let mut records = Vec::new();
    let mut fetched_at = 0_i64;
    for year in start.year()..=end.year() {
        let path = seed_dir.join(format!("pit_{year}.json"));
        let raw: RawPitFile = read_json(&path)?;
        let modified = fs::metadata(&path)
            .ok()?
            .modified()
            .ok()?
            .duration_since(UNIX_EPOCH)
            .ok()?
            .as_secs() as i64;
        fetched_at = fetched_at.max(modified);
        records.extend(raw.data.into_iter().filter(|record| {
            insider::parse_nse_date(record.disc_date())
                .is_some_and(|date| date >= start && date <= end)
        }));
    }
    (!records.is_empty()).then_some(InsiderDiskCache {
        fetched_at,
        start,
        end,
        records,
    })
}

async fn insiders_cached(app: &App) -> Arc<Vec<insider::Record>> {
    let mut guard = app.cache.lock().await;
    if let Some(c) = guard.as_ref() {
        return c.clone();
    }
    let end = insider::today();
    let start = end - chrono::Duration::days(WINDOW_DAYS);
    let path = app.cache_dir.join("nse_insider_buyers.json");
    let disk: Option<InsiderDiskCache> = read_json(&path).or_else(|| {
        app.seed_dir
            .as_deref()
            .and_then(|dir| import_raw_pit_cache(dir, start, end))
    });
    if let Some(saved) = disk.as_ref().filter(|saved| fresh(saved.fetched_at)) {
        eprintln!("(api) NSE cache hit: {} disclosures", saved.records.len());
        if !path.exists() {
            let _ = write_json_atomic(&path, saved);
        }
        let arc = Arc::new(saved.records.clone());
        *guard = Some(arc.clone());
        return arc;
    }

    // Stale but present: serve the stale cache IMMEDIATELY and refresh in the
    // background, so an HTTP request never blocks on the slow NSE crawl.
    if let Some(saved) = disk.as_ref() {
        eprintln!("(api) NSE cache stale ({} disclosures); serving stale + refreshing in background",
                  saved.records.len());
        let arc = Arc::new(saved.records.clone());
        *guard = Some(arc.clone());
        drop(guard);
        let app2 = app.clone();
        let bg_path = path.clone();
        tokio::spawn(async move {
            eprintln!("(api) background NSE refresh {start}..{end}; 6s between requests");
            match insider::fetch_window(&app2.http, start, end, true).await {
                Ok(records) if !records.is_empty() => {
                    let saved = InsiderDiskCache {
                        fetched_at: unix_now(),
                        start,
                        end,
                        records: records.clone(),
                    };
                    if let Err(err) = write_json_atomic(&bg_path, &saved) {
                        eprintln!("WARN: could not write NSE cache: {err}");
                    }
                    *app2.cache.lock().await = Some(Arc::new(records));
                    eprintln!("(api) background NSE refresh complete");
                }
                Ok(_) => eprintln!("WARN: background NSE refresh empty; keeping stale cache"),
                Err(err) => eprintln!("WARN: background NSE refresh failed: {err}; keeping stale cache"),
            }
        });
        return arc;
    }

    // No cache at all: must block once on the fetch.
    eprintln!("(api) no NSE cache; fetching {start}..{end}; 6s between requests");
    let recs = match insider::fetch_window(&app.http, start, end, true).await {
        Ok(records) => records,
        Err(err) => {
            eprintln!("WARN: NSE fetch failed and no cache exists: {err}");
            Vec::new()
        }
    };
    let saved = InsiderDiskCache {
        fetched_at: unix_now(),
        start,
        end,
        records: recs.clone(),
    };
    let _ = write_json_atomic(&path, &saved);
    eprintln!("(api) cached {} disclosures", recs.len());
    let arc = Arc::new(recs);
    *guard = Some(arc.clone());
    arc
}

/// Records from the NEW `-gg` source, read from the disk cache (filled by the
/// background collector). Any age is fine: filings are immutable once filed.
fn gg_disk(app: &App) -> Vec<insider::Record> {
    let path = app.cache_dir.join("pit_gg_records.json");
    read_json::<InsiderDiskCache>(&path)
        .map(|d| {
            // Normalise the XBRL category names on load (Promoter -> Promoters …)
            // so the strategy filter matches the old endpoint's naming.
            d.records
                .into_iter()
                .map(|mut r| {
                    if let Some(cat) = r.person_category.take() {
                        r.person_category = Some(insider::normalize_category(&cat));
                    }
                    r
                })
                .collect()
        })
        .unwrap_or_default()
}

/// Old source (yearly PIT seed) + new source (`-gg`), de-duplicated. This is the
/// record set every handler uses, so the strategy sees LIVE buyers as well.
async fn all_records(app: &App) -> Vec<insider::Record> {
    let old = insiders_cached(app).await;
    let mut merged = (*old).clone();
    merged.extend(gg_disk(app));
    let mut seen = std::collections::HashSet::new();
    merged.retain(|r| {
        seen.insert((
            r.sym().to_uppercase(),
            r.buyer().to_string(),
            r.trade_date().to_string(),
            r.txn.as_deref().unwrap_or("").to_string(),
            r.value() as i64,
        ))
    });
    merged
}

#[derive(Deserialize)]
struct InsidersQ {
    #[serde(default)]
    all: Option<bool>,
}

async fn insiders(State(app): State<App>, Query(q): Query<InsidersQ>) -> Json<Value> {
    let ins = all_records(&app).await;
    let pool = insider::pool_set(&app.pool);
    let all = q.all.unwrap_or(false);
    let events: Vec<Value> = ins
        .iter()
        .filter(|r| r.is_strategy_buy())
        .filter(|r| all || pool.is_empty() || pool.contains(&r.sym().to_uppercase()))
        .map(|r| {
            json!({
                "symbol": r.sym(),
                "trade_date": r.trade_date(),
                "disclosure_date": r.disc_date(),
                "intimation_date": r.intimation_date(),
                "buyer": r.buyer(),
                "role": insider::short_role(r.role()),
                "qty": r.qty(),
                "value_inr": r.value(),
                "estimated_price": r.estimated_price(),
                "price_basis": if r.estimated_price().is_some() { "disclosed_value_div_quantity" } else { "unavailable" },
            })
        })
        .collect();
    Json(json!({
        "window_days": WINDOW_DAYS,
        "pool_size": app.pool.len(),
        "count": events.len(),
        "events": events,
    }))
}

fn range_start(range: &str, end: NaiveDate) -> NaiveDate {
    let days = match range {
        "1y" => 370,
        "2y" => 740,
        "5y" => 5 * 365 + 10,
        "10y" | "max" => 10 * 365 + 20,
        _ => 740,
    };
    end - ChronoDuration::days(days)
}

async fn fetch_groww_range(
    client: &groww::Client,
    symbol: &str,
    range: &str,
) -> anyhow::Result<Vec<insider::Bar>> {
    let end = insider::today();
    let mut cursor = range_start(range, end);
    let mut by_date = BTreeMap::new();
    while cursor <= end {
        let page_end = (cursor + ChronoDuration::days(GROWW_PAGE_DAYS - 1)).min(end);
        for bar in client.historical_daily(symbol, cursor, page_end).await? {
            by_date.insert(bar.date, bar);
        }
        cursor = page_end + ChronoDuration::days(1);
    }
    Ok(by_date.into_values().collect())
}

/// Memory + disk cache for buyer-stock prices. Groww is preferred when keys are
/// configured; Yahoo is an explicit fallback so the buyer list still renders.
async fn prices_cached(app: &App, symbol: &str, range: &str) -> PriceResult {
    let key = format!("{}:{range}", symbol.to_uppercase());
    if let Some(hit) = app.px.lock().await.get(&key).cloned() {
        return hit;
    }

    let safe_symbol: String = symbol
        .chars()
        .filter(|c| c.is_ascii_alphanumeric() || *c == '-')
        .collect();
    let path = app
        .cache_dir
        .join(format!("price_{}_{}.json", safe_symbol, range));
    let disk: Option<PriceDiskCache> = read_json(&path);
    // Any fresh cache is usable, including the Yahoo fallback. (Do not force a
    // Groww refetch when a Groww client merely exists — its token may be dead.)
    if let Some(saved) = disk.as_ref().filter(|saved| fresh(saved.fetched_at)) {
        let result = PriceResult {
            bars: Arc::new(saved.bars.clone()),
            source: saved.source.clone(),
            cache_hit: true,
        };
        app.px.lock().await.insert(key, result.clone());
        return result;
    }

    let fetched = if let Some(client) = &app.groww {
        match fetch_groww_range(client, symbol, range).await {
            Ok(bars) if !bars.is_empty() => Ok((bars, "groww".to_string())),
            Ok(_) => Err(anyhow::anyhow!("Groww returned no bars")),
            Err(err) => Err(err),
        }
    } else {
        Err(anyhow::anyhow!("Groww credentials are not configured"))
    };
    let (bars, source) = match fetched {
        Ok(value) => value,
        Err(err) => {
            eprintln!("WARN: Groww prices failed for {symbol} ({err}); trying fallback");
            match insider::fetch_prices(&app.http, symbol, range).await {
                Ok(bars) if !bars.is_empty() => (bars, "yahoo-fallback".to_string()),
                _ if disk.is_some() => {
                    let saved = disk.unwrap();
                    (saved.bars, format!("{}-stale", saved.source))
                }
                _ => (Vec::new(), "unavailable".to_string()),
            }
        }
    };
    let saved = PriceDiskCache {
        fetched_at: unix_now(),
        source: source.clone(),
        bars: bars.clone(),
    };
    if !bars.is_empty() {
        if let Err(err) = write_json_atomic(&path, &saved) {
            eprintln!("WARN: could not cache {symbol} prices: {err}");
        }
    }
    let result = PriceResult {
        bars: Arc::new(bars),
        source,
        cache_hit: false,
    };
    app.px.lock().await.insert(key, result.clone());
    result
}

fn momentum_row(symbol: &str, bars: &[insider::Bar]) -> Option<(f64, Value)> {
    let n = bars.len();
    if n < 60 {
        return None;
    }
    let closes: Vec<f64> = bars.iter().map(|b| b.close).collect();
    let e50 = insider::ema(&closes, 50);
    let e200 = insider::ema(&closes, 200);
    let r = insider::rsi(&closes, 14);
    let last = closes[n - 1];
    let ema50 = e50[n - 1];
    let ema200 = if n >= 200 { e200[n - 1] } else { f64::NAN };
    let ret = |d: usize| {
        if n > d {
            last / closes[n - 1 - d] - 1.0
        } else {
            f64::NAN
        }
    };
    let hi = bars[n.saturating_sub(253)..n - 1]
        .iter()
        .map(|b| b.high)
        .fold(f64::MIN, f64::max);
    let above50 = last > ema50;
    let above200 = ema200.is_finite() && last > ema200;
    let golden = ema50.is_finite() && ema200.is_finite() && ema50 > ema200;
    let r3 = ret(63);
    let momentum = above50 && above200 && golden && r3 > 0.0;
    let num = |v: f64| if v.is_finite() { json!(v) } else { Value::Null };
    Some((
        r3,
        json!({
            "symbol": symbol,
            "close": last,
            "ema50": num(ema50),
            "ema200": num(ema200),
            "rsi": num(r[n - 1]),
            "ret1m": num(ret(21)),
            "ret3m": num(r3),
            "ret6m": num(ret(126)),
            "ret12m": num(ret(252)),
            "dist52w": num(last / hi - 1.0),
            "breakout52w": last > hi,
            "above_ema50": above50,
            "above_ema200": above200,
            "golden_cross": golden,
            "momentum": momentum,
        }),
    ))
}

#[derive(Deserialize)]
struct MomQ {
    #[serde(default)]
    all: Option<bool>,
    /// Keep only symbols whose latest qualifying buy is within this many days of
    /// the newest disclosure in the data (0/absent = no filter). The NSE feed lags
    /// a few months, so "recent" is measured against the newest signal, not today.
    #[serde(default)]
    recent: Option<i64>,
}

async fn momentum(State(app): State<App>, Query(q): Query<MomQ>) -> Json<Value> {
    let records = all_records(&app).await;
    let pool_set = insider::pool_set(&app.pool);
    let mut qualifying: Vec<&insider::Record> = records
        .iter()
        .filter(|r| r.is_strategy_buy())
        .filter(|r| {
            q.all.unwrap_or(false)
                || pool_set.is_empty()
                || pool_set.contains(&r.sym().to_uppercase())
        })
        .collect();
    qualifying.sort_by_key(|r| insider::parse_nse_date(r.disc_date()));

    // "Recently had a buyer": filter to buys within `recent` days of the newest
    // signal in the data (the feed lags, so anchoring on today would be empty).
    let latest_disc: Option<NaiveDate> = qualifying
        .iter()
        .filter_map(|r| insider::parse_nse_date(r.disc_date()))
        .max();
    let recent = q.recent.unwrap_or(DEFAULT_RECENT_DAYS);
    if recent > 0 {
        if let Some(cut) = latest_disc.map(|d| d - ChronoDuration::days(recent)) {
            qualifying.retain(|r| {
                insider::parse_nse_date(r.disc_date()).is_some_and(|d| d >= cut)
            });
        }
    }

    let mut symbols: Vec<String> = qualifying.iter().map(|r| r.sym().to_uppercase()).collect();
    symbols.sort();
    symbols.dedup();
    let mut rows: Vec<(f64, Value)> = Vec::new();
    for sym in symbols.iter().take(100) {
        let prices = prices_cached(&app, sym, "2y").await;
        let bars = prices.bars.as_ref();
        let Some((_, trend)) = momentum_row(sym, bars) else {
            continue;
        };
        let symbol_events: Vec<&insider::Record> = qualifying
            .iter()
            .copied()
            .filter(|r| r.sym().eq_ignore_ascii_case(sym))
            .collect();
        let Some(latest) = symbol_events
            .iter()
            .max_by_key(|r| insider::parse_nse_date(r.disc_date()))
        else {
            continue;
        };
        let Some(disclosure_date) = insider::parse_nse_date(latest.disc_date()) else {
            continue;
        };
        let Some(reference_bar) = bars.iter().find(|b| b.date >= disclosure_date) else {
            continue;
        };
        let Some(last) = bars.last() else { continue };
        let cluster_start = disclosure_date - chrono::Duration::days(30);
        let cluster: Vec<&&insider::Record> = symbol_events
            .iter()
            .filter(|r| {
                insider::parse_nse_date(r.disc_date())
                    .is_some_and(|d| d >= cluster_start && d <= disclosure_date)
            })
            .collect();
        let mut buyers: Vec<String> = cluster
            .iter()
            .map(|r| r.buyer().trim().to_uppercase())
            .filter(|name| !name.is_empty())
            .collect();
        buyers.sort();
        buyers.dedup();
        let cluster_buyers: Vec<Value> = cluster
            .iter()
            .map(|r| {
                json!({
                    "name": r.buyer(),
                    "role": insider::short_role(r.role()),
                    "trade_date": r.trade_date(),
                    "disclosure_date": r.disc_date(),
                    "intimation_date": r.intimation_date(),
                    "quantity": r.qty(),
                    "value_inr": r.value(),
                    "estimated_price": r.estimated_price(),
                    "price_basis": if r.estimated_price().is_some() { "disclosed_value_div_quantity" } else { "unavailable" },
                })
            })
            .collect();
        let aggregate_value: f64 = cluster.iter().map(|r| r.value()).sum();
        let mut traded_values: Vec<f64> = bars
            .iter()
            .rev()
            .take(20)
            .map(|b| b.close * b.volume)
            .filter(|v| v.is_finite() && *v > 0.0)
            .collect();
        traded_values.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
        let median_value = traded_values
            .get(traded_values.len() / 2)
            .copied()
            .unwrap_or(0.0);
        let commitment = if median_value > 0.0 {
            aggregate_value / median_value
        } else {
            f64::NAN
        };
        let rise = last.close / reference_bar.close - 1.0;
        let trend_ok = trend["above_ema50"] == json!(true) && trend["golden_cross"] == json!(true);
        let breakout = trend["breakout52w"] == json!(true);
        let ready = rise >= 0.10 && trend_ok && breakout;
        let dist = trend["dist52w"].as_f64().unwrap_or(f64::NAN);
        let status = if ready {
            "ready"
        } else if !trend_ok {
            "below-trend"
        } else if rise < 0.10 {
            "waiting-rise"
        } else if dist >= -0.05 {
            "near-breakout"
        } else {
            "trend-building"
        };
        let score = usize::from(commitment.is_finite() && commitment >= 0.5)
            + usize::from(buyers.len() >= 2);
        rows.push((if ready { 10.0 + rise } else { rise }, json!({
            "symbol": sym,
            "status": status,
            "ready": ready,
            "disclosure_date": disclosure_date.to_string(),
            "buyer": latest.buyer(),
            "role": insider::short_role(latest.role()),
            "quantity": latest.qty(),
            "event_value_inr": latest.value(),
            "cluster_value_inr": aggregate_value,
            "distinct_buyers_30d": buyers.len(),
            "buyer_names_30d": buyers,
            "cluster_buyers": cluster_buyers,
            "purchase_to_median_traded_value_20d": if commitment.is_finite() { json!(commitment) } else { Value::Null },
            "rise_from_disclosure": rise,
            "osint_score_partial": score,
            "close": trend["close"],
            "ema50": trend["ema50"],
            "ema200": trend["ema200"],
            "rsi": trend["rsi"],
            "dist52w": trend["dist52w"],
            "breakout52w": breakout,
            "trend_ok": trend_ok,
            "price_source": prices.source,
            "price_cache_hit": prices.cache_hit
        })));
    }
    rows.sort_by(|a, b| b.0.partial_cmp(&a.0).unwrap_or(std::cmp::Ordering::Equal));
    let vals: Vec<Value> = rows.into_iter().map(|(_, v)| v).collect();
    let n_ready = vals.iter().filter(|v| v["ready"] == json!(true)).count();
    Json(json!({
        "count": vals.len(), "ready_count": n_ready,
        "latest_disclosure_date": latest_disc.map(|d| d.to_string()),
        "recent_days": recent,
        "minimum_value_inr": insider::STRATEGY_MIN_VALUE_INR,
        "note": "Only qualifying buyer symbols are priced; Groww requests are disk-cached for 24h and spaced by 6s",
        "rows": vals
    }))
}

// -------------------------------------------------------------------------- //
// /api/scan — the standalone `insider_momentum` tool, served over HTTP.
// Recent major-insider buyers (last N days, anchored on the newest disclosure),
// then a simple momentum test per stock. This is what the "Momentum scan" page
// renders; from there a stock can be *mounted* and its chart fetched.

#[derive(Deserialize)]
struct ScanQ {
    #[serde(default)]
    recent: Option<i64>,
    #[serde(default)]
    min: Option<f64>,
    #[serde(default)]
    top: Option<usize>,
}

async fn scan(State(app): State<App>, Query(q): Query<ScanQ>) -> Json<Value> {
    let recent = q.recent.unwrap_or(DEFAULT_RECENT_DAYS);
    let min_value = q.min.unwrap_or(insider::STRATEGY_MIN_VALUE_INR);
    let top = q.top.unwrap_or(40);

    let records = all_records(&app).await;
    let mut buys: Vec<&insider::Record> = records
        .iter()
        .filter(|r| r.is_major_buy() && r.value() >= min_value)
        .collect();

    // anchor on the newest buy (the feed lags), keep only the last `recent` days
    let anchor = buys
        .iter()
        .filter_map(|r| insider::parse_nse_date(r.trade_date()))
        .max();
    if let Some(cut) = anchor.map(|d| d - ChronoDuration::days(recent)) {
        buys.retain(|r| insider::parse_nse_date(r.trade_date()).is_some_and(|d| d >= cut));
    }

    let mut latest: HashMap<String, NaiveDate> = HashMap::new();
    for r in &buys {
        if let Some(d) = insider::parse_nse_date(r.trade_date()) {
            latest
                .entry(r.sym().to_uppercase())
                .and_modify(|cur| {
                    if d > *cur {
                        *cur = d;
                    }
                })
                .or_insert(d);
        }
    }
    let mut syms: Vec<(String, NaiveDate)> = latest.into_iter().collect();
    syms.sort_by(|a, b| b.1.cmp(&a.1));
    syms.truncate(top);

    let mut rows: Vec<(f64, Value)> = Vec::new();
    for (sym, last_buy) in &syms {
        let prices = prices_cached(&app, sym, "2y").await;
        let Some((score, trend)) = momentum_row(sym, prices.bars.as_ref()) else {
            continue;
        };
        rows.push((score, json!({
            "symbol": sym,
            "last_buy": last_buy.to_string(),
            "close": trend["close"],
            "ema50": trend["ema50"],
            "ema200": trend["ema200"],
            "rsi": trend["rsi"],
            "ret1m": trend["ret1m"],
            "ret3m": trend["ret3m"],
            "ret6m": trend["ret6m"],
            "ret12m": trend["ret12m"],
            "dist52w": trend["dist52w"],
            "breakout52w": trend["breakout52w"],
            "trend_ok": trend["above_ema50"] == json!(true) && trend["golden_cross"] == json!(true),
            "momentum": trend["momentum"],
            "price_source": prices.source,
        })));
    }
    rows.sort_by(|a, b| b.0.partial_cmp(&a.0).unwrap_or(std::cmp::Ordering::Equal));
    let vals: Vec<Value> = rows.into_iter().map(|(_, v)| v).collect();
    let n_mom = vals.iter().filter(|v| v["momentum"] == json!(true)).count();
    Json(json!({
        "anchor": anchor.map(|d| d.to_string()),
        "recent_days": recent,
        "min_value_inr": min_value,
        "count": vals.len(),
        "momentum_count": n_mom,
        "rows": vals
    }))
}

#[derive(Deserialize)]
struct SeriesQ {
    symbol: String,
    #[serde(default = "def_range")]
    range: String,
}
fn def_range() -> String {
    "10y".to_string()
}

async fn series(State(app): State<App>, Query(q): Query<SeriesQ>) -> Json<Value> {
    // Safety: symbol only reaches fixed read-only market-data URLs.
    let symbol: String = q
        .symbol
        .chars()
        .filter(|c| c.is_ascii_alphanumeric() || *c == '-' || *c == '&')
        .take(20)
        .collect();
    let range = if matches!(q.range.as_str(), "1y" | "2y" | "5y" | "10y" | "max") {
        q.range.clone()
    } else {
        "10y".to_string()
    };

    let prices = prices_cached(&app, &symbol, &range).await;
    let bars = prices.bars.as_ref();
    let closes: Vec<f64> = bars.iter().map(|b| b.close).collect();
    let e50 = insider::ema(&closes, 50);
    let e200 = insider::ema(&closes, 200);
    let rsi14 = insider::rsi(&closes, 14);

    let ins = all_records(&app).await;
    let buys: Vec<Value> = ins
        .iter()
        .filter(|r| r.is_strategy_buy() && r.sym().eq_ignore_ascii_case(&symbol))
        .map(|r| {
            json!({
                "trade_date": r.trade_date(),
                "disclosure_date": r.disc_date(),
                "intimation_date": r.intimation_date(),
                "buyer": r.buyer(),
                "role": insider::short_role(r.role()),
                "qty": r.qty(),
                "value_inr": r.value(),
                "estimated_price": r.estimated_price(),
                "price_basis": if r.estimated_price().is_some() { "disclosed_value_div_quantity" } else { "unavailable" },
            })
        })
        .collect();

    let num = |v: f64| -> Value { if v.is_finite() { json!(v) } else { Value::Null } };
    Json(json!({
        "symbol": symbol,
        "range": range,
        "price_source": prices.source,
        "price_cache_hit": prices.cache_hit,
        "dates": bars.iter().map(|b| b.date.to_string()).collect::<Vec<_>>(),
        "close": closes.iter().map(|&c| num(c)).collect::<Vec<_>>(),
        "high": bars.iter().map(|b| num(b.high)).collect::<Vec<_>>(),
        "ema50": e50.iter().map(|&c| num(c)).collect::<Vec<_>>(),
        "ema200": e200.iter().map(|&c| num(c)).collect::<Vec<_>>(),
        "rsi": rsi14.iter().map(|&c| num(c)).collect::<Vec<_>>(),
        "buys": buys,
    }))
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    dotenvy::dotenv().ok();
    let cache_dir = std::env::var("INSIDER_CACHE_DIR")
        .map(PathBuf::from)
        .unwrap_or_else(|_| {
            PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("backtesting/data/insider_app_cache")
        });
    fs::create_dir_all(&cache_dir)?;
    let seed_dir = std::env::var("INSIDER_SEED_DIR")
        .ok()
        .map(PathBuf::from)
        .filter(|path| path.is_dir())
        .map(Arc::new);
    let groww = groww_client_from_env().await;
    let pool = Arc::new(insider::read_pool(POOL_FILE));
    let app = App {
        http: insider::client(),
        groww: groww.clone(),
        pool,
        cache: Arc::new(Mutex::new(None)),
        cache_dir: Arc::new(cache_dir.clone()),
        seed_dir,
        px: Arc::new(Mutex::new(HashMap::new())),
    };

    // Background collector: refresh the NEW `-gg` source into the disk cache so
    // every handler can merge LIVE filings without per-request NSE calls.
    {
        let app_bg = app.clone();
        tokio::spawn(async move {
            let path = app_bg.cache_dir.join("pit_gg_records.json");
            if read_json::<InsiderDiskCache>(&path)
                .map(|d| fresh(d.fetched_at))
                .unwrap_or(false)
            {
                eprintln!("(api) GG cache fresh — skipping background refresh");
                return;
            }
            let end = insider::today();
            let start = end - chrono::Duration::days(GG_WINDOW_DAYS);
            eprintln!("(api) background GG refresh {start}..{end} (a few minutes)…");
            match insider::fetch_gg(&app_bg.http, start, end, true).await {
                Ok(records) if !records.is_empty() => {
                    let saved = InsiderDiskCache {
                        fetched_at: unix_now(),
                        start,
                        end,
                        records,
                    };
                    let n = saved.records.len();
                    if let Err(e) = write_json_atomic(&path, &saved) {
                        eprintln!("(api) GG cache write failed: {e}");
                    } else {
                        eprintln!("(api) GG refresh complete: {n} live records cached");
                    }
                }
                Ok(_) => eprintln!("(api) GG refresh returned no filings"),
                Err(e) => eprintln!("(api) GG refresh failed: {e}"),
            }
        });
    }

    let cors = CorsLayer::new()
        .allow_origin(Any)
        .allow_methods([Method::GET]);

    let router = Router::new()
        .route(
            "/health",
            get({
                let groww_ready = groww.is_some();
                let cache_dir = cache_dir.display().to_string();
                move || async move {
                    Json(json!({
                        "ok": true,
                        "groww_market_data": groww_ready,
                        "cache_dir": cache_dir,
                        "cache_ttl_hours": 24,
                        "request_gap_seconds": 6
                    }))
                }
            }),
        )
        .route("/api/insiders", get(insiders))
        .route("/api/series", get(series))
        .route("/api/momentum", get(momentum))
        .route("/api/scan", get(scan))
        .layer(cors)
        .with_state(app);

    let listener = tokio::net::TcpListener::bind(ADDR).await?;
    println!("insider API on http://{ADDR}  (read-only, 127.0.0.1 only, GET only)");
    println!(
        "  Groww market data: {} | cache: {}",
        if groww.is_some() {
            "configured"
        } else {
            "fallback only"
        },
        cache_dir.display()
    );
    println!("  GET /api/insiders  GET /api/momentum  GET /api/series?symbol=AXISBANK&range=10y");
    axum::serve(listener, router).await?;
    Ok(())
}

async fn groww_client_from_env() -> Option<Arc<groww::Client>> {
    let usable = |value: String| {
        let trimmed = value.trim().trim_matches(['\'', '"']).to_string();
        (!trimmed.is_empty() && !trimmed.starts_with("your_")).then_some(trimmed)
    };
    let key = std::env::var("GROWW_API_KEY").ok().and_then(usable);
    let secret = std::env::var("GROWW_API_SECRET").ok().and_then(usable);
    if let (Some(key), Some(secret)) = (key, secret) {
        match groww::Client::login_with_api_key(&key, &secret).await {
            Ok(token) => {
                eprintln!("(api) Groww access token refreshed from API key/secret");
                return Some(Arc::new(groww::Client::new(&token)));
            }
            Err(err) => eprintln!(
                "WARN: Groww key/secret refresh failed ({err}); trying stored access token"
            ),
        }
    }
    if let Some(token) = std::env::var("GROWW_ACCESS_TOKEN").ok().and_then(usable) {
        eprintln!("(api) using stored Groww access token");
        return Some(Arc::new(groww::Client::new(&token)));
    }
    eprintln!("WARN: Groww credentials absent; prices will use fallback");
    None
}
