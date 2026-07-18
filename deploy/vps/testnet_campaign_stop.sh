#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

CONFIRMATION="${1:-}"
REQUIRED_CONFIRMATION="I_APPROVE_RESTORE_PRODUCTION_KILL_SWITCH"
APP_DIR="${APP_DIR:-/opt/sharipovai-repo}"
COMPOSE_DIR="${COMPOSE_DIR:-${APP_DIR}/deploy/vps}"
BASE_ENV_FILE="${BASE_ENV_FILE:-${COMPOSE_DIR}/.env.vps}"
LOCK_FILE="${LOCK_FILE:-/run/lock/sharipovai-testnet-campaign.lock}"
AUTO_STOP_TIMER="sharipovai-testnet-auto-stop.timer"

fail() { printf '[testnet-stop] ERROR: %s\n' "$*" >&2; exit 1; }
log() { printf '[testnet-stop] %s\n' "$*"; }

[[ ${EUID} -eq 0 ]] || fail 'run as root'
[[ "${CONFIRMATION}" == "${REQUIRED_CONFIRMATION}" ]] || fail "exact confirmation required: ${REQUIRED_CONFIRMATION}"
[[ -f "${BASE_ENV_FILE}" ]] || fail "missing base env file: ${BASE_ENV_FILE}"
install -d -m 0755 "$(dirname "${LOCK_FILE}")"
exec 9>"${LOCK_FILE}"
flock -n 9 || fail 'another campaign deployment transition is running'

systemctl stop "${AUTO_STOP_TIMER}" >/dev/null 2>&1 || true
python3 "${COMPOSE_DIR}/validate_runtime_env.py" --env-file "${BASE_ENV_FILE}" --mode production
log 'restoring production-safe compose with kill switch enabled'
docker compose --project-directory "${COMPOSE_DIR}" -f "${COMPOSE_DIR}/docker-compose.yml" --env-file "${BASE_ENV_FILE}" up -d --force-recreate --remove-orphans
BASE_ENV_FILE="${BASE_ENV_FILE}" COMPOSE_DIR="${COMPOSE_DIR}" bash "${COMPOSE_DIR}/smoke_check.sh" production
log 'PRODUCTION_LOCKS_RESTORED kill_switch=1 testnet_execution=0 mainnet=false'
