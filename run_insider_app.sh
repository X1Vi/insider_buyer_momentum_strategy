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
# LAN access: the frontend binds to 0.0.0.0 so other machines on the same
# router/LAN can open it at  http://<this-machine-ip>:<port>. The backend stays
# on 127.0.0.1 (the Vite proxy reaches it locally), so only the UI is exposed.
# Keep it local-only with INSIDER_FRONTEND_HOST=127.0.0.1.
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
# 0.0.0.0 = reachable from other machines on the LAN. Set to 127.0.0.1 for
# local-only access.
FRONTEND_HOST="${INSIDER_FRONTEND_HOST:-0.0.0.0}"
BACKEND_PORT=8787

mkdir -p "$LOG_DIR" "$INSIDER_CACHE_DIR"

for cmd in cargo npm curl ss setsid; do
  command -v "$cmd" >/dev/null 2>&1 || { echo "Missing required command: $cmd" >&2; exit 1; }
done

if ss -ltn 2>/dev/null | grep -qE ":${BACKEND_PORT}\\b"; then
  echo "Port ${BACKEND_PORT} already in use — stop the existing backend first." >&2
  exit 1
fi
if ss -ltn 2>/dev/null | grep -qE ":${FRONTEND_PORT}\\b"; then
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

echo "Starting frontend (${FRONTEND_HOST}:${FRONTEND_PORT})…"
setsid bash -c 'cd -- "$1" && exec npm run dev -- --host "$2" --port "$3" --strictPort' \
  _ "$FRONTEND_DIR" "$FRONTEND_HOST" "$FRONTEND_PORT" >"$LOG_DIR/frontend.log" 2>&1 &
FRONTEND_PID=$!

LAN_IP="$(ip -4 route get 1.1.1.1 2>/dev/null | sed -n 's/.* src \([0-9.]*\).*/\1/p' | head -n1)"
[[ -n "$LAN_IP" ]] || LAN_IP="$(hostname -I 2>/dev/null | tr ' ' '\n' | grep -E '^[0-9]+\.' | head -n1)"

cat <<EOF

  Insider-momentum app is up:
    UI (this machine)  http://127.0.0.1:${FRONTEND_PORT}
    UI (LAN)           http://${LAN_IP:-<this-machine-ip>}:${FRONTEND_PORT}
    API                http://127.0.0.1:${BACKEND_PORT}/health  (localhost only)
    cache              ${INSIDER_CACHE_DIR}
    logs               ${LOG_DIR}

  Other machines on the same router/LAN can open the "UI (LAN)" URL above.
  If nothing loads from another machine, allow TCP ${FRONTEND_PORT} through the
  firewall (e.g. \`sudo ufw allow ${FRONTEND_PORT}/tcp\`).

  The backend's background collector pulls the NEW NSE insider source (-gg + XBRL)
  in the background on first run (a few minutes); it is cached for 24h.
  Press Ctrl-C to stop both.
EOF

wait -n "$BACKEND_PID" "$FRONTEND_PID"
status=$?
echo "A process stopped (exit $status). Logs in $LOG_DIR." >&2
exit "$status"
