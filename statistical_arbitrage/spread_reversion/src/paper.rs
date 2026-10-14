//! Paper-trading ledger — emulated fills, persisted to disk.
//!
//! No order endpoint is reachable from this module. Fills are simulated against
//! the daily close, with slippage applied to the price and a fee applied to the
//! notional, matching the backtest's cost model.
//!
//! Persistence is not a nicety here, it is a correctness requirement. The
//! previous Hummingbot port kept `entry_price` and the running peak as
//! in-memory fields that were never saved, so restarting while holding a
//! position reset `entry_price` to `0.0` and left that position permanently
//! stop-less. Everything needed to resume a position — entry price, entry date,
//! quantity — is serialised here, and [`PaperAccount::already_processed`] makes
//! re-running on the same closed bar a no-op rather than a double trade.

use std::fs;
use std::io::Write as _;
use std::path::{Path, PathBuf};

use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};

/// Fee charged on notional, per side (0.10%).
pub const FEE_PER_SIDE: f64 = 0.0010;
/// Slippage applied to the execution price, per side (0.05%).
pub const SLIPPAGE_PER_SIDE: f64 = 0.0005;
/// Fraction of equity deployed per trade — the "1x" sizing from the backtest.
pub const POSITION_FRACTION: f64 = 0.20;
/// Yield earned on idle USDT (Binance flexible savings), annualised.
///
/// This is not a refinement, it is a correction. The book is flat ~69% of days
/// and deploys only 20% even when in a trade, so ~94% of capital sits idle on
/// average. Modelling that at 0% while USDT actually pays ~4% understated the
/// return by ~3.8%/yr and was the single largest error in the backtest.
pub const CASH_YIELD_ANNUAL: f64 = 0.04;

fn default_cash_yield() -> f64 {
    CASH_YIELD_ANNUAL
}

/// Why a position was closed. Recorded so the trade log can be audited later.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ExitReason {
    /// close < EMA50 * 1.03
    Signal,
    /// close <= entry * 0.95
    StopLoss,
}

