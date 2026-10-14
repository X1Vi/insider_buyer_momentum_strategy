#!/usr/bin/env bash
# Fetch recent major-insider buys (NSE) and test which stocks are in momentum.
# Only the LAST 1-2 MONTHS of insider activity are considered, anchored on the
# newest disclosure available (the NSE feed lags a few months).
# Standalone — does not touch the main spread_reversion crate or the web app.
#
# Usage:
#   ./run.sh                # last 60 days (~2 months), top 30, min Rs 25 lakh
#   ./run.sh 30             # last 1 month
#   ./run.sh 60 40 1000000  # + top 40, min value Rs 10 lakh
set -euo pipefail
cd "$(dirname "$0")"

RECENT_DAYS="${1:-60}"
TOP="${2:-30}"
MIN="${3:-2500000}"

echo "building (first run downloads crates)..."
cargo build --release --quiet
exec ./target/release/insider_momentum "$RECENT_DAYS" "$TOP" "$MIN"
