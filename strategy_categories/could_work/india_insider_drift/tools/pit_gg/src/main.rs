//! pit_gg — fetch RECENT NSE insider (PIT) filings.
//!
//! Why this exists: the old endpoint `/api/corporates-pit` was retired on
//! 2026-04-30 (the XBRL says "PIT V2.0 (30-04-2026)") and now returns 0 rows for
//! recent months. NSE's live list is `/api/corporates-pit-gg`, which returns
//! filing METADATA; the trade numbers live inside each filing's XBRL/XML.
//!
//! This tool: list `-gg` filings for the window -> fetch each XBRL -> parse the
//! `in-bse-co:*` fields -> print the recent insider BUYS (and write a CSV).
//!
//! Self-contained (its own crate). Read-only; reads public NSE links only.
//!
//! Usage:  pit_gg [DAYS] [LIMIT]
//!         defaults: 30      200     (LIMIT caps XBRL fetches; 0 = no cap)

use std::fs;
use std::thread::sleep;
use std::time::Duration;

use chrono::{Duration as ChronoDuration, Local};
use serde::Deserialize;

const LIST_API: &str = "https://www.nseindia.com/api/corporates-pit-gg";
const REFERER: &str =
    "https://www.nseindia.com/companies-listing/corporate-filings-insider-trading";
const UA: &str = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36";
const GAP: Duration = Duration::from_millis(300);
const CSV: &str = "pit_gg_recent.csv";

#[derive(Deserialize, Debug)]
struct Envelope {
    #[serde(default)]
    data: Vec<Filing>,
}

#[derive(Deserialize, Debug)]
struct Filing {
    #[serde(rename = "appId", default)]
    app_id: Option<String>,
    #[serde(default)]
    symbol: Option<String>,
    #[serde(rename = "companyName", default)]
    company: Option<String>,
    #[serde(rename = "broadcastDateTime", default)]
    broadcast: Option<String>,
    #[serde(default)]
    regulation: Option<String>,
    #[serde(rename = "typeOfSubmission", default)]
    submission: Option<String>,
    #[serde(rename = "xmlFileName", default)]
    xml: Option<String>,
}

#[derive(Debug, Clone)]
struct Trade {
    symbol: String,
    company: String,
    person: String,
    category: String,
    txn: String,
    qty: String,
    value: String,
    mode: String,
    trade_from: String,
    trade_to: String,
    intimation: String,
    broadcast: String,
    regulation: String,
}

fn extract(xml: &str, tag: &str) -> String {
    // pull <in-bse-co:TAG ...>VALUE</in-bse-co:TAG> (first occurrence)
    let open = format!("<in-bse-co:{tag}");
    let close = format!("</in-bse-co:{tag}>");
    let Some(i) = xml.find(&open) else {
        return String::new();
    };
    let rest = &xml[i..];
    let Some(gt) = rest.find('>') else { return String::new() };
    let after = &rest[gt + 1..];
    match after.find(&close) {
        Some(j) => after[..j].trim().to_string(),
        None => String::new(),
    }
}

fn parse_value(s: &str) -> Option<f64> {
    let cleaned: String = s.chars().filter(|c| c.is_ascii_digit() || *c == '.' || *c == '-').collect();
    cleaned.parse::<f64>().ok()
}

