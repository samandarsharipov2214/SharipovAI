#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

APP_DIR="${APP_DIR:-/opt/sharipovai-repo}"
BRANCH="${BRANCH:-main}"
COMPOSE_DIR="${COMPOSE_DIR:-${APP_DIR}/deploy/vps}"
CONTAINER="${CONTAINER:-sharipovai}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8000/health}"
PUBLIC_HEALTH_URL="${PUBLIC_HEALTH_URL:-https://85-137-88-17.sslip.io/health}"
LOCK_FILE="${LOCK_FILE:-/run/lock/sharipovai-recovery.lock}"
DATABASE_NAME="${DATABASE_NAME:-sharipovai_shared.db}"
DATA_DESTINATION="/var/lib/sharipovai"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
RECOVERY_ROOT="${COMPOSE_DIR}/emergency-recovery/${STAMP}"
ORIGINAL_DATA="${RECOVERY_ROOT}/original-data"
RESTORE_DATA="${RECOVERY_ROOT}/restore-data"
BACKUP_DIR="${COMPOSE_DIR}/backups"
RENAMED_CONTAINER="${CONTAINER}-before-recovery-${STAMP}"

log() { printf '[sharipovai-recovery] %s\n' "$*"; }
fail() { printf '[sharipovai-recovery] ERROR: %s\n' "$*" >&2; exit 1; }

