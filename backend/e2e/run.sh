#!/usr/bin/env bash
# Author: Ching Kao
# Student ID: 85768427
# Browser checks: the real frontend (MSW off) against the real backend.
#
# Starts the Vite dev server once, then for each scenario starts the backend
# with that scenario's settings, runs the scenario in Chrome, and stops the
# backend. Runtime data goes to a temporary folder, never to the repository.
#
# Usage, from anywhere:  backend/e2e/run.sh
# Needs: backend/.venv (see docs/backend-spec.md), `npm ci` in frontend/,
# Google Chrome (or E2E_BROWSER_CHANNEL=bundled), and free test ports 18081 and 15174.
set -euo pipefail

E2E_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "$E2E_DIR/.." && pwd)"
FRONTEND_DIR="$(cd "$BACKEND_DIR/../frontend" && pwd)"
DATA_DIR="$(mktemp -d)"
LOG_DIR="$DATA_DIR/logs"
mkdir -p "$LOG_DIR"

API_PORT=18081
UI_PORT=15174
export API_URL="http://127.0.0.1:$API_PORT/api"
export APP_URL="http://127.0.0.1:$UI_PORT"

FRONTEND_PID=""
BACKEND_PID=""

cleanup() {
  [ -n "$BACKEND_PID" ] && kill "$BACKEND_PID" 2>/dev/null || true
  [ -n "$FRONTEND_PID" ] && kill "$FRONTEND_PID" 2>/dev/null || true
  wait 2>/dev/null || true
  rm -rf "$DATA_DIR"
}
trap cleanup EXIT

port_in_use() { lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1; }

wait_for() {  # wait_for URL NAME LOGFILE
  for _ in $(seq 1 60); do
    curl -s -o /dev/null "$1" && return 0
    sleep 0.5
  done
  echo "$2 did not start; log:" >&2
  cat "$3" >&2
  return 1
}

for port in "$API_PORT" "$UI_PORT"; do
  if port_in_use "$port"; then
    echo "Port $port is already in use; stop that server first." >&2
    exit 1
  fi
done
[ -x "$BACKEND_DIR/.venv/bin/uvicorn" ] || { echo "Missing backend/.venv; see docs/backend-spec.md." >&2; exit 1; }
[ -d "$FRONTEND_DIR/node_modules" ] || { echo "Run 'npm ci' in frontend/ first." >&2; exit 1; }

echo "Starting the frontend (MSW off) ..."
(
  cd "$FRONTEND_DIR"
  VITE_ENABLE_MSW=false VITE_API_BASE_URL="$API_URL" \
    exec npx vite --host 127.0.0.1 --port "$UI_PORT" --strictPort
) >"$LOG_DIR/frontend.log" 2>&1 &
FRONTEND_PID=$!
wait_for "$APP_URL" "The frontend" "$LOG_DIR/frontend.log"

start_backend() {  # start_backend NAME [ENV=VALUE ...]
  local name="$1" factory="$2"; shift 2
  (
    cd "$BACKEND_DIR"
    exec env AI_CODER_WORKSPACES_ROOT="$DATA_DIR/$name" AI_CODER_CORS_ORIGINS="$APP_URL" \
      CHAT_RECORD_PATH="$LOG_DIR/$name-chat.jsonl" LLM_RECORD_PATH="$LOG_DIR/$name-llm.jsonl" "$@" \
      .venv/bin/uvicorn "$factory" --factory --app-dir tests --port "$API_PORT"
  ) >"$LOG_DIR/backend-$name.log" 2>&1 &
  BACKEND_PID=$!
  wait_for "$API_URL/health" "The backend" "$LOG_DIR/backend-$name.log"
}

stop_backend() {
  kill "$BACKEND_PID" 2>/dev/null || true
  wait "$BACKEND_PID" 2>/dev/null || true
  BACKEND_PID=""
}

FAILED=0
scenario() {  # scenario SCRIPT
  node "$E2E_DIR/$1" || FAILED=1
}

chat_run() {
  start_backend chat-run browser_apps:tdd
  scenario chat-run.mjs
  stop_backend
}

if [[ "${1:-}" == "chat-run" ]]; then
  chat_run
  exit "$FAILED"
fi

if [[ "${1:-}" == "codex-chat" ]]; then
  start_backend codex-chat browser_apps:codex
  scenario codex-chat.mjs
  stop_backend
  exit "$FAILED"
fi

if [[ "${1:-}" == "preview" ]]; then
  start_backend preview browser_apps:preview
  scenario preview.mjs
  stop_backend
  exit "$FAILED"
fi

start_backend workspaces ai_coder.main:create_app
scenario workspaces.mjs
stop_backend

start_backend blocked browser_apps:tdd AI_CODER_MAX_REPAIRS=0
scenario blocked-run.mjs
stop_backend

chat_run

start_backend codex-chat browser_apps:codex
scenario codex-chat.mjs
stop_backend

start_backend preview browser_apps:preview
scenario preview.mjs
stop_backend

# No backend at all.
scenario backend-down.mjs

echo
if [ "$FAILED" -eq 0 ]; then
  echo "All browser checks passed."
else
  echo "Some browser checks failed (see FAIL lines above)."
fi
exit "$FAILED"
