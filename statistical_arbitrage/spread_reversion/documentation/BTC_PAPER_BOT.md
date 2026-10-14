# BTC Paper-Trading Bot (Rust)

**Paper trading only.** No exchange credentials, no signing code, and no order
endpoint is linked into any of these binaries. `src/binance.rs` implements
exactly three public GET endpoints and nothing else.

Built into the existing `spread_reversion` crate rather than a new project, so
it reuses the Pushover code in `src/notify.rs` instead of adding a fourth copy
of it.

---

## Quick start

```bash
cd /home/null/Documents/development/statistical_arbitrage/spread_reversion

./run_btc_bot.sh backtest        # re-validate the rule on Binance data
./run_btc_bot.sh backtest --all  # BTC + THETA
./run_btc_bot.sh screen          # one-shot screener table
./run_btc_bot.sh screen --push   # ...and send a Pushover digest
./run_btc_bot.sh once            # one paper-trading pass (cron-friendly)
./run_btc_bot.sh status          # print the paper account, change nothing
./run_btc_bot.sh run             # poll loop
```

Daily cron, a few minutes after the 00:00 UTC daily close:

```cron
7 0 * * * cd /home/null/Documents/development/statistical_arbitrage/spread_reversion && ./run_btc_bot.sh once >> btc_bot.cron.log 2>&1
```

`--once` is idempotent, so a missed run self-heals on the next one and an
overlapping run does nothing.

---

## Pushover — action required

`.env` currently has `PUSHOVER_USER_KEY` but **not `PUSHOVER_APP_TOKEN`**, so
every Pushover send in this repo has been silently no-oping. `pushover.log` is
wall-to-wall `SKIP: PUSHOVER_APP_TOKEN not set`.

Add the missing line to `.env`:

```
PUSHOVER_APP_TOKEN=<the API token from pushover.net "Your Applications">
```

Until then the bot still runs, warns loudly at startup, and falls back to a
desktop toast:

```
WARN PUSHOVER_APP_TOKEN is not set — phone alerts are DISABLED (desktop toast only).
```

`volume_screener.rs::update_env_token()` rewrites `.env` in place but preserves
every other line, so the new key will survive a token refresh.

---

## The strategy

Daily bars, closed bars only.

```
spread_pct = (max(EMA20, EMA50) - min(EMA20, EMA50)) / close * 100
entry = spread_pct < 10 AND EMA50 > EMA200 AND volume > 1.5 * MA20(volume)
        AND close > EMA200 AND NOT exit
exit  = close < EMA50 * 1.03
stop  = 5% FIXED below the entry bar's close
```

Sizing 20% of cash per trade. Costs 0.10% fee + 0.05% slippage per side. First
200 bars discarded as EMA200 warm-up.

---

## Validation — Rust vs Python, on different data

The Python research used yfinance `BTC-USD` (volume aggregated across venues).
The bot reads Binance `BTCUSDT` (single venue). The `volume > 1.5x` leg
therefore fires on different days, so an exact match was never expected. What
matters is that two independent implementations on two data vendors agree:

| | CAGR | Sharpe | MaxDD | Trades | Years |
|---|---:|---:|---:|---:|---:|
| Python / vectorbt, yfinance BTC-USD | 8.21% | 1.01 | −11.7% | 18 | 8.1 |
| **Rust / Binance BTCUSDT** | **9.03%** | **1.05** | **−11.81%** | **23** | 8.5 |
| Python / vectorbt, yfinance THETA-USD | 17.41% | 0.83 | −29.47% | 24 | 8.1 |
| **Rust / Binance THETAUSDT** | **18.79%** | **0.88** | **−28.24%** | **18** | 6.9 |

Read honestly: **BTC buy-and-hold returned 24.96% over the same window against
the strategy's 9.03%.** The rule de-risks BTC, it does not beat it. THETA is the
one name where the rule beats holding (18.79% vs 8.53%) — on 18 trades, with a
27.8% win rate, over 6.9 years. That is a small sample.

---

## Architecture

