#!/usr/bin/env bash
# Build and run the ML3 WATCH scanner.
#
# Usage:
#   ./run_scanner.sh            build + run live TUI
#   ./run_scanner.sh --headless build + run live, no TUI (logs to terminal)
#   ./run_scanner.sh --sim       build + run seeded replay
#   ./run_scanner.sh --build     build only
#
# Optional env overrides (also read from .env):
#   SCANNER_LEGS=AXISBANK,HDFCBANK   subset of legs to enable
#   SCANNER_POLL_SECS=4              live poll rate in seconds
set -euo pipefail

cd "$(dirname "$0")"

BIN=target/release/scanner
HEADLESS=0
SIM=0
BUILD_ONLY=0

for arg in "$@"; do
    case "$arg" in
        --headless) HEADLESS=1 ;;
        --sim)      SIM=1 ;;
        --build)    BUILD_ONLY=1 ;;
        *)          echo "unknown arg: $arg" >&2; exit 1 ;;
    esac
done

cargo build --release --bin scanner

if [ "$BUILD_ONLY" = "1" ]; then
    echo "built $BIN"
    exit 0
fi

ARGS=()
if [ "$SIM" = "1" ]; then
    ARGS+=(--sim)
else
    ARGS+=(--live)
    [ "$HEADLESS" = "1" ] && ARGS+=(--headless)
fi

exec "$BIN" "${ARGS[@]}"
