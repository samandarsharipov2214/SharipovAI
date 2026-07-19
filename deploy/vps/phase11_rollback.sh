#!/usr/bin/env bash
set -Eeuo pipefail
umask 027

ROOT="${SHARIPOVAI_ROOT:-${APP_DIR:-/opt/sharipovai-repo}}"
TARGET_SHA="${SHARIPOVAI_ROLLBACK_SHA:-}"
EXPECTED_CURRENT_SHA="${SHARIPOVAI_EXPECTED_SHA:-}"
CONFIRMATION="${1:-}"
LOCK_FILE="${SHARIPOVAI_DEPLOY_LOCK_FILE:-/run/lock/sharipovai-deploy.lock}"
HEALTH_URL="${SHARIPOVAI_HEALTH_URL:-http://127.0.0.1:8000/api/health}"
HEALTH_ATTEMPTS="${SHARIPOVAI_HEALTH_ATTEMPTS:-30}"
HEALTH_DELAY_SECONDS="${SHARIPOVAI_HEALTH_DELAY_SECONDS:-2}"

log(){ printf '[phase11-rollback] %s\n' "$*"; }
fail(){ printf '[phase11-rollback] BLOCKED: %s\n' "$*" >&2; exit 2; }

[[ "${EUID}" -eq 0 ]] || fail "run as root"
[[ "$CONFIRMATION" == "I_APPROVE_PHASE11_EXACT_SHA_ROLLBACK" ]] || fail "exact rollback confirmation is required"
[[ -d "$ROOT/.git" ]] || fail "canonical repository not found: $ROOT"
[[ "$TARGET_SHA" =~ ^[0-9a-f]{40}$ ]] || fail "SHARIPOVAI_ROLLBACK_SHA must be a full commit SHA"
[[ "$EXPECTED_CURRENT_SHA" =~ ^[0-9a-f]{40}$ ]] || fail "SHARIPOVAI_EXPECTED_SHA must be the current full commit SHA"

install -d -m 0755 "$(dirname "$LOCK_FILE")"
exec 9>"$LOCK_FILE"
flock -n 9 || fail "another deployment operation is running"

cd "$ROOT"
CURRENT_SHA="$(git rev-parse HEAD)"
[[ "$CURRENT_SHA" == "$EXPECTED_CURRENT_SHA" ]] || fail "current SHA differs from operator-approved SHA"
[[ "$TARGET_SHA" != "$CURRENT_SHA" ]] || fail "rollback target equals current SHA"
[[ -z "$(git status --porcelain --untracked-files=normal)" ]] || fail "worktree is not clean"
git cat-file -e "$TARGET_SHA^{commit}" 2>/dev/null || fail "rollback commit is not present locally"
git merge-base --is-ancestor "$TARGET_SHA" "$CURRENT_SHA" || fail "rollback target is not an ancestor of current SHA"

for path in \
  deploy/vps/docker-compose.yml \
  deploy/vps/phase7_preflight.sh \
  deploy/vps/export_backup.sh \
  deploy/vps/smoke_check.sh; do
  git cat-file -e "$TARGET_SHA:$path" 2>/dev/null || fail "rollback target misses $path"
done

health_check(){
  local attempt
  for ((attempt=1; attempt<=HEALTH_ATTEMPTS; attempt++)); do
    if curl --fail --silent --show-error --max-time 5 "$HEALTH_URL" >/dev/null; then
      return 0
    fi
    sleep "$HEALTH_DELAY_SECONDS"
  done
  return 1
}

