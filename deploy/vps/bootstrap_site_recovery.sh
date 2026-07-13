#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="${APP_DIR:-}"
BRANCH="${BRANCH:-main}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8000/health}"

log() { printf '[site-recovery] %s\n' "$*"; }
fail() { printf '[site-recovery] ERROR: %s\n' "$*" >&2; exit 1; }

[[ ${EUID} -eq 0 ]] || fail 'run as root'

if [[ -z "${APP_DIR}" ]]; then
  for candidate in /opt/sharipovai-repo /opt/SharipovAI; do
    if [[ -d "${candidate}/.git" ]]; then
      APP_DIR="${candidate}"
      break
    fi
  done
fi

[[ -n "${APP_DIR}" && -d "${APP_DIR}/.git" ]] || fail 'SharipovAI repository was not found under /opt'
[[ -f "${APP_DIR}/deploy/vps/.env.vps" ]] || fail 'production environment file deploy/vps/.env.vps is missing'
[[ "${BRANCH}" =~ ^[A-Za-z0-9._/-]+$ ]] || fail 'unsafe branch name'

cleanup_file=''
cleanup() { [[ -n "${cleanup_file}" ]] && rm -f "${cleanup_file}"; }
trap cleanup EXIT

log "fetching origin/${BRANCH}"
git -C "${APP_DIR}" fetch --prune origin "${BRANCH}"
target_sha="$(git -C "${APP_DIR}" rev-parse "origin/${BRANCH}")"
current_sha="$(git -C "${APP_DIR}" rev-parse HEAD)"
log "production ${current_sha} -> target ${target_sha}"

# Execute the updater from the fetched target commit. This works even when the
# checked-out production tree predates the latest recovery implementation.
cleanup_file="$(mktemp)"
git -C "${APP_DIR}" show "origin/${BRANCH}:deploy/vps/update_from_main.sh" >"${cleanup_file}"
chmod 0700 "${cleanup_file}"
APP_DIR="${APP_DIR}" BRANCH="${BRANCH}" HEALTH_URL="${HEALTH_URL}" bash "${cleanup_file}"

# The checkout now contains the current installer. Install the root timer only
# after a healthy deployment so future main updates need no manual terminal work.
chmod 0755 "${APP_DIR}/deploy/vps/install_remote_agent.sh" \
  "${APP_DIR}/deploy/vps/remote_agent.sh" \
  "${APP_DIR}/deploy/vps/update_from_main.sh"
APP_DIR="${APP_DIR}" bash "${APP_DIR}/deploy/vps/install_remote_agent.sh"

curl --fail --silent --show-error --max-time 8 "${HEALTH_URL}" >/dev/null \
  || fail 'health check failed after deployment and agent installation'

final_sha="$(git -C "${APP_DIR}" rev-parse HEAD)"
log "site recovered at ${final_sha}"
log 'automatic updates are now managed by sharipovai-agent.timer'
systemctl --no-pager --full status sharipovai-agent.timer || true
