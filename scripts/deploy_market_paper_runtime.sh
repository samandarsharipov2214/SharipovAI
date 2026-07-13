#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="/opt/sharipovai-repo"
DEPLOY="$ROOT/deploy/vps"
SERVICE="sharipovai"
CADDY_SERVICE="sharipovai-caddy"
ACTIVE_IMAGE_REF="vps-sharipovai:latest"
LOCAL_HEALTH="http://127.0.0.1:8000/health"
PUBLIC_HEALTH="https://85-137-88-17.sslip.io/health"

production_replaced=0
backup_container=""
old_network=""
proxy_network=""
data_volume=""
runtime_override=""
runtime_project="sharipovai-runtime-$(date +%s)-$$"

cd "$DEPLOY"

if docker container inspect "$CADDY_SERVICE" >/dev/null 2>&1; then
  proxy_network="$(docker inspect -f '{{range $name, $_ := .NetworkSettings.Networks}}{{println $name}}{{end}}' "$CADDY_SERVICE" | head -n 1 | tr -d '[:space:]')"
fi
if docker container inspect "$SERVICE" >/dev/null 2>&1; then
  old_network="$(docker inspect -f '{{range $name, $_ := .NetworkSettings.Networks}}{{println $name}}{{end}}' "$SERVICE" | head -n 1 | tr -d '[:space:]')"
  data_volume="$(docker inspect -f '{{range .Mounts}}{{if eq .Destination "/var/lib/sharipovai"}}{{.Name}}{{end}}{{end}}' "$SERVICE" | tr -d '[:space:]')"
fi
old_network="${proxy_network:-${old_network:-vps_default}}"
proxy_network="${proxy_network:-$old_network}"
data_volume="${data_volume:-vps_sharipovai_data}"

cleanup() {
  if [[ -n "$runtime_override" ]]; then
    rm -f "$runtime_override"
  fi
}
trap cleanup EXIT

refresh_caddy_route() {
  if ! docker container inspect "$CADDY_SERVICE" >/dev/null 2>&1; then
    echo "Caddy container is missing." >&2
    return 1
  fi
  if ! docker inspect -f '{{json .NetworkSettings.Networks}}' "$SERVICE" | grep -Fq "\"$proxy_network\""; then
    docker network connect --alias "$SERVICE" "$proxy_network" "$SERVICE"
  fi
  docker restart "$CADDY_SERVICE" >/dev/null
  for _ in $(seq 1 45); do
    if curl --fail --silent --show-error "$PUBLIC_HEALTH" >/tmp/public-health.json 2>/tmp/public-health.err; then
      cat /tmp/public-health.json
      echo
      return 0
    fi
    sleep 2
  done
  echo "Public Caddy route did not recover within 90 seconds." >&2
  cat /tmp/public-health.err 2>/dev/null || true
  docker logs --tail 160 "$CADDY_SERVICE" 2>/dev/null || true
  return 1
}

rollback() {
  if [[ "$production_replaced" != "1" ]]; then
    echo "Candidate verification failed before production replacement; running service was not touched."
    return 0
  fi

  echo "New runtime verification failed; restoring the previous SharipovAI container."
  if docker container inspect "$SERVICE" >/dev/null 2>&1; then
    docker rm -f "$SERVICE" >/dev/null 2>&1 || true
  fi

  if [[ -n "$backup_container" ]] && docker container inspect "$backup_container" >/dev/null 2>&1; then
    docker rename "$backup_container" "$SERVICE"
    if ! docker inspect -f '{{json .NetworkSettings.Networks}}' "$SERVICE" | grep -Fq "\"$proxy_network\""; then
      docker network connect --alias "$SERVICE" "$proxy_network" "$SERVICE"
    fi
    docker start "$SERVICE" >/dev/null
    for _ in $(seq 1 45); do
      if curl --fail --silent "$LOCAL_HEALTH" >/dev/null 2>&1; then
        if refresh_caddy_route; then
          echo "Previous SharipovAI container restored and publicly healthy."
          return 0
        fi
      fi
      sleep 2
    done
    echo "Previous container was restored but did not pass end-to-end health within 90 seconds." >&2
    docker logs --tail 160 "$SERVICE" 2>/dev/null || true
    return 1
  fi

  echo "No previous container snapshot is available for rollback." >&2
  return 1
}

on_error() {
  status=$?
  rollback || true
  exit "$status"
}
trap on_error ERR

echo "[1/6] Building candidate image..."
docker compose build "$SERVICE"
docker image inspect "$ACTIVE_IMAGE_REF" >/dev/null

echo "[2/6] Running focused tests and importing the complete FastAPI graph..."
docker compose run --rm --no-deps \
  -e PAPER_ACTIVITY_AUTORUN_ENABLED=0 \
  --entrypoint sh "$SERVICE" -lc '
set -Eeuo pipefail
export PYTHONPATH="/app${PYTHONPATH:+:$PYTHONPATH}"
cd /app
python -m pytest \
  tests/test_market_paper_engine.py \
  tests/test_news_intelligence_runtime.py \
  tests/test_lifecycle_compat.py \
  tests/test_ai_organ_safe_runtime.py \
  tests/test_verify_market_paper_runtime_script.py \
  tests/test_config_loader_cwd.py \
  tests/test_web2_page_ownership.py -q
