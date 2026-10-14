//! Insider (PIT/SAST) buyer fetcher for a selected pool of NSE symbols.
//!
//! READ-ONLY. Source: NSE corporate-filings "corporate-insider-trading" API —
//! free, no auth, no API key, and no order code anywhere in this file. This is
//! the Rust port of the Python recon in
//! `strategy_categories/could_work/india_insider_drift/insider_drift.py`.
//!
//! What it does
//! ------------
//! 1. Reads a pool of symbols from `backtesting/data/insider_universe.txt`
//!    (one per line, `#` comments allowed), or from the command line.
//! 2. Pulls the PIT disclosures for the date window, month-by-month, honouring a
//!    polite gap between calls.
//! 3. Keeps only **major-insider market purchases** of equity:
//!    personCategory in {Promoters, Promoter Group, Director, KMP},
//!    acqMode == "Market Purchase", secType == "Equity Shares".
//! 4. Prints the BUYERS per symbol and writes JSON to
//!    `backtesting/data/insider_buyers.json`.
//!
//! Point-in-time note: the event time is the **disclosure date** (`date`), not
//! the trade date (`acqfromDt`). Using the trade date is look-ahead.
//!
//! NOTE: the NSE feed is **stale** for the most recent 2–3 months (verified
//! 2026-10-13: last populated month ≈ Apr/May 2026). Widen `--days` to reach data.
//!
//! Usage:
//!   insider_buyers                 # pool file, last 365 days
//!   insider_buyers --days 550
//!   insider_buyers RELIANCE TCS INFY   # explicit pool, no file
//!   insider_buyers --all           # every symbol in the window (no pool filter)

use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::time::Duration;

use anyhow::{Context, Result};
use chrono::{Datelike, Duration as ChronoDuration, Local, NaiveDate};
use serde::Deserialize;
use tokio::time::sleep;

const API: &str = "https://www.nseindia.com/api/corporates-pit";
const REFERER: &str =
    "https://www.nseindia.com/companies-listing/corporate-filings-insider-trading";
const USER_AGENT: &str = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36";
const UNIVERSE: &str = "backtesting/data/insider_universe.txt";
const OUT_JSON: &str = "backtesting/data/insider_buyers.json";

/// Min gap between monthly calls (NSE tolerated 8 back-to-back, but be polite).
const REQUEST_GAP: Duration = Duration::from_secs(6);

#[derive(Deserialize, Debug)]
struct Envelope {
    #[serde(default)]
    data: Vec<Record>,
}

/// Every string field is `Option<String>` because the NSE feed puts `null` in
/// some records; a plain `String` would fail the WHOLE month's parse. `default`
/// alone does not help — it covers a *missing* field, not an explicit `null`.
#[derive(Deserialize, Debug)]
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
    #[serde(rename = "intimDt", default)]
    intim_dt: Option<String>,
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
    fn buyer(&self) -> &str {
        self.acq_name.as_deref().unwrap_or("")
    }
    fn role(&self) -> &str {
        self.person_category.as_deref().unwrap_or("")
    }
    fn trade_date(&self) -> &str {
        self.from_dt.as_deref().unwrap_or("")
    }
    fn disc_date(&self) -> &str {
        self.date.as_deref().unwrap_or("")
    }

    /// A "big party" market BUY of equity by a promoter/director/KMP.
    fn is_major_buy(&self) -> bool {
        let sec_type = self.sec_type.as_deref().unwrap_or("");
        matches!(
            self.role(),
            "Promoters" | "Promoter Group" | "Director" | "Key Managerial Personnel"
        ) && self.acq_mode.as_deref().unwrap_or("") == "Market Purchase"
            && self.txn.as_deref().unwrap_or("") == "Buy"
            && (sec_type.is_empty() || sec_type == "Equity Shares")
    }

    fn value(&self) -> f64 {
        as_f64(&self.sec_val)
    }

    fn qty(&self) -> f64 {
        as_f64(&self.sec_acq)
    }
}

fn as_f64(v: &serde_json::Value) -> f64 {
    match v {
        serde_json::Value::Number(n) => n.as_f64().unwrap_or(0.0),
        serde_json::Value::String(s) => s.replace(',', "").parse().unwrap_or(0.0),
        _ => 0.0,
    }
}

fn read_pool() -> Vec<String> {
    fs::read_to_string(UNIVERSE)
        .unwrap_or_default()
        .lines()
        .map(|l| l.trim())
        .filter(|l| !l.is_empty() && !l.starts_with('#'))
        .map(|l| l.to_uppercase())
        .collect()
}

/// Fetch one calendar month of PIT disclosures.
async fn fetch_month(
    http: &reqwest::Client,
    from: NaiveDate,
    to: NaiveDate,
) -> Result<Vec<Record>> {
    let url = format!(
        "{API}?index=equities&from_date={}&to_date={}&symbol=",
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
        anyhow::bail!("HTTP {} for {}", resp.status(), url);
    }
    let env: Envelope = resp.json().await.context("parsing PIT JSON")?;
    Ok(env.data)
}

