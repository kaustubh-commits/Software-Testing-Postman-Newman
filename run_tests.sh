#!/usr/bin/env bash
# run_tests.sh - BACKUP: run the Postman collection with the Newman CLI
# (no dashboard needed). Uses the running server, or starts one temporarily.
#
#   ./run_tests.sh               # all six suites
#   ./run_tests.sh Boundary Auth # only some suites
#
# Writes one htmlextra report per suite plus index.html to reports/cli/<time>/
# Exit code is non-zero when any test fails (this is what CI pipelines use).
source "$(dirname "$0")/scripts/common.sh"
ensure_deps
cd "$ROOT"

if PORT=$(find_running_app); then
  info "Using the server already running on port $PORT"
else
  PORT=$(find_free_port) || { fail "No free port"; exit 1; }
  info "Starting a temporary server on port $PORT"
  start_server_bg "$PORT" || exit 1
  trap 'kill $SERVER_PID 2>/dev/null' EXIT
fi

SUITES=("$@")
[ ${#SUITES[@]} -eq 0 ] && SUITES=(Positive Negative Boundary Auth Chaining Data-Driven)
OUT="reports/cli/$(date +%Y%m%d-%H%M%S)"
mkdir -p "$OUT"
ROWS=""
FAILED=0

for SUITE in "${SUITES[@]}"; do
  echo
  info "Running suite: $SUITE"
  DATA=()
  [ "$SUITE" = "Data-Driven" ] && DATA=(-d postman/data/students.csv)
  # The actual Newman command (this is what you would put in a CI pipeline):
  npx newman run postman/Student_Management_API.postman_collection.json \
      -e postman/Local.postman_environment.json \
      --folder "$SUITE" "${DATA[@]}" \
      --env-var "baseUrl=http://127.0.0.1:$PORT" \
      -r cli,htmlextra --reporter-htmlextra-export "$OUT/$SUITE.html" \
      --reporter-htmlextra-title "Student API - $SUITE suite"
  if [ $? -eq 0 ]; then RESULT="PASS"; else RESULT="FAIL"; FAILED=$((FAILED + 1)); fi
  ROWS+="<tr><td>$SUITE</td><td class=\"$RESULT\">$RESULT</td><td><a href=\"$SUITE.html\">Open report →</a></td></tr>"
  SUMMARY+="$(printf '  %-12s %s' "$SUITE" "$RESULT")"$'\n'
done

# One index page that links every suite report
cat > "$OUT/index.html" <<HTML
<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Newman CLI run</title>
<style>body{font-family:-apple-system,Segoe UI,sans-serif;background:#0f141b;color:#e6edf3;padding:40px}
table{border-collapse:collapse;min-width:480px}td,th{padding:12px 16px;border-bottom:1px solid #243041;text-align:left}
.PASS{color:#3fb950;font-weight:700}.FAIL{color:#f85149;font-weight:700}a{color:#58a6ff}</style></head>
<body><h1>Student API: Newman CLI run</h1><p>$(date)</p>
<table><tr><th>Suite</th><th>Result</th><th>Report</th></tr>$ROWS</table></body></html>
HTML

echo
echo "Summary"
printf "%s" "$SUMMARY"
echo
info "Reports: $OUT/index.html"
if [ $FAILED -eq 0 ]; then ok "All suites passed"; else fail "$FAILED suite(s) had failures"; fi
exit $FAILED
