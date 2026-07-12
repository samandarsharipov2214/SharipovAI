#!/usr/bin/env bash
set -euo pipefail

APP_DIR=${APP_DIR:-/opt/sharipovai}
SCRIPT="$APP_DIR/deploy/vps/export_backup.sh"
SERVICE=/etc/systemd/system/sharipovai-backup.service
TIMER=/etc/systemd/system/sharipovai-backup.timer

if [ "$(id -u)" -ne 0 ]; then
  echo "Run as root: sudo APP_DIR=$APP_DIR bash $0" >&2
  exit 1
fi
if [ ! -x "$SCRIPT" ]; then
  chmod 750 "$SCRIPT"
fi

cat > "$SERVICE" <<EOF
[Unit]
Description=SharipovAI verified VPS backup
Requires=docker.service
After=docker.service

[Service]
Type=oneshot
User=root
Environment=APP_DIR=$APP_DIR
ExecStart=/usr/bin/bash $SCRIPT
Nice=10
IOSchedulingClass=best-effort
IOSchedulingPriority=7
PrivateTmp=true
NoNewPrivileges=true
EOF

cat > "$TIMER" <<'EOF'
[Unit]
Description=Run SharipovAI verified backup every hour

[Timer]
OnBootSec=10min
OnUnitActiveSec=1h
RandomizedDelaySec=5min
Persistent=true
Unit=sharipovai-backup.service

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable --now sharipovai-backup.timer
systemctl start sharipovai-backup.service
systemctl is-active --quiet sharipovai-backup.timer
systemctl is-failed --quiet sharipovai-backup.service && exit 1 || true
latest=$(readlink -f "$APP_DIR/deploy/vps/backups/latest.tar.gz")
test -s "$latest"
test -s "$latest.sha256"
echo "SharipovAI VPS backup timer installed and first verified backup created: $latest"
