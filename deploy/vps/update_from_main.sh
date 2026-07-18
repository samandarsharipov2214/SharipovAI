#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="${APP_DIR:-/opt/sharipovai-repo}"
BRANCH="${BRANCH:-main}"
FETCH_REMOTE="${FETCH_REMOTE:-origin}"
LOCK_FILE="${LOCK_FILE:-/run/lock/sharipovai-deploy.lock}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8000/health}"
HEALTH_ATTEMPTS="${HEALTH_ATTEMPTS:-30}"
HEALTH_DELAY_SECONDS="${HEALTH_DELAY_SECONDS:-2}"

log() { printf '[sharipovai-update] %s\n' "$*"; }
fail() { printf '[sharipovai-update] ERROR: %s\n' "$*" >&2; exit 1; }

[[ ${EUID} -eq 0 ]] || fail 'run as root'
[[ "${APP_DIR}" == /* ]] || fail 'APP_DIR must be an absolute path'
[[ "${BRANCH}" =~ ^[A-Za-z0-9._/-]+$ ]] || fail 'BRANCH contains unsafe characters'
[[ -d "${APP_DIR}/.git" ]] || fail "git repository not found at ${APP_DIR}"
[[ -f "${APP_DIR}/deploy/vps/.env.vps" ]] || fail 'deploy/vps/.env.vps is missing'

if [[ "${FETCH_REMOTE}" == https://github.com/* ]]; then
  [[ "${FETCH_REMOTE}" =~ ^https://github\.com/[A-Za-z0-9._-]+/[A-Za-z0-9._-]+(\.git)?$ ]] \
    || fail 'FETCH_REMOTE must be a plain HTTPS GitHub repository URL'
else
  [[ "${FETCH_REMOTE}" =~ ^[A-Za-z0-9._-]+$ ]] || fail 'FETCH_REMOTE contains unsafe characters'
fi

install -d -m 0755 "$(dirname "${LOCK_FILE}")"
exec 9>"${LOCK_FILE}"
flock -n 9 || fail 'another SharipovAI update is already running'

previous_sha="$(git -C "${APP_DIR}" rev-parse HEAD)"
compose_dir="${APP_DIR}/deploy/vps"
rollback_started=0
backup_exporter_tmp=""
preflight_tmp=""
target_compose_tmp=""
rendered_config=""

cleanup() {
  rm -f \
    "${backup_exporter_tmp:-}" \
    "${preflight_tmp:-}" \
    "${target_compose_tmp:-}" \
    "${rendered_config:-}"
}
trap cleanup EXIT

health_check() {
  local attempt
  for ((attempt = 1; attempt <= HEALTH_ATTEMPTS; attempt++)); do
    if curl --fail --silent --show-error --max-time 5 "${HEALTH_URL}" >/dev/null; then
      return 0
    fi
    sleep "${HEALTH_DELAY_SECONDS}"
  done
  return 1
}

set_build_provenance() {
  local sha="$1"
  export SHARIPOVAI_RELEASE_SHA="${sha}"
  export SHARIPOVAI_RELEASE_TAG="${sha:0:12}"
  export SHARIPOVAI_BUILD_DATE="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}

verify_container_sha() {
  local expected="$1"
  local actual
  actual="$(docker exec sharipovai printenv SHARIPOVAI_BUILD_SHA 2>/dev/null || true)"
  [[ "${actual}" == "${expected}" ]] || return 1
  local label
  label="$(docker image inspect --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}' "sharipovai:${expected:0:12}" 2>/dev/null || true)"
  [[ "${label}" == "${expected}" ]]
}

validate_financial_locks() {
  local rendered="$1"
  python3 - "${rendered}" <<'PY'
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
service = payload.get("services", {}).get("sharipovai", {})
environment = service.get("environment", {})
if isinstance(environment, list):
    environment = dict(item.split("=", 1) for item in environment if "=" in item)
required = {
    "EXCHANGE_LIVE_TRADING_ENABLED": "0",
    "EXECUTION_KILL_SWITCH": "1",
}
for key, expected in required.items():
    actual = str(environment.get(key, ""))
    if actual != expected:
        raise SystemExit(f"unsafe compose environment: {key}={actual!r}, expected {expected!r}")
for key in (
    "AUTONOMOUS_TESTNET_BRIDGE_ENABLED",
    "TESTNET_EXECUTION_ENABLED",
    "FEATURE_BYBIT_TESTNET",
    "FEATURE_BYBIT_LIVE_EXECUTION",
):
    actual = str(environment.get(key, "0")).strip().lower()
    if actual in {"1", "true", "yes", "on"}:
        raise SystemExit(f"unsafe compose environment: {key} is enabled")
PY
}

rollback() {
  local reason="$1"
  trap - ERR
  if [[ ${rollback_started} -eq 1 ]]; then
    fail "rollback failed after: ${reason}"
  fi
  rollback_started=1
  log "deployment failed: ${reason}; rolling back to ${previous_sha}"
  git -C "${APP_DIR}" reset --hard "${previous_sha}"
  set_build_provenance "${previous_sha}"
  cd "${compose_dir}"
  local rollback_config
  rollback_config="$(mktemp)"
  docker compose config --format json >"${rollback_config}"
  validate_financial_locks "${rollback_config}"
  rm -f "${rollback_config}"
  docker compose build
  docker compose up -d --remove-orphans
  health_check || fail 'rollback container did not become healthy'
  verify_container_sha "${previous_sha}" || fail 'rollback container SHA is incorrect'
  fail "new deployment was rolled back safely: ${reason}"
}

if [[ "${FETCH_REMOTE}" == https://github.com/* ]]; then
  log "fetching ${BRANCH} directly over HTTPS"
  git -C "${APP_DIR}" fetch --no-tags "${FETCH_REMOTE}" "${BRANCH}"
  target_sha="$(git -C "${APP_DIR}" rev-parse FETCH_HEAD)"
else
  log "fetching ${FETCH_REMOTE}/${BRANCH}"
  git -C "${APP_DIR}" fetch --prune "${FETCH_REMOTE}" "${BRANCH}"
  target_sha="$(git -C "${APP_DIR}" rev-parse "${FETCH_REMOTE}/${BRANCH}")"
fi
[[ "${target_sha}" =~ ^[0-9a-f]{40}$ ]] || fail 'target commit could not be resolved to a full SHA'

if [[ "${target_sha}" == "${previous_sha}" ]]; then
  log "already at ${target_sha}"
  health_check || fail 'current deployment is not healthy'
  verify_container_sha "${target_sha}" || fail 'current container does not embed the deployed SHA; rebuild required'
  exit 0
fi

for target_path in \
  deploy/vps/phase7_preflight.sh \
  deploy/vps/docker-compose.yml \
  deploy/vps/export_backup.sh; do
  git -C "${APP_DIR}" cat-file -e "${target_sha}:${target_path}" 2>/dev/null \
    || fail "target artifact is missing: ${target_path}"
done

log 'materializing immutable target deployment artifacts'
preflight_tmp="$(mktemp)"
target_compose_tmp="$(mktemp "${compose_dir}/.phase7-target-compose-XXXXXX.yml")"
backup_exporter_tmp="$(mktemp)"
git -C "${APP_DIR}" show "${target_sha}:deploy/vps/phase7_preflight.sh" >"${preflight_tmp}"
git -C "${APP_DIR}" show "${target_sha}:deploy/vps/docker-compose.yml" >"${target_compose_tmp}"
git -C "${APP_DIR}" show "${target_sha}:deploy/vps/export_backup.sh" >"${backup_exporter_tmp}"
chmod 0700 "${preflight_tmp}" "${backup_exporter_tmp}"
bash -n "${preflight_tmp}"
bash -n "${backup_exporter_tmp}"

log 'running immutable target Phase 7 deployment preflight'
APP_DIR="${APP_DIR}" \
COMPOSE_DIR="${compose_dir}" \
PHASE7_COMPOSE_FILE="${target_compose_tmp}" \
bash "${preflight_tmp}"

log 'creating verified backup before code update'
APP_DIR="${APP_DIR}" COMPOSE_DIR="${compose_dir}" bash "${backup_exporter_tmp}"

trap 'rollback "unexpected error at line ${LINENO}"' ERR
log "updating ${previous_sha} -> ${target_sha}"
git -C "${APP_DIR}" checkout -q "${BRANCH}"
git -C "${APP_DIR}" reset --hard "${target_sha}"
chmod 600 "${compose_dir}/.env.vps"
set_build_provenance "${target_sha}"

cd "${compose_dir}"
rendered_config="$(mktemp)"
docker compose config --format json >"${rendered_config}"
validate_financial_locks "${rendered_config}"

log 'building the new image with immutable commit provenance'
docker compose build --pull
log 'starting the updated services'
docker compose up -d --remove-orphans

health_check || rollback 'health endpoint did not recover in time'
container_state="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' sharipovai 2>/dev/null || true)"
[[ "${container_state}" == "healthy" || "${container_state}" == "running" ]] || rollback "container state is ${container_state:-missing}"
verify_container_sha "${target_sha}" || rollback 'container/image commit provenance mismatch'

trap - ERR
log "deployment completed successfully at ${target_sha}"
docker compose ps
