//! Insider (PIT) fetch + price series + indicators. Shared by the CLI bin and the
//! HTTP API. READ-ONLY: no API key, no order code, nothing that can trade.
//!
//! NSE PIT disclosure fetching plus a Yahoo price fallback and indicators.
//! The API server prefers authenticated, read-only Groww candles; this module's
//! Yahoo reader keeps charts available when Groww authentication is unavailable.
//!
//! The NSE feed puts `null` in some fields; every string field is `Option<String>`
//! or a single month fails to parse. The feed is also **stale** for the most
//! recent 2–3 months (verified 2026-10-13).

use std::collections::BTreeSet;
use std::time::Duration;

use anyhow::{Context, Result};
use chrono::{Datelike, Duration as ChronoDuration, Local, NaiveDate};
use serde::{Deserialize, Serialize};
use tokio::time::sleep;

pub const PIT_API: &str = "https://www.nseindia.com/api/corporates-pit";
pub const STRATEGY_MIN_VALUE_INR: f64 = 2_500_000.0;
const REFERER: &str =
    "https://www.nseindia.com/companies-listing/corporate-filings-insider-trading";
const USER_AGENT: &str = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36";
/// NSE is intentionally polled slowly. The API server also persists a 24-hour
/// cache, so this delay is only paid during a real disclosure refresh.
pub const REQUEST_GAP: Duration = Duration::from_secs(6);

/// A major-insider "big party".
pub fn is_major_role(role: &str) -> bool {
    matches!(
        role,
        "Promoters" | "Promoter Group" | "Director" | "Key Managerial Personnel"
    )
}

#[derive(Deserialize, Serialize, Debug, Clone)]
pub struct Record {
    #[serde(default)]
    pub symbol: Option<String>,
    #[serde(rename = "acqName", default)]
    pub acq_name: Option<String>,
    #[serde(rename = "personCategory", default)]
    pub person_category: Option<String>,
    #[serde(rename = "tdpTransactionType", default)]
    pub txn: Option<String>,
    #[serde(rename = "acqMode", default)]
    pub acq_mode: Option<String>,
    #[serde(rename = "acqfromDt", default)]
    pub from_dt: Option<String>,
    #[serde(rename = "intimDt", default)]
    pub intim_dt: Option<String>,
    #[serde(default)]
    pub date: Option<String>,
    #[serde(rename = "secAcq", default)]
    pub sec_acq: serde_json::Value,
    #[serde(rename = "secVal", default)]
    pub sec_val: serde_json::Value,
    #[serde(rename = "secType", default)]
    pub sec_type: Option<String>,
}

impl Record {
    pub fn sym(&self) -> &str {
        self.symbol.as_deref().unwrap_or("")
    }
    pub fn buyer(&self) -> &str {
        self.acq_name.as_deref().unwrap_or("")
    }
    pub fn role(&self) -> &str {
        self.person_category.as_deref().unwrap_or("")
    }
    pub fn trade_date(&self) -> &str {
        self.from_dt.as_deref().unwrap_or("")
    }
    pub fn disc_date(&self) -> &str {
        self.date.as_deref().unwrap_or("")
    }
    pub fn intimation_date(&self) -> &str {
        self.intim_dt.as_deref().unwrap_or("")
    }
    pub fn is_major_buy(&self) -> bool {
        let sec = self.sec_type.as_deref().unwrap_or("");
        is_major_role(self.role())
            && self.acq_mode.as_deref().unwrap_or("") == "Market Purchase"
            && self.txn.as_deref().unwrap_or("") == "Buy"
            && (sec.is_empty() || sec == "Equity Shares")
    }
    /// The event that is allowed to arm the strategy watchlist.
    pub fn is_strategy_buy(&self) -> bool {
        self.is_major_buy() && self.value() >= STRATEGY_MIN_VALUE_INR
    }
    pub fn value(&self) -> f64 {
        as_f64(&self.sec_val)
    }
    pub fn qty(&self) -> f64 {
        as_f64(&self.sec_acq)
    }
    /// NSE PIT exposes total transaction value and quantity, not individual
    /// fills. Their ratio is the disclosed batch's volume-weighted average.
    pub fn estimated_price(&self) -> Option<f64> {
        let qty = self.qty();
        let value = self.value();
        (qty > 0.0 && value > 0.0).then_some(value / qty)
    }
}

