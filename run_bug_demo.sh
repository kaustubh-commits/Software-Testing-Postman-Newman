#!/usr/bin/env bash
# run_bug_demo.sh - BACKUP of the "bug mode" demo, from the terminal:
#   1. plants a bug in the running API (default: marks above 100 are accepted)
#   2. runs the suite(s) that should catch it, where some tests should FAIL
#   3. switches bug mode off again (always, even if you press Ctrl+C)
#
#   ./run_bug_demo.sh                 # marks_over_100 → Boundary (BVA-08 fails)
#   ./run_bug_demo.sh wrong_status    # POST returns 200 instead of 201 → Positive
#   ./run_bug_demo.sh auth_bypass     # wrong token accepted → Auth
#   ./run_bug_demo.sh name_length     # names over 50 chars accepted → Boundary
#   ./run_bug_demo.sh duplicate_usn   # duplicate USN allowed → Negative
#   ./run_bug_demo.sh slow_response   # GET /students takes 800 ms → Positive
#   ./run_bug_demo.sh wrong_body      # GET by id renames "age" → Positive
#   ./run_bug_demo.sh all             # every bug at once → all suites
source "$(dirname "$0")/scripts/common.sh"
ensure_deps
cd "$ROOT"
BUG="${1:-marks_over_100}"

# Which suite(s) catch which bug
case "$BUG" in
  marks_over_100|name_length) SUITES=(Boundary) ;;
  wrong_status|slow_response|wrong_body) SUITES=(Positive) ;;
  auth_bypass)   SUITES=(Auth) ;;
  duplicate_usn) SUITES=(Negative) ;;
  all)           SUITES=() ;;               # empty = run_tests.sh runs every suite
  *) fail "Unknown bug '$BUG'"; exit 1 ;;
esac

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
info "Running: ${SUITES[*]:-all suites}. Expect at least one test to FAIL."
"$ROOT/run_tests.sh" "${SUITES[@]}"
CODE=$?
echo
if [ $CODE -ne 0 ]; then
  ok "Newman caught the planted bug (see the failed assertions above)."
else
  fail "No failures. The bug was NOT caught."
fi
