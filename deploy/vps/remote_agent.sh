#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="${APP_DIR:-/opt/sharipovai-repo}"
BRANCH="${BRANCH:-main}"
COMPOSE_DIR="${COMPOSE_DIR:-${APP_DIR}/deploy/vps}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8000/health}"
STATUS_FILE="${STATUS_FILE:-/var/lib/sharipovai-agent/status.json}"
LOG_TAG="sharipovai-agent"

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

[[ ${EUID} -eq 0 ]] || fail 'run as root'
[[ -d "${APP_DIR}/.git" ]] || fail "repository not found: ${APP_DIR}"
[[ -x "${APP_DIR}/deploy/vps/update_from_main.sh" ]] || chmod +x "${APP_DIR}/deploy/vps/update_from_main.sh"

before="$(git -C "${APP_DIR}" rev-parse HEAD)"
write_status "running" "checking origin/${BRANCH}"

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

if [[ "${before}" == "${after}" ]]; then
  write_status "healthy" "already up to date at ${after}"
  log "already up to date at ${after}"
else
  write_status "healthy" "updated ${before} -> ${after}"
  log "updated ${before} -> ${after}"
  notify_telegram "✅ SharipovAI safely updated. ${before:0:8} → ${after:0:8}. Health check passed."
fi
