#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

CONFIRMATION="${1:-}"
REQUIRED_CONFIRMATION="I_APPROVE_BOUNDED_TESTNET_RUNTIME_DEPLOYMENT"
APP_DIR="${APP_DIR:-/opt/sharipovai-repo}"
COMPOSE_DIR="${COMPOSE_DIR:-${APP_DIR}/deploy/vps}"
BASE_ENV_FILE="${BASE_ENV_FILE:-${COMPOSE_DIR}/.env.vps}"
CAMPAIGN_ENV_FILE="${CAMPAIGN_ENV_FILE:-${COMPOSE_DIR}/.env.testnet-campaign}"
LOCK_FILE="${LOCK_FILE:-/run/lock/sharipovai-testnet-campaign.lock}"

fail() { printf '[testnet-deploy] ERROR: %s\n' "$*" >&2; exit 1; }
log() { printf '[testnet-deploy] %s\n' "$*"; }

[[ ${EUID} -eq 0 ]] || fail 'run as root'
[[ "${CONFIRMATION}" == "${REQUIRED_CONFIRMATION}" ]] || fail "exact confirmation required: ${REQUIRED_CONFIRMATION}"
[[ -f "${BASE_ENV_FILE}" ]] || fail "missing base env file: ${BASE_ENV_FILE}"
[[ -f "${CAMPAIGN_ENV_FILE}" ]] || fail "missing campaign env file: ${CAMPAIGN_ENV_FILE}"
chmod 600 "${BASE_ENV_FILE}" "${CAMPAIGN_ENV_FILE}"
for command in docker python3 curl flock git; do command -v "${command}" >/dev/null || fail "missing command: ${command}"; done
install -d -m 0755 "$(dirname "${LOCK_FILE}")"
exec 9>"${LOCK_FILE}"
flock -n 9 || fail 'another campaign deployment transition is running'

python3 "${COMPOSE_DIR}/validate_runtime_env.py" --env-file "${BASE_ENV_FILE}" --env-file "${CAMPAIGN_ENV_FILE}" --mode testnet-campaign
APP_DIR="${APP_DIR}" COMPOSE_DIR="${COMPOSE_DIR}" bash "${COMPOSE_DIR}/phase7_preflight.sh"
APP_DIR="${APP_DIR}" COMPOSE_DIR="${COMPOSE_DIR}" bash "${COMPOSE_DIR}/export_backup.sh"

rollback() {
  trap - ERR
  log 'campaign runtime deployment failed; restoring production-safe compose'
  docker compose --project-directory "${COMPOSE_DIR}" -f "${COMPOSE_DIR}/docker-compose.yml" --env-file "${BASE_ENV_FILE}" up -d --force-recreate --remove-orphans
  BASE_ENV_FILE="${BASE_ENV_FILE}" COMPOSE_DIR="${COMPOSE_DIR}" bash "${COMPOSE_DIR}/smoke_check.sh" production || true
  fail 'bounded Testnet runtime deployment was rolled back'
}
trap rollback ERR

compose=(docker compose --project-directory "${COMPOSE_DIR}" -f "${COMPOSE_DIR}/docker-compose.yml" -f "${COMPOSE_DIR}/docker-compose.testnet-campaign.yml" --env-file "${CAMPAIGN_ENV_FILE}")
"${compose[@]}" config >/dev/null
log 'recreating application container in bounded Testnet mode'
"${compose[@]}" up -d --force-recreate --remove-orphans
BASE_ENV_FILE="${BASE_ENV_FILE}" CAMPAIGN_ENV_FILE="${CAMPAIGN_ENV_FILE}" COMPOSE_DIR="${COMPOSE_DIR}" bash "${COMPOSE_DIR}/smoke_check.sh" testnet-campaign
trap - ERR
commit="$(git -C "${APP_DIR}" rev-parse HEAD 2>/dev/null || true)"
log "TESTNET_RUNTIME_READY commit=${commit:-unknown} mainnet=false max_notional_usdt=25"