| File | Purpose |
|---|---|
| `src/lib.rs` | New lib target. `src/bin/*` are separate crates and could not reach `src/notify.rs` before this — which is why `pushover` was copy-pasted three times. |
| `src/binance.rs` | Public REST: daily klines (paged), server time, filtered 24h ticker. Retry with backoff; 451 points at the `data-api.binance.vision` mirror. |
| `src/strategy.rs` | The rule as a pure function. No I/O, no clock. |
| `src/engine.rs` | `process_bar` — the single place a bar becomes an action. |
| `src/paper.rs` | Paper ledger: fills, fees, persisted JSON state, CSV trade log. |
| `src/bin/btc_backtest.rs` | Replays klines through `engine::replay`. |
| `src/bin/btc_bot.rs` | Daily paper bot. |
| `src/bin/btc_screener.rs` | Watchlist screener, alert-only. |

**The live bot and the backtest call the same `engine::process_bar`.** There is
exactly one implementation of the rule in the tree, so the thing running cannot
drift from the thing that was validated.

---

## Defects in the earlier Hummingbot port, and how each is prevented here

| Defect | Fix |
|---|---|
| Read the **in-progress** daily candle (`close.iloc[-1]`), so a signal seen at 08:00 UTC could vanish by the close — a repaint bug | `binance::daily_closed` drops the forming bar structurally, using **Binance's** server time, not the local clock. There is no public method that returns raw pages. |
| `entry_price` / peak held in memory only — a restart while holding left the position permanently **stop-less** | Full position state persisted to JSON via write-temp-then-rename. Test: `state_round_trips_through_disk_with_an_open_position`. |
| Nothing stopped a bar being acted on twice | `already_processed(bar_open_time)`; the fill and the "bar seen" mark are written in one atomic save so they cannot disagree after a crash. |
| Backtest ran a 5% **trailing** stop while the docs and the live port said "5% fixed + 10% trailing" — `sl_trail` is a *boolean* in vectorbt, so the `0.10` was truthy and the value ignored | One fixed 5% stop, everywhere. Test: `fixed_stop_triggers_at_five_percent_down`. |
| Backtest volume came from yfinance, live volume from Binance — the volume leg could not reproduce | Measured, quantified in the table above, and the bot is validated on the data it actually trades. |
| Entry fee deducted from cash but never attributed to trade P&L, so realised P&L drifted from the balance | `pnl` includes both sides. Test: `realised_pnl_reconciles_with_cash`. |
| `logging::init` filters on `spread_reversion=info`, which silently discards everything a `src/bin/*` binary logs | `logging::init_filtered`; the bot passes `btc_bot=info,spread_reversion=info`. |

---

## Known limitations

1. **The stop is evaluated on the close, not the intraday low.** Faithful to the
   backtest (which never gave vectorbt a high/low series) and to what a
   once-a-day bot can execute — but it **understates drawdown** versus a real
   exchange stop. Do not read the paper equity curve as achievable with a
   resting stop order.
2. **The watchlist is selection-biased.** BTC and THETA were chosen *because*
   they scored well in the same study. 2 survivors out of 72 coins is close to
   what chance produces, and THETA's two sample halves were 1.07 then 0.49.
3. **Small samples.** 23 and 18 trades. A Sharpe from 18 observations has a very
   wide confidence interval.
4. **The rule loses to buy-and-hold on BTC** by a wide margin. Its appeal is a
   −11.8% drawdown against BTC's own, not its return.
5. **20% sizing with ~23% time in market** means most capital is idle most of
   the time. That is where the single-digit CAGR comes from; `Time in market` is
   printed so it stays visible.
6. **No intraday risk management.** Between daily closes the position is
   unmanaged.

---

## Tests

```bash
cargo test --lib          # 21 tests
```

Notable ones:
- `ema_matches_pandas_adjust_false` — pinned to pandas `ewm(span=3, adjust=False)` output, so signal dates cannot silently shift.
- `evaluate_never_reads_future_bars` — recomputes on a truncated series and asserts the same decision.
- `stop_does_not_fire_on_the_entry_bar`.
- `a_bar_that_exits_cannot_also_enter`.
- `sizing_matches_vectorbt_percent_of_cash` — the 20% is a cash budget the fee comes out of, not a notional it is added to.
- `realised_pnl_reconciles_with_cash`.
