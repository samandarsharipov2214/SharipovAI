#!/usr/bin/env bash
set -Eeuo pipefail
umask 027

ROOT="${SHARIPOVAI_ROOT:-${APP_DIR:-/opt/sharipovai-repo}}"
SERVICE_USER="${SHARIPOVAI_SERVICE_USER:-sharipovai}"
SERVICE_GROUP="${SHARIPOVAI_SERVICE_GROUP:-sharipovai}"
[[ "${EUID}" -eq 0 ]] || { echo "run as root" >&2; exit 2; }
[[ -d "$ROOT/.git" ]] || { echo "canonical repository missing: $ROOT" >&2; exit 2; }
[[ -f "$ROOT/deploy/vps/systemd/sharipovai-monthly-performance.service" ]] || { echo "service unit missing" >&2; exit 2; }
[[ -f "$ROOT/deploy/vps/systemd/sharipovai-monthly-performance.timer" ]] || { echo "timer unit missing" >&2; exit 2; }
id "$SERVICE_USER" >/dev/null 2>&1 || { echo "service user not found" >&2; exit 2; }
getent group "$SERVICE_GROUP" >/dev/null 2>&1 || { echo "service group not found" >&2; exit 2; }
install -d -m 0750 -o "$SERVICE_USER" -g "$SERVICE_GROUP" /var/lib/sharipovai/performance
sed "s|@SHARIPOVAI_ROOT@|$ROOT|g" \
  "$ROOT/deploy/vps/systemd/sharipovai-monthly-performance.service" \
  | install -m 0644 /dev/stdin /etc/systemd/system/sharipovai-monthly-performance.service
install -m 0644 \
  "$ROOT/deploy/vps/systemd/sharipovai-monthly-performance.timer" \
  /etc/systemd/system/sharipovai-monthly-performance.timer
systemd-analyze verify \
  /etc/systemd/system/sharipovai-monthly-performance.service \
  /etc/systemd/system/sharipovai-monthly-performance.timer
systemctl daemon-reload
systemctl enable --now sharipovai-monthly-performance.timer
systemctl is-enabled --quiet sharipovai-monthly-performance.timer
systemctl is-active --quiet sharipovai-monthly-performance.timer
systemctl list-timers sharipovai-monthly-performance.timer --no-pager
