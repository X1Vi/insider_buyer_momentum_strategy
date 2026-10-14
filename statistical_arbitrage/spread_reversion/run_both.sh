#!/usr/bin/env bash
# Run BOTH screeners together:
#   1) the Ross-style momentum screener (prints the candidates table)
#   2) the ML WATCH scanner (TUI takes over after the screener prints)
#
# For truly simultaneous use, run them in two terminals instead:
#   term 1:  ./run_screener.sh
#   term 2:  ./run_scanner.sh --sim
#
# Usage:
#   ./run_both.sh               # screener (all sectors) + LIVE scanner
#   ./run_both.sh --sim         # screener + offline sim scanner
#   ./run_both.sh --headless    # screener + live scanner without TUI
#   SCREENER_HOT=1 ./run_both.sh --sim   # screener only hot sector + sim
set -euo pipefail

cd "$(dirname "$0")"

echo "========== ROSS-STYLE MOMENTUM SCREENER (read-only) =========="
./run_screener.sh

echo
echo "========== ML WATCH SCANNER (read-only) =========="
./run_scanner.sh "$@"
