#!/usr/bin/env bash
# Build and run the two-stage Ross-style momentum screener (read-only).
#
# Data cache (backtesting/ross/ross_data) is populated by:
#   .venv/bin/python backtesting/ross/fetch_data.py            # sector ETFs
#   .venv/bin/python backtesting/ross/fetch_data.py <SECTOR>   # a sector's stocks
#
# Usage:
#   ./run_screener.sh                # rank all sectors + any cached stocks
#   ./run_screener.sh --sector BANK  # only rank that sector's stocks
#   ./run_screener.sh --fetch        # refresh sector-ETF cache, then rank
#   SCREENER_HOT=1 ./run_screener.sh # only drill into the hot sector
set -euo pipefail

cd "$(dirname "$0")"

ARGS=()
for arg in "$@"; do
    case "$arg" in
        --fetch)
            .venv/bin/python backtesting/ross/fetch_data.py
            ;;
        *)
            ARGS+=("$arg")
            ;;
    esac
done

cargo build --release --bin screener
exec ./target/release/screener "${ARGS[@]}"
