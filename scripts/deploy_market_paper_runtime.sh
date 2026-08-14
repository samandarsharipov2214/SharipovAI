#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="${SHARIPOVAI_DEPLOY_ROOT:-/opt/sharipovai-repo}"
DEPLOY="$ROOT/deploy/vps"
SERVICE="sharipovai"
CADDY_SERVICE="sharipovai-caddy"
LOCAL_HEALTH="http://127.0.0.1:8000/health"
PUBLIC_HEALTH="https://85-137-88-17.sslip.io/health"
DEPLOY_PROFILE="${SHARIPOVAI_DEPLOY_PROFILE:-}"

production_replaced=0
backup_container=""
old_network=""
proxy_network=""
data_volume=""
runtime_override=""
docker_config_tmp=""
runtime_project="sharipovai-runtime-$(date +%s)-$$"
head_sha=""
candidate_image_ref=""
expected_web2_sha=""
BUILD_TIMEOUT_SECONDS="${SHARIPOVAI_DEPLOY_BUILD_TIMEOUT_SECONDS:-900}"
CANDIDATE_TEST_TIMEOUT_SECONDS="${SHARIPOVAI_DEPLOY_CANDIDATE_TEST_TIMEOUT_SECONDS:-900}"
CANDIDATE_PROBE_TIMEOUT_SECONDS="${SHARIPOVAI_DEPLOY_CANDIDATE_PROBE_TIMEOUT_SECONDS:-180}"
RUNTIME_UP_TIMEOUT_SECONDS="${SHARIPOVAI_DEPLOY_RUNTIME_UP_TIMEOUT_SECONDS:-120}"
RUNTIME_VERIFY_TIMEOUT_SECONDS="${SHARIPOVAI_DEPLOY_RUNTIME_VERIFY_TIMEOUT_SECONDS:-180}"

for limit in "$BUILD_TIMEOUT_SECONDS" "$CANDIDATE_TEST_TIMEOUT_SECONDS" "$CANDIDATE_PROBE_TIMEOUT_SECONDS" "$RUNTIME_UP_TIMEOUT_SECONDS" "$RUNTIME_VERIFY_TIMEOUT_SECONDS"; do
  [[ "$limit" =~ ^[1-9][0-9]*$ ]] || { echo "Deploy timeout values must be positive integers." >&2; exit 64; }
done

run_bounded() {
  local limit="$1"
  shift
  # timeout creates an isolated process group, so a timed-out compose/test child
  # cannot leave its own helper processes behind while the host watcher survives.
  timeout --signal=TERM --kill-after=30s "${limit}s" "$@"
}