set_build_provenance(){
  local sha="$1"
  export SHARIPOVAI_RELEASE_SHA="$sha"
  export SHARIPOVAI_RELEASE_TAG="${sha:0:12}"
  export SHARIPOVAI_BUILD_DATE="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}

verify_container_sha(){
  local expected="$1"
  local runtime_sha label_sha
  runtime_sha="$(docker exec sharipovai printenv SHARIPOVAI_BUILD_SHA 2>/dev/null || true)"
  label_sha="$(docker inspect --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}' sharipovai 2>/dev/null || true)"
  [[ "$label_sha" == "$expected" ]] || return 1
  if [[ -n "$runtime_sha" && "$runtime_sha" != "unknown" ]]; then
    [[ "$runtime_sha" == "$expected" ]] || return 1
  fi
}

validate_financial_locks(){
  local rendered="$1"
  python3 - "$rendered" <<'PY'
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
service = payload.get("services", {}).get("sharipovai", {})
environment = service.get("environment", {})
if isinstance(environment, list):
    environment = dict(item.split("=", 1) for item in environment if "=" in item)
required = {"EXCHANGE_LIVE_TRADING_ENABLED": "0", "EXECUTION_KILL_SWITCH": "1"}
for key, expected in required.items():
    actual = str(environment.get(key, ""))
    if actual != expected:
        raise SystemExit(f"unsafe compose environment: {key}={actual!r}")
for key in (
    "TESTNET_EXECUTION_ENABLED",
    "AUTONOMOUS_TESTNET_ENABLED",
    "AUTONOMOUS_TESTNET_BRIDGE_ENABLED",
    "FEATURE_BYBIT_LIVE_EXECUTION",
    "FEATURE_BYBIT_TESTNET_EXECUTION",
):
    if str(environment.get(key, "0")).strip().lower() in {"1", "true", "yes", "on"}:
        raise SystemExit(f"unsafe compose environment: {key} is enabled")
PY
}

compose_dir="$ROOT/deploy/vps"
target_preflight="$(mktemp)"
target_compose="$(mktemp "$compose_dir/.phase11-rollback-compose.XXXXXX.yml")"
rendered="$(mktemp)"
restore_started=0
cleanup(){ rm -f "$target_preflight" "$target_compose" "$rendered"; }
trap cleanup EXIT

restore_original(){
  local reason="$1"
  trap - ERR
  [[ "$restore_started" -eq 0 ]] || fail "rollback and recovery both failed: $reason"
  restore_started=1
  log "rollback target failed: $reason; restoring original $CURRENT_SHA"
  git reset --hard "$CURRENT_SHA"
  set_build_provenance "$CURRENT_SHA"
  cd "$compose_dir"
  docker compose build
  docker compose up -d --remove-orphans
  health_check || fail "original deployment did not recover"
  verify_container_sha "$CURRENT_SHA" || fail "original container SHA did not recover"
  bash smoke_check.sh production || fail "original deployment smoke check failed"
  fail "rollback target rejected and original deployment restored"
}

git show "$TARGET_SHA:deploy/vps/phase7_preflight.sh" >"$target_preflight"
git show "$TARGET_SHA:deploy/vps/docker-compose.yml" >"$target_compose"
chmod 0700 "$target_preflight"
bash -n "$target_preflight"

log "running rollback-target preflight"
APP_DIR="$ROOT" COMPOSE_DIR="$compose_dir" PHASE7_COMPOSE_FILE="$target_compose" bash "$target_preflight"
log "creating verified backup with the current trusted exporter"
APP_DIR="$ROOT" COMPOSE_DIR="$compose_dir" bash "$ROOT/deploy/vps/export_backup.sh"

trap 'restore_original "unexpected error at line ${LINENO}"' ERR
log "resetting $CURRENT_SHA -> $TARGET_SHA"
git reset --hard "$TARGET_SHA"
set_build_provenance "$TARGET_SHA"
cd "$compose_dir"
docker compose config --format json >"$rendered"
validate_financial_locks "$rendered"
docker compose build
docker compose up -d --remove-orphans
health_check || restore_original "health endpoint did not recover"
verify_container_sha "$TARGET_SHA" || restore_original "container SHA differs from rollback target"
bash smoke_check.sh production || restore_original "production smoke check failed"
container_state="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' sharipovai 2>/dev/null || true)"
[[ "$container_state" == "healthy" || "$container_state" == "running" ]] || restore_original "container state is ${container_state:-missing}"
trap - ERR

log "rollback completed safely at $TARGET_SHA"
printf 'PHASE11_ROLLBACK_OK from=%s to=%s\n' "$CURRENT_SHA" "$TARGET_SHA"