/// XBRL PIT-V2 category names differ from the old endpoint's ("Promoter" vs
/// "Promoters", "Directors", …). Normalise to the old naming so `is_major_role`
/// (and therefore the strategy filter) keeps working on the new source.
pub fn normalize_category(cat: &str) -> String {
    match cat.trim() {
        "Promoter" | "Promoter and Director" | "Promoter and Promoter Group" => {
            "Promoters".to_string()
        }
        "Promoter Group" => "Promoter Group".to_string(),
        "Directors" | "Director" | "Director and KMP" | "Directors and KMP" => {
            "Director".to_string()
        }
        "Directors Immediate relative" | "Immediate relative" | "Immediate relatives" => {
            "Immediate relative".to_string()
        }
        "Key Managerial Personnel" | "KMP" => "Key Managerial Personnel".to_string(),
        other => other.to_string(),
    }
}

pub fn as_f64(v: &serde_json::Value) -> f64 {
    match v {
        serde_json::Value::Number(n) => n.as_f64().unwrap_or(0.0),
        serde_json::Value::String(s) => s.replace(',', "").parse().unwrap_or(0.0),
        _ => 0.0,
    }
}

#[derive(Deserialize, Debug)]
struct Envelope {
    #[serde(default)]
    data: Vec<Record>,
}

async fn fetch_month(
    http: &reqwest::Client,
    from: NaiveDate,
    to: NaiveDate,
) -> Result<Vec<Record>> {
    let url = format!(
        "{PIT_API}?index=equities&from_date={}&to_date={}&symbol=",
        from.format("%d-%m-%Y"),
        to.format("%d-%m-%Y")
    );
    let resp = http
        .get(&url)
        .header("Accept", "application/json")
        .header("Referer", REFERER)
        .send()
        .await
        .with_context(|| format!("GET {url}"))?;
    if !resp.status().is_success() {
        anyhow::bail!("HTTP {} for {url}", resp.status());
    }
    let env: Envelope = resp.json().await.context("parsing PIT JSON")?;
    Ok(env.data)
}

/// Fetch disclosures month-by-month over `[start, end]`.
pub async fn fetch_window(
    http: &reqwest::Client,
    start: NaiveDate,
    end: NaiveDate,
    log: bool,
) -> Result<Vec<Record>> {
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
        match fetch_month(http, from, to).await {
            Ok(mut recs) => {
                if log {
                    eprintln!("  {from} .. {to} -> {} rows", recs.len());
                }
                all.append(&mut recs);
            }
            Err(e) => {
                if log {
                    eprintln!("  WARN {from}..{to}: {e}");
                }
            }
        }
        cursor = next_month;
        sleep(REQUEST_GAP).await;
    }
    Ok(all)
}

// --------------------------------------------------------------------------- //
// NEW source (2026-04-30+): /api/corporates-pit-gg — filing metadata + XBRL.
// The old /corporates-pit endpoint was retired on 2026-04-30 (its XBRL says
// "PIT V2.0") and returns nothing for recent months. This lists filings from the
// live endpoint and parses each filing's XBRL into a Record.
// --------------------------------------------------------------------------- //

pub const GG_LIST_API: &str = "https://www.nseindia.com/api/corporates-pit-gg";
pub const GG_GAP: Duration = Duration::from_millis(300);

#[derive(Deserialize, Debug)]
struct GgEnvelope {
    #[serde(default)]
    data: Vec<GgFiling>,
}

#[derive(Deserialize, Debug, Clone)]
struct GgFiling {
    #[serde(default)]
    symbol: Option<String>,
    #[serde(rename = "broadcastDateTime", default)]
    broadcast: Option<String>,
    #[serde(rename = "xmlFileName", default)]
    xml: Option<String>,
}

/// Pull `<in-bse-co:TAG …>VALUE</in-bse-co:TAG>` out of the XBRL text.
fn xbrl_field(xml: &str, tag: &str) -> Option<String> {
    let open = format!("<in-bse-co:{tag}");
    let close = format!("</in-bse-co:{tag}>");
    let i = xml.find(&open)?;
    let rest = &xml[i..];
    let gt = rest.find('>')?;
    let after = &rest[gt + 1..];
    let j = after.find(&close)?;
    Some(after[..j].trim().to_string())
}

