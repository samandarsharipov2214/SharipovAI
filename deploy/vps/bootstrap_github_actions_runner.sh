#!/usr/bin/env bash
set -Eeuo pipefail

REPOSITORY="${GITHUB_REPOSITORY:-samandarsharipov2214/SharipovAI}"
REPO_DIR="${REPO_DIR:-}"
AUTH_CREATED=0
AUTH_USER=""
BOOTSTRAP_SUCCEEDED=0

log() { printf '[sharipovai-runner-bootstrap] %s\n' "$*"; }
fail() { printf '[sharipovai-runner-bootstrap] ERROR: %s\n' "$*" >&2; exit 1; }

cleanup() {
  local rc=$?
  unset GH_TOKEN || true
  if [[ "${AUTH_CREATED}" == '1' && -n "${AUTH_USER}" ]]; then
    if [[ "${BOOTSTRAP_SUCCEEDED}" == '1' ]]; then
      printf 'y\n' | gh auth logout --hostname github.com --user "${AUTH_USER}" >/dev/null 2>&1 || true
    else
      log 'GitHub CLI login kept locally on the VPS so the bootstrap can be retried without a new device code'
    fi
  fi
  return "${rc}"
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
    --git-protocol https \
    --web \
    --scopes repo,workflow
  AUTH_CREATED=1
fi

AUTH_USER="$(gh api user --jq '.login')"
[[ -n "${AUTH_USER}" ]] || fail 'GitHub authentication did not return a user'
export GH_TOKEN="$(gh auth token --hostname github.com)"
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
  systemctl list-unit-files --type=service --no-legend 2>/dev/null \
    | awk '$1 ~ /^actions\.runner\..*\.service$/ {print $1; exit}'
)"
[[ -n "${runner_service}" ]] || fail 'runner systemd service was not created'
systemctl is-enabled --quiet "${runner_service}" || fail "${runner_service} is not enabled"
systemctl is-active --quiet "${runner_service}" || fail "${runner_service} is not active"

variable_value="$(
  gh api "repos/${REPOSITORY}/actions/variables/SHARIPOVAI_SELF_HOSTED_CI" \
    --jq '.value' 2>/dev/null || true
)"
[[ "${variable_value}" == '1' ]] || fail 'SHARIPOVAI_SELF_HOSTED_CI was not enabled'

log 'starting a real CI verification run on the VPS runner'
previous_run_id="$(
  gh api "repos/${REPOSITORY}/actions/workflows/ci.yml/runs?event=workflow_dispatch&per_page=1" \
    --jq '.workflow_runs[0].id // 0'
)"
gh api --method POST "repos/${REPOSITORY}/actions/workflows/ci.yml/dispatches" -f ref=main >/dev/null

run_id=''
for _ in $(seq 1 30); do
  run_id="$(
    gh api "repos/${REPOSITORY}/actions/workflows/ci.yml/runs?event=workflow_dispatch&per_page=1" \
      --jq '.workflow_runs[0].id // 0'
  )"
  if [[ -n "${run_id}" && "${run_id}" != '0' && "${run_id}" != "${previous_run_id}" ]]; then
    break
  fi
  sleep 2
done
[[ -n "${run_id}" && "${run_id}" != '0' && "${run_id}" != "${previous_run_id}" ]] \
  || fail 'new CI run was not created'

last_status=''
for _ in $(seq 1 180); do
  run_json="$(gh api "repos/${REPOSITORY}/actions/runs/${run_id}")"
  run_status="$(jq -r '.status // empty' <<<"${run_json}")"
  run_conclusion="$(jq -r '.conclusion // empty' <<<"${run_json}")"

  if [[ "${run_status}:${run_conclusion}" != "${last_status}" ]]; then
    log "workflow ${run_id}: status=${run_status:-unknown}; conclusion=${run_conclusion:-pending}"
    last_status="${run_status}:${run_conclusion}"
  fi

  if [[ "${run_status}" == 'completed' ]]; then
    [[ "${run_conclusion}" == 'success' ]] \
      || fail "workflow ${run_id} completed with conclusion ${run_conclusion:-unknown}"
    break
  fi
  sleep 5
done

final_conclusion="$(
  gh api "repos/${REPOSITORY}/actions/runs/${run_id}" --jq '.conclusion // empty'
)"
[[ "${final_conclusion}" == 'success' ]] || fail "workflow ${run_id} did not finish successfully"

BOOTSTRAP_SUCCEEDED=1
log "runner ready: service=${runner_service}; workflow_run=${run_id}; ci=passed"
