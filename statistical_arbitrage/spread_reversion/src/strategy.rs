//! The refined EMA-squeeze + volume-surge rule, as a pure function.
//!
//! This is deliberately free of I/O, clocks and network so that the *same* code
//! decides both the backtest and the live paper bot. Any divergence between
//! "what we tested" and "what we run" has to come from the data, not the logic.
//!
//! Rule (daily bars, closed bars only):
//! ```text
//! spread_pct = (max(EMA20, EMA50) - min(EMA20, EMA50)) / close * 100
//! entry = spread_pct < 10          (the 20/50 EMAs are squeezed together)
//!       & EMA50 > EMA200           (uptrend)
//!       & volume > 1.5 * MA20(vol) (volume surge)
//!       & close > EMA200           (risk-on)
//!       & !exit
//! exit  = close < EMA50 * 1.03
//! stop  = 5% FIXED below entry price
//! ```
//!
//! Two details that previous versions got wrong:
//!
//! * **The stop is FIXED, not trailing.** The original backtests passed
//!   `sl_stop=0.05, sl_trail=0.10` to vectorbt. `sl_trail` is a *boolean*
//!   ("should the stop trail?"), so `0.10` was truthy and silently converted
//!   the 5% stop into a 5% *trailing* stop, while the 0.10 was ignored
//!   entirely. That is why results were identical for every trailing value.
//!   The authoritative backtest uses `sl_trail=False`, which is what this
//!   implements.
//!
//! * **The stop is evaluated on the CLOSE**, not the intraday low. That
//!   matches the backtest (which passed only a close series, so vectorbt had no
//!   high/low to test against) and it also matches what a once-a-day bot can
//!   actually do — it cannot fill at an intraday level it never observed.
//!   Honest consequence: real intraday stops would trigger more often, so
//!   backtested drawdowns are understated relative to an intraday-stopped
//!   version of the same rule.

use serde::{Deserialize, Serialize};

pub const EMA_FAST: usize = 20;
pub const EMA_MID: usize = 50;
pub const EMA_SLOW: usize = 200;
pub const VOLUME_MA_DAYS: usize = 20;
pub const SQUEEZE_PCT: f64 = 10.0;
pub const VOLUME_MULTIPLE: f64 = 1.5;
pub const EXIT_BUFFER: f64 = 0.03;
pub const STOP_LOSS_PCT: f64 = 0.05;

/// Bars discarded before signals are trusted, matching `close.index[200:]` in
/// the Python. An EMA200 seeded from the first observation needs this long
/// before it stops being dominated by its seed.
pub const WARMUP_BARS: usize = EMA_SLOW;

/// Minimum bars needed to produce even one tradable signal.
pub const MIN_BARS: usize = WARMUP_BARS + 1;

/// Exponentially weighted moving average matching pandas
/// `Series.ewm(span, adjust=False).mean()`.
///
/// That means: seed with the first observation, then
/// `ema[i] = alpha * x[i] + (1 - alpha) * ema[i-1]` with `alpha = 2/(span+1)`.
/// Getting this wrong (e.g. seeding with an SMA, as many libraries do) shifts
/// every signal date, so it is pinned by a unit test against known pandas output.
pub fn ema(values: &[f64], span: usize) -> Vec<f64> {
    let mut out = Vec::with_capacity(values.len());
    if values.is_empty() {
        return out;
    }
    let alpha = 2.0 / (span as f64 + 1.0);
    let mut prev = values[0];
    out.push(prev);
    for &value in &values[1..] {
        prev = alpha * value + (1.0 - alpha) * prev;
        out.push(prev);
    }
    out
}

/// Trailing simple mean over `window`, `None` until `window` observations exist.
/// Mirrors `rolling(window, min_periods=window).mean()`.
pub fn rolling_mean(values: &[f64], window: usize) -> Vec<Option<f64>> {
    let mut out = Vec::with_capacity(values.len());
    let mut sum = 0.0;
    for (i, &value) in values.iter().enumerate() {
        sum += value;
        if i >= window {
            sum -= values[i - window];
        }
        out.push(if i + 1 >= window {
            Some(sum / window as f64)
        } else {
            None
        });
    }
    out
}

