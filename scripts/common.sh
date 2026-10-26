#!/usr/bin/env bash
# common.sh - helper functions shared by start.sh, run_tests.sh and run_bug_demo.sh
# (it is "sourced" by those scripts, not run on its own)

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_ID='"app":"student-mgmt-aat"'          # what our /health endpoint returns
export NODE_OPTIONS="--no-deprecation"     # hide a harmless Node warning from a dependency

info()  { printf "\033[1;36m▸\033[0m %s\n" "$*"; }
ok()    { printf "\033[1;32m✔\033[0m %s\n" "$*"; }
fail()  { printf "\033[1;31m✘\033[0m %s\n" "$*"; }

# Is OUR app answering on this port?
is_our_app() { curl -s -m 1 "http://127.0.0.1:$1/health" 2>/dev/null | grep -q "$APP_ID"; }

# Is anything at all listening on this port?
port_busy() { lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1; }

# Print the port our app is already running on (8000-8020), if any
find_running_app() {
  for p in $(seq 8000 8020); do
    if is_our_app "$p"; then echo "$p"; return 0; fi
  done
  return 1
}

# Print the first free port from 8000 upwards (never kills anything)
find_free_port() {
  for p in $(seq 8000 8020); do
    if ! port_busy "$p"; then echo "$p"; return 0; fi
  done
  return 1
}

# Install Python and Node dependencies only if they are missing
ensure_deps() {
  command -v python3 >/dev/null || { fail "python3 not found. Install Python 3.9+"; exit 1; }
  command -v node >/dev/null    || { fail "node not found. Install Node.js 18+ from nodejs.org"; exit 1; }
  cd "$ROOT"
  if [ ! -x .venv/bin/uvicorn ]; then
    info "Creating Python virtual environment and installing FastAPI + Uvicorn…"
    python3 -m venv .venv && .venv/bin/pip install -q --disable-pip-version-check -r requirements.txt
  fi
  if [ ! -d node_modules/newman ] || [ ! -d node_modules/newman-reporter-htmlextra ]; then
    info "Installing newman, newman-reporter-htmlextra and chart.js (npm)…"
    npm install --no-audit --no-fund --silent
  fi
}

# Start the server in the background on port $1 and wait until /health answers
start_server_bg() {
  cd "$ROOT"
  APP_PORT="$1" .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port "$1" --log-level warning &
  SERVER_PID=$!
  for _ in $(seq 40); do is_our_app "$1" && return 0; sleep 0.25; done
  fail "Server did not start on port $1"; return 1
}
