#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="${APP_DIR:-/opt/sharipovai-repo}"
REPO_URL="${REPO_URL:-https://github.com/samandarsharipov2214/SharipovAI.git}"
BRANCH="${BRANCH:-main}"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run as root: sudo bash deploy/vps/install.sh" >&2
  exit 1
fi
[[ "${APP_DIR}" == /* ]] || { echo "APP_DIR must be absolute" >&2; exit 1; }
[[ "${BRANCH}" =~ ^[A-Za-z0-9._/-]+$ ]] || { echo "Unsafe BRANCH" >&2; exit 1; }

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y ca-certificates curl git python3 util-linux
install -m 0755 -d /etc/apt/keyrings
curl -fsSL --proto '=https' --tlsv1.2 https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
. /etc/os-release
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${UBUNTU_CODENAME:-$VERSION_CODENAME} stable" > /etc/apt/sources.list.d/docker.list
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable --now docker

if [[ -d "${APP_DIR}/.git" ]]; then
  # Fetch the updater itself without changing the checked-out production tree.
  # The updater creates a verified backup before reset/build and rolls back on
  # health failure, so repeat installation is safe and idempotent.
  git -C "${APP_DIR}" fetch --prune origin "${BRANCH}"
  updater="$(mktemp)"
  trap 'rm -f "${updater:-}"' EXIT
  git -C "${APP_DIR}" show "origin/${BRANCH}:deploy/vps/update_from_main.sh" >"${updater}"
  APP_DIR="${APP_DIR}" BRANCH="${BRANCH}" bash "${updater}"
  exit 0
fi

git clone --branch "${BRANCH}" --single-branch "${REPO_URL}" "${APP_DIR}"
cd "${APP_DIR}/deploy/vps"
if [[ ! -f .env.vps ]]; then
  cp .env.vps.example .env.vps
  chmod 600 .env.vps
  echo "Created ${APP_DIR}/deploy/vps/.env.vps"
  echo "Fill it with the domain and secrets, then rerun this script."
  exit 2
fi

chmod 600 .env.vps
rendered_config="$(mktemp)"
trap 'rm -f "${rendered_config:-}"' EXIT
docker compose config --format json >"${rendered_config}"
python3 - "${rendered_config}" <<'PY'
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
environment = payload.get("services", {}).get("sharipovai", {}).get("environment", {})
if isinstance(environment, list):
    environment = dict(item.split("=", 1) for item in environment if "=" in item)
if str(environment.get("EXCHANGE_LIVE_TRADING_ENABLED", "")) != "0":
    raise SystemExit("initial install blocked: live trading must be disabled")
if str(environment.get("EXECUTION_KILL_SWITCH", "")) != "1":
    raise SystemExit("initial install blocked: execution kill switch must be enabled")
PY

docker compose build --pull
docker compose up -d --remove-orphans
docker compose ps
curl --fail --silent --show-error --retry 30 --retry-delay 2 --retry-all-errors http://127.0.0.1:8000/health >/dev/null
echo "SharipovAI is healthy on 127.0.0.1:8000. HTTPS is served by Caddy after DOMAIN resolves to this VPS."
