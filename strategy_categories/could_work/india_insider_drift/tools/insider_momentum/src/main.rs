//! insider_momentum — a standalone, READ-ONLY tool.
//!
//! 1. Fetch recent major-insider market BUYS (NSE PIT API, free, no auth).
//! 2. For those stocks, fetch daily prices (Yahoo chart) and test **momentum**
//!    per our strategy:
//!        momentum = close > EMA50 > EMA200  AND  3-month return > 0
//!        ready    = momentum AND 52-week-high breakout AND rise since the buy >= 10%
//! 3. Print a table and a summary of which stocks are in momentum.
//!
//! Deliberately self-contained: it shares no code with `spread_reversion` and
//! writes nothing except stdout. No keys, no orders.
//!
//! Only the LAST 1–2 MONTHS of insider activity are considered, anchored on the
//! newest disclosure available (the NSE feed lags a few months), so "recent" stays
//! meaningful even when today's disclosures have not published yet.
//!
//! Usage:  insider_momentum [RECENT_DAYS] [TOP_N] [MIN_VALUE_INR]
//!         defaults:           60          30       2500000

use std::collections::BTreeMap;
use std::thread::sleep;
use std::time::Duration;

use chrono::{Datelike, Duration as ChronoDuration, Local, NaiveDate};
use serde::Deserialize;

const PIT_API: &str = "https://www.nseindia.com/api/corporates-pit";
const REFERER: &str =
    "https://www.nseindia.com/companies-listing/corporate-filings-insider-trading";
const UA: &str = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36";
const REQUEST_GAP: Duration = Duration::from_secs(2);

#[derive(Deserialize, Debug, Clone)]
struct Envelope {
    #[serde(default)]
    data: Vec<Record>,
}

// NOTE: every string is Option<String> — the NSE feed puts `null` in some fields
// and a plain String would fail the whole month's parse.
#[derive(Deserialize, Debug, Clone)]
struct Record {
    #[serde(default)]
    symbol: Option<String>,
    #[serde(rename = "acqName", default)]
    acq_name: Option<String>,
    #[serde(rename = "personCategory", default)]
    person_category: Option<String>,
    #[serde(rename = "tdpTransactionType", default)]
    txn: Option<String>,
    #[serde(rename = "acqMode", default)]
    acq_mode: Option<String>,
    #[serde(rename = "acqfromDt", default)]
    from_dt: Option<String>,
    #[serde(default)]
    date: Option<String>,
    #[serde(rename = "secAcq", default)]
    sec_acq: serde_json::Value,
    #[serde(rename = "secVal", default)]
    sec_val: serde_json::Value,
    #[serde(rename = "secType", default)]
    sec_type: Option<String>,
}

impl Record {
    fn sym(&self) -> &str {
        self.symbol.as_deref().unwrap_or("")
    }
    fn role(&self) -> &str {
        self.person_category.as_deref().unwrap_or("")
    }
    fn trade_date(&self) -> &str {
        self.from_dt.as_deref().unwrap_or("")
    }
    fn value(&self) -> f64 {
        match &self.sec_val {
            serde_json::Value::Number(n) => n.as_f64().unwrap_or(0.0),
            serde_json::Value::String(s) => s.replace(',', "").parse().unwrap_or(0.0),
            _ => 0.0,
        }
    }
    fn is_major_buy(&self) -> bool {
        let sec = self.sec_type.as_deref().unwrap_or("");
        matches!(
            self.role(),
            "Promoters" | "Promoter Group" | "Director" | "Key Managerial Personnel"
        ) && self.acq_mode.as_deref().unwrap_or("") == "Market Purchase"
            && self.txn.as_deref().unwrap_or("") == "Buy"
            && (sec.is_empty() || sec == "Equity Shares")
    }
}

fn parse_dmy(s: &str) -> Option<NaiveDate> {
    let head = s.split_whitespace().next().unwrap_or(s);
    NaiveDate::parse_from_str(head, "%d-%b-%Y").ok()
}

