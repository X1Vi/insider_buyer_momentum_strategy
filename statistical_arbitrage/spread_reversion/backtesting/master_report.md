# Master Backtest Report — BANKBEES.NS vs SETFNIFBK.NS

**Data:** Yahoo intraday  2026-06-08 09:15:00+05:30 → 2026-08-28 15:25:00+05:30  (4056 bars)

**Strategy:** two-sided spread reversion, spread = ln(PA) − ln(PB), rolling z-score; enter LONG z<−2.0 / SHORT z>+2.0; exit z crosses 0, stop ₹off, take-profit ₹off.

**Portfolio:** start ₹10,000, qty = floor(balance / (PA+PB)) per trade.

**Fees:** Groww intraday (MIS) 4 legs/round trip.


## Summary

| Metric | Value | Metric | Value |
|---|---:|---|---:|
| Trades | 109 | LONG / SHORT | 39 / 70 |
| Trades / month | 41.0 | Avg hold (bars) | 1.8 |
| Gross P&L | ₹658.96 | Fees | ₹2,891.90 |
| Net P&L | ₹-2,232.94 | Final portfolio | ₹7,767.06 |
| Total return | -22.33% | CAGR | -68.00% |
| Sharpe (daily, ann.) | -27.59 | Sortino | -30.28 |
| Max drawdown | -22.33% | Max DD duration | 4032 |
| Calmar | -3.05 | Profit factor | 0.00 |
| Net win rate | 0.00% | Avg win | ₹0.00 |
| Avg loss | ₹20.49 | Expectancy / trade | ₹-20.49 |
| Max consecutive losses | 109 |  |  |

## Trade list (last 20)

| in | out | dir | qty | exit | gross | fees | net |
|---|---|---|---:|---|---:|---:|---:|
| 2026-08-17 11:25 | 2026-08-17 11:30 | SHORT | 6 | Z | ₹4 | ₹26 | ₹-23 |
| 2026-08-17 13:00 | 2026-08-17 13:05 | SHORT | 6 | Z | ₹6 | ₹26 | ₹-20 |
| 2026-08-17 15:25 | 2026-08-18 09:25 | LONG | 6 | Z | ₹5 | ₹26 | ₹-22 |
| 2026-08-18 13:25 | 2026-08-18 13:40 | SHORT | 6 | Z | ₹3 | ₹26 | ₹-23 |
| 2026-08-19 10:45 | 2026-08-19 10:50 | SHORT | 6 | Z | ₹5 | ₹26 | ₹-21 |
| 2026-08-19 11:20 | 2026-08-19 11:30 | SHORT | 6 | Z | ₹3 | ₹26 | ₹-23 |
| 2026-08-19 13:25 | 2026-08-19 13:45 | SHORT | 6 | Z | ₹5 | ₹26 | ₹-21 |
| 2026-08-19 14:40 | 2026-08-19 14:50 | SHORT | 6 | Z | ₹5 | ₹26 | ₹-22 |
| 2026-08-20 10:00 | 2026-08-20 10:05 | SHORT | 6 | Z | ₹5 | ₹26 | ₹-21 |
| 2026-08-20 14:00 | 2026-08-20 14:10 | LONG | 6 | Z | ₹7 | ₹26 | ₹-19 |
| 2026-08-21 11:25 | 2026-08-21 11:30 | SHORT | 6 | Z | ₹3 | ₹26 | ₹-23 |
| 2026-08-21 12:10 | 2026-08-21 12:20 | LONG | 6 | Z | ₹1 | ₹26 | ₹-25 |
| 2026-08-21 12:30 | 2026-08-21 12:35 | LONG | 6 | Z | ₹5 | ₹26 | ₹-21 |
| 2026-08-21 14:30 | 2026-08-21 14:50 | LONG | 6 | Z | ₹7 | ₹26 | ₹-19 |
| 2026-08-24 12:35 | 2026-08-24 12:45 | SHORT | 6 | Z | ₹4 | ₹26 | ₹-22 |
| 2026-08-26 13:25 | 2026-08-26 13:35 | LONG | 6 | Z | ₹5 | ₹26 | ₹-21 |
| 2026-08-26 15:05 | 2026-08-26 15:10 | LONG | 6 | Z | ₹7 | ₹26 | ₹-20 |
| 2026-08-27 11:05 | 2026-08-27 11:20 | SHORT | 6 | Z | ₹4 | ₹26 | ₹-22 |
| 2026-08-27 12:30 | 2026-08-27 12:40 | LONG | 6 | Z | ₹6 | ₹26 | ₹-20 |
| 2026-08-28 09:20 | 2026-08-28 09:40 | SHORT | 6 | Z | ₹6 | ₹26 | ₹-20 |

## How to read this

- **Sharpe -27.59** = profit per unit of risk (daily, annualized). >1 good, <0 losing.

- **Sortino -30.28** = like Sharpe but only counts downside moves.

- **MaxDD -22.33%** = worst peak-to-trough drop of your balance.

- **CAGR -68.00%** = average yearly growth.

- **Profit factor 0.00** = total winnings ÷ total losses (>1 profitable).

- **Expectancy ₹-20.49** = average ₹ per trade.

- **Net win rate 0%** = fraction of trades that made money after fees.


The graphs show: prices (top), log spread, z-score with ±entry lines, and portfolio equity with a red drawdown overlay.
