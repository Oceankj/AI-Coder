#!/usr/bin/env bash
# Browser checks: the real frontend (MSW off) against the real backend.
#
# Starts the Vite dev server once, then for each scenario starts the backend
# with that scenario's settings, runs the scenario in Chrome, and stops the
# backend. Runtime data goes to a temporary folder, never to the repository.
#
# Usage, from anywhere:  backend/e2e/run.sh
# Needs: backend/.venv (see docs/backend-spec.md), `npm ci` in frontend/,
# Google Chrome (or E2E_BROWSER_CHANNEL=bundled), and free ports 8000 and 5173.
set -euo pipefail

E2E_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "$E2E_DIR/.." && pwd)"
FRONTEND_DIR="$(cd "$BACKEND_DIR/../frontend" && pwd)"
DATA_DIR="$(mktemp -d)"
LOG_DIR="$DATA_DIR/logs"
mkdir -p "$LOG_DIR"

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

for port in 8000 5173; do
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
  VITE_ENABLE_MSW=false VITE_API_BASE_URL=http://localhost:8000/api \
    exec npx vite --host 127.0.0.1 --port 5173 --strictPort
) >"$LOG_DIR/frontend.log" 2>&1 &
FRONTEND_PID=$!
wait_for http://127.0.0.1:5173/ "The frontend" "$LOG_DIR/frontend.log"

start_backend() {  # start_backend NAME [ENV=VALUE ...]
  local name="$1"; shift
  (
    cd "$BACKEND_DIR"
    exec env AI_CODER_WORKSPACES_ROOT="$DATA_DIR/$name" "$@" \
      .venv/bin/uvicorn ai_coder.main:create_app --factory --app-dir src --port 8000
  ) >"$LOG_DIR/backend-$name.log" 2>&1 &
  BACKEND_PID=$!
  wait_for http://localhost:8000/api/health "The backend" "$LOG_DIR/backend-$name.log"
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

start_backend workspaces
scenario workspaces.mjs
stop_backend

# Placeholder Tester fails its first task, so the run uses one repair.
start_backend run AI_CODER_PLACEHOLDER_DELAY_SECONDS=0.5 AI_CODER_PLACEHOLDER_TEST_FAILURES=1
scenario run.mjs
stop_backend

# Placeholder Tester always fails and one repair is allowed, so the run fails.
start_backend failed-run AI_CODER_PLACEHOLDER_DELAY_SECONDS=0.3 \
  AI_CODER_PLACEHOLDER_TEST_FAILURES=99 AI_CODER_MAX_REPAIRS=1
scenario failed-run.mjs
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
