#!/usr/bin/env bash
# Build and run the BTC paper-trading bot / screener / backtest.
#
# PAPER TRADING ONLY. No exchange credentials are used and no order endpoint is
# linked into these binaries — see AGENTS.md for the approved endpoint list.
#
# Usage:
#   ./run_btc_bot.sh backtest              # re-validate the rule on Binance data
#   ./run_btc_bot.sh backtest --all        # whole watchlist
#   ./run_btc_bot.sh screen                # one-shot screener, prints a table
#   ./run_btc_bot.sh screen --push         # ...and send a Pushover digest
#   ./run_btc_bot.sh once                  # one paper-trading pass (for cron)
#   ./run_btc_bot.sh status                # print paper account, do nothing
#   ./run_btc_bot.sh run                   # poll loop (15 min default)
#
# Cron (daily, a few minutes after the 00:00 UTC daily close):
#   7 0 * * * cd /home/null/Documents/development/statistical_arbitrage/spread_reversion \
#             && ./run_btc_bot.sh once >> btc_bot.cron.log 2>&1
set -euo pipefail

# Must cd first: the paper state file, logs and .env are all resolved relative
# to the working directory, and volume_screener.rs::update_env_token() rewrites
# ./.env in place — running from elsewhere would write a stray .env there.
cd "$(dirname "$0")"

MODE="${1:-status}"
shift || true

case "$MODE" in
    backtest)
        cargo build --release --bin btc_backtest
        exec ./target/release/btc_backtest "$@"
        ;;
    screen|screener)
        cargo build --release --bin btc_screener
        exec ./target/release/btc_screener "$@"
        ;;
    once)
        cargo build --release --bin btc_bot
        exec ./target/release/btc_bot --once "$@"
        ;;
    status)
        cargo build --release --bin btc_bot
        exec ./target/release/btc_bot --status "$@"
        ;;
    run|daemon)
        cargo build --release --bin btc_bot
        exec ./target/release/btc_bot "$@"
        ;;
    *)
        echo "unknown mode: $MODE" >&2
        sed -n '2,18p' "$0" >&2
        exit 2
        ;;
esac