/// Everything the rule needs, precomputed once per bar series.
#[derive(Debug, Clone)]
pub struct Indicators {
    pub ema_fast: Vec<f64>,
    pub ema_mid: Vec<f64>,
    pub ema_slow: Vec<f64>,
    pub volume_ma: Vec<Option<f64>>,
    pub spread_pct: Vec<f64>,
}

impl Indicators {
    pub fn compute(closes: &[f64], volumes: &[f64]) -> Self {
        let ema_fast = ema(closes, EMA_FAST);
        let ema_mid = ema(closes, EMA_MID);
        let ema_slow = ema(closes, EMA_SLOW);
        let volume_ma = rolling_mean(volumes, VOLUME_MA_DAYS);
        let spread_pct = closes
            .iter()
            .zip(&ema_fast)
            .zip(&ema_mid)
            .map(|((close, fast), mid)| {
                if *close <= 0.0 {
                    f64::INFINITY
                } else {
                    (fast.max(*mid) - fast.min(*mid)) / close * 100.0
                }
            })
            .collect();
        Self {
            ema_fast,
            ema_mid,
            ema_slow,
            volume_ma,
            spread_pct,
        }
    }
}

/// What the rule says about one bar, before any position context is applied.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct Signal {
    pub entry: bool,
    pub exit: bool,
}

/// Why the entry did or did not fire — carried into notifications so an alert
/// explains itself instead of just asserting a conclusion.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct SignalDetail {
    pub squeezed: bool,
    pub uptrend: bool,
    pub volume_surge: bool,
    pub risk_on: bool,
    pub spread_pct: f64,
    pub volume_ratio: Option<f64>,
    pub close: f64,
    pub ema_mid: f64,
    pub ema_slow: f64,
}

impl SignalDetail {
    /// One-line human summary, e.g. for a Pushover body.
    pub fn describe(&self) -> String {
        let ratio = self
            .volume_ratio
            .map(|r| format!("{r:.2}x"))
            .unwrap_or_else(|| "n/a".to_string());
        format!(
            "squeeze {} ({:.1}%<10) | trend {} | vol {} ({} >1.5x) | risk-on {}",
            tick(self.squeezed),
            self.spread_pct,
            tick(self.uptrend),
            tick(self.volume_surge),
            ratio,
            tick(self.risk_on),
        )
    }
}

fn tick(passed: bool) -> &'static str {
    if passed { "OK" } else { "no" }
}

/// Evaluate the rule at bar `i`. Reads only indices `<= i`, so it cannot see
/// the future; callers must still ensure bar `i` is a *closed* bar.
pub fn evaluate(
    indicators: &Indicators,
    closes: &[f64],
    volumes: &[f64],
    i: usize,
) -> (Signal, SignalDetail) {
    let close = closes[i];
    let ema_mid = indicators.ema_mid[i];
    let ema_slow = indicators.ema_slow[i];
    let volume_ma = indicators.volume_ma[i];

    let squeezed = indicators.spread_pct[i] < SQUEEZE_PCT;
    let uptrend = ema_mid > ema_slow;
    let volume_surge = volume_ma.is_some_and(|ma| volumes[i] > ma * VOLUME_MULTIPLE);
    let risk_on = close > ema_slow;

    let exit = close < ema_mid * (1.0 + EXIT_BUFFER);
    // `entry & ~exit` in the Python: a bar that simultaneously satisfies the
    // exit condition never opens a position.
    let entry = squeezed && uptrend && volume_surge && risk_on && !exit;

    let detail = SignalDetail {
        squeezed,
        uptrend,
        volume_surge,
        risk_on,
        spread_pct: indicators.spread_pct[i],
        volume_ratio: volume_ma.and_then(|ma| (ma > 0.0).then(|| volumes[i] / ma)),
        close,
        ema_mid,
        ema_slow,
    };
    (Signal { entry, exit }, detail)
}