/// Fetch recent filings from the LIVE `-gg` endpoint and parse each XBRL.
/// Slow by design (~300 ms per filing); call from a background/collector task.
pub async fn fetch_gg(
    http: &reqwest::Client,
    start: NaiveDate,
    end: NaiveDate,
    log: bool,
) -> Result<Vec<Record>> {
    let url = format!(
        "{GG_LIST_API}?index=equities&from_date={}&to_date={}&symbol=",
        start.format("%d-%m-%Y"),
        end.format("%d-%m-%Y")
    );
    let resp = http
        .get(&url)
        .header("Accept", "application/json")
        .header("Referer", REFERER)
        .send()
        .await?;
    if !resp.status().is_success() {
        anyhow::bail!("GG list HTTP {} for {}", resp.status(), url);
    }
    let env: GgEnvelope = resp.json().await.context("parsing GG list")?;
    let total = env.data.len();
    let mut out = Vec::with_capacity(total);
    for (i, f) in env.data.into_iter().enumerate() {
        let Some(xml_url) = f.xml.clone().filter(|u| !u.is_empty()) else {
            continue;
        };
        let xml = match http
            .get(&xml_url)
            .header("Referer", REFERER)
            .send()
            .await
        {
            Ok(r) if r.status().is_success() => match r.text().await {
                Ok(t) => t,
                Err(_) => continue,
            },
            _ => continue,
        };
        let Some(txn) = xbrl_field(&xml, "SecuritiesAcquiredOrDisposedTransactionType") else {
            continue;
        };
        out.push(Record {
            symbol: f.symbol.clone(),
            acq_name: xbrl_field(&xml, "NameOfThePerson"),
            person_category: xbrl_field(&xml, "CategoryOfPerson").map(|c| normalize_category(&c)),
            txn: Some(txn),
            acq_mode: xbrl_field(&xml, "ModeOfAcquisitionOrDisposal"),
            from_dt: xbrl_field(
                &xml,
                "DateOfAllotmentAdviceOrAcquisitionOfSharesOrSaleOfSharesSpecifyFromDate",
            ),
            intim_dt: xbrl_field(&xml, "DateOfIntimationToCompany"),
            date: f.broadcast.clone(),
            sec_acq: serde_json::json!(
                xbrl_field(&xml, "SecuritiesAcquiredOrDisposedNumberOfSecurity").unwrap_or_default()
            ),
            sec_val: serde_json::json!(
                xbrl_field(&xml, "SecuritiesAcquiredOrDisposedValueOfSecurity").unwrap_or_default()
            ),
            sec_type: Some("Equity Shares".to_string()),
        });
        if log && (i + 1) % 50 == 0 {
            eprintln!("  GG parsed {}/{} filings", i + 1, total);
        }
        sleep(GG_GAP).await;
    }
    Ok(out)
}

pub fn client() -> reqwest::Client {
    reqwest::Client::builder()
        .timeout(Duration::from_secs(40))
        .user_agent(USER_AGENT)
        .build()
        .expect("static reqwest config")
}

// --------------------------------------------------------------------------- //
// Prices (Yahoo chart) + indicators
// --------------------------------------------------------------------------- //

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Bar {
    pub date: NaiveDate,
    pub open: f64,
    pub high: f64,
    pub low: f64,
    pub close: f64,
    pub volume: f64,
}

#[derive(Deserialize)]
struct Yahoo {
    chart: YahooChart,
}
#[derive(Deserialize)]
struct YahooChart {
    result: Option<Vec<YahooResult>>,
}
#[derive(Deserialize)]
struct YahooResult {
    timestamp: Option<Vec<i64>>,
    indicators: YahooIndicators,
}
#[derive(Deserialize)]
struct YahooIndicators {
    quote: Vec<YahooQuote>,
}
#[derive(Deserialize)]
struct YahooQuote {
    open: Vec<Option<f64>>,
    high: Vec<Option<f64>>,
    low: Vec<Option<f64>>,
    close: Vec<Option<f64>>,
    volume: Vec<Option<f64>>,
}

/// Daily closes from Yahoo. `range` is a Yahoo window like "10y".
pub async fn fetch_prices(http: &reqwest::Client, symbol: &str, range: &str) -> Result<Vec<Bar>> {
    let url = format!(
        "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}.NS?range={range}&interval=1d"
    );
    let resp = http
        .get(&url)
        .header("Accept", "application/json")
        .send()
        .await
        .with_context(|| format!("GET {url}"))?
        .error_for_status()
        .context("yahoo returned an error status")?;
    let y: Yahoo = resp.json().await.context("parsing yahoo chart")?;
    let r = y
        .chart
        .result
        .and_then(|mut v| v.pop())
        .ok_or_else(|| anyhow::anyhow!("no chart result for {symbol}"))?;
    let ts = r.timestamp.unwrap_or_default();
    let quote = r.indicators.quote.into_iter().next().unwrap_or(YahooQuote {
        open: Vec::new(),
        high: Vec::new(),
        low: Vec::new(),
        close: Vec::new(),
        volume: Vec::new(),
    });
    let mut out = Vec::new();
    for (i, t) in ts.iter().enumerate() {
        if let Some(Some(c)) = quote.close.get(i) {
            if c.is_finite() && *c > 0.0 {
                if let Some(dt) = chrono::DateTime::from_timestamp(*t, 0) {
                    let finite_or = |values: &[Option<f64>], fallback: f64| {
                        values
                            .get(i)
                            .and_then(|v| *v)
                            .filter(|v| v.is_finite() && *v > 0.0)
                            .unwrap_or(fallback)
                    };
                    out.push(Bar {
                        date: dt.date_naive(),
                        open: finite_or(&quote.open, *c),
                        high: finite_or(&quote.high, *c),
                        low: finite_or(&quote.low, *c),
                        close: *c,
                        volume: quote
                            .volume
                            .get(i)
                            .and_then(|v| *v)
                            .filter(|v| v.is_finite() && *v >= 0.0)
                            .unwrap_or(0.0),
                    });
                }
            }
        }
    }
    Ok(out)
}

