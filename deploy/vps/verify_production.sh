#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="${APP_DIR:-/opt/sharipovai-repo}"
COMPOSE_DIR="${COMPOSE_DIR:-${APP_DIR}/deploy/vps}"
ENV_FILE="${ENV_FILE:-${COMPOSE_DIR}/.env.vps}"
BACKUP_DIR="${BACKUP_DIR:-${COMPOSE_DIR}/backups}"
REPOSITORY="${GITHUB_REPOSITORY:-samandarsharipov2214/SharipovAI}"
ORIGIN_REF="${ORIGIN_REF:-origin/main}"
LOCAL_BASE_URL="${LOCAL_BASE_URL:-http://127.0.0.1:8000}"
MAX_BACKUP_AGE_HOURS="${MAX_BACKUP_AGE_HOURS:-48}"
REPORT_JSON="${REPORT_JSON:-/var/tmp/sharipovai-production-verification.json}"
VERIFY_SESSION_COOKIE="${VERIFY_SESSION_COOKIE:-}"

log() { printf '[sharipovai-verify] %s\n' "$*"; }
fail_fast() { printf '[sharipovai-verify] ERROR: %s\n' "$*" >&2; exit 1; }

[[ ${EUID} -eq 0 ]] || fail_fast 'run as root'
[[ "${APP_DIR}" == /* ]] || fail_fast 'APP_DIR must be absolute'
[[ "${COMPOSE_DIR}" == /* ]] || fail_fast 'COMPOSE_DIR must be absolute'
[[ "${BACKUP_DIR}" == /* ]] || fail_fast 'BACKUP_DIR must be absolute'
[[ "${REPORT_JSON}" == /* ]] || fail_fast 'REPORT_JSON must be absolute'
[[ "${MAX_BACKUP_AGE_HOURS}" =~ ^[0-9]+$ ]] || fail_fast 'MAX_BACKUP_AGE_HOURS must be an integer'

for command in git docker curl python3 systemctl sha256sum stat; do
  command -v "${command}" >/dev/null 2>&1 || fail_fast "required command is missing: ${command}"
done

records_file="$(mktemp)"
compose_json="$(mktemp)"
http_body="$(mktemp)"
cleanup() { rm -f "${records_file}" "${compose_json}" "${http_body}"; }
trap cleanup EXIT

pass_count=0
warn_count=0
fail_count=0

record() {
  local status="$1" name="$2" detail="$3"
  detail="$(printf '%s' "${detail}" | tr '\t\r\n' '   ')"
  printf '%s\t%s\t%s\n' "${status}" "${name}" "${detail}" >>"${records_file}"
  case "${status}" in
    PASS) pass_count=$((pass_count + 1)) ;;
    WARN) warn_count=$((warn_count + 1)) ;;
    FAIL) fail_count=$((fail_count + 1)) ;;
    *) fail_fast "unknown record status: ${status}" ;;
  esac
  log "${status} ${name}: ${detail}"
}

check_json_object() {
  python3 - "$1" <<'PY'
import json
import sys
from pathlib import Path
payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
if not isinstance(payload, dict):
    raise SystemExit("response is not a JSON object")
PY
}

http_code() {
  local url="$1"
  local -a args=(--silent --show-error --max-time 10 --output "${http_body}" --write-out '%{http_code}')
  if [[ -n "${VERIFY_SESSION_COOKIE}" ]]; then
    args+=(--header "Cookie: ${VERIFY_SESSION_COOKIE}")
  fi
  curl "${args[@]}" "${url}" 2>/dev/null || printf '000'
}

check_endpoint() {
  local name="$1" url="$2" validator="${3:-object}"
  local code
  : >"${http_body}"
  code="$(http_code "${url}")"
  if [[ "${code}" == '200' ]]; then
    if ! check_json_object "${http_body}" 2>/dev/null; then
      record FAIL "${name}" 'HTTP 200 but response is not a JSON object'
      return
    fi
    if [[ "${validator}" == 'canonical-runtime' ]]; then
      if python3 - "${http_body}" <<'PY'
import json
import sys
from pathlib import Path
payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
assert payload.get("decision_mode") == "CANONICAL_COUNCIL_REQUIRED"
assert payload.get("entry_without_authorization_allowed") is False
assert payload.get("synthetic_fallback_used") is False
PY
      then
        record PASS "${name}" 'canonical council mode confirmed'
      else
        record FAIL "${name}" 'runtime response violates canonical council contract'
      fi
    else
      record PASS "${name}" 'HTTP 200 JSON response confirmed'
    fi
  elif [[ "${code}" == '401' || "${code}" == '403' ]]; then
    record WARN "${name}" "endpoint is reachable but requires an authenticated session (HTTP ${code})"
  else
    record FAIL "${name}" "unexpected HTTP status ${code}"
  fi
}

if [[ -d "${APP_DIR}/.git" ]]; then
  record PASS repository "git checkout exists at ${APP_DIR}"
else
  record FAIL repository "git checkout is missing at ${APP_DIR}"
fi

local_sha=''
target_sha=''
if [[ -d "${APP_DIR}/.git" ]]; then
  local_sha="$(git -C "${APP_DIR}" rev-parse HEAD 2>/dev/null || true)"
  current_branch="$(git -C "${APP_DIR}" symbolic-ref --short HEAD 2>/dev/null || true)"
  if [[ "${current_branch}" == 'main' ]]; then
    record PASS git_branch 'main is checked out'
  else
    record FAIL git_branch "unexpected branch ${current_branch:-detached}"
  fi

  if git -C "${APP_DIR}" fetch --quiet origin main; then
    target_sha="$(git -C "${APP_DIR}" rev-parse "${ORIGIN_REF}" 2>/dev/null || true)"
    if [[ -n "${local_sha}" && "${local_sha}" == "${target_sha}" ]]; then
      record PASS git_commit "checkout matches ${ORIGIN_REF} at ${local_sha}"
    else
      record FAIL git_commit "checkout=${local_sha:-unknown}; ${ORIGIN_REF}=${target_sha:-unknown}"
    fi
  else
    record FAIL git_fetch 'could not fetch origin/main'
  fi

  tracked_changes="$(git -C "${APP_DIR}" status --porcelain --untracked-files=no 2>/dev/null || true)"
  if [[ -z "${tracked_changes}" ]]; then
    record PASS git_worktree 'tracked production files are clean'
  else
    record WARN git_worktree 'tracked production files contain local changes'
  fi
fi

if [[ -f "${ENV_FILE}" ]]; then
  mode="$(stat -c '%a' "${ENV_FILE}" 2>/dev/null || true)"
  if [[ "${mode}" == '600' ]]; then
    record PASS env_permissions '.env.vps permissions are 600'
  else
    record FAIL env_permissions ".env.vps permissions are ${mode:-unknown}, expected 600"
  fi
else
  record FAIL env_file "missing ${ENV_FILE}"
fi

if [[ -f "${COMPOSE_DIR}/docker-compose.yml" && -f "${ENV_FILE}" ]]; then
  if (cd "${COMPOSE_DIR}" && docker compose config --format json >"${compose_json}"); then
    if python3 - "${compose_json}" <<'PY'
import json
import sys
from pathlib import Path
payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
environment = payload.get("services", {}).get("sharipovai", {}).get("environment", {})
if isinstance(environment, list):
    environment = dict(item.split("=", 1) for item in environment if "=" in item)
required = {
    "EXCHANGE_LIVE_TRADING_ENABLED": "0",
    "EXECUTION_KILL_SWITCH": "1",
}
for key, expected in required.items():
    if str(environment.get(key, "")) != expected:
        raise SystemExit(f"{key} is not safely locked")
for key in (
    "AUTONOMOUS_TESTNET_BRIDGE_ENABLED",
    "TESTNET_EXECUTION_ENABLED",
    "FEATURE_BYBIT_TESTNET",
    "FEATURE_BYBIT_LIVE_EXECUTION",
):
    if str(environment.get(key, "0")).strip().lower() in {"1", "true", "yes", "on"}:
        raise SystemExit(f"{key} is enabled")
PY
    then
      record PASS financial_locks 'live/testnet disabled and execution kill switch enabled'
    else
      record FAIL financial_locks 'rendered compose contains unsafe financial settings'
    fi
  else
    record FAIL compose_config 'docker compose config failed'
  fi
fi

container_state() {
  docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$1" 2>/dev/null || true
}

backend_state="$(container_state sharipovai)"
if [[ "${backend_state}" == 'healthy' || "${backend_state}" == 'running' ]]; then
  record PASS backend_container "sharipovai is ${backend_state}"
else
  record FAIL backend_container "sharipovai state is ${backend_state:-missing}"
fi

caddy_state="$(container_state sharipovai-caddy)"
if [[ "${caddy_state}" == 'healthy' || "${caddy_state}" == 'running' ]]; then
  record PASS caddy_container "sharipovai-caddy is ${caddy_state}"
else
  record FAIL caddy_container "sharipovai-caddy state is ${caddy_state:-missing}"
fi

health_status="$(curl --silent --show-error --max-time 10 --output "${http_body}" --write-out '%{http_code}' "${LOCAL_BASE_URL}/health" 2>/dev/null || printf '000')"
if [[ "${health_status}" == '200' ]]; then
  record PASS backend_health 'local /health returned HTTP 200'
else
  record FAIL backend_health "local /health returned HTTP ${health_status}"
fi

check_endpoint system_health "${LOCAL_BASE_URL}/api/system/health"
check_endpoint paper_decision_runtime "${LOCAL_BASE_URL}/api/autonomous-paper/decision-runtime" canonical-runtime
check_endpoint paper_status "${LOCAL_BASE_URL}/api/autonomous-paper/status"

public_domain=''
if [[ -f "${ENV_FILE}" ]]; then
  public_domain="$(python3 - "${ENV_FILE}" <<'PY'
import sys
from pathlib import Path
for raw in Path(sys.argv[1]).read_text(encoding="utf-8-sig").splitlines():
    line = raw.strip()
    if line.startswith("DOMAIN="):
        print(line.split("=", 1)[1].strip())
        break
PY
)"
fi
if [[ -n "${public_domain}" && "${public_domain}" != 'sharipovai.example.com' ]]; then
  public_status="$(curl --silent --show-error --max-time 15 --output /dev/null --write-out '%{http_code}' "https://${public_domain}/health" 2>/dev/null || printf '000')"
  if [[ "${public_status}" == '200' ]]; then
    record PASS public_https "https://${public_domain}/health returned HTTP 200"
  else
    record FAIL public_https "https://${public_domain}/health returned HTTP ${public_status}"
  fi
else
  record WARN public_https 'DOMAIN is missing or still uses the example placeholder'
fi

latest_archive="${BACKUP_DIR}/latest.tar.gz"
latest_checksum="${BACKUP_DIR}/latest.tar.gz.sha256"
if [[ -e "${latest_archive}" && -e "${latest_checksum}" ]]; then
  archive_target="$(readlink -f "${latest_archive}" 2>/dev/null || true)"
  checksum_target="$(readlink -f "${latest_checksum}" 2>/dev/null || true)"
  if [[ -f "${archive_target}" && -f "${checksum_target}" ]] && sha256sum -c "${checksum_target}" >/dev/null 2>&1; then
    record PASS backup_checksum "latest backup checksum is valid: $(basename "${archive_target}")"
  else
    record FAIL backup_checksum 'latest backup or checksum is invalid'
  fi
  archive_epoch="$(stat -c '%Y' "${archive_target}" 2>/dev/null || printf '0')"
  now_epoch="$(date +%s)"
  age_hours=$(( (now_epoch - archive_epoch) / 3600 ))
  if (( age_hours <= MAX_BACKUP_AGE_HOURS )); then
    record PASS backup_age "latest backup age is ${age_hours}h"
  else
    record FAIL backup_age "latest backup age is ${age_hours}h, limit is ${MAX_BACKUP_AGE_HOURS}h"
  fi
else
  record FAIL backup_presence 'latest backup archive/checksum is missing'
fi

runner_service="$(systemctl list-unit-files --type=service --no-legend 2>/dev/null | awk '$1 ~ /^actions\.runner\..*\.service$/ {print $1; exit}')"
if [[ -n "${runner_service}" ]]; then
  if systemctl is-enabled --quiet "${runner_service}" && systemctl is-active --quiet "${runner_service}"; then
    record PASS runner_service "${runner_service} is enabled and active"
  else
    record FAIL runner_service "${runner_service} is not both enabled and active"
  fi
else
  record FAIL runner_service 'GitHub Actions runner systemd service is missing'
fi

if command -v gh >/dev/null 2>&1 && gh auth status --hostname github.com >/dev/null 2>&1; then
  variable_value="$(gh api "repos/${REPOSITORY}/actions/variables/SHARIPOVAI_SELF_HOSTED_CI" --jq '.value' 2>/dev/null || true)"
  if [[ "${variable_value}" == '1' ]]; then
    record PASS runner_variable 'SHARIPOVAI_SELF_HOSTED_CI=1'
  else
    record FAIL runner_variable 'SHARIPOVAI_SELF_HOSTED_CI is not enabled'
  fi

  runner_status="$(gh api "repos/${REPOSITORY}/actions/runners" 2>/dev/null | python3 -c '
import json, sys
payload = json.load(sys.stdin)
for runner in payload.get("runners", []):
    labels = {item.get("name") for item in runner.get("labels", [])}
    if "sharipovai-ci" in labels:
        print(runner.get("status", "unknown"))
        break
' 2>/dev/null || true)"
  if [[ "${runner_status}" == 'online' ]]; then
    record PASS runner_online 'GitHub reports sharipovai-ci runner online'
  else
    record FAIL runner_online "GitHub runner status is ${runner_status:-missing}"
  fi
else
  record WARN github_runner_api 'gh authentication unavailable; remote runner status was not queried'
fi

disk_free_percent="$(df -P "${APP_DIR}" | awk 'NR == 2 {gsub(/%/, "", $5); print 100-$5}')"
if [[ "${disk_free_percent}" =~ ^[0-9]+$ ]] && (( disk_free_percent >= 10 )); then
  record PASS disk_space "${disk_free_percent}% free on application filesystem"
else
  record FAIL disk_space "only ${disk_free_percent:-unknown}% free on application filesystem"
fi

install -d -m 0755 "$(dirname "${REPORT_JSON}")"
python3 - "${records_file}" "${REPORT_JSON}" "${local_sha}" "${target_sha}" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
records_path, report_path, local_sha, target_sha = sys.argv[1:]
checks = []
for raw in Path(records_path).read_text(encoding="utf-8").splitlines():
    status, name, detail = raw.split("\t", 2)
    checks.append({"status": status, "name": name, "detail": detail})
counts = {status: sum(item["status"] == status for item in checks) for status in ("PASS", "WARN", "FAIL")}
payload = {
    "schema": 1,
    "checked_at": datetime.now(timezone.utc).isoformat(),
    "overall_status": "FAIL" if counts["FAIL"] else ("WARN" if counts["WARN"] else "PASS"),
    "counts": counts,
    "local_commit": local_sha or None,
    "target_commit": target_sha or None,
    "checks": checks,
}
Path(report_path).write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
print(json.dumps(payload, indent=2, ensure_ascii=False))
PY
chmod 0644 "${REPORT_JSON}"

if (( fail_count > 0 )); then
  log "verification failed: pass=${pass_count} warn=${warn_count} fail=${fail_count}; report=${REPORT_JSON}"
  exit 2
fi

log "verification completed: pass=${pass_count} warn=${warn_count} fail=${fail_count}; report=${REPORT_JSON}"
