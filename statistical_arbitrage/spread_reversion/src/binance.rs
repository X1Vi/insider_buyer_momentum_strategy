//! Binance public REST client — daily klines only, no authentication.
//!
//! Scope is deliberately tiny: this module can fetch public candles and nothing
//! else. There is no signing code, no API key handling and no order endpoint,
//! so it cannot place a trade even by accident. That matches the paper-only
//! mandate in AGENTS.md.
//!
//! Two things here are load-bearing and easy to get wrong:
//!
//! 1. **The last kline Binance returns is the bar still forming.** Its
//!    `close_time` is in the future. Acting on it is a repaint bug: the signal
//!    you see at 08:00 UTC can vanish by the close. The previous Hummingbot
//!    port did exactly this. [`Kline::is_closed`] and
//!    [`Client::daily_closed`] exist so that mistake cannot be repeated.
//!
//! 2. **`limit` is capped at 1000**, whatever you ask for. Requesting 1500
//!    silently returns 1000, which is only ~2.7 years of daily bars — not
//!    enough to warm up an EMA200 *and* leave a meaningful backtest. Longer
//!    histories therefore have to be paged with `startTime`.

use std::time::Duration;

use anyhow::{Context, Result, bail};
use serde::Deserialize;
use tracing::{debug, warn};

const BASE_URL: &str = "https://api.binance.com";

/// Binance caps daily klines at this many per request regardless of `limit`.
const MAX_LIMIT: usize = 1000;

/// Minimum gap between requests. AGENTS.md mandates a 5-second floor for the
/// Groww endpoints; Binance's public limits are far looser, but pacing keeps us
/// well inside them while paging and costs nothing on a once-a-day job.
const MIN_REQUEST_GAP: Duration = Duration::from_millis(400);

const MILLIS_PER_DAY: i64 = 86_400_000;

/// One completed (or forming) daily candle.
#[derive(Debug, Clone, PartialEq)]
pub struct Kline {
    /// Bar open time, epoch milliseconds UTC.
    pub open_time: i64,
    /// Bar close time, epoch milliseconds UTC. In the future for a forming bar.
    pub close_time: i64,
    pub open: f64,
    pub high: f64,
    pub low: f64,
    pub close: f64,
    /// Base-asset volume (e.g. BTC), matching what the strategy's volume filter
    /// was specified against.
    pub volume: f64,
    /// Quote-asset volume (e.g. USDT). Used for liquidity ranking, not signals.
    pub quote_volume: f64,
}

impl Kline {
    /// True once the bar's close time has passed, i.e. it will never change.
    pub fn is_closed(&self, now_ms: i64) -> bool {
        self.close_time <= now_ms
    }

    /// Bar date as `YYYY-MM-DD` (UTC), for logs and the trade ledger.
    pub fn date(&self) -> String {
        chrono::DateTime::from_timestamp_millis(self.open_time)
            .map(|dt| dt.format("%Y-%m-%d").to_string())
            .unwrap_or_else(|| self.open_time.to_string())
    }
}

/// Binance returns klines as arrays of mixed types, so they are parsed
/// positionally rather than by field name.
#[derive(Deserialize)]
struct RawKline(
    i64,                                   // 0 open time
    String,                                // 1 open
    String,                                // 2 high
    String,                                // 3 low
    String,                                // 4 close
    String,                                // 5 base volume
    i64,                                   // 6 close time
    String,                                // 7 quote volume
    #[allow(dead_code)] serde_json::Value, // 8 trade count
    #[allow(dead_code)] serde_json::Value, // 9 taker buy base
    #[allow(dead_code)] serde_json::Value, // 10 taker buy quote
    #[allow(dead_code)] serde_json::Value, // 11 ignored
);

impl TryFrom<RawKline> for Kline {
    type Error = anyhow::Error;

    fn try_from(raw: RawKline) -> Result<Self> {
        let parse = |field: &str, value: &str| -> Result<f64> {
            value
                .parse::<f64>()
                .with_context(|| format!("kline field `{field}` was not a number: {value:?}"))
        };
        Ok(Kline {
            open_time: raw.0,
            open: parse("open", &raw.1)?,
            high: parse("high", &raw.2)?,
            low: parse("low", &raw.3)?,
            close: parse("close", &raw.4)?,
            volume: parse("volume", &raw.5)?,
            close_time: raw.6,
            quote_volume: parse("quote_volume", &raw.7)?,
        })
    }
}

/// 24h rolling stats for one symbol — liquidity context for the screener.
#[derive(Debug, Clone)]
pub struct Ticker24h {
    pub symbol: String,
    pub last_price: f64,
    /// Quote-asset (USDT) volume over the trailing 24h.
    pub quote_volume: f64,
    pub change_pct_24h: f64,
}