[[ ${EUID} -eq 0 ]] || fail 'run as root'
[[ "${APP_DIR}" == /* ]] || fail 'APP_DIR must be absolute'
[[ "${BRANCH}" =~ ^[A-Za-z0-9._/-]+$ ]] || fail 'unsafe BRANCH'
[[ -d "${APP_DIR}/.git" ]] || fail "repository not found: ${APP_DIR}"
[[ -f "${COMPOSE_DIR}/.env.vps" ]] || fail 'deploy/vps/.env.vps is missing'
for command in docker git python3 curl tar sha256sum flock; do
  command -v "${command}" >/dev/null || fail "required command is missing: ${command}"
done

install -d -m 0755 "$(dirname "${LOCK_FILE}")"
exec 9>"${LOCK_FILE}"
flock -n 9 || fail 'another recovery/deployment is already running'
install -d -m 0700 "${ORIGINAL_DATA}" "${RESTORE_DATA}"

sqlite_valid() {
  local database="$1"
  [[ -f "${database}" ]] || return 1
  python3 - "${database}" <<'PY'
import sqlite3
import sys
from pathlib import Path

path = Path(sys.argv[1])
try:
    with path.open("rb") as handle:
        if handle.read(16) != b"SQLite format 3\x00":
            raise RuntimeError("invalid SQLite header")
    uri = f"file:{path}?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        result = connection.execute("PRAGMA quick_check").fetchone()
    if not result or result[0] != "ok":
        raise RuntimeError(f"quick_check={result!r}")
except Exception as exc:
    print(f"INVALID_SQLITE: {exc}", file=sys.stderr)
    raise SystemExit(1)
print("VALID_SQLITE")
PY
}

health_check() {
  local attempt
  for ((attempt = 1; attempt <= 60; attempt++)); do
    if curl --fail --silent --show-error --max-time 5 "${HEALTH_URL}" >/dev/null; then
      return 0
    fi
    sleep 2
  done
  return 1
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
    if str(environment.get(key, "0")).strip().lower() in {"1", "true", "yes", "on"}:
        raise SystemExit(f"unsafe compose environment: {key} is enabled")
PY
}

previous_sha="$(git -C "${APP_DIR}" rev-parse HEAD)"
log "current repository commit: ${previous_sha}"

if ! docker container inspect "${CONTAINER}" >/dev/null 2>&1; then
  fail "existing container is missing: ${CONTAINER}"
fi

data_mount_type="$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/var/lib/sharipovai"}}{{.Type}}{{end}}{{end}}' "${CONTAINER}")"
data_mount_source="$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/var/lib/sharipovai"}}{{.Source}}{{end}}{{end}}' "${CONTAINER}")"
[[ "${data_mount_type}" == "volume" || "${data_mount_type}" == "bind" ]] || fail "unsupported data mount type: ${data_mount_type:-missing}"
[[ -n "${data_mount_source}" && -d "${data_mount_source}" ]] || fail 'existing data mount source is unavailable'

log "stopping the broken container without deleting it"
docker stop --time 20 "${CONTAINER}" >/dev/null 2>&1 || true

log "creating immutable emergency copy of the current data volume"
cp -a "${data_mount_source}/." "${ORIGINAL_DATA}/"
tar -C "${RECOVERY_ROOT}" -czf "${RECOVERY_ROOT}/original-data.tar.gz" original-data
sha256sum "${RECOVERY_ROOT}/original-data.tar.gz" > "${RECOVERY_ROOT}/original-data.tar.gz.sha256"

recovery_source="quarantined-current-data"
if sqlite_valid "${ORIGINAL_DATA}/${DATABASE_NAME}" >/dev/null 2>&1; then
  log 'current database passed SQLite integrity checks'
  cp -a "${ORIGINAL_DATA}/." "${RESTORE_DATA}/"
  recovery_source="current-valid-data"
else
  log 'current database is corrupt; searching verified backups'
  mapfile -t backup_candidates < <(
    find "${BACKUP_DIR}" -maxdepth 1 -type f -name 'sharipovai-*.tar.gz' -printf '%T@ %p\n' 2>/dev/null \
      | sort -rn | cut -d' ' -f2-
  )
  for archive in "${backup_candidates[@]:-}"; do
    [[ -n "${archive}" ]] || continue
    candidate_dir="$(mktemp -d "${RECOVERY_ROOT}/candidate-XXXXXX")"
    if [[ -f "${archive}.sha256" ]] && ! sha256sum --check --status "${archive}.sha256"; then
      log "skipping backup with invalid SHA-256: ${archive}"
      rm -rf "${candidate_dir}"
      continue
    fi
    if ! tar -xzf "${archive}" -C "${candidate_dir}"; then
      log "skipping unreadable backup: ${archive}"
      rm -rf "${candidate_dir}"
      continue
    fi
    if sqlite_valid "${candidate_dir}/data/${DATABASE_NAME}" >/dev/null 2>&1; then
      cp -a "${candidate_dir}/data/." "${RESTORE_DATA}/"
      recovery_source="backup:${archive}"
      rm -rf "${candidate_dir}"
      break
    fi
    rm -rf "${candidate_dir}"
  done

  if [[ "${recovery_source}" == "quarantined-current-data" ]]; then
    log 'no valid database backup found; preserving corrupt files and initializing a fresh database'
    cp -a "${ORIGINAL_DATA}/." "${RESTORE_DATA}/"
    for suffix in '' '-wal' '-shm' '-journal'; do
      path="${RESTORE_DATA}/${DATABASE_NAME}${suffix}"
      if [[ -e "${path}" ]]; then
        mv "${path}" "${path}.corrupt-${STAMP}"
      fi
    done
  fi
fi

log "selected recovery source: ${recovery_source}"
log "renaming the broken container to preserve its image/configuration"
docker rename "${CONTAINER}" "${RENAMED_CONTAINER}"

log "fetching exact origin/${BRANCH}"
git -C "${APP_DIR}" fetch --prune origin "${BRANCH}"
target_sha="$(git -C "${APP_DIR}" rev-parse "origin/${BRANCH}")"
[[ -n "${target_sha}" ]] || fail 'target commit could not be resolved'
git -C "${APP_DIR}" checkout -q "${BRANCH}" 2>/dev/null || git -C "${APP_DIR}" checkout -q -B "${BRANCH}"
git -C "${APP_DIR}" reset --hard "${target_sha}"
chmod 600 "${COMPOSE_DIR}/.env.vps"

cd "${COMPOSE_DIR}"
rendered_config="$(mktemp)"
docker compose config --format json > "${rendered_config}"
validate_financial_locks "${rendered_config}"
expected_volume="$(python3 - "${rendered_config}" <<'PY'
import json
import sys
from pathlib import Path
payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
volume = payload.get("volumes", {}).get("sharipovai_data", {})
print(volume.get("name", ""))
PY
)"
rm -f "${rendered_config}"
[[ -n "${expected_volume}" ]] || fail 'Compose did not resolve the sharipovai_data volume name'
docker volume create "${expected_volume}" >/dev/null
expected_mount="$(docker volume inspect --format '{{.Mountpoint}}' "${expected_volume}")"
[[ -n "${expected_mount}" && -d "${expected_mount}" ]] || fail 'resolved Compose volume mountpoint is unavailable'

log "restoring data into Compose volume: ${expected_volume}"
find "${expected_mount}" -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +
cp -a "${RESTORE_DATA}/." "${expected_mount}/"
chown -R 10001:10001 "${expected_mount}"

log "building commit ${target_sha}"
docker compose build --pull
log 'starting repaired production services'
docker compose up -d --remove-orphans

if ! health_check; then
  docker compose ps -a || true
  docker logs --tail 200 "${CONTAINER}" 2>&1 || true
  fail "new container did not become healthy; emergency data remains at ${RECOVERY_ROOT}"
fi

container_state="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "${CONTAINER}")"
[[ "${container_state}" == "healthy" || "${container_state}" == "running" ]] || fail "unexpected container state: ${container_state}"

log 'creating a standard verified post-recovery backup'
bash "${APP_DIR}/deploy/vps/export_backup.sh"

log 'installing autonomous maintenance and protected deployment controls'
bash "${APP_DIR}/deploy/vps/install_remote_agent.sh"
bash "${APP_DIR}/scripts/install_telegram_deploy_watcher.sh"

if curl --fail --silent --show-error --max-time 20 "${PUBLIC_HEALTH_URL}" >/dev/null; then
  public_state='healthy'
else
  public_state='local-health-only'
fi

# The old stopped container no longer owns unique data; the emergency archive is the rollback evidence.
docker rm "${RENAMED_CONTAINER}" >/dev/null 2>&1 || true

log "RECOVERY_COMPLETE commit=${target_sha} source=${recovery_source} container=${container_state} public=${public_state}"
log "emergency archive: ${RECOVERY_ROOT}/original-data.tar.gz"
