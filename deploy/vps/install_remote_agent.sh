#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="${APP_DIR:-/opt/sharipovai-repo}"
AGENT_SCRIPT="${APP_DIR}/deploy/vps/remote_agent.sh"
SERVICE_FILE="/etc/systemd/system/sharipovai-agent.service"
TIMER_FILE="/etc/systemd/system/sharipovai-agent.timer"

fail() { printf '[install-agent] ERROR: %s\n' "$*" >&2; exit 1; }
[[ ${EUID} -eq 0 ]] || fail 'run as root'
[[ -d "${APP_DIR}/.git" ]] || fail "repository not found at ${APP_DIR}"
[[ -f "${AGENT_SCRIPT}" ]] || fail "agent script not found: ${AGENT_SCRIPT}"

origin_url="$(git -C "${APP_DIR}" remote get-url origin)"
agent_fetch_url="${SHARIPOVAI_AGENT_FETCH_URL:-}"
if [[ -z "${agent_fetch_url}" ]]; then
  case "${origin_url}" in
    git@github.com:*)
      agent_fetch_url="https://github.com/${origin_url#git@github.com:}"
      ;;
    ssh://git@github.com/*)
      agent_fetch_url="https://github.com/${origin_url#ssh://git@github.com/}"
      ;;
    https://github.com/*)
      agent_fetch_url="${origin_url}"
      ;;
    *)
      fail "set SHARIPOVAI_AGENT_FETCH_URL to a non-interactive HTTPS repository URL"
      ;;
  esac
fi
[[ "${agent_fetch_url}" =~ ^https://github\.com/[A-Za-z0-9._-]+/[A-Za-z0-9._-]+(\.git)?$ ]] \
  || fail 'agent fetch URL must be an HTTPS GitHub repository URL'

apt-get update
apt-get install -y ca-certificates curl git python3 util-linux
chmod 0755 "${AGENT_SCRIPT}" "${APP_DIR}/deploy/vps/update_from_main.sh"
install -d -m 0755 /var/lib/sharipovai-agent

cat >"${SERVICE_FILE}" <<EOF
[Unit]
Description=SharipovAI autonomous maintenance agent
Wants=network-online.target docker.service
After=network-online.target docker.service
ConditionPathExists=${APP_DIR}/.git

[Service]
Type=oneshot
User=root
Group=root
Environment=APP_DIR=${APP_DIR}
Environment=BRANCH=main
Environment=FETCH_REMOTE=${agent_fetch_url}
Environment=HEALTH_URL=http://127.0.0.1:8000/health
ExecStart=${AGENT_SCRIPT}
TimeoutStartSec=1800
Nice=10
IOSchedulingClass=best-effort
IOSchedulingPriority=6
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=full
ReadWritePaths=${APP_DIR} /var/lib/sharipovai-agent /run/lock /var/lib/docker

[Install]
WantedBy=multi-user.target
EOF

cat >"${TIMER_FILE}" <<'EOF'
[Unit]
Description=Check SharipovAI updates every 3 minutes

[Timer]
OnBootSec=90s
OnUnitActiveSec=3min
AccuracySec=20s
Persistent=true
Unit=sharipovai-agent.service

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl reset-failed sharipovai-agent.service >/dev/null 2>&1 || true
systemctl enable --now sharipovai-agent.timer
systemctl start sharipovai-agent.service

printf '\n[install-agent] installed successfully\n'
systemctl --no-pager --full status sharipovai-agent.timer || true
printf '\nStatus file: /var/lib/sharipovai-agent/status.json\n'
printf 'Logs: journalctl -u sharipovai-agent -n 100 --no-pager\n'
