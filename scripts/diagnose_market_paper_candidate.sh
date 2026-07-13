#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="/opt/sharipovai-repo"
DEPLOY="$ROOT/deploy/vps"
SERVICE="sharipovai"

cd "$DEPLOY"
echo "[1/3] Building candidate image..."
docker compose build "$SERVICE"

echo "[2/3] Importing the full FastAPI application in an isolated container..."
docker compose run --rm --no-deps \
  -e PAPER_ACTIVITY_AUTORUN_ENABLED=0 \
  --entrypoint sh "$SERVICE" -lc '
set -Eeuo pipefail
python -m py_compile \
  /app/market_paper_engine.py \
  /app/paper_activity_autorun.py \
  /app/dashboard/paper_activity_api.py \
  /app/dashboard/realtime_status_api.py
python - <<"PY"
from dashboard.app import app
paths = sorted({getattr(route, "path", "") for route in app.routes})
print("APP_IMPORT_OK")
print("HEALTH_ROUTE_PRESENT=" + str("/health" in paths))
print("ROUTE_COUNT=" + str(len(paths)))
PY
'

echo "[3/3] Starting the candidate API in isolation and probing /health..."
docker compose run --rm --no-deps \
  -e PAPER_ACTIVITY_AUTORUN_ENABLED=0 \
  --entrypoint sh "$SERVICE" -lc '
set -Eeuo pipefail
log=/tmp/sharipovai-candidate.log
uvicorn dashboard.app:app --host 127.0.0.1 --port 8000 >"$log" 2>&1 &
pid=$!
cleanup() {
  kill "$pid" 2>/dev/null || true
  wait "$pid" 2>/dev/null || true
}
trap cleanup EXIT
for i in $(seq 1 45); do
  if curl --fail --silent --show-error http://127.0.0.1:8000/health >/tmp/health.json 2>/tmp/curl.err; then
    echo "CANDIDATE_HEALTH_OK"
    cat /tmp/health.json
    echo
    exit 0
  fi
  if ! kill -0 "$pid" 2>/dev/null; then
    echo "CANDIDATE_PROCESS_EXITED"
    cat "$log"
    exit 1
  fi
  sleep 1
done
echo "CANDIDATE_HEALTH_TIMEOUT"
cat /tmp/curl.err 2>/dev/null || true
cat "$log"
exit 1
'

echo "Candidate diagnostic completed without touching the production container."