fn main() -> anyhow::Result<()> {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let days: i64 = args.first().and_then(|s| s.parse().ok()).unwrap_or(30);
    let limit: usize = args.get(1).and_then(|s| s.parse().ok()).unwrap_or(200);

    let http = reqwest::blocking::Client::builder()
        .timeout(Duration::from_secs(40))
        .user_agent(UA)
        .build()?;

    let end = Local::now().date_naive();
    let start = end - ChronoDuration::days(days);
    let list_url = format!(
        "{LIST_API}?index=equities&from_date={}&to_date={}&symbol=",
        start.format("%d-%m-%Y"),
        end.format("%d-%m-%Y")
    );
    println!("pit_gg — {start}..{end} ({days}d), cap {limit} XBRL fetches\n");
    eprintln!("listing filings from the -gg endpoint…");

    let env: Envelope = http
        .get(&list_url)
        .header("Accept", "application/json")
        .header("Referer", REFERER)
        .send()?
        .error_for_status()?
        .json()?;
    let filings = env.data;
    println!("filings listed: {}", filings.len());

    let cap = if limit == 0 { filings.len() } else { limit.min(filings.len()) };
    let mut trades: Vec<Trade> = Vec::new();
    let mut buys = 0usize;

    for (i, f) in filings.iter().take(cap).enumerate() {
        let Some(url) = f.xml.clone().filter(|u| !u.is_empty()) else {
            continue;
        };
        let xml = match http
            .get(&url)
            .header("Referer", REFERER)
            .send()
            .and_then(|r| r.error_for_status())
            .and_then(|r| r.text())
        {
            Ok(t) => t,
            Err(e) => {
                eprintln!("  WARN filing {}: {e}", f.app_id.as_deref().unwrap_or("?"));
                continue;
            }
        };
        let txn = extract(&xml, "SecuritiesAcquiredOrDisposedTransactionType");
        let person = extract(&xml, "NameOfThePerson");
        if person.is_empty() && txn.is_empty() {
            continue; // not a standard PIT-2 disclosure
        }
        let t = Trade {
            symbol: f.symbol.clone().unwrap_or_default(),
            company: f.company.clone().unwrap_or_default(),
            person,
            category: extract(&xml, "CategoryOfPerson"),
            txn: txn.clone(),
            qty: extract(&xml, "SecuritiesAcquiredOrDisposedNumberOfSecurity"),
            value: extract(&xml, "SecuritiesAcquiredOrDisposedValueOfSecurity"),
            mode: extract(&xml, "ModeOfAcquisitionOrDisposal"),
            trade_from: extract(&xml, "DateOfAllotmentAdviceOrAcquisitionOfSharesOrSaleOfSharesSpecifyFromDate"),
            trade_to: extract(&xml, "DateOfAllotmentAdviceOrAcquisitionOfSharesOrSaleOfSharesSpecifyToDate"),
            intimation: extract(&xml, "DateOfIntimationToCompany"),
            broadcast: f.broadcast.clone().unwrap_or_default(),
            regulation: f.regulation.clone().unwrap_or_default(),
        };
        if t.txn.eq_ignore_ascii_case("buy") {
            buys += 1;
        }
        trades.push(t);

        if (i + 1) % 50 == 0 {
            eprintln!("  parsed {}/{} filings ({} buys so far)", i + 1, cap, buys);
        }
        sleep(GAP);
    }

    // keep buys >= Rs 25 lakh, most recent first
    let mut big_buys: Vec<&Trade> = trades
        .iter()
        .filter(|t| t.txn.eq_ignore_ascii_case("buy"))
        .filter(|t| parse_value(&t.value).map_or(false, |v| v >= 2_500_000.0))
        .collect();
    big_buys.sort_by(|a, b| b.broadcast.cmp(&a.broadcast));

    println!(
        "\nparsed {} filings: {} buys, {} sells; {} buys >= Rs 25L\n",
        trades.len(),
        trades.iter().filter(|t| t.txn.eq_ignore_ascii_case("buy")).count(),
        trades.iter().filter(|t| t.txn.eq_ignore_ascii_case("sell")).count(),
        big_buys.len()
    );

    println!(
        "{:<12}{:<12}{:<20}{:<10}{:>12}{:>14}{:>14}",
        "SYMBOL", "CATEGORY", "PERSON", "MODE", "QTY", "VALUE(Rs)", "TRADE"
    );
    println!("{}", "-".repeat(96));
    for t in &big_buys {
        println!(
            "{:<12}{:<12}{:<20}{:<10}{:>12}{:>14}{:>14}",
            trunc(&t.symbol, 11),
            trunc(&t.category, 11),
            trunc(&t.person, 19),
            trunc(&t.mode, 9),
            t.qty,
            parse_value(&t.value).map(|v| format!("{v:.0}")).unwrap_or_default(),
            trunc(&t.trade_from, 13),
        );
    }

    // CSV
    let mut csv = String::from(
        "symbol,company,person,category,type,qty,value,mode,trade_from,trade_to,intimation,broadcast,regulation\n",
    );
    for t in &trades {
        let esc = |s: &str| s.replace(',', " ");
        csv.push_str(&format!(
            "{},{},{},{},{},{},{},{},{},{},{},{},{}\n",
            esc(&t.symbol), esc(&t.company), esc(&t.person), esc(&t.category),
            esc(&t.txn), esc(&t.qty), esc(&t.value), esc(&t.mode),
            esc(&t.trade_from), esc(&t.trade_to), esc(&t.intimation),
            esc(&t.broadcast), esc(&t.regulation),
        ));
    }
    fs::write(CSV, csv)?;
    println!("\nwrote {CSV} ({} rows)", trades.len());
    println!("NOTE: this is the LIVE source; the retired /corporates-pit endpoint had nothing after 2026-04-30.");
    Ok(())
}

fn trunc(s: &str, n: usize) -> String {
    if s.chars().count() <= n {
        s.to_string()
    } else {
        s.chars().take(n).collect::<String>()
    }
}
