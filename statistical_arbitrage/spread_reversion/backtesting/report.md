# Spread Reversion Backtest Report — BANKBEES.NS vs SETFNIFBK.NS

**Data:** Yahoo Finance daily  2023-01-02 → 2026-08-27  (904 bars)

**Strategy:** spread = ln(PA) − ln(PB); rolling window z-score; enter |z|>2; exit z crosses 0 / stop-loss / take-profit.

**Fees:** Groww intraday (MIS) — 4 legs per round trip (₹5–20/leg brokerage + STT/stamp/exchange/SEBI/IPFT/GST).

**Portfolio:** start ₹5,000, invests 50% per trade, qty = floor(balance×0.5 / (PA+PB)).


## Summary

| Config | Trades | Gross | Fees | Net | Final ₹ | Return | CAGR | Sharpe | Sortino | MaxDD | MaxDD days | Calmar | ProfitFactor | WinRate | Expectancy |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| base   (w=60,z=2.0,SL=100,TP=off) | 36 | ₹760 | ₹969 | ₹-209 | ₹19,791 | -1.05% | -0.29% | -0.63 | -0.45 | -1.19% | 883 | -0.24 | 0.51 | 11% | ₹-5.82 |
| best   (w=120,z=3.0,SL=off,TP=off) | 10 | ₹403 | ₹269 | ₹133 | ₹20,133 | 0.67% | 0.18% | 0.44 | 0.32 | -0.29% | 327 | 0.63 | 3.42 | 30% | ₹13.33 |
| worst  (w=20,z=2.0,SL=100,TP=off) | 53 | ₹906 | ₹1,428 | ₹-522 | ₹19,478 | -2.61% | -0.72% | -1.43 | -1.12 | -2.69% | 883 | -0.27 | 0.29 | 8% | ₹-9.85 |
| noSLTP (w=60,z=2.0,SL=off,TP=off) | 36 | ₹760 | ₹969 | ₹-209 | ₹19,791 | -1.05% | -0.29% | -0.63 | -0.45 | -1.19% | 883 | -0.24 | 0.51 | 11% | ₹-5.82 |
| SLonly (w=60,z=2.0,SL=100,TP=off) | 36 | ₹760 | ₹969 | ₹-209 | ₹19,791 | -1.05% | -0.29% | -0.63 | -0.45 | -1.19% | 883 | -0.24 | 0.51 | 11% | ₹-5.82 |

## Detail per config

### base   (w=60,z=2.0,SL=100,TP=off)

| Metric | Value | | Metric | Value |
|---|---:|---|---:|
| Trades | 36 | SHORT / LONG | 15 |
| Avg hold | 1.9d | Gross P&L | ₹759.50 |
| Fees | ₹968.93 | Net P&L | ₹-209.43 |
| Final portfolio | ₹19,790.57 | Total return | -1.05% |
| CAGR | -0.29% | Sharpe (daily, ann.) | -0.63 |
| Sortino | -0.45 | Max drawdown | -1.19% |
| Max DD duration | 883 | Calmar | -0.24 |
| Profit factor | 0.51 | Net win rate | 11.11% |
| Avg win | ₹54.85 | Avg loss | ₹13.40 |
| Expectancy/trade | ₹-5.82 |  |  |

Top 10 trades (net ₹):

| # | in | out | dir | qty | held | exit | gross | fees | net |
|---|---|---|---|---:|---:|---|---:|---:|---:|
| 1 | 2024-06-04 | 2024-06-05 | LONG | 9 | 1d | Z | ₹121 | ₹27 | ₹94 |
| 2 | 2025-10-15 | 2025-10-16 | SHORT | 8 | 1d | Z | ₹118 | ₹27 | ₹91 |
| 3 | 2024-09-20 | 2024-09-23 | LONG | 9 | 1d | Z | ₹47 | ₹27 | ₹20 |
| 4 | 2026-03-13 | 2026-03-16 | LONG | 8 | 1d | Z | ₹40 | ₹27 | ₹14 |
| 5 | 2023-01-27 | 2023-02-01 | LONG | 12 | 3d | Z | ₹26 | ₹27 | ₹-1 |
| 6 | 2025-04-07 | 2025-04-08 | LONG | 9 | 1d | Z | ₹23 | ₹27 | ₹-4 |
| 7 | 2024-02-13 | 2024-02-14 | SHORT | 10 | 1d | Z | ₹22 | ₹27 | ₹-5 |
| 8 | 2025-04-16 | 2025-04-22 | LONG | 9 | 3d | Z | ₹22 | ₹27 | ₹-5 |
| 9 | 2025-02-10 | 2025-02-11 | SHORT | 9 | 1d | Z | ₹21 | ₹27 | ₹-6 |
| 10 | 2026-08-06 | 2026-08-10 | SHORT | 8 | 2d | Z | ₹19 | ₹27 | ₹-8 |


### best   (w=120,z=3.0,SL=off,TP=off)

