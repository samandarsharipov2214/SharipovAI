#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="/opt/sharipovai-repo"
SERVICE="sharipovai"
WATCHER_SOURCE="$ROOT/scripts/sharipovai_deploy_watcher.sh"
WATCHER_TARGET="/usr/local/sbin/sharipovai-deploy-watcher"
UNIT_FILE="/etc/systemd/system/sharipovai-deploy-watcher.service"

[[ "$(id -u)" == "0" ]] || { echo "Run as root" >&2; exit 1; }
[[ -f "$WATCHER_SOURCE" ]] || { echo "Missing $WATCHER_SOURCE" >&2; exit 1; }
docker container inspect "$SERVICE" >/dev/null
bash -n "$WATCHER_SOURCE"

origin_url="$(git -C "$ROOT" remote get-url origin)"
watcher_fetch_url="${SHARIPOVAI_WATCHER_FETCH_URL:-}"
if [[ -z "$watcher_fetch_url" ]]; then
  case "$origin_url" in
    git@github.com:*)
      watcher_fetch_url="https://github.com/${origin_url#git@github.com:}"
      ;;
    ssh://git@github.com/*)
      watcher_fetch_url="https://github.com/${origin_url#ssh://git@github.com/}"
      ;;
    https://github.com/*)
      watcher_fetch_url="$origin_url"
      ;;
    *)
      echo "Set SHARIPOVAI_WATCHER_FETCH_URL to a non-interactive HTTPS repository URL" >&2
      exit 1
      ;;
  esac
fi
[[ "$watcher_fetch_url" =~ ^https://github\.com/[A-Za-z0-9._-]+/[A-Za-z0-9._-]+(\.git)?$ ]] || {
  echo "Watcher fetch URL must be an HTTPS GitHub repository URL" >&2
  exit 1
}

install -o root -g root -m 0750 "$WATCHER_SOURCE" "$WATCHER_TARGET"
cat >"$UNIT_FILE" <<EOF
[Unit]
Description=SharipovAI Telegram protected deployment watcher
After=docker.service network-online.target
Wants=network-online.target
Requires=docker.service

[Service]
Type=simple
Environment=FETCH_REMOTE=${watcher_fetch_url}
ExecStart=/usr/local/sbin/sharipovai-deploy-watcher
Restart=always
RestartSec=5
User=root
Group=root
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=full
ReadWritePaths=/opt/sharipovai-repo /run /tmp

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable sharipovai-deploy-watcher.service >/dev/null
if [[ "${SHARIPOVAI_DEPLOY_WATCHER_ACTIVE:-0}" != "1" ]]; then
  systemctl restart sharipovai-deploy-watcher.service
fi
systemctl is-active --quiet sharipovai-deploy-watcher.service

claim_code="$(docker exec "$SERVICE" python - <<'PY'
import json, os, secrets, time
from pathlib import Path
root = Path('/var/lib/sharipovai/deployment_control')
root.mkdir(parents=True, exist_ok=True)
owner = root / 'owner.json'
claim = root / 'owner_claim.json'
env_owner = bool(os.getenv('TELEGRAM_ADMIN_USER_ID', '').strip() or os.getenv('TELEGRAM_ADMIN_CHAT_ID', '').strip())
if owner.exists() or env_owner:
    print('')
else:
    code = f'{secrets.randbelow(900000) + 100000}'
    temp = root / f'owner_claim.tmp-{os.getpid()}'
    temp.write_text(json.dumps({'code': code, 'expires_at': int(time.time()) + 1800}), encoding='utf-8')
    os.replace(temp, claim)
    print(code)
PY
)"

echo "TELEGRAM_DEPLOY_WATCHER_OK"
if [[ -n "$claim_code" ]]; then
  echo "TELEGRAM_OWNER_CLAIM_CODE=$claim_code"
  echo "Send to the bot within 30 minutes: /claim_owner $claim_code"
else
  echo "TELEGRAM_OWNER_ALREADY_CONFIGURED"
fi
