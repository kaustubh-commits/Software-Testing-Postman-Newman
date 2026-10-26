#!/usr/bin/env bash
# start.sh - ONE command to start the whole demo:
#   1. installs dependencies if they are missing
#   2. starts the server (API + Test Control Center) on port 8000,
#      or the next free port if 8000 is used by something else
#   3. opens the dashboard in the browser
# Stop the server with Ctrl+C.
set -e
source "$(dirname "$0")/scripts/common.sh"
ensure_deps

# Already running? Just open the browser.
if PORT=$(find_running_app); then
  ok "Test Control Center is already running on port $PORT"
  open "http://localhost:$PORT/"
  exit 0
fi

PORT=$(find_free_port) || { fail "No free port between 8000 and 8020"; exit 1; }
[ "$PORT" != "8000" ] && info "Port 8000 is used by another program, using port $PORT instead"

echo
printf "\033[1m  Student API + Newman Test Control Center\033[0m\n"
echo "  Dashboard : http://localhost:$PORT/"
echo "  Swagger   : http://localhost:$PORT/docs"
echo "  Stop      : Ctrl+C"
echo

# Open the browser as soon as the server answers (in the background)
( for _ in $(seq 60); do is_our_app "$PORT" && { open "http://localhost:$PORT/"; break; }; sleep 0.25; done ) &

cd "$ROOT"
APP_PORT="$PORT" exec .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port "$PORT" --log-level warning