python -m py_compile \
  /app/market_paper_engine.py \
  /app/paper_activity_autorun.py \
  /app/scripts/verify_market_paper_runtime.py \
  /app/config/loader.py \
  /app/dashboard/lifecycle_compat.py \
  /app/dashboard/ai_organ_state_safe_api.py \
  /app/dashboard/paper_activity_api.py \
  /app/dashboard/realtime_status_api.py \
  /app/news_intelligence/models.py \
  /app/news_intelligence/sources.py \
  /app/news_intelligence/agents.py \
  /app/news_intelligence/hub.py \
  /app/news_intelligence/network.py
cd /tmp
SHARIPOVAI_VERIFY_IMPORT_ONLY=1 python /app/scripts/verify_market_paper_runtime.py
python - <<"PY"
from config.loader import DEFAULT_CONFIG_PATH
from config.settings import settings
assert DEFAULT_CONFIG_PATH.is_absolute(), "default config path must be absolute"
assert DEFAULT_CONFIG_PATH.exists(), "default config file missing"
assert settings.market.exchange == "bybit", "default config did not load"
print("CONFIG_CWD_INDEPENDENT_OK")

from dashboard.app import app
paths = {getattr(route, "path", "") for route in app.routes}
assert "/health" in paths, "health route missing"
assert "/api/virtual-account/state" in paths, "virtual account route missing"
assert "/api/news-agents/status" in paths, "news agents route missing"
assert "/api/system/ai-organs" in paths, "AI organ monitor route missing"
print("FULL_APP_IMPORT_OK")
PY
'

echo "[3/6] Probing candidate /health in isolation..."
docker compose run --rm --no-deps \
  -e PAPER_ACTIVITY_AUTORUN_ENABLED=0 \
  --entrypoint sh "$SERVICE" -lc '
set -Eeuo pipefail
export PYTHONPATH="/app${PYTHONPATH:+:$PYTHONPATH}"
cd /app
log=/tmp/sharipovai-candidate.log
uvicorn dashboard.app:app --host 127.0.0.1 --port 8000 >"$log" 2>&1 &
pid=$!
cleanup_candidate() {
  kill "$pid" 2>/dev/null || true
  wait "$pid" 2>/dev/null || true
}
trap cleanup_candidate EXIT
for _ in $(seq 1 60); do
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

runtime_override="$(mktemp /tmp/sharipovai-runtime-XXXXXX.yml)"
cat >"$runtime_override" <<YAML
services:
  sharipovai:
    image: ${ACTIVE_IMAGE_REF}
volumes:
  sharipovai_data:
    external: true
    name: ${data_volume}
networks:
  default:
    external: true
    name: ${proxy_network}
YAML

docker compose -p "$runtime_project" \
  -f "$DEPLOY/docker-compose.yml" \
  -f "$runtime_override" \
  config --quiet

echo "[4/6] Replacing production while retaining the previous container for rollback..."
if docker container inspect "$SERVICE" >/dev/null 2>&1; then
  backup_container="${SERVICE}-rollback-$(date +%s)-$$"
  docker stop "$SERVICE" >/dev/null
  docker rename "$SERVICE" "$backup_container"
  docker network disconnect "$proxy_network" "$backup_container" >/dev/null 2>&1 || true
fi
production_replaced=1

docker compose -p "$runtime_project" \
  -f "$DEPLOY/docker-compose.yml" \
  -f "$runtime_override" \
  up -d --no-deps --no-build "$SERVICE"

health="starting"
for _ in $(seq 1 90); do
  container_state="$(docker inspect -f '{{.State.Status}}' "$SERVICE" 2>/dev/null || true)"
  if [[ "$container_state" == "running" ]] && curl --fail --silent "$LOCAL_HEALTH" >/tmp/production-health.json 2>/dev/null; then
    health="healthy"
    break
  fi
  if [[ "$container_state" == "exited" || "$container_state" == "dead" ]]; then
    health="$container_state"
    break
  fi
  sleep 2
done

if [[ "$health" != "healthy" ]]; then
  echo "SharipovAI production health check failed after 180s: $health" >&2
  docker inspect "$SERVICE" --format '{{json .State}}' 2>/dev/null || true
  docker logs --tail 160 "$SERVICE" 2>/dev/null || true
  rollback || true
  trap - ERR
  exit 1
fi

echo "[5/6] Verifying the running market-backed virtual account..."
docker exec -e PYTHONPATH=/app "$SERVICE" python /app/scripts/verify_market_paper_runtime.py

echo "[6/6] Refreshing and verifying the public Caddy route..."
refresh_caddy_route

if [[ -n "$backup_container" ]] && docker container inspect "$backup_container" >/dev/null 2>&1; then
  docker rm "$backup_container" >/dev/null
fi

production_replaced=0
trap - ERR
echo "Market-backed virtual account deployed and verified."
echo "Public HTTPS route deployed and verified."
echo "Real exchange orders remain blocked."