pub struct Client {
    http: reqwest::Client,
    base_url: String,
}

impl Default for Client {
    fn default() -> Self {
        Self::new()
    }
}

impl Client {
    pub fn new() -> Self {
        let http = reqwest::Client::builder()
            .timeout(Duration::from_secs(20))
            .user_agent("spread_reversion-btc-bot/0.1 (paper trading, read-only)")
            .build()
            .expect("reqwest client builds with static config");
        Self {
            http,
            base_url: BASE_URL.to_string(),
        }
    }

    /// Point the client at a different host — used by tests and by anyone who
    /// needs `api.binance.us` instead of the global endpoint.
    pub fn with_base_url(mut self, base_url: impl Into<String>) -> Self {
        self.base_url = base_url.into();
        self
    }

    /// Binance server time in epoch milliseconds.
    ///
    /// Preferred over the local clock when deciding whether a bar has closed:
    /// a machine whose clock is a few minutes fast would otherwise treat the
    /// forming bar as complete.
    pub async fn server_time_ms(&self) -> Result<i64> {
        #[derive(Deserialize)]
        struct ServerTime {
            #[serde(rename = "serverTime")]
            server_time: i64,
        }
        let url = format!("{}/api/v3/time", self.base_url);
        let resp: ServerTime = self
            .http
            .get(&url)
            .send()
            .await
            .context("binance /time request failed")?
            .error_for_status()
            .context("binance /time returned an error status")?
            .json()
            .await
            .context("binance /time returned unparseable JSON")?;
        Ok(resp.server_time)
    }

    /// GET + JSON with bounded retries.
    ///
    /// Retries connect/timeout/5xx with backoff; never retries a rate-limit
    /// (418/429) or a geo-block (451), because hammering either makes things
    /// worse. A single transient failure must not kill a long-running bot.
    async fn get_json<T: serde::de::DeserializeOwned>(&self, url: &str) -> Result<T> {
        let mut backoff = Duration::from_secs(1);
        let mut last_error: Option<anyhow::Error> = None;

        for attempt in 1..=3 {
            match self.http.get(url).send().await {
                Ok(response) => {
                    let status = response.status();
                    if status.is_success() {
                        return response.json::<T>().await.context("unparseable JSON");
                    }
                    let body = response.text().await.unwrap_or_default();
                    if status.as_u16() == 429 || status.as_u16() == 418 {
                        bail!("binance rate limited this client ({status}) — back off: {body}");
                    }
                    if status.as_u16() == 451 {
                        bail!(
                            "binance returned 451 (geo-blocked). Retry against the public \
                             market-data mirror: Client::new().with_base_url(\
                             \"https://data-api.binance.vision\")"
                        );
                    }
                    if status.is_client_error() {
                        bail!("binance returned {status}: {body}");
                    }
                    last_error = Some(anyhow::anyhow!("binance returned {status}: {body}"));
                }
                Err(e) => last_error = Some(anyhow::Error::new(e)),
            }
            if attempt < 3 {
                warn!(url, attempt, "binance request failed, retrying");
                tokio::time::sleep(backoff).await;
                backoff *= 4;
            }
        }
        Err(last_error.unwrap_or_else(|| anyhow::anyhow!("binance request failed")))
    }

    /// Fetch up to `MAX_LIMIT` daily klines, optionally starting at `start_ms`.
    async fn daily_page(&self, symbol: &str, start_ms: Option<i64>) -> Result<Vec<Kline>> {
        let mut url = format!(
            "{}/api/v3/klines?symbol={}&interval=1d&limit={}",
            self.base_url, symbol, MAX_LIMIT
        );
        if let Some(start) = start_ms {
            url.push_str(&format!("&startTime={start}"));
        }

        let raw: Vec<RawKline> = self
            .get_json(&url)
            .await
            .with_context(|| format!("klines request failed for {symbol}"))?;
        raw.into_iter().map(Kline::try_from).collect()
    }

