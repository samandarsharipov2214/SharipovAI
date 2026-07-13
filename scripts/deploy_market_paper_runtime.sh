#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="/opt/sharipovai-repo"
DEPLOY="$ROOT/deploy/vps"
SERVICE="sharipovai"
ROLLBACK_TAG="sharipovai-market-paper-rollback:latest"

cd "$DEPLOY"
old_image_id="$(docker inspect -f '{{.Image}}' "$SERVICE" 2>/dev/null || true)"
old_image_ref="$(docker inspect -f '{{.Config.Image}}' "$SERVICE" 2>/dev/null || true)"
if [[ -n "$old_image_id" ]]; then
  docker tag "$old_image_id" "$ROLLBACK_TAG"
fi

rollback() {
  if [[ -n "$old_image_ref" ]] && docker image inspect "$ROLLBACK_TAG" >/dev/null 2>&1; then
    echo "New runtime verification failed; restoring previous SharipovAI image."
    docker tag "$ROLLBACK_TAG" "$old_image_ref"
    docker compose up -d --no-deps --force-recreate "$SERVICE"
  fi
}

on_error() {
  status=$?
  rollback || true
  exit "$status"
}
trap on_error ERR

echo "[1/5] Building candidate image..."
docker compose build "$SERVICE"

echo "[2/5] Running focused tests and importing the complete FastAPI graph..."
docker compose run --rm --no-deps \
  -e PAPER_ACTIVITY_AUTORUN_ENABLED=0 \
  --entrypoint sh "$SERVICE" -lc '
set -Eeuo pipefail
python -m pytest \
  tests/test_market_paper_engine.py \
  tests/test_news_intelligence_runtime.py -q
python -m py_compile \
  /app/market_paper_engine.py \
  /app/paper_activity_autorun.py \
  /app/dashboard/paper_activity_api.py \
  /app/dashboard/realtime_status_api.py \
  /app/news_intelligence/models.py \
  /app/news_intelligence/sources.py \
  /app/news_intelligence/agents.py \
  /app/news_intelligence/hub.py \
  /app/news_intelligence/network.py
python - <<"PY"
from dashboard.app import app
paths = {getattr(route, "path", "") for route in app.routes}
assert "/health" in paths, "health route missing"
assert "/api/virtual-account/state" in paths, "virtual account route missing"
assert "/api/news-agents/status" in paths, "news agents route missing"
print("FULL_APP_IMPORT_OK")
PY
'

echo "[3/5] Probing candidate /health in isolation..."
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
for i in $(seq 1 60); do
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

echo "[4/5] Replacing production SharipovAI only after candidate verification..."
docker compose up -d --no-deps --force-recreate "$SERVICE"

health="starting"
for _ in $(seq 1 90); do
  health="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$SERVICE" 2>/dev/null || true)"
  if [[ "$health" == "healthy" ]]; then
    break
  fi
  if [[ "$health" == "unhealthy" || "$health" == "exited" || "$health" == "dead" ]]; then
    break
  fi
  sleep 2
done

if [[ "$health" != "healthy" ]]; then
  echo "SharipovAI health check failed after 180s: $health" >&2
  docker inspect "$SERVICE" --format '{{json .State}}' 2>/dev/null || true
  docker logs --tail 160 "$SERVICE" 2>/dev/null || true
  rollback || true
  trap - ERR
  exit 1
fi

echo "[5/5] Verifying the running market-backed virtual account..."
docker exec "$SERVICE" python /app/scripts/verify_market_paper_runtime.py

trap - ERR
echo "Market-backed virtual account deployed and verified."
echo "Real exchange orders remain blocked."