/// Should an open position be stopped out at this close?
pub fn stop_triggered(entry_price: f64, close: f64) -> bool {
    entry_price > 0.0 && close <= entry_price * (1.0 - STOP_LOSS_PCT)
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Pinned against pandas:
    /// `pd.Series([1,2,3,4,5]).ewm(span=3, adjust=False).mean().tolist()`
    /// -> [1.0, 1.5, 2.25, 3.125, 4.0625]
    #[test]
    fn ema_matches_pandas_adjust_false() {
        let got = ema(&[1.0, 2.0, 3.0, 4.0, 5.0], 3);
        let want = [1.0, 1.5, 2.25, 3.125, 4.0625];
        assert_eq!(got.len(), want.len());
        for (g, w) in got.iter().zip(want) {
            assert!((g - w).abs() < 1e-12, "got {g}, want {w}");
        }
    }

    #[test]
    fn ema_seeds_with_first_value_not_sma() {
        let got = ema(&[10.0, 10.0, 10.0], 50);
        // A constant series must stay exactly constant from bar 0.
        assert!(got.iter().all(|v| (v - 10.0).abs() < 1e-12));
    }

    #[test]
    fn rolling_mean_is_none_until_window_filled() {
        let got = rolling_mean(&[1.0, 2.0, 3.0, 4.0], 3);
        assert_eq!(got[0], None);
        assert_eq!(got[1], None);
        assert_eq!(got[2], Some(2.0));
        assert_eq!(got[3], Some(3.0));
    }

    /// Build a series that trends up smoothly so EMA50 > EMA200 and price sits
    /// above EMA200, then spike the volume on the final bar.
    fn rising_series(n: usize) -> (Vec<f64>, Vec<f64>) {
        let closes: Vec<f64> = (0..n).map(|i| 100.0 + i as f64 * 0.5).collect();
        let volumes = vec![1_000.0; n];
        (closes, volumes)
    }

    #[test]
    fn entry_requires_a_volume_surge() {
        let (closes, mut volumes) = rising_series(400);
        let last = closes.len() - 1;

        // Without a surge, the volume leg fails and there is no entry.
        let indicators = Indicators::compute(&closes, &volumes);
        let (signal, detail) = evaluate(&indicators, &closes, &volumes, last);
        assert!(!detail.volume_surge);
        assert!(!signal.entry);

        // With a 2x surge on the final bar, it fires.
        volumes[last] = 2_000.0;
        let indicators = Indicators::compute(&closes, &volumes);
        let (signal, detail) = evaluate(&indicators, &closes, &volumes, last);
        assert!(detail.volume_surge, "2x volume should clear the 1.5x bar");
        assert!(detail.uptrend && detail.risk_on && detail.squeezed);
        assert!(signal.entry);
    }

    #[test]
    fn exit_suppresses_a_simultaneous_entry() {
        // Price below EMA50*1.03 sets exit, which must veto entry.
        let (mut closes, mut volumes) = rising_series(400);
        let last = closes.len() - 1;
        volumes[last] = 5_000.0;
        closes[last] = closes[last] * 0.80; // drop hard on the final bar

        let indicators = Indicators::compute(&closes, &volumes);
        let (signal, _) = evaluate(&indicators, &closes, &volumes, last);
        assert!(signal.exit);
        assert!(!signal.entry, "exit must veto entry on the same bar");
    }

    #[test]
    fn evaluate_never_reads_future_bars() {
        let (closes, mut volumes) = rising_series(300);
        let cut = 250;
        volumes[cut] = 3_000.0;

        let full = Indicators::compute(&closes, &volumes);
        let (full_signal, _) = evaluate(&full, &closes, &volumes, cut);

        // Recomputing with the series truncated at `cut` must give the same
        // answer — if it does not, something is peeking ahead.
        let truncated_closes = &closes[..=cut];
        let truncated_volumes = &volumes[..=cut];
        let truncated = Indicators::compute(truncated_closes, truncated_volumes);
        let (truncated_signal, _) = evaluate(&truncated, truncated_closes, truncated_volumes, cut);

        assert_eq!(full_signal, truncated_signal);
    }

    #[test]
    fn fixed_stop_triggers_at_five_percent_down() {
        assert!(!stop_triggered(100.0, 96.0));
        assert!(stop_triggered(100.0, 95.0));
        assert!(stop_triggered(100.0, 90.0));
        // No position -> no stop.
        assert!(!stop_triggered(0.0, 1.0));
    }
}
