//! The single place a bar is turned into an action.
//!
//! Both `btc_backtest` and `btc_bot` call [`process_bar`]. That is the whole
//! point of this module: if the backtest and the live bot each had their own
//! copy of "check the stop, then the exit, then the entry", they would drift,
//! and the live bot would stop being the thing that was validated. The only
//! difference between backtest and live is the loop around this function.
//!
//! Ordering is load-bearing and matches the backtest:
//!   1. If a position is open, check the stop **first**.
//!   2. Otherwise check the exit signal.
//!   3. Only if flat, check the entry signal.
//! A bar that closes a position therefore cannot also open one.

use crate::paper::{ExitReason, PaperAccount, Position, Trade};
use crate::strategy::{self, Indicators, Signal, SignalDetail};

/// What happened on a bar.
#[derive(Debug, Clone, PartialEq)]
pub enum Action {
    Hold,
    Entered(Position),
    Exited(Trade),
}

impl Action {
    pub fn changed(&self) -> bool {
        !matches!(self, Action::Hold)
    }
}

/// The full result of evaluating one closed bar.
#[derive(Debug, Clone)]
pub struct BarOutcome {
    pub index: usize,
    pub bar_open_time: i64,
    pub date: String,
    pub close: f64,
    pub signal: Signal,
    pub detail: SignalDetail,
    pub action: Action,
    /// Mark-to-market equity *after* the action.
    pub equity: f64,
}

/// Evaluate exactly one closed bar and mutate the account accordingly.
///
/// Reads no index greater than `i`. The caller guarantees bar `i` is closed and
/// that `dates[i]` / `open_times[i]` line up with `closes`/`volumes`.
pub fn process_bar(
    account: &mut PaperAccount,
    indicators: &Indicators,
    closes: &[f64],
    volumes: &[f64],
    dates: &[String],
    open_times: &[i64],
    i: usize,
) -> BarOutcome {
    let close = closes[i];
    // Idle USDT earns first, before any trading decision. The book is flat most
    // days, so this is where the majority of the return actually accrues.
    account.accrue_cash_yield(open_times[i]);
    let (signal, detail) = strategy::evaluate(indicators, closes, volumes, i);

    let action = if let Some(position) = account.position.clone() {
        // The stop is measured from the entry bar's close, and never fires on
        // the entry bar itself — a position opened at today's close cannot also
        // be stopped out at that same close.
        let stopped = position.entry_bar_open_time != open_times[i]
            && strategy::stop_triggered(position.stop_ref_price, close);
        if stopped || signal.exit {
            let reason = if stopped {
                ExitReason::StopLoss
            } else {
                ExitReason::Signal
            };
            match account.exit(close, &dates[i], reason) {
                Some(trade) => Action::Exited(trade),
                None => Action::Hold,
            }
        } else {
            Action::Hold
        }
    } else if signal.entry {
        match account.enter(close, &dates[i], open_times[i]) {
            Some(position) => Action::Entered(position),
            None => Action::Hold,
        }
    } else {
        Action::Hold
    };

    BarOutcome {
        index: i,
        bar_open_time: open_times[i],
        date: dates[i].clone(),
        close,
        signal,
        detail,
        action,
        equity: account.equity(close),
    }
}