impl ExitReason {
    pub fn label(&self) -> &'static str {
        match self {
            ExitReason::Signal => "signal",
            ExitReason::StopLoss => "stop_loss",
        }
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Position {
    pub symbol: String,
    pub quantity: f64,
    /// Price actually paid, i.e. after slippage. This is the P&L cost basis.
    pub entry_price: f64,
    /// The entry bar's *unslipped* close, which is what the stop is measured
    /// from. vectorbt's default `stop_entry_price="close"` anchors the stop to
    /// the bar close, not the fill, so measuring from `entry_price` would put
    /// our stop 0.05% lower than the backtest's and occasionally skip a stop
    /// the research counted.
    #[serde(default)]
    pub stop_ref_price: f64,
    /// Fee paid on the way in. Carried on the position so the round-trip P&L
    /// can include it — otherwise realised P&L silently understates costs by
    /// one side and stops reconciling with the cash balance.
    #[serde(default)]
    pub entry_fee: f64,
    pub entry_date: String,
    pub entry_bar_open_time: i64,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Trade {
    pub symbol: String,
    pub entry_date: String,
    pub exit_date: String,
    pub entry_price: f64,
    pub exit_price: f64,
    pub quantity: f64,
    pub fees: f64,
    /// Net of fees and slippage.
    pub pnl: f64,
    pub return_pct: f64,
    pub exit_reason: ExitReason,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PaperAccount {
    pub symbol: String,
    pub cash: f64,
    pub initial_cash: f64,
    pub position: Option<Position>,
    pub realised_pnl: f64,
    pub total_fees: f64,
    pub trades: Vec<Trade>,
    /// Open time of the most recent bar already acted upon. Guards against
    /// double-trading if the bot is restarted or run twice in a day.
    pub last_bar_open_time: Option<i64>,
    /// Annualised yield credited on idle cash. Set to 0.0 to reproduce the
    /// older numbers. `serde(default)` so state files written before this
    /// existed still load.
    #[serde(default = "default_cash_yield")]
    pub cash_yield: f64,
    /// Interest credited so far, tracked separately so realised trading P&L
    /// stays distinguishable from carry.
    #[serde(default)]
    pub cash_interest: f64,
    /// Last bar interest was credited for, so re-running a bar cannot
    /// double-credit.
    #[serde(default)]
    pub last_yield_time: Option<i64>,
    #[serde(skip)]
    path: Option<PathBuf>,
}

impl PaperAccount {
    pub fn new(symbol: impl Into<String>, initial_cash: f64) -> Self {
        Self {
            symbol: symbol.into(),
            cash: initial_cash,
            initial_cash,
            position: None,
            realised_pnl: 0.0,
            total_fees: 0.0,
            trades: Vec::new(),
            last_bar_open_time: None,
            cash_yield: CASH_YIELD_ANNUAL,
            cash_interest: 0.0,
            last_yield_time: None,
            path: None,
        }
    }

    /// Load from disk, or start a fresh account if the file does not exist.
    pub fn load_or_new(path: impl AsRef<Path>, symbol: &str, initial_cash: f64) -> Result<Self> {
        let path = path.as_ref().to_path_buf();
        let mut account = if path.exists() {
            let text = fs::read_to_string(&path)
                .with_context(|| format!("reading paper state {}", path.display()))?;
            serde_json::from_str::<PaperAccount>(&text)
                .with_context(|| format!("parsing paper state {}", path.display()))?
        } else {
            Self::new(symbol, initial_cash)
        };
        account.path = Some(path);
        Ok(account)
    }

    pub fn save(&self) -> Result<()> {
        let Some(path) = &self.path else {
            return Ok(());
        };
        if let Some(parent) = path.parent() {
            if !parent.as_os_str().is_empty() {
                fs::create_dir_all(parent).ok();
            }
        }
        // Write via a temp file then rename, so a crash mid-write cannot leave
        // a truncated state file that loses an open position.
        let tmp = path.with_extension("json.tmp");
        let text = serde_json::to_string_pretty(self)?;
        fs::write(&tmp, text).with_context(|| format!("writing {}", tmp.display()))?;
        fs::rename(&tmp, path).with_context(|| format!("renaming into {}", path.display()))?;
        Ok(())
    }

    /// Credit interest on idle cash for the days elapsed since the last accrual.
    ///
    /// Driven by elapsed time rather than bar count, so a bot that was down for
    /// three days credits three days — which is what the real USDT balance would
    /// have done. Idempotent: calling twice for the same bar credits nothing, so
    /// this and `already_processed` are independent safety nets.
    ///
    /// Deliberately NOT called from `enter`/`exit`: keeping it out of those paths
    /// is what preserves the vectorbt sizing parity test.
    pub fn accrue_cash_yield(&mut self, bar_open_time: i64) -> f64 {
        let Some(previous) = self.last_yield_time else {
            self.last_yield_time = Some(bar_open_time);
            return 0.0;
        };
        if bar_open_time <= previous || self.cash_yield <= 0.0 {
            return 0.0;
        }
        let days = (bar_open_time - previous) as f64 / 86_400_000.0;
        let interest = self.cash * (self.cash_yield / 365.0) * days;
        self.cash += interest;
        self.cash_interest += interest;
        self.last_yield_time = Some(bar_open_time);
        interest
    }

    /// True if this closed bar has already been acted on.
    pub fn already_processed(&self, bar_open_time: i64) -> bool {
        self.last_bar_open_time
            .is_some_and(|seen| seen >= bar_open_time)
    }

    pub fn mark_processed(&mut self, bar_open_time: i64) {
        self.last_bar_open_time = Some(bar_open_time);
    }

    pub fn is_flat(&self) -> bool {
        self.position.is_none()
    }

    /// Mark-to-market account value at the given price.
    pub fn equity(&self, price: f64) -> f64 {
        self.cash + self.position.as_ref().map_or(0.0, |p| p.quantity * price)
    }

    /// Unrealised P&L of the open position at the given price.
    pub fn unrealised_pnl(&self, price: f64) -> f64 {
        self.position
            .as_ref()
            .map_or(0.0, |p| (price - p.entry_price) * p.quantity)
    }

    /// Buy `POSITION_FRACTION` of current equity at the bar close.
    ///
    /// Returns the position opened, or `None` if already long or the sizing
    /// rounds to nothing.
    pub fn enter(&mut self, price: f64, date: &str, bar_open_time: i64) -> Option<Position> {
        if self.position.is_some() || price <= 0.0 {
            return None;
        }
        // vectorbt's `size_type='percent'` treats the fraction as a budget of
        // CASH that the fee comes out of, not a notional the fee is added to:
        //   cash_limit = percent * cash
        //   notional   = cash_limit / (1 + fee)
        //   fee        = cash_limit - notional
        // Spending `notional + fee` instead would deploy 0.1% more than the
        // backtest did on every trade.
        let budget = (self.cash * POSITION_FRACTION).min(self.cash);
        if budget <= 0.0 {
            return None;
        }
        let fill_price = price * (1.0 + SLIPPAGE_PER_SIDE);
        let notional = budget / (1.0 + FEE_PER_SIDE);
        let fee = budget - notional;
        let quantity = notional / fill_price;
        if !quantity.is_finite() || quantity <= 0.0 {
            return None;
        }

        self.cash -= budget;
        self.total_fees += fee;
        let position = Position {
            symbol: self.symbol.clone(),
            quantity,
            entry_price: fill_price,
            stop_ref_price: price,
            entry_fee: fee,
            entry_date: date.to_string(),
            entry_bar_open_time: bar_open_time,
        };
        self.position = Some(position.clone());
        Some(position)
    }

    /// Sell the whole position at the bar close.
    pub fn exit(&mut self, price: f64, date: &str, reason: ExitReason) -> Option<Trade> {
        let position = self.position.take()?;
        let fill_price = price * (1.0 - SLIPPAGE_PER_SIDE);
        let proceeds = position.quantity * fill_price;
        let fee = proceeds * FEE_PER_SIDE;

        self.cash += proceeds - fee;
        self.total_fees += fee;

        let cost_basis = position.quantity * position.entry_price;
        // Both sides of the fee belong to this round trip. Counting only the
        // exit fee would leave realised P&L out of step with the cash balance.
        let round_trip_fees = fee + position.entry_fee;
        let pnl = proceeds - fee - cost_basis - position.entry_fee;
        self.realised_pnl += pnl;

        let trade = Trade {
            symbol: position.symbol,
            entry_date: position.entry_date,
            exit_date: date.to_string(),
            entry_price: position.entry_price,
            exit_price: fill_price,
            quantity: position.quantity,
            fees: round_trip_fees,
            pnl,
            return_pct: if cost_basis > 0.0 {
                pnl / cost_basis * 100.0
            } else {
                0.0
            },
            exit_reason: reason,
        };
        self.trades.push(trade.clone());
        Some(trade)
    }

    pub fn win_rate(&self) -> Option<f64> {
        if self.trades.is_empty() {
            return None;
        }
        let wins = self.trades.iter().filter(|t| t.pnl > 0.0).count();
        Some(wins as f64 / self.trades.len() as f64 * 100.0)
    }

    /// Append the trade to a CSV audit log, writing a header if new.
    pub fn append_trade_csv(path: impl AsRef<Path>, trade: &Trade) -> Result<()> {
        let path = path.as_ref();
        let is_new = !path.exists();
        let mut file = fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(path)
            .with_context(|| format!("opening trade log {}", path.display()))?;
        if is_new {
            writeln!(
                file,
                "symbol,entry_date,exit_date,entry_price,exit_price,quantity,fees,pnl,return_pct,exit_reason"
            )?;
        }
        writeln!(
            file,
            "{},{},{},{:.8},{:.8},{:.8},{:.4},{:.4},{:.4},{}",
            trade.symbol,
            trade.entry_date,
            trade.exit_date,
            trade.entry_price,
            trade.exit_price,
            trade.quantity,
            trade.fees,
            trade.pnl,
            trade.return_pct,
            trade.exit_reason.label(),
        )?;
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Pinned to vectorbt's `size_type='percent'` arithmetic: the 20% is a cash
    /// BUDGET that the fee is taken out of, not a notional the fee is added to.
    #[test]
    fn sizing_matches_vectorbt_percent_of_cash() {
        let mut account = PaperAccount::new("BTCUSDT", 1_000.0);
        let position = account.enter(100.0, "2024-01-01", 0).expect("opens");

        let budget = 200.0;
        let expected_notional = budget / (1.0 + FEE_PER_SIDE); // 199.8002
        let expected_fee = budget - expected_notional; // 0.1998
        let expected_fill = 100.0 * (1.0 + SLIPPAGE_PER_SIDE);

        assert!((position.entry_price - expected_fill).abs() < 1e-9);
        assert!((position.quantity * expected_fill - expected_notional).abs() < 1e-9);
        assert!((account.total_fees - expected_fee).abs() < 1e-9);
        // Cash falls by exactly the budget — not budget + fee.
        assert!(
            (account.cash - 800.0).abs() < 1e-9,
            "cash should be exactly 800.0, got {}",
            account.cash
        );
    }

    /// The stop is anchored to the bar close, not the slipped fill, matching
    /// vectorbt's `stop_entry_price="close"`.
    #[test]
    fn stop_reference_is_the_unslipped_close() {
        let mut account = PaperAccount::new("BTCUSDT", 1_000.0);
        let position = account.enter(100.0, "2024-01-01", 0).expect("opens");
        assert!((position.stop_ref_price - 100.0).abs() < 1e-12);
        assert!(
            position.entry_price > position.stop_ref_price,
            "fill is slipped up"
        );
    }

    #[test]
    fn round_trip_at_the_same_price_loses_exactly_the_costs() {
        let mut account = PaperAccount::new("BTCUSDT", 1_000.0);
        account.enter(100.0, "2024-01-01", 0).unwrap();
        let trade = account
            .exit(100.0, "2024-01-05", ExitReason::Signal)
            .unwrap();

        // Two sides of slippage plus two fees, all negative.
        assert!(trade.pnl < 0.0);
        let round_trip_cost = 2.0 * (FEE_PER_SIDE + SLIPPAGE_PER_SIDE);
        assert!(
            (trade.pnl.abs() / 200.0 - round_trip_cost).abs() < 1e-3,
            "expected ~{round_trip_cost} of 200 notional, got {}",
            trade.pnl
        );
        assert!(account.is_flat());
        assert_eq!(account.trades.len(), 1);
    }

    /// The invariant the entry-fee bug broke: once flat, the change in cash must
    /// equal the sum of realised trade P&L, to the cent.
    #[test]
    fn realised_pnl_reconciles_with_cash() {
        let mut account = PaperAccount::new("BTCUSDT", 1_000.0);
        for (i, (entry, exit)) in [(100.0, 110.0), (110.0, 104.0), (104.0, 130.0)]
            .into_iter()
            .enumerate()
        {
            account
                .enter(entry, &format!("2024-01-{:02}", i * 2 + 1), i as i64 * 2)
                .unwrap();
            account
                .exit(
                    exit,
                    &format!("2024-01-{:02}", i * 2 + 2),
                    ExitReason::Signal,
                )
                .unwrap();
        }
        assert!(account.is_flat());
        assert_eq!(account.trades.len(), 3);

        let cash_change = account.cash - account.initial_cash;
        let summed: f64 = account.trades.iter().map(|t| t.pnl).sum();
        assert!(
            (cash_change - summed).abs() < 1e-9,
            "cash moved {cash_change} but trades summed to {summed}"
        );
        assert!((account.realised_pnl - summed).abs() < 1e-9);
    }

    #[test]
    fn cannot_open_a_second_position() {
        let mut account = PaperAccount::new("BTCUSDT", 1_000.0);
        assert!(account.enter(100.0, "2024-01-01", 0).is_some());
        assert!(account.enter(101.0, "2024-01-02", 1).is_none());
    }

    const DAY: i64 = 86_400_000;

    #[test]
    fn cash_yield_accrues_and_is_idempotent() {
        let mut account = PaperAccount::new("BTCUSDT", 1_000.0);
        // First call only seeds the clock — there is no elapsed time yet.
        assert_eq!(account.accrue_cash_yield(0), 0.0);

        let one_day = account.accrue_cash_yield(DAY);
        let expected = 1_000.0 * CASH_YIELD_ANNUAL / 365.0;
        assert!(
            (one_day - expected).abs() < 1e-9,
            "got {one_day}, want {expected}"
        );

        // Re-running the SAME bar must credit nothing, or a restart would pay
        // interest twice for one day.
        assert_eq!(account.accrue_cash_yield(DAY), 0.0);

        // A three-day outage credits three days, like the real balance would.
        // Slightly more than 3x the first day's interest, because the balance
        // it accrues on has itself grown — that compounding is correct.
        let balance = account.cash;
        let gap = account.accrue_cash_yield(DAY * 4);
        let want = balance * CASH_YIELD_ANNUAL / 365.0 * 3.0;
        assert!((gap - want).abs() < 1e-9, "expected {want}, got {gap}");
        assert!(gap / expected > 3.0, "compounding means slightly over 3x");
    }

    #[test]
    fn cash_yield_can_be_switched_off() {
        let mut account = PaperAccount::new("BTCUSDT", 1_000.0);
        account.cash_yield = 0.0;
        account.accrue_cash_yield(0);
        assert_eq!(account.accrue_cash_yield(DAY), 0.0);
        assert_eq!(account.cash, 1_000.0);
    }

    /// The reconciliation invariant, extended. Interest is carry, not trading
    /// P&L, so the identity gains a term rather than breaking.
    #[test]
    fn cash_reconciles_with_pnl_plus_interest() {
        let mut account = PaperAccount::new("BTCUSDT", 1_000.0);
        account.accrue_cash_yield(0);
        for (i, (entry, exit)) in [(100.0, 110.0), (110.0, 104.0)].into_iter().enumerate() {
            account.accrue_cash_yield(DAY * (i as i64 * 2 + 1));
            account.enter(entry, "2024-01-01", 0).unwrap();
            account.accrue_cash_yield(DAY * (i as i64 * 2 + 2));
            account
                .exit(exit, "2024-01-02", ExitReason::Signal)
                .unwrap();
        }
        assert!(account.is_flat());
        assert!(account.cash_interest > 0.0, "interest should have accrued");

        let summed: f64 = account.trades.iter().map(|t| t.pnl).sum();
        let cash_change = account.cash - account.initial_cash;
        assert!(
            (cash_change - (summed + account.cash_interest)).abs() < 1e-9,
            "cash moved {cash_change} but trades {summed} + interest {}",
            account.cash_interest
        );
    }

    #[test]
    fn already_processed_blocks_replaying_a_bar() {
        let mut account = PaperAccount::new("BTCUSDT", 1_000.0);
        assert!(!account.already_processed(100));
        account.mark_processed(100);
        assert!(account.already_processed(100));
        assert!(account.already_processed(99), "older bars are also done");
        assert!(
            !account.already_processed(101),
            "a newer bar is still pending"
        );
    }

    #[test]
    fn state_round_trips_through_disk_with_an_open_position() {
        let dir = std::env::temp_dir().join(format!("paper_test_{}", std::process::id()));
        fs::create_dir_all(&dir).unwrap();
        let path = dir.join("state.json");

        let mut account = PaperAccount::load_or_new(&path, "BTCUSDT", 1_000.0).unwrap();
        account.enter(100.0, "2024-01-01", 42).unwrap();
        account.mark_processed(42);
        account.save().unwrap();

        // The whole point: a restart must recover entry_price, or the position
        // comes back stop-less.
        let reloaded = PaperAccount::load_or_new(&path, "BTCUSDT", 1_000.0).unwrap();
        let position = reloaded.position.expect("position survives restart");
        assert!((position.entry_price - 100.0 * (1.0 + SLIPPAGE_PER_SIDE)).abs() < 1e-9);
        assert_eq!(reloaded.last_bar_open_time, Some(42));

        fs::remove_dir_all(&dir).ok();
    }
}
