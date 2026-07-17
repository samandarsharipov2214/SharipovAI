#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

APP_DIR="${APP_DIR:-/opt/sharipovai-repo}"
COMPOSE_DIR="${COMPOSE_DIR:-${APP_DIR}/deploy/vps}"
SERVICE="${SERVICE:-sharipovai}"
MIN_FREE_MIB="${PHASE7_MIN_FREE_MIB:-1536}"
REPORT_FILE="${PHASE7_PREFLIGHT_REPORT:-/tmp/sharipovai-phase7-preflight.json}"

fail() { printf '[phase7-preflight] ERROR: %s\n' "$*" >&2; exit 1; }
log() { printf '[phase7-preflight] %s\n' "$*"; }

[[ ${EUID} -eq 0 ]] || fail 'run as root'
[[ -d "${APP_DIR}/.git" ]] || fail "repository missing: ${APP_DIR}"
[[ -f "${COMPOSE_DIR}/docker-compose.yml" ]] || fail 'docker-compose.yml is missing'
[[ -f "${COMPOSE_DIR}/.env.vps" ]] || fail '.env.vps is missing'
for command in docker python3 curl df stat; do
  command -v "${command}" >/dev/null || fail "required command is missing: ${command}"
done

env_mode="$(stat -c '%a' "${COMPOSE_DIR}/.env.vps")"
if (( (8#${env_mode}) & 8#077 )); then
  fail ".env.vps permissions are too broad: ${env_mode}; expected 600 or stricter"
fi

free_mib="$(df -Pm "${COMPOSE_DIR}" | awk 'NR==2 {print $4}')"
[[ "${free_mib}" =~ ^[0-9]+$ ]] || fail 'unable to read free disk space'
(( free_mib >= MIN_FREE_MIB )) || fail "free disk ${free_mib} MiB is below ${MIN_FREE_MIB} MiB"

docker info >/dev/null
rendered="$(mktemp)"
trap 'rm -f "${rendered}"' EXIT
(
  cd "${COMPOSE_DIR}"
  docker compose config --format json >"${rendered}"
)

python3 - "${rendered}" <<'PY'
import json
import math
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
service = payload.get("services", {}).get("sharipovai", {})
environment = service.get("environment", {})
if isinstance(environment, list):
    environment = dict(item.split("=", 1) for item in environment if "=" in item)

def truthy(value: object) -> bool:
    return str(value or "0").strip().lower() in {"1", "true", "yes", "on"}

if truthy(environment.get("EXCHANGE_LIVE_TRADING_ENABLED")):
    raise SystemExit("EXCHANGE_LIVE_TRADING_ENABLED must remain disabled")
if truthy(environment.get("FEATURE_BYBIT_LIVE_EXECUTION")):
    raise SystemExit("FEATURE_BYBIT_LIVE_EXECUTION must remain disabled")
if str(environment.get("EXCHANGE_MODE", "sandbox")).strip().lower() not in {"", "sandbox"}:
    raise SystemExit("production compose must remain in sandbox exchange mode")
try:
    maximum = float(environment.get("EXECUTION_MAX_NOTIONAL_USDT", 25) or 25)
except (TypeError, ValueError):
    raise SystemExit("EXECUTION_MAX_NOTIONAL_USDT must be numeric")
if not math.isfinite(maximum) or maximum <= 0 or maximum > 25:
    raise SystemExit("EXECUTION_MAX_NOTIONAL_USDT must be within 0..25 for Phase 7")
health = service.get("healthcheck") or {}
if not health.get("test"):
    raise SystemExit("application healthcheck is required")
if service.get("restart") not in {"unless-stopped", "always"}:
    raise SystemExit("application restart policy is missing")
PY

container_state="missing"
database_state="not_checked"
data_source=""
if docker container inspect "${SERVICE}" >/dev/null 2>&1; then
  container_state="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "${SERVICE}")"
  data_source="$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/var/lib/sharipovai"}}{{.Source}}{{end}}{{end}}' "${SERVICE}")"
  if [[ -n "${data_source}" && -f "${data_source}/sharipovai_shared.db" ]]; then
    python3 - "${data_source}/sharipovai_shared.db" <<'PY'
import sqlite3
import sys
from pathlib import Path

path = Path(sys.argv[1])
with path.open("rb") as handle:
    if handle.read(16) != b"SQLite format 3\x00":
        raise SystemExit("database header is not SQLite")
with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as connection:
    result = connection.execute("PRAGMA quick_check").fetchone()
if not result or result[0] != "ok":
    raise SystemExit(f"database quick_check failed: {result!r}")
PY
    database_state="ok"
  fi
fi

mkdir -p "${COMPOSE_DIR}/backups" "${COMPOSE_DIR}/emergency-recovery"
test -w "${COMPOSE_DIR}/backups" || fail 'backup directory is not writable'

python3 - "${REPORT_FILE}" "${free_mib}" "${container_state}" "${database_state}" "${data_source}" <<'PY'
import json
import os
import sys
import time
from pathlib import Path

path = Path(sys.argv[1])
payload = {
    "status": "ok",
    "checked_at_ms": int(time.time() * 1000),
    "free_disk_mib": int(sys.argv[2]),
    "container_state": sys.argv[3],
    "database_state": sys.argv[4],
    "data_source_present": bool(sys.argv[5]),
    "mainnet_enabled": False,
}
tmp = path.with_name(f"{path.name}.tmp-{os.getpid()}")
tmp.write_text(json.dumps(payload, sort_keys=True, indent=2), encoding="utf-8")
os.replace(tmp, path)
print(json.dumps(payload, sort_keys=True))
PY

log "PREFLIGHT_OK report=${REPORT_FILE}"
