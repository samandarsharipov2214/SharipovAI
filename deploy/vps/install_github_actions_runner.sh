#!/usr/bin/env bash
set -Eeuo pipefail

REPOSITORY="${GITHUB_REPOSITORY:-samandarsharipov2214/SharipovAI}"
RUNNER_USER="${RUNNER_USER:-sharipov-ci}"
RUNNER_HOME="${RUNNER_HOME:-/opt/sharipovai-actions-runner}"
RUNNER_NAME="${RUNNER_NAME:-sharipovai-vps-$(hostname -s)}"
RUNNER_LABELS="${RUNNER_LABELS:-sharipovai-ci}"
RUNNER_WORK="${RUNNER_WORK:-_work}"
CI_VARIABLE="SHARIPOVAI_SELF_HOSTED_CI"

log() { printf '[sharipovai-ci] %s\n' "$*"; }
fail() { printf '[sharipovai-ci] ERROR: %s\n' "$*" >&2; exit 1; }
run_svc() { (cd "${RUNNER_HOME}" && ./svc.sh "$@"); }

[[ ${EUID} -eq 0 ]] || fail 'run as root'
[[ "${REPOSITORY}" == */* ]] || fail 'GITHUB_REPOSITORY must be owner/repo'

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq curl ca-certificates git jq tar gzip python3 python3-venv python3-pip >/dev/null

if ! id -u "${RUNNER_USER}" >/dev/null 2>&1; then
  useradd --system --create-home --home-dir "/var/lib/${RUNNER_USER}" --shell /usr/sbin/nologin "${RUNNER_USER}"
fi

mkdir -p "${RUNNER_HOME}"
chown -R "${RUNNER_USER}:${RUNNER_USER}" "${RUNNER_HOME}"

latest_json="$(curl --fail --silent --show-error --location \
  --proto '=https' --tlsv1.2 \
  https://api.github.com/repos/actions/runner/releases/latest)"
runner_tag="$(jq -r '.tag_name // empty' <<<"${latest_json}")"
[[ -n "${runner_tag}" ]] || fail 'cannot determine latest actions/runner release'
runner_version="${runner_tag#v}"
runner_archive="actions-runner-linux-x64-${runner_version}.tar.gz"
runner_url="https://github.com/actions/runner/releases/download/${runner_tag}/${runner_archive}"

if [[ ! -x "${RUNNER_HOME}/config.sh" ]]; then
  log "downloading GitHub Actions runner ${runner_version}"
  tmp_archive="$(mktemp)"
  trap 'rm -f "${tmp_archive:-}"' EXIT
  curl --fail --silent --show-error --location \
    --proto '=https' --tlsv1.2 \
    "${runner_url}" -o "${tmp_archive}"
  tar -xzf "${tmp_archive}" -C "${RUNNER_HOME}"
  chown -R "${RUNNER_USER}:${RUNNER_USER}" "${RUNNER_HOME}"
fi

if [[ -x "${RUNNER_HOME}/bin/installdependencies.sh" ]]; then
  dependency_log="$(mktemp)"
  if ! "${RUNNER_HOME}/bin/installdependencies.sh" >"${dependency_log}" 2>&1; then
    cat "${dependency_log}" >&2
    rm -f "${dependency_log}"
    fail 'GitHub Actions runner dependency installation failed'
  fi
  rm -f "${dependency_log}"
fi

registration_token="${GITHUB_RUNNER_TOKEN:-}"
if [[ -z "${registration_token}" && -n "${GH_TOKEN:-}" ]]; then
  registration_token="$(curl --fail --silent --show-error --request POST \
    --header "Authorization: Bearer ${GH_TOKEN}" \
    --header 'Accept: application/vnd.github+json' \
    --header 'X-GitHub-Api-Version: 2022-11-28' \
    "https://api.github.com/repos/${REPOSITORY}/actions/runners/registration-token" | jq -r '.token // empty')"
fi
[[ -n "${registration_token}" ]] || fail 'set GH_TOKEN (repo admin) or one-time GITHUB_RUNNER_TOKEN'

if [[ -f "${RUNNER_HOME}/.runner" ]]; then
  log 'runner is already configured; replacing registration safely'
  if [[ -x "${RUNNER_HOME}/svc.sh" ]]; then
    run_svc stop >/dev/null 2>&1 || true
    run_svc uninstall >/dev/null 2>&1 || true
  fi
  remove_token="${GITHUB_RUNNER_REMOVE_TOKEN:-}"
  if [[ -z "${remove_token}" && -n "${GH_TOKEN:-}" ]]; then
    remove_token="$(curl --fail --silent --show-error --request POST \
      --header "Authorization: Bearer ${GH_TOKEN}" \
      --header 'Accept: application/vnd.github+json' \
      --header 'X-GitHub-Api-Version: 2022-11-28' \
      "https://api.github.com/repos/${REPOSITORY}/actions/runners/remove-token" | jq -r '.token // empty')"
  fi
  if [[ -n "${remove_token}" ]]; then
    runuser -u "${RUNNER_USER}" -- bash -lc \
      "cd '${RUNNER_HOME}' && ./config.sh remove --unattended --token '${remove_token}'" >/dev/null 2>&1 || true
  fi
fi

runuser -u "${RUNNER_USER}" -- bash -lc \
  "cd '${RUNNER_HOME}' && ./config.sh \
    --url 'https://github.com/${REPOSITORY}' \
    --token '${registration_token}' \
    --name '${RUNNER_NAME}' \
    --labels '${RUNNER_LABELS}' \
    --work '${RUNNER_WORK}' \
    --unattended --replace"

run_svc install "${RUNNER_USER}" >/dev/null
run_svc start >/dev/null

if [[ -n "${GH_TOKEN:-}" ]]; then
  variable_payload="$(jq -nc --arg name "${CI_VARIABLE}" --arg value '1' '{name:$name,value:$value}')"
  status="$(curl --silent --output /dev/null --write-out '%{http_code}' --request PATCH \
    --header "Authorization: Bearer ${GH_TOKEN}" \
    --header 'Accept: application/vnd.github+json' \
    --header 'X-GitHub-Api-Version: 2022-11-28' \
    "https://api.github.com/repos/${REPOSITORY}/actions/variables/${CI_VARIABLE}" \
    --data "${variable_payload}")"
  if [[ "${status}" == '404' ]]; then
    curl --fail --silent --show-error --request POST \
      --header "Authorization: Bearer ${GH_TOKEN}" \
      --header 'Accept: application/vnd.github+json' \
      --header 'X-GitHub-Api-Version: 2022-11-28' \
      "https://api.github.com/repos/${REPOSITORY}/actions/variables" \
      --data "${variable_payload}" >/dev/null
  elif [[ "${status}" != '204' ]]; then
    fail "runner installed, but repository variable update returned HTTP ${status}"
  fi
else
  log "runner installed; set repository variable ${CI_VARIABLE}=1 to enable workflows"
fi

log "runner ${RUNNER_NAME} is installed with label ${RUNNER_LABELS}"
