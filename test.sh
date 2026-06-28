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
  -d '{"text":"honestly the bus was late again, third time this week. i just stood there cold thinking about nothing really. maybe lunch, maybe not.","creator_id":"test-user-2"}' \
  | pretty

echo
echo "=== /submit — too short (expect 400) ==="
curl -s -X POST "$BASE/submit" -H "Content-Type: application/json" \
  -d '{"text":"hi","creator_id":"test-user-3"}' | pretty

echo
echo "=== /submit — missing text (expect 400) ==="
curl -s -X POST "$BASE/submit" -H "Content-Type: application/json" \
  -d '{"creator_id":"test-user-4"}' | pretty


echo
echo "=== /submit — AI-Generated ==="
curl -s -X POST "$BASE/submit" -H "Content-Type: application/json" \
  -d '{"text": "Artificial intelligence represents a transformative paradigm shift in modern society. It is important to note that while the benefits of AI are numerous, it is equally essential to consider the ethical implications. Furthermore, stakeholders across various sectors must collaborate to ensure responsible deployment.","creator_id":"test-user-5"}' \
  | pretty

echo
echo "=== /submit — clearly human (casual review) ==="
curl -s -X POST "$BASE/submit" -H "Content-Type: application/json" \
  -d '{"text": "ok so i finally tried that new ramen place downtown and honestly? underwhelming. the broth was fine but they put WAY too much sodium in it and i was thirsty for like three hours after. my friend got the spicy version and said it was better. probably won'"'"'t go back unless someone drags me there","creator_id":"test-user-6"}' \
  | pretty

echo
echo "=== /submit — borderline: formal human ==="
curl -s -X POST "$BASE/submit" -H "Content-Type: application/json" \
  -d '{"text": "The relationship between monetary policy and asset price inflation has been extensively studied in the literature. Central banks face a fundamental tension between their mandate for price stability and the unintended consequences of prolonged low interest rates on equity and real estate valuations.","creator_id":"test-user-7"}' \
  | pretty

echo
echo "=== /submit — borderline: lightly edited AI ==="
curl -s -X POST "$BASE/submit" -H "Content-Type: application/json" \
  -d '{"text": "I'"'"'ve been thinking a lot about remote work lately. There are genuine tradeoffs — flexibility and no commute on one side, isolation and blurred work-life boundaries on the other. Studies show productivity varies widely by individual and role type.","creator_id":"test-user-8"}' \
  | pretty

echo
echo "Done. Stopping server."