/// Exponential moving average (span = N). Same convention as the Python work.
pub fn ema(values: &[f64], span: usize) -> Vec<f64> {
    let mut out = Vec::with_capacity(values.len());
    let k = 2.0 / (span as f64 + 1.0);
    let mut prev = f64::NAN;
    for (i, &v) in values.iter().enumerate() {
        if i == 0 || !prev.is_finite() {
            prev = v;
        } else {
            prev = v * k + prev * (1.0 - k);
        }
        out.push(prev);
    }
    out
}

/// Wilder RSI.
pub fn rsi(closes: &[f64], period: usize) -> Vec<f64> {
    let n = closes.len();
    let mut out = vec![f64::NAN; n];
    if n <= period {
        return out;
    }
    let (mut ag, mut al) = (0.0, 0.0);
    for i in 1..=period {
        let d = closes[i] - closes[i - 1];
        if d >= 0.0 {
            ag += d;
        } else {
            al -= d;
        }
    }
    ag /= period as f64;
    al /= period as f64;
    out[period] = if al == 0.0 {
        100.0
    } else {
        100.0 - 100.0 / (1.0 + ag / al)
    };
    for i in (period + 1)..n {
        let d = closes[i] - closes[i - 1];
        let (g, l) = if d >= 0.0 { (d, 0.0) } else { (0.0, -d) };
        ag = (ag * (period as f64 - 1.0) + g) / period as f64;
        al = (al * (period as f64 - 1.0) + l) / period as f64;
        out[i] = if al == 0.0 {
            100.0
        } else {
            100.0 - 100.0 / (1.0 + ag / al)
        };
    }
    out
}

// --------------------------------------------------------------------------- //

pub fn read_pool(path: &str) -> Vec<String> {
    std::fs::read_to_string(path)
        .unwrap_or_default()
        .lines()
        .map(|l| l.trim())
        .filter(|l| !l.is_empty() && !l.starts_with('#'))
        .map(|l| l.to_uppercase())
        .collect()
}

pub fn pool_set(pool: &[String]) -> BTreeSet<String> {
    pool.iter().cloned().collect()
}

pub fn short_role(cat: &str) -> &str {
    match cat {
        "Promoters" => "promoter",
        "Promoter Group" => "promoter-grp",
        "Director" => "director",
        "Key Managerial Personnel" => "KMP",
        "Employees/Designated Employees" => "employee",
        other => other,
    }
}

pub fn truncate(s: &str, n: usize) -> String {
    if s.chars().count() <= n {
        s.to_string()
    } else {
        s.chars().take(n).collect::<String>() + "..."
    }
}

/// "today" in IST-ish terms (local clock) — used only to bound windows.
pub fn today() -> NaiveDate {
    Local::now().date_naive()
}

/// NSE currently emits dates such as `27-May-2025 00:00:00`.  Keep parsing in
/// one place so the API and strategy never silently disagree about event time.
pub fn parse_nse_date(raw: &str) -> Option<NaiveDate> {
    let date = raw.split_whitespace().next().unwrap_or(raw);
    ["%d-%b-%Y", "%d-%m-%Y", "%Y-%m-%d"]
        .iter()
        .find_map(|fmt| NaiveDate::parse_from_str(date, fmt).ok())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_known_nse_date_shapes() {
        assert_eq!(
            parse_nse_date("27-May-2025 18:30:00").unwrap().to_string(),
            "2025-05-27"
        );
        assert_eq!(
            parse_nse_date("27-05-2025").unwrap().to_string(),
            "2025-05-27"
        );
        assert_eq!(
            parse_nse_date("2025-05-27").unwrap().to_string(),
            "2025-05-27"
        );
    }
}