fn fetch_month(
    http: &reqwest::blocking::Client,
    from: NaiveDate,
    to: NaiveDate,
) -> anyhow::Result<Vec<Record>> {
    let url = format!(
        "{PIT_API}?index=equities&from_date={}&to_date={}&symbol=",
        from.format("%d-%m-%Y"),
        to.format("%d-%m-%Y")
    );
    let resp = http
        .get(&url)
        .header("Accept", "application/json")
        .header("Referer", REFERER)
        .send()?;
    if !resp.status().is_success() {
        anyhow::bail!("HTTP {} for {}", resp.status(), url);
    }
    let env: Envelope = resp.json()?;
    Ok(env.data)
}

fn fetch_recent(http: &reqwest::blocking::Client, start: NaiveDate, end: NaiveDate) -> Vec<Record> {
    let mut all = Vec::new();
    let mut cursor = NaiveDate::from_ymd_opt(start.year(), start.month(), 1).unwrap();
    while cursor <= end {
        let next_month = if cursor.month() == 12 {
            NaiveDate::from_ymd_opt(cursor.year() + 1, 1, 1).unwrap()
        } else {
            NaiveDate::from_ymd_opt(cursor.year(), cursor.month() + 1, 1).unwrap()
        };
        let month_end = next_month - ChronoDuration::days(1);
        let from = cursor.max(start);
        let to = month_end.min(end);
        match fetch_month(http, from, to) {
            Ok(mut recs) => {
                eprintln!("  {from} .. {to} -> {} rows", recs.len());
                all.append(&mut recs);
            }
            Err(e) => eprintln!("  WARN {from}..{to}: {e}"),
        }
        cursor = next_month;
        sleep(REQUEST_GAP);
    }
    all
}

// ----------------------------------------------------------------- prices ---

#[derive(Deserialize)]
struct Yahoo {
    chart: Chart,
}
#[derive(Deserialize)]
struct Chart {
    result: Option<Vec<ChartResult>>,
}
#[derive(Deserialize)]
struct ChartResult {
    timestamp: Option<Vec<i64>>,
    indicators: Indicators,
}
#[derive(Deserialize)]
struct Indicators {
    quote: Vec<Quote>,
}
#[derive(Deserialize)]
struct Quote {
    close: Vec<Option<f64>>,
    high: Vec<Option<f64>>,
}

#[derive(Clone, Copy)]
struct Bar {
    date: NaiveDate,
    close: f64,
    high: f64,
}

fn fetch_bars(http: &reqwest::blocking::Client, symbol: &str) -> anyhow::Result<Vec<Bar>> {
    let url = format!(
        "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}.NS?range=2y&interval=1d"
    );
    let resp = http.get(&url).header("Accept", "application/json").send()?;
    if !resp.status().is_success() {
        anyhow::bail!("yahoo HTTP {} for {symbol}", resp.status());
    }
    let y: Yahoo = resp.json()?;
    let r = y
        .chart
        .result
        .and_then(|mut v| v.pop())
        .ok_or_else(|| anyhow::anyhow!("no chart result for {symbol}"))?;
    let ts = r.timestamp.unwrap_or_default();
    let q = r
        .indicators
        .quote
        .into_iter()
        .next()
        .ok_or_else(|| anyhow::anyhow!("no quote for {symbol}"))?;
    let mut out = Vec::new();
    for (i, t) in ts.iter().enumerate() {
        let c = q.close.get(i).copied().flatten();
        let h = q.high.get(i).copied().flatten().or(c);
        if let (Some(c), Some(h)) = (c, h) {
            if c.is_finite() && c > 0.0 {
                if let Some(dt) = chrono::DateTime::from_timestamp(*t, 0) {
                    out.push(Bar { date: dt.date_naive(), close: c, high: h });
                }
            }
        }
    }
    Ok(out)
}