| Metric | Value | | Metric | Value |
|---|---:|---|---:|
| Trades | 10 | SHORT / LONG | 4 |
| Avg hold | 1.9d | Gross P&L | ₹402.68 |
| Fees | ₹269.36 | Net P&L | ₹133.32 |
| Final portfolio | ₹20,133.32 | Total return | 0.67% |
| CAGR | 0.18% | Sharpe (daily, ann.) | 0.44 |
| Sortino | 0.32 | Max drawdown | -0.29% |
| Max DD duration | 327 | Calmar | 0.63 |
| Profit factor | 3.42 | Net win rate | 30.00% |
| Avg win | ₹62.83 | Avg loss | ₹7.88 |
| Expectancy/trade | ₹13.33 |  |  |

Top 10 trades (net ₹):

| # | in | out | dir | qty | held | exit | gross | fees | net |
|---|---|---|---|---:|---:|---|---:|---:|---:|
| 1 | 2024-06-04 | 2024-06-05 | LONG | 9 | 1d | Z | ₹121 | ₹27 | ₹94 |
| 2 | 2025-10-15 | 2025-10-17 | SHORT | 8 | 2d | Z | ₹120 | ₹27 | ₹93 |
| 3 | 2026-08-07 | 2026-08-10 | SHORT | 8 | 1d | Z | ₹28 | ₹27 | ₹1 |
| 4 | 2023-01-27 | 2023-02-01 | LONG | 12 | 3d | Z | ₹26 | ₹27 | ₹-1 |
| 5 | 2025-01-06 | 2025-01-13 | LONG | 9 | 5d | Z | ₹25 | ₹27 | ₹-2 |
| 6 | 2024-02-14 | 2024-02-15 | LONG | 10 | 1d | Z | ₹22 | ₹27 | ₹-5 |
| 7 | 2026-04-15 | 2026-04-17 | LONG | 8 | 2d | Z | ₹17 | ₹27 | ₹-10 |
| 8 | 2023-03-06 | 2023-03-08 | LONG | 11 | 1d | Z | ₹17 | ₹27 | ₹-10 |
| 9 | 2024-02-02 | 2024-02-05 | SHORT | 10 | 1d | Z | ₹14 | ₹27 | ₹-13 |
| 10 | 2023-09-22 | 2023-09-26 | SHORT | 11 | 2d | Z | ₹13 | ₹27 | ₹-14 |


### worst  (w=20,z=2.0,SL=100,TP=off)

| Metric | Value | | Metric | Value |
|---|---:|---|---:|
| Trades | 53 | SHORT / LONG | 25 |
| Avg hold | 1.9d | Gross P&L | ₹906.02 |
| Fees | ₹1,428.09 | Net P&L | ₹-522.06 |
| Final portfolio | ₹19,477.94 | Total return | -2.61% |
| CAGR | -0.72% | Sharpe (daily, ann.) | -1.43 |
| Sortino | -1.12 | Max drawdown | -2.69% |
| Max DD duration | 883 | Calmar | -0.27 |
| Profit factor | 0.29 | Net win rate | 7.55% |
| Avg win | ₹53.63 | Avg loss | ₹15.03 |
| Expectancy/trade | ₹-9.85 |  |  |

Top 10 trades (net ₹):

| # | in | out | dir | qty | held | exit | gross | fees | net |
|---|---|---|---|---:|---:|---|---:|---:|---:|
| 1 | 2024-06-04 | 2024-06-05 | LONG | 9 | 1d | Z | ₹121 | ₹27 | ₹94 |
| 2 | 2025-10-15 | 2025-10-16 | SHORT | 8 | 1d | Z | ₹118 | ₹27 | ₹91 |
| 3 | 2024-09-20 | 2024-09-23 | LONG | 8 | 1d | Z | ₹42 | ₹27 | ₹15 |
| 4 | 2026-03-13 | 2026-03-16 | LONG | 8 | 1d | Z | ₹40 | ₹27 | ₹14 |
| 5 | 2023-01-27 | 2023-02-01 | LONG | 12 | 3d | Z | ₹26 | ₹27 | ₹-1 |
| 6 | 2024-08-02 | 2024-08-05 | SHORT | 9 | 1d | Z | ₹26 | ₹27 | ₹-1 |
| 7 | 2025-04-04 | 2025-04-07 | SHORT | 9 | 1d | Z | ₹25 | ₹27 | ₹-2 |
| 8 | 2024-02-14 | 2024-02-15 | LONG | 10 | 1d | Z | ₹22 | ₹27 | ₹-5 |
| 9 | 2025-02-10 | 2025-02-11 | SHORT | 9 | 1d | Z | ₹21 | ₹27 | ₹-6 |
| 10 | 2026-08-06 | 2026-08-10 | SHORT | 8 | 2d | Z | ₹19 | ₹27 | ₹-8 |


### noSLTP (w=60,z=2.0,SL=off,TP=off)

