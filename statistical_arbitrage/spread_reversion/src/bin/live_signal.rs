//! Minimal live buy/sell signal — HDFCBANK vs KOTAKBANK gap (Groww live quotes).
//!
//! spread = ln(HDFC) − 1.1622·ln(KOTAK) + 0.2189 ; rolling-60 z-score.
//! |z| ≥ 3  ->  BUY the LAGGARD (long-only) with precomputed margin.
//! Exit when z reverts to 0 / stop |z| ≥ 4.5 / 5 polls held.
//! NO ORDERS ARE PLACED — signals only.
//!
//! Logging: structured (tracing) to live_signal.log; falls back to stdout if the
//! filesystem is read-only (e.g. Groww sandbox). Every failure is logged.
//!
//! Usage:
//!   live_signal                  # live (GROWW_ACCESS_TOKEN or GROWW_API_KEY/SECRET)
//!   live_signal --sim file.csv   # replay recorded data fast (verify logic)

use std::collections::VecDeque;
use std::time::Duration;

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use tracing::{error, info, warn};
use tracing_appender::non_blocking::WorkerGuard;

const BASE: &str = "https://api.groww.in/v1";
const BETA: f64 = 1.1622;
const ALPHA: f64 = -0.2189;
const WINDOW: usize = 60;
const Z_ENTER: f64 = 3.0;
const Z_EXIT: f64 = 0.0;
const Z_STOP: f64 = 4.5;
const CAPITAL: f64 = 15_000.0;
const FEES: f64 = 35.0;
const FOLLOW_RS_PER_UNIT: f64 = 9.0;
const POLL_SECS: u64 = 3;
const LOG_PATH: &str = "live_signal.log";

fn spread(pa: f64, pb: f64) -> f64 {
    pa.ln() - BETA * pb.ln() - ALPHA
}

/// Structured logging to file; falls back to stdout on read-only filesystems
/// (Groww sandbox) so logging NEVER silently fails.
fn init_logging() -> anyhow::Result<WorkerGuard> {
    let (writer, guard) = match std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(LOG_PATH)
    {
        Ok(f) => tracing_appender::non_blocking(f),
        Err(e) => {
            eprintln!("WARN: cannot open {LOG_PATH} ({e}) — logging to stdout");
            tracing_appender::non_blocking(std::io::stdout())
        }
    };
    tracing_subscriber::fmt()
        .with_env_filter("live_signal=info")
        .with_target(false)
        .with_writer(writer)
        .init();
    Ok(guard)
}

// ---------------------------------------------------------------- groww client

struct Client {
    http: reqwest::Client,
    token: String,
}

impl Client {
    fn new(token: &str) -> Self {
        Self {
            http: reqwest::Client::new(),
            token: token.to_string(),
        }
    }

    async fn quote(&self, symbol: &str) -> anyhow::Result<f64> {
        let url =
            format!("{BASE}/live-data/quote?exchange=NSE&segment=CASH&trading_symbol={symbol}");
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
            anyhow::bail!("auth HTTP {}", resp.status());
        }
        Ok(resp.json::<Res>().await?.token)
    }
}

async fn fetch_token() -> anyhow::Result<String> {
    if let Ok(t) = std::env::var("GROWW_ACCESS_TOKEN") {
        let t = t.trim().trim_matches('"').trim_matches('\'').trim();
        if !t.is_empty() {
            info!("using GROWW_ACCESS_TOKEN from environment");
            return Ok(t.to_string());
        }
    }
    let k = std::env::var("GROWW_API_KEY")
        .map_err(|_| anyhow::anyhow!("set GROWW_ACCESS_TOKEN or GROWW_API_KEY/GROWW_API_SECRET"))?;
    let s = std::env::var("GROWW_API_SECRET")
        .map_err(|_| anyhow::anyhow!("set GROWW_ACCESS_TOKEN or GROWW_API_KEY/GROWW_API_SECRET"))?;
    info!("generating access token via API key/secret checksum flow");
    Client::login(&k, &s).await
}

// ---------------------------------------------------------------- signal engine

struct Engine {
    hist: VecDeque<f64>,
    state: &'static str,
    entry_z: f64,
    held: usize,
}

impl Engine {
    fn new() -> Self {
        Self {
            hist: VecDeque::with_capacity(WINDOW),
            state: "FLAT",
            entry_z: 0.0,
            held: 0,
        }
    }

