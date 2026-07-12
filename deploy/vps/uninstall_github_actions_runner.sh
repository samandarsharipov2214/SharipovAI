#!/usr/bin/env bash
set -Eeuo pipefail

REPOSITORY="${GITHUB_REPOSITORY:-samandarsharipov2214/SharipovAI}"
RUNNER_USER="${RUNNER_USER:-sharipov-ci}"
RUNNER_HOME="${RUNNER_HOME:-/opt/sharipovai-actions-runner}"
CI_VARIABLE="SHARIPOVAI_SELF_HOSTED_CI"

fail() { printf '[sharipovai-ci] ERROR: %s\n' "$*" >&2; exit 1; }
[[ ${EUID} -eq 0 ]] || fail 'run as root'

if [[ -x "${RUNNER_HOME}/svc.sh" ]]; then
  "${RUNNER_HOME}/svc.sh" stop >/dev/null 2>&1 || true
  "${RUNNER_HOME}/svc.sh" uninstall >/dev/null 2>&1 || true
fi

remove_token="${GITHUB_RUNNER_REMOVE_TOKEN:-}"
if [[ -z "${remove_token}" && -n "${GH_TOKEN:-}" ]]; then
  remove_token="$(curl --fail --silent --show-error --request POST \
    --header "Authorization: Bearer ${GH_TOKEN}" \
    --header 'Accept: application/vnd.github+json' \
    --header 'X-GitHub-Api-Version: 2022-11-28' \
    "https://api.github.com/repos/${REPOSITORY}/actions/runners/remove-token" | jq -r '.token // empty')"
fi

if [[ -f "${RUNNER_HOME}/.runner" && -n "${remove_token}" ]]; then
  runuser -u "${RUNNER_USER}" -- bash -lc \
    "cd '${RUNNER_HOME}' && ./config.sh remove --unattended --token '${remove_token}'" >/dev/null
fi

if [[ -n "${GH_TOKEN:-}" ]]; then
  payload="$(jq -nc --arg name "${CI_VARIABLE}" --arg value '0' '{name:$name,value:$value}')"
  curl --silent --output /dev/null --request PATCH \
    --header "Authorization: Bearer ${GH_TOKEN}" \
    --header 'Accept: application/vnd.github+json' \
    --header 'X-GitHub-Api-Version: 2022-11-28' \
    "https://api.github.com/repos/${REPOSITORY}/actions/variables/${CI_VARIABLE}" \
    --data "${payload}" || true
fi

rm -rf "${RUNNER_HOME}"
if id -u "${RUNNER_USER}" >/dev/null 2>&1; then
  userdel "${RUNNER_USER}" >/dev/null 2>&1 || true
fi
printf '[sharipovai-ci] runner removed\n'
