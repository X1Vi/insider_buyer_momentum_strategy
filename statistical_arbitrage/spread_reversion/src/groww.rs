use std::sync::Arc;
use std::sync::atomic::{AtomicBool, Ordering};
use std::time::{Duration, Instant};

use chrono::{NaiveDate, TimeZone, Utc};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use tokio::sync::Mutex;
use tokio::time::sleep;
use tracing::{debug, info};

use crate::insider::Bar;

const BASE: &str = "https://api.groww.in/v1";

/// Read-only Groww market-data client. The shared limiter deliberately leaves
/// six seconds between historical requests; cached callers should normally pay
/// this cost only once per symbol/range.
#[derive(Clone)]
pub struct Client {
    http: reqwest::Client,
    token: String,
    last_history_request: Arc<Mutex<Option<Instant>>>,
    auth_failed: Arc<AtomicBool>,
}

const HISTORY_GAP: Duration = Duration::from_secs(6);

impl Client {
    pub fn new(token: &str) -> Self {
        Self {
            http: reqwest::Client::builder()
                .timeout(Duration::from_secs(45))
                .build()
                .expect("static Groww HTTP config"),
            token: token.to_string(),
            last_history_request: Arc::new(Mutex::new(None)),
            auth_failed: Arc::new(AtomicBool::new(false)),
        }
    }

    /// Generate an access token via the Groww API key/secret checksum flow.
    /// See https://groww.in/trade-api/docs/curl — requires an API key/secret
    /// created (and daily-approved) on the Groww Cloud API Keys page.
    /// Set GROWW_API_KEY and GROWW_API_SECRET env vars.
    pub async fn login_with_api_key(api_key: &str, api_secret: &str) -> anyhow::Result<String> {
        let timestamp = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)?
            .as_secs()
            .to_string();
        let checksum = sha256_hex(&format!("{api_secret}{timestamp}"));

        let body = AccessRequest {
            key_type: "approval".to_string(),
            checksum,
            timestamp,
        };

        let resp = reqwest::Client::new()
            .post(format!("{BASE}/token/api/access"))
            .header("Accept", "application/json")
            .header("Authorization", format!("Bearer {api_key}"))
            .json(&body)
            .send()
            .await?;

        if !resp.status().is_success() {
            let status = resp.status();
            let text = resp.text().await.unwrap_or_default();
            anyhow::bail!("token request failed (HTTP {status}): {text}");
        }

