#!/usr/bin/env bash
# Fetch RECENT NSE insider filings (new -gg endpoint + XBRL) — the live source.
# The old /corporates-pit endpoint stopped at 2026-04-30.
#
# Usage:
#   ./run.sh            # last 30 days, cap 200 XBRL fetches
#   ./run.sh 60 400     # last 60 days, cap 400
#   ./run.sh 30 0       # last 30 days, no cap (fetches every filing)
set -euo pipefail
cd "$(dirname "$0")"

DAYS="${1:-30}"
LIMIT="${2:-200}"

echo "building (first run downloads crates)..."
cargo build --release --quiet
exec ./target/release/pit_gg "$DAYS" "$LIMIT"
