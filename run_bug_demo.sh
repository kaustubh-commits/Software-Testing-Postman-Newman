#!/usr/bin/env bash
# run_bug_demo.sh - BACKUP of the "bug mode" demo, from the terminal:
#   1. plants a bug in the running API (default: marks above 100 are accepted)
#   2. runs the Boundary suite, where the BVA-08 "Marks 101" test should FAIL
#   3. switches bug mode off again (always, even if you press Ctrl+C)
#
#   ./run_bug_demo.sh                 # marks_over_100 bug, Boundary suite
#   ./run_bug_demo.sh wrong_status    # POST returns 200 instead of 201
source "$(dirname "$0")/scripts/common.sh"
ensure_deps
cd "$ROOT"
BUG="${1:-marks_over_100}"

if PORT=$(find_running_app); then
  info "Using the server already running on port $PORT"
else
  PORT=$(find_free_port) || { fail "No free port"; exit 1; }
  info "Starting a temporary server on port $PORT"
  start_server_bg "$PORT" || exit 1
fi

set_bug() {
  curl -s -X POST "http://127.0.0.1:$PORT/control/bug-mode" \
       -H "Content-Type: application/json" -d "{\"enabled\": $1, \"type\": \"$BUG\"}" >/dev/null
}
cleanup() { set_bug false; info "Bug mode switched OFF again"; [ -n "$SERVER_PID" ] && kill "$SERVER_PID" 2>/dev/null; }
trap cleanup EXIT

set_bug true
printf "\n\033[1;31m⚠  BUG MODE ON:\033[0m %s\n" "$BUG"
info "Running the Boundary suite. Expect at least one test to FAIL."
"$ROOT/run_tests.sh" Boundary
CODE=$?
echo
if [ $CODE -ne 0 ]; then
  ok "Newman caught the planted bug (see the failed assertions above)."
else
  fail "No failures. The bug was NOT caught."
fi