fn ema(values: &[f64], span: usize) -> Vec<f64> {
    let k = 2.0 / (span as f64 + 1.0);
    let mut out = Vec::with_capacity(values.len());
    let mut prev = f64::NAN;
    for (i, &v) in values.iter().enumerate() {
        prev = if i == 0 || !prev.is_finite() { v } else { v * k + prev * (1.0 - k) };
        out.push(prev);
    }
    out
}

fn rsi(closes: &[f64], period: usize) -> Vec<f64> {
    let n = closes.len();
    let mut out = vec![f64::NAN; n];
    if n <= period {
        return out;
    }
    let (mut ag, mut al) = (0.0, 0.0);
    for i in 1..=period {
        let d = closes[i] - closes[i - 1];
        if d >= 0.0 { ag += d } else { al -= d }
    }
    ag /= period as f64;
    al /= period as f64;
    out[period] = if al == 0.0 { 100.0 } else { 100.0 - 100.0 / (1.0 + ag / al) };
    for i in (period + 1)..n {
        let d = closes[i] - closes[i - 1];
        let (g, l) = if d >= 0.0 { (d, 0.0) } else { (0.0, -d) };
        ag = (ag * (period as f64 - 1.0) + g) / period as f64;
        al = (al * (period as f64 - 1.0) + l) / period as f64;
        out[i] = if al == 0.0 { 100.0 } else { 100.0 - 100.0 / (1.0 + ag / al) };
    }
    out
}

struct Momentum {
    close: f64,
    ema50: f64,
    ema200: f64,
    rsi: f64,
    ret3m: f64,
    ret12m: f64,
    dist52w: f64,
    breakout52w: bool,
    above50: bool,
    above200: bool,
    golden: bool,
    momentum: bool,
}

fn test_momentum(bars: &[Bar]) -> Option<Momentum> {
    let n = bars.len();
    if n < 60 {
        return None;
    }
    let closes: Vec<f64> = bars.iter().map(|b| b.close).collect();
    let highs: Vec<f64> = bars.iter().map(|b| b.high).collect();
    let e50 = ema(&closes, 50);
    let e200 = ema(&closes, 200);
    let r = rsi(&closes, 14);
    let last = closes[n - 1];
    let ema50 = e50[n - 1];
    let ema200 = if n >= 200 { e200[n - 1] } else { f64::NAN };
    let ret = |d: usize| if n > d { last / closes[n - 1 - d] - 1.0 } else { f64::NAN };
    let hi52 = if n > 253 { &highs[n - 253..n - 1] } else { &highs[..n - 1] };
    let hi = hi52.iter().cloned().fold(f64::MIN, f64::max);
    let above50 = last > ema50;
    let above200 = ema200.is_finite() && last > ema200;
    let golden = ema50.is_finite() && ema200.is_finite() && ema50 > ema200;
    let ret3m = ret(63);
    Some(Momentum {
        close: last,
        ema50,
        ema200,
        rsi: r[n - 1],
        ret3m,
        ret12m: ret(252),
        dist52w: if hi > 0.0 { last / hi - 1.0 } else { f64::NAN },
        breakout52w: last > hi,
        above50,
        above200,
        golden,
        momentum: above50 && above200 && golden && ret3m > 0.0,
    })
}

fn pct(v: f64) -> String {
    if v.is_finite() { format!("{:>+7.1}%", v * 100.0) } else { "     na".into() }
}

