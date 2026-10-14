//! Shared library target for the `spread_reversion` crate.
//!
//! Why this file exists: binaries under `src/bin/` are separate crate roots and
//! cannot reach the modules declared in `src/main.rs`. That is why `pushover`
//! is currently copy-pasted three times (`notify.rs`, `bin/scanner.rs`,
//! `bin/volume_screener.rs`). Declaring the shared modules here lets new
//! binaries `use spread_reversion::notify` instead of growing a fourth copy.
//!
//! `src/main.rs` is deliberately left untouched — it keeps its own `mod`
//! declarations, so nothing about the existing spread-reversion bot changes.
//! `notify.rs` is simply compiled into both targets, which is harmless because
//! it holds no state and shares no types across the boundary.

pub mod binance;
pub mod engine;
pub mod groww;
pub mod insider;
pub mod logging;
pub mod notify;
pub mod paper;
pub mod strategy;