/// Walk the window month-by-month (NSE caps the payload per call).
async fn fetch_window(
    http: &reqwest::Client,
    start: NaiveDate,
    end: NaiveDate,
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
                eprintln!("  {} .. {} -> {} rows", from, to, recs.len());
                all.append(&mut recs);
            }
            Err(e) => eprintln!("  WARN {from}..{to}: {e}"),
        }
        cursor = next_month;
        sleep(REQUEST_GAP).await;
    }
    Ok(all)
}

#[tokio::main]
async fn main() -> Result<()> {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let all = args.iter().any(|a| a == "--all");
    let days: i64 = args
        .iter()
        .position(|a| a == "--days")
        .and_then(|i| args.get(i + 1))
        .and_then(|s| s.parse().ok())
        .unwrap_or(365);

    let pool: Vec<String> = {
        let explicit: Vec<String> = args
            .iter()
            .filter(|a| !a.starts_with('-') && a.chars().any(|c| c.is_ascii_alphabetic()))
            .map(|s| s.to_uppercase())
            .collect();
        if !explicit.is_empty() {
            explicit
        } else {
            read_pool()
        }
    };

    let end = Local::now().date_naive();
    let start = end - ChronoDuration::days(days);
    let http = reqwest::Client::builder()
        .timeout(Duration::from_secs(40))
        .user_agent(USER_AGENT)
        .build()?;

    println!(
        "Insider buyers — window {start}..{end}  ({days} days)  pool: {}{}",
        if all {
            "(ALL symbols)".to_string()
        } else {
            format!("{} names", pool.len())
        },
        if all || pool.is_empty() {
            String::new()
        } else {
            format!("  {}", pool.join(","))
        }
    );

    let records = fetch_window(&http, start, end).await?;
    println!("fetched {} disclosures total", records.len());

    let pool_set: BTreeSet<String> = pool.iter().cloned().collect();
    let buyers: Vec<&Record> = records
        .iter()
        .filter(|r| r.is_major_buy())
        .filter(|r| all || pool_set.is_empty() || pool_set.contains(&r.sym().to_uppercase()))
        .collect();

    let mut by_symbol: BTreeMap<String, Vec<&Record>> = BTreeMap::new();
    for r in &buyers {
        by_symbol.entry(r.sym().to_string()).or_default().push(r);
    }

    println!(
        "\nMAJOR-INSIDER MARKET PURCHASES ({} events, {} symbols):\n",
        buyers.len(),
        by_symbol.len()
    );
    println!(
        "{:<12} {:<14} {:<26} {:>10} {:>14} {:>12}",
        "SYMBOL", "TRADE DATE", "BUYER / ROLE", "QTY", "VALUE (Rs)", "DISC DATE"
    );
    println!("{}", "-".repeat(96));
    for (sym, recs) in &by_symbol {
        let total: f64 = recs.iter().map(|r| r.value()).sum();
        for r in recs {
            println!(
                "{:<12} {:<14} {:<26} {:>10.0} {:>14.0} {:>12}",
                sym,
                r.trade_date(),
                format!("{} ({})", truncate(r.buyer(), 16), short_role(r.role())),
                r.qty(),
                r.value(),
                r.disc_date().split_whitespace().next().unwrap_or("")
            );
        }
        println!("   {sym}: {} buy(s), Rs {total:.0} total\n", recs.len());
    }

    let json: Vec<serde_json::Value> = buyers
        .iter()
        .map(|r| {
            serde_json::json!({
                "symbol": r.sym(),
                "disclosure_date": r.disc_date(),
                "trade_date": r.trade_date(),
                "intimation_date": r.intim_dt.as_deref().unwrap_or(""),
                "buyer": r.buyer(),
                "role": r.role(),
                "mode": r.acq_mode.as_deref().unwrap_or(""),
                "qty": r.qty(),
                "value_inr": r.value(),
            })
        })
        .collect();
    let out = serde_json::json!({
        "generated": end.to_string(),
        "window_days": days,
        "pool_size": if all { 0 } else { pool.len() },
        "events": json,
    });
    if let Err(e) = fs::write(
        OUT_JSON,
        serde_json::to_string_pretty(&out).unwrap_or_default(),
    ) {
        eprintln!("WARN: could not write {OUT_JSON}: {e}");
    } else {
        println!("JSON -> {OUT_JSON}");
    }

    println!(
        "NOTE: read-only. Event time = disclosure date, not trade date. Feed is stale for recent months."
    );
    Ok(())
}

fn short_role(cat: &str) -> &str {
    match cat {
        "Promoters" => "promoter",
        "Promoter Group" => "promoter-grp",
        "Director" => "director",
        "Key Managerial Personnel" => "KMP",
        "Employees/Designated Employees" => "employee",
        other => other,
    }
}

fn truncate(s: &str, n: usize) -> String {
    if s.chars().count() <= n {
        s.to_string()
    } else {
        s.chars().take(n).collect::<String>() + "..."
    }
}