    /// Fetch **closed** daily klines, newest last, paging back far enough to
    /// cover `min_bars`.
    ///
    /// The forming bar is dropped here rather than by the caller, so no
    /// downstream code has to remember to do it. `now_ms` comes from Binance's
    /// own clock, not the local one.
    pub async fn daily_closed(&self, symbol: &str, min_bars: usize) -> Result<Vec<Kline>> {
        let now_ms = self.server_time_ms().await?;

        // Page backwards from a start time chosen to cover the requested depth,
        // with a margin for the exchange's early history being shorter.
        let span_days = (min_bars as i64) + 5;
        let mut start_ms = now_ms - span_days * MILLIS_PER_DAY;

        let mut collected: Vec<Kline> = Vec::with_capacity(min_bars + MAX_LIMIT);
        // Bounded: a pathological response must not spin forever. 32 pages of
        // 1000 daily bars is ~87 years, far beyond any listing.
        for _ in 0..32 {
            let page = self.daily_page(symbol, Some(start_ms)).await?;
            if page.is_empty() {
                break;
            }
            let last_open = page[page.len() - 1].open_time;
            collected.extend(page);

            // A short page means we have reached the present.
            if collected.len() >= min_bars + MAX_LIMIT || last_open + MILLIS_PER_DAY >= now_ms {
                break;
            }
            start_ms = last_open + MILLIS_PER_DAY;
            tokio::time::sleep(MIN_REQUEST_GAP).await;
        }

        // Pages can overlap at the seam; de-duplicate on open_time.
        collected.sort_by_key(|k| k.open_time);
        collected.dedup_by_key(|k| k.open_time);

        let total = collected.len();
        collected.retain(|k| k.is_closed(now_ms));
        let dropped = total - collected.len();
        if dropped > 0 {
            debug!(symbol, dropped, "dropped forming bar(s) — closed bars only");
        }

        if collected.len() < min_bars {
            warn!(
                symbol,
                got = collected.len(),
                wanted = min_bars,
                "fewer closed bars than requested — listing is younger than the window"
            );
        }
        Ok(collected)
    }

    /// 24h stats for a specific set of symbols.
    ///
    /// Always filtered with `?symbols=[...]`. The unfiltered call returns ~1.9MB
    /// and costs 80 request-weight; naming the handful we care about costs 2 and
    /// a few hundred bytes.
    pub async fn tickers(&self, symbols: &[String]) -> Result<Vec<Ticker24h>> {
        if symbols.is_empty() {
            return Ok(Vec::new());
        }
        #[derive(Deserialize)]
        struct Raw {
            symbol: String,
            #[serde(rename = "lastPrice")]
            last_price: String,
            #[serde(rename = "quoteVolume")]
            quote_volume: String,
            #[serde(rename = "priceChangePercent")]
            price_change_percent: String,
        }
        let list = symbols
            .iter()
            .map(|s| format!("\"{s}\""))
            .collect::<Vec<_>>()
            .join(",");
        let encoded = format!("[{list}]").replace('"', "%22");
        let url = format!("{}/api/v3/ticker/24hr?symbols={}", self.base_url, encoded);

        let raw: Vec<Raw> = self.get_json(&url).await.context("24hr ticker failed")?;
        Ok(raw
            .into_iter()
            .map(|r| Ticker24h {
                symbol: r.symbol,
                last_price: r.last_price.parse().unwrap_or(f64::NAN),
                quote_volume: r.quote_volume.parse().unwrap_or(f64::NAN),
                change_pct_24h: r.price_change_percent.parse().unwrap_or(f64::NAN),
            })
            .collect())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn kline(open_time: i64, close_time: i64) -> Kline {
        Kline {
            open_time,
            close_time,
            open: 1.0,
            high: 1.0,
            low: 1.0,
            close: 1.0,
            volume: 1.0,
            quote_volume: 1.0,
        }
    }

    #[test]
    fn forming_bar_is_not_closed() {
        let now = 1_000_000;
        // Bar whose close time has not yet arrived.
        assert!(!kline(now - 100, now + 100).is_closed(now));
        // Bar that closed exactly now counts as closed.
        assert!(kline(now - 200, now).is_closed(now));
        // Historical bar.
        assert!(kline(now - 500, now - 400).is_closed(now));
    }

    #[test]
    fn date_formats_as_utc_day() {
        // 2024-01-02T00:00:00Z
        let k = kline(1_704_153_600_000, 1_704_239_999_999);
        assert_eq!(k.date(), "2024-01-02");
    }

    #[test]
    fn raw_kline_parses_binance_shape() {
        let json = r#"[[1788912000000,"78455.80","79760.00","77770.00","78306.43","14129.92",1788998399999,"1108236085.13",1,"0","0","0"]]"#;
        let raw: Vec<RawKline> = serde_json::from_str(json).expect("parses");
        let k = Kline::try_from(raw.into_iter().next().unwrap()).expect("converts");
        assert_eq!(k.open_time, 1_788_912_000_000);
        assert_eq!(k.close_time, 1_788_998_399_999);
        assert!((k.close - 78_306.43).abs() < 1e-6);
        assert!((k.volume - 14_129.92).abs() < 1e-6);
        assert!((k.quote_volume - 1_108_236_085.13).abs() < 1e-6);
    }
}
