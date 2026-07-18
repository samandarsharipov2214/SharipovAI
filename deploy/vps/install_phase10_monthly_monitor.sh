#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="${REPO_ROOT:-/opt/sharipovai-repo}"
SERVICE_SRC="$REPO_ROOT/deploy/vps/systemd/sharipovai-monthly-performance.service"
TIMER_SRC="$REPO_ROOT/deploy/vps/systemd/sharipovai-monthly-performance.timer"

[[ "${EUID}" -eq 0 ]] || { echo "root required" >&2; exit 1; }
[[ -f "$SERVICE_SRC" && -f "$TIMER_SRC" ]] || { echo "Phase 10 systemd units missing" >&2; exit 1; }
install -m 0644 "$SERVICE_SRC" /etc/systemd/system/sharipovai-monthly-performance.service
install -m 0644 "$TIMER_SRC" /etc/systemd/system/sharipovai-monthly-performance.timer
mkdir -p /var/lib/sharipovai/performance
systemctl daemon-reload
systemctl enable --now sharipovai-monthly-performance.timer
systemctl is-enabled --quiet sharipovai-monthly-performance.timer
systemctl is-active --quiet sharipovai-monthly-performance.timer
systemctl list-timers sharipovai-monthly-performance.timer --no-pager
