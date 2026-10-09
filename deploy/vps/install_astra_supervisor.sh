#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

APP_DIR=${APP_DIR:-/opt/sharipovai-repo}
SERVICE=sharipovai-astra-supervisor.service
TIMER=sharipovai-astra-supervisor.timer

[[ $(id -u) -eq 0 ]] || { echo 'run as root' >&2; exit 1; }
[[ "$APP_DIR" == /* && "$APP_DIR" != *$'\n'* && "$APP_DIR" != *'/../'* ]] || exit 1
for path in deploy/vps/astra_supervisor_run.sh tools/astra_supervisor.py scripts/astra_paper_diagnose.py; do
  test -f "$APP_DIR/$path" || { echo "missing $path" >&2; exit 1; }
done
install -d -m 0700 /var/lib/sharipovai/astra-supervisor/tasks /run/lock /etc/sharipovai
# The unit invokes this tracked script explicitly through /usr/bin/bash.  Do
# not chmod it here: changing its executable bit makes the production checkout
# dirty and fail-closes the canonical updater before its recovery gates.
for unit in "$SERVICE" "$TIMER"; do
  install -m 0644 "$APP_DIR/deploy/vps/systemd/$unit" "/etc/systemd/system/$unit"
  cmp "$APP_DIR/deploy/vps/systemd/$unit" "/etc/systemd/system/$unit"
done
systemctl daemon-reload
systemctl enable --now "$TIMER"
systemctl is-enabled --quiet "$TIMER"
systemctl is-active --quiet "$TIMER"
