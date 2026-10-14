# AI Rules — spread_reversion Trading System

## CRITICAL: Read Before Any Code Changes

### API Access Rules
- We can call **ONLY TWO** Groww API endpoints:
  1. **Token generation** — `POST /v1/token/api/access` using API key/secret (SHA256 checksum flow, see https://groww.in/trade-api/docs/curl), or a pre-generated access token, from env vars
  2. **Live Quote** — `GET /v1/live-data/quote?exchange=NSE&segment=CASH&trading_symbol={SYMBOL}`

- **Read-only universe/backtest access (approved 2026-09-10, NO orders):**
  3. **Instruments list** — public static CSV: `GET https://growwapi-assets.groww.in/instruments/instrument.csv` (unauthenticated; used to enumerate the NSE CASH EQ universe for screening; cache it locally)
  4. **Historical candles** — `GET /v1/historical/candles?exchange=NSE&segment=CASH&groww_symbol=NSE-{SYMBOL}&start_time=...&end_time=...&candle_interval=1day` (authenticated; used to backtest candidates before they enter the screener watchlist; cache the CSVs in backtesting/data/)
- These two extra endpoints are **read-only data access only**. They are never used to place, modify, or cancel orders.

- **Binance public market data (approved 2026-09-11, NO auth, NO orders):**
  5. **Daily klines** — `GET https://api.binance.com/api/v3/klines?symbol={SYMBOL}&interval=1d&limit=1000[&startTime={ms}]`
     (unauthenticated; `limit` is silently capped at 1000, so longer histories are paged with `startTime`)
  6. **Server time** — `GET https://api.binance.com/api/v3/time` (used to decide whether a bar has CLOSED;
     the local clock is never trusted for that)
  7. **24h ticker, filtered** — `GET https://api.binance.com/api/v3/ticker/24hr?symbols=[...]`
     (always pass `symbols=`; the unfiltered call is ~1.9 MB and costs weight 80 instead of 2)
- These three endpoints are **public, unauthenticated and read-only**. No Binance API key is stored,
  no request is ever signed, and no `/api/v3/order*` path may appear anywhere in this repository.
  `https://data-api.binance.vision` is an approved mirror for the same paths if the primary host
  returns HTTP 451. The client in `src/binance.rs` implements only these three calls.

### Trading Rules
- **ALL TRADING IS PAPER TRADING ONLY** — emulated through code, logged to files
- We NEVER execute real trades, place orders, or move money
- We NEVER call any order placement/modification/cancellation endpoints
- P&L is calculated and logged locally — it NEVER touches a real account

### Data Rules
- Only fetch data for instruments on an explicit watchlist: the Groww tokens we already hold
  (BANKBEES, SETFNIFBK for the ETF pair) and the crypto watchlist below.
- Rate limit (Groww): minimum 5-second interval between API calls
- Rate limit (Binance public): minimum 400 ms between requests while paging history, and at most
  one live evaluation per calendar day per symbol. The daily BTC bot makes ~2 requests/day.
- Cache data — don't fetch more than needed

### Pairs to Track
- Primary: BANKBEES.NS (Nippon Bank Bees) vs SETFNIFBK.NS (SBI Nifty Bank ETF)
- Secondary: NIFTYBEES.NS vs SETFNIF50.NS

### Strategy (from Pole 2007)
- Spread = log(BANKBEES_price) - β × log(SETFNIFBK_price) with β=1.0
- Entry: |z-score| > 2.0
- Exit: z-score crosses 0
- Half-life: ~0 days (nearly instant reversion)
- 75% rule hit rate on this pair: 73.4% in backtesting

### Crypto Watchlist (paper only)
- Default: `BTCUSDT`, `THETAUSDT` — the two coins that cleared the success bar in
  `volume_indicator_studies/documentation/reports/MASTER_TABLE_ALL.md`.
- Override with `BTC_WATCHLIST=SYM1,SYM2` in `.env`.
- Caveat kept deliberately visible: that list was chosen *because* those names scored well in the
  same backtest, so it is a selection-biased universe. 2 survivors out of 72 coins is close to what
  chance produces, and THETA's two sample halves were 1.07 then 0.49.

### Crypto Strategy (refined EMA squeeze + volume surge, daily bars)
- Indicators are computed on **CLOSED bars only**. Binance returns the still-forming bar as the last
  element of every `klines` response; it is dropped using Binance's own server time. Reading the
  forming bar is a repaint bug — the earlier Hummingbot port did exactly that.
- `entry = spread_pct < 10 AND EMA50 > EMA200 AND volume > 1.5x MA20(volume) AND close > EMA200 AND NOT exit`
- `exit  = close < EMA50 * 1.03`
- `stop  = 5% FIXED from the entry bar's close` — **not trailing**. Passing a float to vectorbt's
  boolean `sl_trail` silently made it trailing in the earlier reports; the authoritative run uses
  `sl_trail=False`.
- Size 20% of cash per trade, 0.10% fee + 0.05% slippage per side, first 200 bars discarded.
- The stop is evaluated on the **close**, not the intraday low — faithful to the backtest and to what
  a once-a-day bot can actually execute, but it understates drawdown versus a real intraday stop.
- Position state (entry price, stop reference, quantity, last processed bar) is **persisted to JSON**.
  An un-persisted entry price is how the earlier port left restarted positions stop-less.
- `btc_backtest` and `btc_bot` both call `engine::process_bar`; there is exactly one implementation
  of the rule in the tree, so the live bot cannot drift from what was validated.