[[ "$ROOT" == /* ]] || {
  echo "SHARIPOVAI_DEPLOY_ROOT must be an absolute path." >&2
  exit 64
}
git -c safe.directory="$ROOT" -C "$ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1 || {
  echo "Deployment root is not a Git worktree: $ROOT" >&2
  exit 66
}

cd "$DEPLOY"

case "$DEPLOY_PROFILE" in
  ""|web2-refresh) ;;
  *)
    echo "Unsupported SHARIPOVAI_DEPLOY_PROFILE: $DEPLOY_PROFILE" >&2
    exit 64
    ;;
esac

if [[ "$DEPLOY_PROFILE" == "web2-refresh" ]]; then
  [[ -s "$ROOT/scripts/verify_web2_refresh_contracts.sh" ]] || {
    echo "Missing transactional Web2 verifier." >&2
    exit 65
  }
  bash -n "$ROOT/scripts/verify_web2_refresh_contracts.sh"
fi

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
  if [[ -n "$docker_config_tmp" ]]; then
    rm -rf "$docker_config_tmp"
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
    if curl --connect-timeout 5 --max-time 15 --fail --silent --show-error "$PUBLIC_HEALTH" >/tmp/public-health.json 2>/tmp/public-health.err; then
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
      if curl --connect-timeout 5 --max-time 15 --fail --silent "$LOCAL_HEALTH" >/dev/null 2>&1; then
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

docker_config_tmp="$(mktemp -d /tmp/sharipovai-docker-config-XXXXXX)"
chmod 0700 "$docker_config_tmp"
export DOCKER_CONFIG="$docker_config_tmp"

# Trust only the selected deployment checkout for read-only Git identity checks.
# Production uses /opt/sharipovai-repo by default; tests may explicitly point at
# their isolated checkout without mutating global/system Git configuration.
git_repo() {
  git -c safe.directory="$ROOT" -C "$ROOT" "$@"
}

head_sha="$(git_repo rev-parse HEAD)"
[[ "$head_sha" =~ ^[0-9a-f]{40}$ ]] || {
  echo "Cannot resolve exact deployment HEAD." >&2
  exit 66
}

# Give this build a unique tag and use the same tag for candidate tests and
# production replacement. This prevents a stale legacy image tag from being
# substituted after the candidate has already passed its checks.
export SHARIPOVAI_RELEASE_TAG="deploy-${head_sha:0:12}-$(date +%s)-$$"
export SHARIPOVAI_RELEASE_SHA="$head_sha"
export SHARIPOVAI_BUILD_DATE="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
candidate_image_ref="sharipovai:${SHARIPOVAI_RELEASE_TAG}"

echo "[1/6] Building exact candidate image $candidate_image_ref..."
run_bounded "$BUILD_TIMEOUT_SECONDS" docker compose build "$SERVICE"
docker image inspect "$candidate_image_ref" >/dev/null

candidate_revision="$(docker image inspect -f '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$candidate_image_ref")"
if [[ "$candidate_revision" != "$head_sha" ]]; then
  echo "Candidate image revision mismatch: expected $head_sha, got $candidate_revision" >&2
  exit 67
fi

expected_web2_sha="$(git_repo show "${head_sha}:dashboard/static/web2/index.html" | sha256sum | awk '{print $1}')"
actual_web2_sha="$(docker run --rm --entrypoint sha256sum "$candidate_image_ref" /app/dashboard/static/web2/index.html | awk '{print $1}')"
if [[ -z "$expected_web2_sha" || "$actual_web2_sha" != "$expected_web2_sha" ]]; then
  echo "Candidate Web2 index does not match exact Git HEAD." >&2
  echo "Expected: ${expected_web2_sha:-missing}" >&2
  echo "Actual:   ${actual_web2_sha:-missing}" >&2
  exit 68
fi

echo "CANDIDATE_IMAGE_IDENTITY_OK $head_sha $expected_web2_sha"

echo "[2/6] Running focused tests and importing the complete FastAPI graph..."
run_bounded "$CANDIDATE_TEST_TIMEOUT_SECONDS" docker compose run --rm --no-deps \
  -e PAPER_ACTIVITY_AUTORUN_ENABLED=0 \
  --entrypoint sh "$SERVICE" -lc '
set -Eeuo pipefail
export PYTHONPATH="/app${PYTHONPATH:+:$PYTHONPATH}"
cd /app
command -v git >/dev/null
git --version
python -m pytest \
  tests/test_market_paper_engine.py \
  tests/test_news_intelligence_runtime.py \
  tests/test_lifecycle_compat.py \
  tests/test_ai_organ_safe_runtime.py \
  tests/test_verify_market_paper_runtime_script.py \
  tests/test_config_loader_cwd.py \
  tests/test_web2_page_ownership.py \
  tests/test_source_status_contracts.py -q
python -m py_compile \
  /app/market_paper_engine.py \
  /app/paper_activity_autorun.py \
  /app/scripts/verify_market_paper_runtime.py \
  /app/config/loader.py \
  /app/dashboard/lifecycle_compat.py \
  /app/dashboard/ai_organ_state_safe_api.py \
  /app/dashboard/paper_activity_api.py \
  /app/dashboard/realtime_status_api.py \
  /app/dashboard/learning_os_api.py \
  /app/dashboard/evidence_vault_api.py \
  /app/dashboard/source_status_compat_api.py \
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
assert "/api/learning-os/status" in paths, "Learning OS status route missing"
assert "/api/evidence-vault/recent" in paths, "Evidence Vault recent route missing"
assert "/api/exchange/account/status" in paths, "Bybit account status route missing"
print("FULL_APP_IMPORT_OK")
PY
'

echo "[3/6] Probing candidate /health in isolation..."
run_bounded "$CANDIDATE_PROBE_TIMEOUT_SECONDS" docker compose run --rm --no-deps \
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
  if curl --connect-timeout 3 --max-time 10 --fail --silent --show-error http://127.0.0.1:8000/health >/tmp/health.json 2>/tmp/curl.err; then
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
    image: ${candidate_image_ref}
volumes:
  sharipovai_data:
    external: true
    name: ${data_volume}
networks:
  default:
    external: true
    name: ${proxy_network}
YAML

run_bounded "$RUNTIME_UP_TIMEOUT_SECONDS" docker compose -p "$runtime_project" \
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

run_bounded "$RUNTIME_UP_TIMEOUT_SECONDS" docker compose -p "$runtime_project" \
  -f "$DEPLOY/docker-compose.yml" \
  -f "$runtime_override" \
  up -d --no-deps --no-build "$SERVICE"

running_image_id="$(docker inspect -f '{{.Image}}' "$SERVICE")"
candidate_image_id="$(docker image inspect -f '{{.Id}}' "$candidate_image_ref")"
if [[ -z "$candidate_image_id" || "$running_image_id" != "$candidate_image_id" ]]; then
  echo "Production container is not running the verified candidate image." >&2
  echo "Expected image ID: ${candidate_image_id:-missing}" >&2
  echo "Running image ID:  ${running_image_id:-missing}" >&2
  exit 69
fi

echo "RUNNING_IMAGE_IDENTITY_OK $running_image_id"

health="starting"
for _ in $(seq 1 90); do
  container_state="$(docker inspect -f '{{.State.Status}}' "$SERVICE" 2>/dev/null || true)"
  if [[ "$container_state" == "running" ]] && curl --connect-timeout 5 --max-time 15 --fail --silent "$LOCAL_HEALTH" >/tmp/production-health.json 2>/dev/null; then
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
run_bounded "$RUNTIME_VERIFY_TIMEOUT_SECONDS" docker exec -e PYTHONPATH=/app "$SERVICE" python /app/scripts/verify_market_paper_runtime.py

echo "[6/6] Refreshing and verifying the public Caddy route..."
refresh_caddy_route

if [[ "$DEPLOY_PROFILE" == "web2-refresh" ]]; then
  echo "[transaction] Verifying Dashboard/public/Telegram contracts before commit..."
  bash "$ROOT/scripts/verify_web2_refresh_contracts.sh"
fi

if [[ -n "$backup_container" ]] && docker container inspect "$backup_container" >/dev/null 2>&1; then
  docker rm "$backup_container" >/dev/null
fi

production_replaced=0
trap - ERR
echo "Market-backed virtual account deployed and verified."
echo "Public HTTPS route deployed and verified."
if [[ "$DEPLOY_PROFILE" == "web2-refresh" ]]; then
  echo "Dashboard/public/Telegram verification committed inside rollback boundary."
fi
echo "Real exchange orders remain blocked."
