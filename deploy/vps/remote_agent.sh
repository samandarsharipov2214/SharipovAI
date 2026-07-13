#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="${APP_DIR:-/opt/sharipovai-repo}"
BRANCH="${BRANCH:-main}"
COMPOSE_DIR="${COMPOSE_DIR:-${APP_DIR}/deploy/vps}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8000/health}"
STATUS_FILE="${STATUS_FILE:-/var/lib/sharipovai-agent/status.json}"
LOG_TAG="sharipovai-agent"
RUNNER_RECOVERY_ATTEMPTS="${RUNNER_RECOVERY_ATTEMPTS:-10}"

log() { logger -t "${LOG_TAG}" -- "$*"; printf '[%s] %s\n' "${LOG_TAG}" "$*"; }
fail() { log "ERROR: $*"; write_status "error" "$*"; exit 1; }

write_status() {
  local state="$1"
  local message="$2"
  install -d -m 0755 "$(dirname "${STATUS_FILE}")"
  python3 - "${STATUS_FILE}" "${state}" "${message}" <<'PY'
import json
import sys
import time
from pathlib import Path

path = Path(sys.argv[1])
payload = {
    "state": sys.argv[2],
    "message": sys.argv[3],
    "updated_at": int(time.time()),
}
tmp = path.with_suffix(path.suffix + ".tmp")
tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
tmp.replace(path)
PY
}

notify_telegram() {
  local text="$1"
  local env_file="${COMPOSE_DIR}/.env.vps"
  [[ -f "${env_file}" ]] || return 0
  local token chat_id
  token="$(grep -E '^BOT_TOKEN=' "${env_file}" | tail -n1 | cut -d= -f2- || true)"
  chat_id="$(grep -E '^(TELEGRAM_ADMIN_CHAT_ID|ADMIN_CHAT_ID)=' "${env_file}" | tail -n1 | cut -d= -f2- || true)"
  token="${token%\"}"; token="${token#\"}"
  chat_id="${chat_id%\"}"; chat_id="${chat_id#\"}"
  [[ -n "${token}" && -n "${chat_id}" ]] || return 0
  curl -fsS --max-time 10 \
    -X POST "https://api.telegram.org/bot${token}/sendMessage" \
    -H 'Content-Type: application/json' \
    -d "$(python3 - "${chat_id}" "${text}" <<'PY'
import json, sys
print(json.dumps({"chat_id": sys.argv[1], "text": sys.argv[2]}))
PY
)" >/dev/null || true
}

find_actions_runner_service() {
  systemctl list-unit-files --type=service --no-legend 2>/dev/null \
    | awk '$1 ~ /^actions\.runner\..*\.service$/ {print $1; exit}'
}

ensure_actions_runner() {
  local runner_service attempt
  runner_service="$(find_actions_runner_service)"
  if [[ -z "${runner_service}" ]]; then
    log 'WARN: GitHub Actions runner service is not installed; continuing application maintenance'
    return 2
  fi
  if systemctl is-active --quiet "${runner_service}"; then
    log "GitHub Actions runner is active: ${runner_service}"
    return 0
  fi

  log "GitHub Actions runner is inactive; attempting safe recovery: ${runner_service}"
  systemctl reset-failed "${runner_service}" >/dev/null 2>&1 || true
  if ! systemctl restart "${runner_service}"; then
    log "WARN: systemctl restart failed for ${runner_service}"
    return 1
  fi
  for ((attempt = 1; attempt <= RUNNER_RECOVERY_ATTEMPTS; attempt++)); do
    if systemctl is-active --quiet "${runner_service}"; then
      log "GitHub Actions runner recovered: ${runner_service}"
      notify_telegram "✅ SharipovAI CI runner recovered automatically: ${runner_service}"
      return 0
    fi
    sleep 1
  done
  log "WARN: GitHub Actions runner did not become active: ${runner_service}"
  notify_telegram "⚠️ SharipovAI CI runner recovery failed: ${runner_service}"
  return 1
}

[[ ${EUID} -eq 0 ]] || fail 'run as root'
[[ -d "${APP_DIR}/.git" ]] || fail "repository not found: ${APP_DIR}"
[[ -x "${APP_DIR}/deploy/vps/update_from_main.sh" ]] || chmod +x "${APP_DIR}/deploy/vps/update_from_main.sh"
[[ "${RUNNER_RECOVERY_ATTEMPTS}" =~ ^[0-9]+$ ]] || fail 'RUNNER_RECOVERY_ATTEMPTS must be an integer'

runner_state='active'
if ! ensure_actions_runner; then
  runner_state='degraded'
fi

before="$(git -C "${APP_DIR}" rev-parse HEAD)"
write_status "running" "checking origin/${BRANCH}; runner=${runner_state}"

set +e
output="$(APP_DIR="${APP_DIR}" BRANCH="${BRANCH}" HEALTH_URL="${HEALTH_URL}" bash "${APP_DIR}/deploy/vps/update_from_main.sh" 2>&1)"
code=$?
set -e
printf '%s\n' "${output}"

after="$(git -C "${APP_DIR}" rev-parse HEAD 2>/dev/null || printf 'unknown')"
if [[ ${code} -ne 0 ]]; then
  message="update failed and rollback was attempted; current=${after}; see journalctl -u sharipovai-agent"
  write_status "error" "${message}"
  notify_telegram "❌ SharipovAI update failed. Safe rollback was attempted. Commit: ${after}"
  exit "${code}"
fi

if ! curl -fsS --max-time 5 "${HEALTH_URL}" >/dev/null; then
  fail "health check failed after updater completed"
fi

# The update can replace service-related files or coincide with a runner crash.
# Recheck after deployment, but never restart an already active runner.
runner_state='active'
if ! ensure_actions_runner; then
  runner_state='degraded'
fi

if [[ "${before}" == "${after}" ]]; then
  write_status "healthy" "already up to date at ${after}; runner=${runner_state}"
  log "already up to date at ${after}; runner=${runner_state}"
else
  write_status "healthy" "updated ${before} -> ${after}; runner=${runner_state}"
  log "updated ${before} -> ${after}; runner=${runner_state}"
  notify_telegram "✅ SharipovAI safely updated. ${before:0:8} → ${after:0:8}. Health check passed. Runner: ${runner_state}."
fi
