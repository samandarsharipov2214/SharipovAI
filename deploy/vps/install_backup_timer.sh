#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

APP_DIR=${APP_DIR:-/opt/sharipovai-repo}
SCRIPT="$APP_DIR/deploy/vps/export_backup.sh"
VERIFY="$APP_DIR/deploy/vps/verify_backup_timer.sh"
SERVICE=/etc/systemd/system/sharipovai-backup.service
TIMER=/etc/systemd/system/sharipovai-backup.timer

fail() { printf '[backup-timer] ERROR: %s\n' "$*" >&2; exit 1; }
log() { printf '[backup-timer] %s\n' "$*"; }

if [ "$(id -u)" -ne 0 ]; then
  fail "run as root: sudo APP_DIR=$APP_DIR bash $0"
fi
[[ "$APP_DIR" == /* && "$APP_DIR" != *$'\n'* && "$APP_DIR" != *'/../'* ]] \
  || fail 'APP_DIR must be a safe absolute path'
[[ -f "$SCRIPT" ]] || fail "backup exporter is missing: $SCRIPT"
[[ -f "$VERIFY" ]] || fail "backup verifier is missing: $VERIFY"
chmod 750 "$SCRIPT" "$VERIFY"

cat > "$SERVICE" <<EOF
[Unit]
Description=SharipovAI verified VPS backup
Requires=docker.service
After=docker.service

[Service]
Type=oneshot
User=root
WorkingDirectory=$APP_DIR/deploy/vps
Environment=APP_DIR=$APP_DIR
ExecStartPre=/usr/bin/test -x $SCRIPT
ExecStart=/usr/bin/bash $SCRIPT
TimeoutStartSec=20min
Nice=10
IOSchedulingClass=best-effort
IOSchedulingPriority=7
PrivateTmp=true
NoNewPrivileges=true
EOF

cat > "$TIMER" <<'EOF'
[Unit]
Description=Run SharipovAI verified backup at least once per hour

[Timer]
OnBootSec=5min
OnCalendar=hourly
OnUnitActiveSec=45min
AccuracySec=30s
RandomizedDelaySec=0
Persistent=true
Unit=sharipovai-backup.service

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable --now sharipovai-backup.timer
systemctl reset-failed sharipovai-backup.service || true
systemctl start sharipovai-backup.service
systemctl is-enabled --quiet sharipovai-backup.timer
systemctl is-active --quiet sharipovai-backup.timer
systemctl is-failed --quiet sharipovai-backup.service && fail 'first backup service run failed'

latest=$(readlink -f "$APP_DIR/deploy/vps/backups/latest.tar.gz")
test -s "$latest" || fail 'latest backup archive is missing or empty'
test -s "$latest.sha256" || fail 'latest backup checksum is missing'
(
  cd "$(dirname "$latest")"
  sha256sum -c "$(basename "$latest.sha256")" >/dev/null
) || fail 'latest backup checksum verification failed'

next_run=$(systemctl show sharipovai-backup.timer --property=NextElapseUSecRealtime --value)
[[ -n "$next_run" ]] || fail 'backup timer has no next scheduled run'
APP_DIR="$APP_DIR" BACKUP_MAX_AGE_SECONDS=3600 bash "$VERIFY"
log "timer active; first verified backup: $latest; next run: $next_run"
