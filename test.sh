#!/usr/bin/env bash
#
# test.sh — one-shot smoke test for Provenance Guard.
# Starts the Flask app, runs a few requests, then shuts it down.
#
# Usage:
#   ./test.sh           run the endpoint tests (starts + stops the server)
#   ./test.sh signal    just run the signal function directly (no server)

set -euo pipefail
cd "$(dirname "$0")"

PY=./.venv/bin/python
BASE=http://127.0.0.1:5000

pretty() { "$PY" -m json.tool; }

# --- mode: signal-only ---
if [[ "${1:-}" == "signal" ]]; then
  echo "=== Signal function (direct) ==="
  "$PY" signals.py
  exit 0
fi

# --- mode: full endpoint test ---
echo "Starting server..."
"$PY" app.py > /tmp/provguard-test.log 2>&1 &
SERVER_PID=$!

# Make sure we always stop the server, even on error.
cleanup() { kill "$SERVER_PID" 2>/dev/null || true; }
trap cleanup EXIT

# Wait for the server to come up (poll /health).
for _ in {1..20}; do
  if curl -s "$BASE/health" >/dev/null 2>&1; then break; fi
  sleep 0.3
done

echo
echo "=== /health ==="
curl -s "$BASE/health" | pretty

echo
echo "=== /submit — AI-looking text ==="
curl -s -X POST "$BASE/submit" -H "Content-Type: application/json" \
  -d '{"text":"In todays fast-paced world, it is important to note that leveraging synergies unlocks our full potential and helps us navigate the complexities of modern life.","creator_id":"test-user-1"}' \
  | pretty

echo
echo "=== /submit — human-looking text ==="
curl -s -X POST "$BASE/submit" -H "Content-Type: application/json" \
  -d '{"text":"honestly the bus was late again, third time this week. i just stood there cold thinking about nothing really. maybe lunch, maybe not."}' \
  | pretty

echo
echo "=== /submit — too short (expect 400) ==="
curl -s -X POST "$BASE/submit" -H "Content-Type: application/json" \
  -d '{"text":"hi"}' | pretty

echo
echo "=== /submit — missing text (expect 400) ==="
curl -s -X POST "$BASE/submit" -H "Content-Type: application/json" \
  -d '{}' | pretty

echo
echo "Done. Stopping server."