    fn on_tick(&mut self, pa: f64, pb: f64, label: &str) {
        let s = spread(pa, pb);
        self.hist.push_back(s);
        if self.hist.len() > WINDOW {
            self.hist.pop_front();
        }
        if self.hist.len() < WINDOW {
            info!(tick = label, n = self.hist.len(), window = WINDOW, "warmup");
            return;
        }
        let mean = self.hist.iter().sum::<f64>() / self.hist.len() as f64;
        let var = self.hist.iter().map(|x| (x - mean).powi(2)).sum::<f64>()
            / (self.hist.len() - 1) as f64;
        let z = (s - mean) / var.sqrt().max(1e-6);

        match self.state {
            "FLAT" => {
                if z.abs() >= Z_ENTER {
                    let (lag, px) = if z > 0.0 {
                        ("KOTAKBANK", pb)
                    } else {
                        ("HDFCBANK", pa)
                    };
                    let qty = (CAPITAL / px).max(1.0) as u64;
                    let net = FOLLOW_RS_PER_UNIT * qty as f64 - FEES;
                    let conf = ((z.abs() - Z_ENTER) / (Z_STOP - Z_ENTER) * 100.0).clamp(0.0, 100.0);
                    info!(
                        symbol = lag,
                        qty,
                        price = format!("{px:.2}"),
                        net = format!("{net:.0}"),
                        conf = format!("{conf:.0}"),
                        z = format!("{z:+.2}"),
                        "BUY signal"
                    );
                    println!(
                        "\n  >>> BUY {lag}  qty={qty} @ ₹{px:.2}  |  est net ₹{net:.0} (fees ₹{FEES})  |  conf {conf:.0}%  |  z={z:+.2}\n"
                    );
                    self.state = "POSITION";
                    self.entry_z = z;
                    self.held = 0;
                } else {
                    info!(tick = label, z = format!("{z:+.2}"), "flat");
                }
            }
            "POSITION" => {
                self.held += 1;
                let exit = if self.entry_z > 0.0 {
                    z <= Z_EXIT
                } else {
                    z >= Z_EXIT
                };
                if exit || z.abs() >= Z_STOP || self.held >= 5 {
                    let why = if z.abs() >= Z_STOP {
                        "STOP"
                    } else {
                        "reverted"
                    };
                    info!(
                        tick = label,
                        z = format!("{z:+.2}"),
                        reason = why,
                        held = self.held,
                        "SELL signal"
                    );
                    println!("\n  >>> SELL  z={z:+.2} ({why}) held {}\n", self.held);
                    self.state = "FLAT";
                } else {
                    info!(
                        tick = label,
                        z = format!("{z:+.2}"),
                        held = self.held,
                        "holding"
                    );
                }
            }
            _ => {}
        }
    }
}

fn read_pairs(path: &str) -> anyhow::Result<Vec<(f64, f64)>> {
    let txt = std::fs::read_to_string(path)?;
    let mut out = Vec::new();
    for line in txt.lines() {
        let p: Vec<&str> = line.split(',').collect();
        if p.len() < 3 {
            continue;
        }
        let pa: f64 = match p[p.len() - 2].trim().parse() {
            Ok(v) => v,
            Err(_) => continue,
        };
        let pb: f64 = match p[p.len() - 1].trim().parse() {
            Ok(v) => v,
            Err(_) => continue,
        };
        if pa > 0.0 && pb > 0.0 {
            out.push((pa, pb));
        }
    }
    if out.is_empty() {
        anyhow::bail!("no data in {path}");
    }
    Ok(out)
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    let _guard = init_logging()?;
    let args: Vec<String> = std::env::args().skip(1).collect();
    let mut eng = Engine::new();

    // ---- sim mode (no token) ----
    if let Some(i) = args.iter().position(|a| a == "--sim") {
        let path = args
            .get(i + 1)
            .cloned()
            .unwrap_or_else(|| "backtesting/hdfc_ktak_5m.csv".to_string());
        let data = match read_pairs(&path) {
            Ok(d) => d,
            Err(e) => {
                error!(error = %e, "failed to read sim data");
                eprintln!("ERROR: cannot read {path}: {e}");
                std::process::exit(1);
            }
        };
        info!(mode = "sim", bars = data.len(), path = %path, "started");
        println!("=== SIM replay {path} ({} bars) ===", data.len());
        for (n, (pa, pb)) in data.iter().enumerate() {
            eng.on_tick(*pa, *pb, &format!("t{n}"));
        }
        info!("sim complete");
        return Ok(());
    }

    // ---- live mode ----
    dotenvy::dotenv().ok();
    let token = match fetch_token().await {
        Ok(t) => t,
        Err(e) => {
            error!(error = %e, "authentication failed");
            eprintln!("FATAL: auth failed — {e}");
            std::process::exit(1);
        }
    };
    let c = Client::new(&token);
    info!(
        poll_secs = POLL_SECS,
        pair = "HDFCBANK/KOTAKBANK",
        "started live"
    );
    println!("=== LIVE HDFCBANK vs KOTAKBANK  (poll every {POLL_SECS}s) ===");

    loop {
        let pa = match c.quote("HDFCBANK").await {
            Ok(v) => v,
            Err(e) => {
                warn!(symbol = "HDFCBANK", error = %e, "quote failed — retrying");
                eprintln!("[err] HDFCBANK: {e}");
                tokio::time::sleep(Duration::from_secs(POLL_SECS)).await;
                continue;
            }
        };
        let pb = match c.quote("KOTAKBANK").await {
            Ok(v) => v,
            Err(e) => {
                warn!(symbol = "KOTAKBANK", error = %e, "quote failed — retrying");
                eprintln!("[err] KOTAKBANK: {e}");
                tokio::time::sleep(Duration::from_secs(POLL_SECS)).await;
                continue;
            }
        };
        let label = chrono::Local::now().format("%H:%M:%S").to_string();
        eng.on_tick(pa, pb, &label);
        tokio::time::sleep(Duration::from_secs(POLL_SECS)).await;
    }
}
