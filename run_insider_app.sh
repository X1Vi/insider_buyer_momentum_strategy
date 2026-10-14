#!/usr/bin/env bash
#
# run_insider_app.sh — start the Insider-momentum app (read-only Rust API + React UI).
#
#   Backend : statistical_arbitrage/spread_reversion  -> target/debug/api_server   :8787
#   Frontend: strategy_categories/could_work/india_insider_drift/web (Vite)        :5175
#
# Everything is READ-ONLY: no orders, no keys in the frontend. NSE/Groww data is
# cached for 24h; the app never hammers the source per request.
#
# Usage:
#   ./run_insider_app.sh                 # start backend + frontend
#   INSIDER_FRONTEND_PORT=5180 ./run_insider_app.sh
#   Ctrl-C to stop both.
#
set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$ROOT_DIR/strategy_categories/could_work/india_insider_drift"
BACKEND_DIR="$ROOT_DIR/statistical_arbitrage/spread_reversion"
FRONTEND_DIR="$APP_DIR/web"
LOG_DIR="$APP_DIR/data/app_logs"

export INSIDER_CACHE_DIR="${INSIDER_CACHE_DIR:-$APP_DIR/data/app_cache}"
export INSIDER_SEED_DIR="${INSIDER_SEED_DIR:-$APP_DIR/data/raw}"
FRONTEND_PORT="${INSIDER_FRONTEND_PORT:-5175}"
BACKEND_PORT=8787

mkdir -p "$LOG_DIR" "$INSIDER_CACHE_DIR"

for cmd in cargo npm curl ss setsid; do
  command -v "$cmd" >/dev/null 2>&1 || { echo "Missing required command: $cmd" >&2; exit 1; }
done

if ss -ltn 2>/dev/null | grep -qE "127\\.0\\.0\\.1:${BACKEND_PORT}\\b"; then
  echo "Port ${BACKEND_PORT} already in use — stop the existing backend first." >&2
  exit 1
fi
if ss -ltn 2>/dev/null | grep -qE "127\\.0\\.0\\.1:${FRONTEND_PORT}\\b"; then
  echo "Port ${FRONTEND_PORT} already in use — set INSIDER_FRONTEND_PORT=... and retry." >&2
  exit 1
fi

if [[ ! -d "$FRONTEND_DIR/node_modules" ]]; then
  echo "Installing frontend dependencies…"
  (cd "$FRONTEND_DIR" && npm ci)
fi

echo "Building the read-only Rust API…"
(cd "$BACKEND_DIR" && cargo build --bin api_server)

BACKEND_PID=""
FRONTEND_PID=""
cleanup() {
  trap - EXIT INT TERM
  [[ -n "$FRONTEND_PID" ]] && kill -- "-$FRONTEND_PID" 2>/dev/null || true
  [[ -n "$BACKEND_PID" ]] && kill -- "-$BACKEND_PID" 2>/dev/null || true
  wait "$FRONTEND_PID" "$BACKEND_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "Starting backend (127.0.0.1:${BACKEND_PORT})…"
setsid bash -c 'cd -- "$1" && exec ./target/debug/api_server' _ "$BACKEND_DIR" \
  >"$LOG_DIR/backend.log" 2>&1 &
BACKEND_PID=$!

for _ in $(seq 1 60); do
  if curl --silent --fail "http://127.0.0.1:${BACKEND_PORT}/health" >"$LOG_DIR/health.json"; then
    break
  fi
  if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
    echo "Backend stopped during startup:" >&2
    tail -n 30 "$LOG_DIR/backend.log" >&2 || true
    exit 1
  fi
  sleep 1
done
curl --silent --fail "http://127.0.0.1:${BACKEND_PORT}/health" >/dev/null \
  || { echo "Backend not healthy — see $LOG_DIR/backend.log" >&2; exit 1; }

echo "Starting frontend (127.0.0.1:${FRONTEND_PORT})…"
setsid bash -c 'cd -- "$1" && exec npm run dev -- --host 127.0.0.1 --port "$2" --strictPort' \
  _ "$FRONTEND_DIR" "$FRONTEND_PORT" >"$LOG_DIR/frontend.log" 2>&1 &
FRONTEND_PID=$!

cat <<EOF

  Insider-momentum app is up:
    UI      http://127.0.0.1:${FRONTEND_PORT}
    API     http://127.0.0.1:${BACKEND_PORT}/health
    cache   ${INSIDER_CACHE_DIR}
    logs    ${LOG_DIR}

  The backend's background collector pulls the NEW NSE insider source (-gg + XBRL)
  in the background on first run (a few minutes); it is cached for 24h.
  Press Ctrl-C to stop both.
EOF

wait -n "$BACKEND_PID" "$FRONTEND_PID"
status=$?
echo "A process stopped (exit $status). Logs in $LOG_DIR." >&2
exit "$status"