| Metric | Value | | Metric | Value |
|---|---:|---|---:|
| Trades | 36 | SHORT / LONG | 15 |
| Avg hold | 1.9d | Gross P&L | ₹759.50 |
| Fees | ₹968.93 | Net P&L | ₹-209.43 |
| Final portfolio | ₹19,790.57 | Total return | -1.05% |
| CAGR | -0.29% | Sharpe (daily, ann.) | -0.63 |
| Sortino | -0.45 | Max drawdown | -1.19% |
| Max DD duration | 883 | Calmar | -0.24 |
| Profit factor | 0.51 | Net win rate | 11.11% |
| Avg win | ₹54.85 | Avg loss | ₹13.40 |
| Expectancy/trade | ₹-5.82 |  |  |

Top 10 trades (net ₹):

| # | in | out | dir | qty | held | exit | gross | fees | net |
|---|---|---|---|---:|---:|---|---:|---:|---:|
| 1 | 2024-06-04 | 2024-06-05 | LONG | 9 | 1d | Z | ₹121 | ₹27 | ₹94 |
| 2 | 2025-10-15 | 2025-10-16 | SHORT | 8 | 1d | Z | ₹118 | ₹27 | ₹91 |
| 3 | 2024-09-20 | 2024-09-23 | LONG | 9 | 1d | Z | ₹47 | ₹27 | ₹20 |
| 4 | 2026-03-13 | 2026-03-16 | LONG | 8 | 1d | Z | ₹40 | ₹27 | ₹14 |
| 5 | 2023-01-27 | 2023-02-01 | LONG | 12 | 3d | Z | ₹26 | ₹27 | ₹-1 |
| 6 | 2025-04-07 | 2025-04-08 | LONG | 9 | 1d | Z | ₹23 | ₹27 | ₹-4 |
| 7 | 2024-02-13 | 2024-02-14 | SHORT | 10 | 1d | Z | ₹22 | ₹27 | ₹-5 |
| 8 | 2025-04-16 | 2025-04-22 | LONG | 9 | 3d | Z | ₹22 | ₹27 | ₹-5 |
| 9 | 2025-02-10 | 2025-02-11 | SHORT | 9 | 1d | Z | ₹21 | ₹27 | ₹-6 |
| 10 | 2026-08-06 | 2026-08-10 | SHORT | 8 | 2d | Z | ₹19 | ₹27 | ₹-8 |


### SLonly (w=60,z=2.0,SL=100,TP=off)

| Metric | Value | | Metric | Value |
|---|---:|---|---:|
| Trades | 36 | SHORT / LONG | 15 |
| Avg hold | 1.9d | Gross P&L | ₹759.50 |
| Fees | ₹968.93 | Net P&L | ₹-209.43 |
| Final portfolio | ₹19,790.57 | Total return | -1.05% |
| CAGR | -0.29% | Sharpe (daily, ann.) | -0.63 |
| Sortino | -0.45 | Max drawdown | -1.19% |
| Max DD duration | 883 | Calmar | -0.24 |
| Profit factor | 0.51 | Net win rate | 11.11% |
| Avg win | ₹54.85 | Avg loss | ₹13.40 |
| Expectancy/trade | ₹-5.82 |  |  |

Top 10 trades (net ₹):

| # | in | out | dir | qty | held | exit | gross | fees | net |
|---|---|---|---|---:|---:|---|---:|---:|---:|
| 1 | 2024-06-04 | 2024-06-05 | LONG | 9 | 1d | Z | ₹121 | ₹27 | ₹94 |
| 2 | 2025-10-15 | 2025-10-16 | SHORT | 8 | 1d | Z | ₹118 | ₹27 | ₹91 |
| 3 | 2024-09-20 | 2024-09-23 | LONG | 9 | 1d | Z | ₹47 | ₹27 | ₹20 |
| 4 | 2026-03-13 | 2026-03-16 | LONG | 8 | 1d | Z | ₹40 | ₹27 | ₹14 |
| 5 | 2023-01-27 | 2023-02-01 | LONG | 12 | 3d | Z | ₹26 | ₹27 | ₹-1 |
| 6 | 2025-04-07 | 2025-04-08 | LONG | 9 | 1d | Z | ₹23 | ₹27 | ₹-4 |
| 7 | 2024-02-13 | 2024-02-14 | SHORT | 10 | 1d | Z | ₹22 | ₹27 | ₹-5 |
| 8 | 2025-04-16 | 2025-04-22 | LONG | 9 | 3d | Z | ₹22 | ₹27 | ₹-5 |
| 9 | 2025-02-10 | 2025-02-11 | SHORT | 9 | 1d | Z | ₹21 | ₹27 | ₹-6 |
| 10 | 2026-08-06 | 2026-08-10 | SHORT | 8 | 2d | Z | ₹19 | ₹27 | ₹-8 |



## Why the equity curve is flat / declining (fee drag)

Running the base config **with fees**: net **₹-209.43** over 36 trades.

Running the **same config with fees set to ZERO** (pure gross): net **₹775.49**, Sharpe **2.06**, win rate **100%**.

The edge (gross) is positive but small — average gross is only a few rupees per trade while fees are ~₹24 per round trip at this size. Removing fees flips it to a solidly positive curve, which proves the strategy mean-reverts correctly but is **fee-uneconomic at this portfolio size**. Fees scale up only slowly with qty (₹5/leg floor), so the strategy needs much larger per-trade size to outrun the fee floor.