        let access: AccessResponse = resp.json().await?;
        info!(
            expiry = access.expiry.as_deref().unwrap_or("unknown"),
            "access token obtained"
        );
        Ok(access.token)
    }

    /// Fetch the latest traded price for a trading symbol on NSE CASH segment.
    /// Returns the last price as f64, or an error on network/parse failure.
    pub async fn quote(&self, trading_symbol: &str) -> anyhow::Result<f64> {
        let url = format!(
            "{BASE}/live-data/quote?exchange=NSE&segment=CASH&trading_symbol={trading_symbol}"
        );
        debug!("GET {url}");

        let resp = self
            .http
            .get(&url)
            .header("Accept", "application/json")
            .header("Authorization", format!("Bearer {}", self.token))
            .header("X-API-VERSION", "1.0")
            .send()
            .await?;

        if !resp.status().is_success() {
            let status = resp.status();
            let body = resp.text().await.unwrap_or_default();
            anyhow::bail!("HTTP {status} from quote endpoint: {body}");
        }

        let envelope: QuoteEnvelope = resp.json().await?;
        if envelope.status != "SUCCESS" {
            anyhow::bail!(
                "quote request for {trading_symbol} returned status {}",
                envelope.status
            );
        }
        envelope
            .payload
            .and_then(|p| p.last_price)
            .ok_or_else(|| anyhow::anyhow!("no last_price in quote for {trading_symbol}"))
    }

    /// Fetch one daily-candle page. Groww documents a maximum duration of
    /// 1,080 days for the 1-day interval, so range pagination belongs in the
    /// caller. No portfolio or order endpoint is used.
    pub async fn historical_daily(
        &self,
        trading_symbol: &str,
        start: NaiveDate,
        end: NaiveDate,
    ) -> anyhow::Result<Vec<Bar>> {
        if self.auth_failed.load(Ordering::Relaxed) {
            anyhow::bail!("Groww access token was rejected earlier in this process");
        }
        self.wait_for_history_slot().await;

        let url = format!("{BASE}/historical/candles");
        debug!(symbol = trading_symbol, %start, %end, "GET Groww daily candles");
        let resp = self
            .http
            .get(&url)
            .header("Accept", "application/json")
            .header("Authorization", format!("Bearer {}", self.token))
            .header("X-API-VERSION", "1.0")
            .query(&[
                ("exchange", "NSE".to_string()),
                ("segment", "CASH".to_string()),
                ("groww_symbol", format!("NSE-{trading_symbol}")),
                ("start_time", format!("{start} 00:00:00")),
                ("end_time", format!("{end} 23:59:59")),
                ("candle_interval", "1day".to_string()),
            ])
            .send()
            .await?;

        if !resp.status().is_success() {
            let status = resp.status();
            let body = resp.text().await.unwrap_or_default();
            if status == reqwest::StatusCode::UNAUTHORIZED {
                self.auth_failed.store(true, Ordering::Relaxed);
            }
            anyhow::bail!("Groww history HTTP {status} for {trading_symbol}: {body}");
        }
        let envelope: CandleEnvelope = resp.json().await?;
        if envelope.status != "SUCCESS" {
            anyhow::bail!(
                "Groww history for {trading_symbol} returned status {}",
                envelope.status
            );
        }

        let mut bars = Vec::new();
        for candle in envelope.payload.and_then(|p| p.candles).unwrap_or_default() {
            if candle.len() < 6 {
                continue;
            }
            let Some(date) = candle_date(&candle[0]) else {
                continue;
            };
            let number = |index: usize| candle[index].as_f64().unwrap_or(0.0);
            let (open, high, low, close, volume) =
                (number(1), number(2), number(3), number(4), number(5));
            if close.is_finite() && close > 0.0 {
                bars.push(Bar {
                    date,
                    open: if open > 0.0 { open } else { close },
                    high: if high > 0.0 { high } else { close },
                    low: if low > 0.0 { low } else { close },
                    close,
                    volume: if volume.is_finite() && volume >= 0.0 {
                        volume
                    } else {
                        0.0
                    },
                });
            }
        }
        bars.sort_by_key(|bar| bar.date);
        bars.dedup_by_key(|bar| bar.date);
        Ok(bars)
    }

    async fn wait_for_history_slot(&self) {
        let mut last = self.last_history_request.lock().await;
        if let Some(previous) = *last {
            let elapsed = previous.elapsed();
            if elapsed < HISTORY_GAP {
                sleep(HISTORY_GAP - elapsed).await;
            }
        }
        *last = Some(Instant::now());
    }
}

fn candle_date(value: &serde_json::Value) -> Option<NaiveDate> {
    if let Some(epoch) = value.as_i64() {
        return Utc
            .timestamp_opt(epoch, 0)
            .single()
            .map(|dt| dt.date_naive());
    }
    let raw = value.as_str()?;
    raw.get(..10)
        .and_then(|date| NaiveDate::parse_from_str(date, "%Y-%m-%d").ok())
}

fn sha256_hex(input: &str) -> String {
    let hash = Sha256::digest(input.as_bytes());
    hash.iter().map(|b| format!("{b:02x}")).collect()
}

#[derive(Debug, Serialize)]
struct AccessRequest {
    key_type: String,
    checksum: String,
    timestamp: String,
}

#[derive(Debug, Deserialize)]
struct AccessResponse {
    token: String,
    expiry: Option<String>,
}

#[derive(Debug, Deserialize)]
struct QuoteEnvelope {
    status: String,
    payload: Option<QuotePayload>,
}

#[derive(Debug, Deserialize)]
struct QuotePayload {
    last_price: Option<f64>,
    #[allow(dead_code)]
    bid_price: Option<f64>,
    #[allow(dead_code)]
    offer_price: Option<f64>,
    #[allow(dead_code)]
    volume: Option<f64>,
    #[allow(dead_code)]
    day_change: Option<f64>,
    #[allow(dead_code)]
    day_change_perc: Option<f64>,
}

#[derive(Debug, Deserialize)]
struct CandleEnvelope {
    status: String,
    payload: Option<CandlePayload>,
}

#[derive(Debug, Deserialize)]
struct CandlePayload {
    candles: Option<Vec<Vec<serde_json::Value>>>,
}

#[cfg(test)]
mod tests {
    use super::candle_date;
    use chrono::NaiveDate;
    use serde_json::json;

    #[test]
    fn candle_dates_accept_epoch_and_documented_text_shape() {
        assert_eq!(
            candle_date(&json!(1_763_078_400)),
            NaiveDate::from_ymd_opt(2025, 11, 14)
        );
        assert_eq!(
            candle_date(&json!("2025-09-24 15:30:00")),
            NaiveDate::from_ymd_opt(2025, 9, 24)
        );
    }
}
