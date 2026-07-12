#!/usr/bin/env bash
set -Eeuo pipefail

REPOSITORY="${GITHUB_REPOSITORY:-samandarsharipov2214/SharipovAI}"
REPO_DIR="${REPO_DIR:-}"
AUTH_CREATED=0
AUTH_USER=""

log() { printf '[sharipovai-runner-bootstrap] %s\n' "$*"; }
fail() { printf '[sharipovai-runner-bootstrap] ERROR: %s\n' "$*" >&2; exit 1; }

cleanup() {
  unset GH_TOKEN || true
  if [[ "${AUTH_CREATED}" == '1' && -n "${AUTH_USER}" ]]; then
    printf 'y\n' | gh auth logout --hostname github.com --user "${AUTH_USER}" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

[[ ${EUID} -eq 0 ]] || fail 'run as root'
[[ "${REPOSITORY}" == */* ]] || fail 'GITHUB_REPOSITORY must be owner/repo'

if [[ -z "${REPO_DIR}" ]]; then
  for candidate in /opt/sharipovai-repo /opt/SharipovAI; do
    if [[ -d "${candidate}/.git" ]]; then
      REPO_DIR="${candidate}"
      break
    fi
  done
fi
[[ -n "${REPO_DIR}" && -d "${REPO_DIR}/.git" ]] || fail 'SharipovAI git repository not found under /opt'

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq gh git ca-certificates curl jq >/dev/null

if gh auth status --hostname github.com >/dev/null 2>&1; then
  log 'using existing GitHub CLI authentication'
else
  log 'GitHub device authorization is required once; approve the code shown below'
  gh auth login \
    --hostname github.com \
    --git-protocol ssh \
    --web \
    --scopes repo,workflow
  AUTH_CREATED=1
fi

AUTH_USER="$(gh api user --jq '.login')"
[[ -n "${AUTH_USER}" ]] || fail 'GitHub authentication did not return a user'
export GH_TOKEN="$(gh auth token --hostname github.com --user "${AUTH_USER}")"
[[ -n "${GH_TOKEN}" ]] || fail 'GitHub authentication token is unavailable'

log "updating ${REPO_DIR} from main"
git -C "${REPO_DIR}" fetch origin main
git -C "${REPO_DIR}" checkout main
git -C "${REPO_DIR}" pull --ff-only origin main

log 'installing and registering the VPS self-hosted runner'
GITHUB_REPOSITORY="${REPOSITORY}" \
  GH_TOKEN="${GH_TOKEN}" \
  bash "${REPO_DIR}/deploy/vps/install_github_actions_runner.sh"

runner_service="$(
  systemctl list-unit-files --type=service --no-legend 'actions.runner.*.service' 2>/dev/null \
    | awk 'NR == 1 {print $1}'
)"
[[ -n "${runner_service}" ]] || fail 'runner systemd service was not created'
systemctl is-enabled --quiet "${runner_service}" || fail "${runner_service} is not enabled"
systemctl is-active --quiet "${runner_service}" || fail "${runner_service} is not active"

variable_value="$(gh variable get SHARIPOVAI_SELF_HOSTED_CI --repo "${REPOSITORY}" --json value --jq '.value')"
[[ "${variable_value}" == '1' ]] || fail 'SHARIPOVAI_SELF_HOSTED_CI was not enabled'

log 'starting a real CI verification run on the VPS runner'
previous_run_id="$(
  gh run list --repo "${REPOSITORY}" --workflow ci.yml --limit 1 --json databaseId \
    --jq '.[0].databaseId // 0'
)"
gh workflow run ci.yml --repo "${REPOSITORY}" --ref main

run_id=''
for _ in $(seq 1 30); do
  run_id="$(
    gh run list --repo "${REPOSITORY}" --workflow ci.yml --limit 1 --json databaseId \
      --jq '.[0].databaseId // 0'
  )"
  if [[ -n "${run_id}" && "${run_id}" != '0' && "${run_id}" != "${previous_run_id}" ]]; then
    break
  fi
  sleep 2
done
[[ -n "${run_id}" && "${run_id}" != '0' && "${run_id}" != "${previous_run_id}" ]] \
  || fail 'new CI run was not created'

gh run watch "${run_id}" --repo "${REPOSITORY}" --exit-status

log "runner ready: service=${runner_service}; workflow_run=${run_id}; ci=passed"
