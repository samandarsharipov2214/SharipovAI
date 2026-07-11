#!/usr/bin/env bash
set -euo pipefail

APP_DIR=${APP_DIR:-/opt/sharipovai}
REPO_URL=${REPO_URL:-https://github.com/samandarsharipov2214/SharipovAI.git}
BRANCH=${BRANCH:-main}

if [ "$(id -u)" -ne 0 ]; then
  echo "Run as root: sudo bash deploy/vps/install.sh" >&2
  exit 1
fi

apt-get update
apt-get install -y ca-certificates curl git
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
. /etc/os-release
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${UBUNTU_CODENAME:-$VERSION_CODENAME} stable" > /etc/apt/sources.list.d/docker.list
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable --now docker

if [ ! -d "$APP_DIR/.git" ]; then
  git clone --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
else
  git -C "$APP_DIR" fetch --prune origin
  git -C "$APP_DIR" checkout "$BRANCH"
  git -C "$APP_DIR" reset --hard "origin/$BRANCH"
fi

cd "$APP_DIR/deploy/vps"
if [ ! -f .env.vps ]; then
  cp .env.vps.example .env.vps
  chmod 600 .env.vps
  echo "Created $APP_DIR/deploy/vps/.env.vps"
  echo "Fill it with the domain and secrets, then rerun this script."
  exit 2
fi

chmod 600 .env.vps
docker compose config >/dev/null
docker compose build --pull
docker compose up -d

docker compose ps
curl --fail --silent --show-error http://127.0.0.1:8000/health >/dev/null
echo "SharipovAI is healthy on 127.0.0.1:8000. HTTPS will become available after DNS points DOMAIN to this VPS."
