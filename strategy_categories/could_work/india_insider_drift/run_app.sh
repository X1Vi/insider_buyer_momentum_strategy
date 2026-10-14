#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd -- "$APP_DIR/../../.." && pwd)"
BACKEND_DIR="$REPO_DIR/statistical_arbitrage/spread_reversion"
FRONTEND_DIR="$APP_DIR/web"
LOG_DIR="$APP_DIR/data/app_logs"
export INSIDER_CACHE_DIR="${INSIDER_CACHE_DIR:-$APP_DIR/data/app_cache}"
export INSIDER_SEED_DIR="${INSIDER_SEED_DIR:-$APP_DIR/data/raw}"
FRONTEND_PORT="${INSIDER_FRONTEND_PORT:-5175}"

mkdir -p "$LOG_DIR" "$INSIDER_CACHE_DIR"

for command_name in cargo npm curl ss setsid; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "Missing required command: $command_name" >&2
    exit 1
  fi
done

if ss -ltn 2>/dev/null | grep -qE '127\.0\.0\.1:8787\b'; then
  echo "Port 8787 is already in use. Stop the existing backend first." >&2
  exit 1
fi
if ss -ltn 2>/dev/null | grep -qE "127\\.0\\.0\\.1:${FRONTEND_PORT}\\b"; then
  echo "Port $FRONTEND_PORT is already in use. Set INSIDER_FRONTEND_PORT to another port." >&2
  exit 1
fi

if [[ ! -d "$FRONTEND_DIR/node_modules" ]]; then
  echo "Installing frontend dependencies..."
  (cd "$FRONTEND_DIR" && npm ci)
fi

echo "Building the read-only Rust API..."
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

echo "Starting backend..."
setsid bash -c 'cd -- "$1" && exec ./target/debug/api_server' _ "$BACKEND_DIR" >"$LOG_DIR/backend.log" 2>&1 &
BACKEND_PID=$!

for _ in $(seq 1 60); do
  if curl --silent --fail http://127.0.0.1:8787/health >"$LOG_DIR/health.json"; then
    break
  fi
  if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
    echo "Backend stopped during startup:" >&2
    tail -n 30 "$LOG_DIR/backend.log" >&2 || true
    exit 1
  fi
  sleep 1
done
if ! curl --silent --fail http://127.0.0.1:8787/health >/dev/null; then
  echo "Backend did not become healthy. See $LOG_DIR/backend.log" >&2
  exit 1
fi

echo "Starting frontend..."
setsid bash -c 'cd -- "$1" && exec npm run dev -- --host 127.0.0.1 --port "$2" --strictPort' _ "$FRONTEND_DIR" "$FRONTEND_PORT" >"$LOG_DIR/frontend.log" 2>&1 &
FRONTEND_PID=$!

echo
echo "Insider buyer app: http://127.0.0.1:$FRONTEND_PORT"
echo "Backend health:   http://127.0.0.1:8787/health"
echo "Cache:            $INSIDER_CACHE_DIR"
echo "Logs:             $LOG_DIR"
echo "NSE and Groww data are cached for 24h; requests are spaced by 6 seconds."
echo "Press Ctrl-C to stop both processes."

wait -n "$BACKEND_PID" "$FRONTEND_PID"
status=$?
echo "A process stopped (exit $status). Check logs in $LOG_DIR." >&2
exit "$status"