/// Replay every bar from `from` to the end, returning the outcomes, the
/// mark-to-market equity curve, and how many bars were spent holding.
pub fn replay(
    account: &mut PaperAccount,
    indicators: &Indicators,
    closes: &[f64],
    volumes: &[f64],
    dates: &[String],
    open_times: &[i64],
    from: usize,
) -> (Vec<BarOutcome>, Vec<f64>, usize) {
    let mut outcomes = Vec::new();
    let mut equity_curve = Vec::with_capacity(closes.len().saturating_sub(from));
    let mut bars_in_market = 0usize;

    for i in from..closes.len() {
        let outcome = process_bar(account, indicators, closes, volumes, dates, open_times, i);
        if account.position.is_some() {
            bars_in_market += 1;
        }
        equity_curve.push(outcome.equity);
        outcomes.push(outcome);
    }
    (outcomes, equity_curve, bars_in_market)
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Build a smoothly rising series with a volume spike at `spike_at`.
    fn fixture(n: usize, spike_at: usize) -> (Vec<f64>, Vec<f64>, Vec<String>, Vec<i64>) {
        let closes: Vec<f64> = (0..n).map(|i| 100.0 + i as f64 * 0.5).collect();
        let mut volumes = vec![1_000.0; n];
        volumes[spike_at] = 4_000.0;
        let dates: Vec<String> = (0..n)
            .map(|i| format!("2024-{:02}-{:02}", i / 28 + 1, i % 28 + 1))
            .collect();
        let open_times: Vec<i64> = (0..n).map(|i| i as i64 * 86_400_000).collect();
        (closes, volumes, dates, open_times)
    }

    #[test]
    fn entry_then_hold_produces_one_position() {
        let (closes, volumes, dates, open_times) = fixture(260, 250);
        let indicators = Indicators::compute(&closes, &volumes);
        let mut account = PaperAccount::new("TEST", 1_000.0);

        let outcome = process_bar(
            &mut account,
            &indicators,
            &closes,
            &volumes,
            &dates,
            &open_times,
            250,
        );
        assert!(matches!(outcome.action, Action::Entered(_)));
        assert!(account.position.is_some());

        // Next bar: still rising, no exit -> hold.
        let outcome = process_bar(
            &mut account,
            &indicators,
            &closes,
            &volumes,
            &dates,
            &open_times,
            251,
        );
        assert_eq!(outcome.action, Action::Hold);
        assert!(account.position.is_some());
    }

    #[test]
    fn stop_does_not_fire_on_the_entry_bar() {
        let (closes, volumes, dates, open_times) = fixture(260, 250);
        let indicators = Indicators::compute(&closes, &volumes);
        let mut account = PaperAccount::new("TEST", 1_000.0);

        let outcome = process_bar(
            &mut account,
            &indicators,
            &closes,
            &volumes,
            &dates,
            &open_times,
            250,
        );
        assert!(matches!(outcome.action, Action::Entered(_)));

        // Re-processing the very same bar must not stop the position out even
        // though the position now exists — the guard is on bar_open_time.
        let before = account.position.clone().unwrap();
        let outcome = process_bar(
            &mut account,
            &indicators,
            &closes,
            &volumes,
            &dates,
            &open_times,
            250,
        );
        assert_eq!(outcome.action, Action::Hold);
        assert_eq!(
            account.position.unwrap().entry_bar_open_time,
            before.entry_bar_open_time
        );
    }

    #[test]
    fn a_bar_that_exits_cannot_also_enter() {
        let (mut closes, mut volumes, dates, open_times) = fixture(260, 250);
        let indicators0 = Indicators::compute(&closes, &volumes);
        let mut account = PaperAccount::new("TEST", 1_000.0);
        process_bar(
            &mut account,
            &indicators0,
            &closes,
            &volumes,
            &dates,
            &open_times,
            250,
        );
        assert!(account.position.is_some());

        // Crash the next bar hard, with a big volume spike that would otherwise
        // look like a fresh entry.
        closes[251] *= 0.70;
        volumes[251] = 9_000.0;
        let indicators = Indicators::compute(&closes, &volumes);
        let outcome = process_bar(
            &mut account,
            &indicators,
            &closes,
            &volumes,
            &dates,
            &open_times,
            251,
        );

        assert!(matches!(outcome.action, Action::Exited(_)));
        assert!(account.is_flat(), "must end the bar flat, not re-entered");
    }

    #[test]
    fn replay_equity_curve_has_one_point_per_bar() {
        let (closes, volumes, dates, open_times) = fixture(260, 250);
        let indicators = Indicators::compute(&closes, &volumes);
        let mut account = PaperAccount::new("TEST", 1_000.0);
        let (outcomes, equity, _) = replay(
            &mut account,
            &indicators,
            &closes,
            &volumes,
            &dates,
            &open_times,
            200,
        );
        assert_eq!(outcomes.len(), 60);
        assert_eq!(equity.len(), 60);
        assert!(equity.iter().all(|e| *e > 0.0));
    }
}