fn main() -> anyhow::Result<()> {
    let args: Vec<String> = std::env::args().skip(1).collect();
    // The first argument is now "how many days back from the NEWEST disclosure we
    // care about" (default 60 = ~2 months). We fetch a wide window only to *find*
    // that newest disclosure, because the NSE feed lags a few months.
    let recent_days: i64 = args.first().and_then(|s| s.parse().ok()).unwrap_or(60);
    let top_n: usize = args.get(1).and_then(|s| s.parse().ok()).unwrap_or(30);
    let min_value: f64 = args.get(2).and_then(|s| s.parse().ok()).unwrap_or(2_500_000.0);

    const LOOKBACK_DAYS: i64 = 400;

    let http = reqwest::blocking::Client::builder()
        .timeout(Duration::from_secs(40))
        .user_agent(UA)
        .build()?;

    let end = Local::now().date_naive();
    let start = end - ChronoDuration::days(LOOKBACK_DAYS);
    eprintln!("fetching NSE insider disclosures (month by month)…");

    let records = fetch_recent(&http, start, end);
    let all_buys: Vec<&Record> = records
        .iter()
        .filter(|r| r.is_major_buy() && r.value() >= min_value)
        .collect();

    // Anchor on the newest insider buy we have; keep only the last `recent_days`.
    let anchor = all_buys.iter().filter_map(|r| parse_dmy(r.trade_date())).max();
    let cut = anchor.map(|d| d - ChronoDuration::days(recent_days));
    let buys: Vec<&Record> = all_buys
        .iter()
        .copied()
        .filter(|r| cut.map_or(true, |c| parse_dmy(r.trade_date()).is_some_and(|d| d >= c)))
        .collect();

    println!(
        "insider_momentum — last {recent_days} days of insider buys (newest signal {}), \
         min Rs{min_value:.0}, top {top_n}\n",
        anchor.map(|d| d.to_string()).unwrap_or_else(|| "—".into())
    );

    // latest qualifying buy per symbol
    let mut latest: BTreeMap<String, NaiveDate> = BTreeMap::new();
    for r in &buys {
        if let Some(d) = parse_dmy(r.trade_date()) {
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
    let newest = latest.values().copied().max();
    let mut syms: Vec<(String, NaiveDate)> = latest.into_iter().collect();
    syms.sort_by(|a, b| b.1.cmp(&a.1));
    syms.truncate(top_n);

    println!(
        "recent buyer stocks: {} total, showing top {} (newest signal {})\n",
        syms.len(),
        syms.len(),
        newest.map(|d| d.to_string()).unwrap_or_else(|| "—".into())
    );

    println!(
        "{:<12}{:>12}{:>9}{:>8}{:>8}{:>8}{:>8}{:>8}  {}",
        "SYMBOL", "last buy", "close", "3m", "12m", "from52w", "RSI", "trend", "MOMENTUM"
    );
    println!("{}", "-".repeat(96));

    let mut n_mom = 0;
    for (sym, last_buy) in &syms {
        let bars = match fetch_bars(&http, sym) {
            Ok(b) if b.len() >= 60 => b,
            Ok(_) => {
                println!("{sym:<12}{:>12}  (insufficient price history)", last_buy.to_string());
                continue;
            }
            Err(e) => {
                println!("{sym:<12}{:>12}  (price error: {e})", last_buy.to_string());
                continue;
            }
        };
        if let Some(m) = test_momentum(&bars) {
            if m.momentum {
                n_mom += 1;
            }
            let trend = match (m.above50, m.above200, m.golden) {
                (true, true, true) => "EMA50>EMA200",
                (true, _, _) => "above EMA50",
                _ => "below",
            };
            println!(
                "{:<12}{:>12}{:>9.1}{}{}{}{:>8.0}{:>9}  {}",
                sym,
                last_buy.to_string(),
                m.close,
                pct(m.ret3m),
                pct(m.ret12m),
                pct(m.dist52w),
                m.rsi,
                trend,
                if m.momentum { "YES" } else { "" }
            );
            sleep(Duration::from_millis(150)); // be polite to Yahoo
        }
    }

    println!(
        "\n{} of {} recent-buyer stocks are in MOMENTUM (close > EMA50 > EMA200 and 3m return > 0).",
        n_mom,
        syms.len()
    );
    println!("Read-only. Not investment advice.");
    Ok(())
}
