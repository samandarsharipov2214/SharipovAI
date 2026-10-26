#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

APP_DIR=${APP_DIR:-/opt/sharipovai-repo}
EXPORTER="$APP_DIR/deploy/vps/export_backup.sh"
STATE_DIR=${SHARIPOVAI_BACKUP_TIMER_STATE_DIR:-/var/lib/sharipovai/backup}
STATUS_FILE="$STATE_DIR/last_timer_run.json"
DEPLOY_LOCK=${LOCK_FILE:-/run/lock/sharipovai-deploy.lock}

fail() { printf '[backup-timer] ERROR: %s\n' "$*" >&2; exit 1; }
[[ "$APP_DIR" == /* && "$APP_DIR" != *$'\n'* && "$APP_DIR" != *'/../'* ]] || fail 'APP_DIR must be a safe absolute path'
[[ "$STATE_DIR" == /* && "$STATE_DIR" != *$'\n'* && "$STATE_DIR" != *'/../'* ]] || fail 'state directory must be a safe absolute path'
[[ "$DEPLOY_LOCK" == /* && "$DEPLOY_LOCK" != *$'\n'* && "$DEPLOY_LOCK" != *'/../'* ]] || fail 'deployment lock must be a safe absolute path'
[[ -r "$EXPORTER" ]] || fail "backup exporter is missing or not readable: $EXPORTER"
mkdir -p -m 0700 "$STATE_DIR"

write_status() {
  local outcome=$1 code=$2
  local tmp
  tmp=$(mktemp "$STATE_DIR/.last_timer_run.XXXXXX")
  python3 - "$outcome" "$code" >"$tmp" <<'PY'
import json
import sys
from datetime import datetime, timezone
print(json.dumps({
    "schema": 1,
    "outcome": sys.argv[1],
    "exit_code": int(sys.argv[2]),
    "finished_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
}, sort_keys=True))
PY
  chmod 0600 "$tmp"
  mv -f "$tmp" "$STATUS_FILE"
}

# Hold the updater's shared lock for the whole scheduled export. Checking only
# .export.lock allowed a new hourly backup during the updater's build/cutover.
# The updater's own mandatory exporter runs directly under its exclusive lock.
exec 8>"$DEPLOY_LOCK"
if ! flock -sn 8; then
  write_status SKIPPED_ACTIVE_DEPLOYMENT 75
  printf '[backup-timer] SKIPPED_ACTIVE_DEPLOYMENT: supervised release owns the lock\n'
  exit 0
fi

set +e
SHARIPOVAI_BACKUP_LOCK_BUSY_EXIT=75 bash "$EXPORTER"
rc=$?
set -e
case "$rc" in
  0)
    write_status VERIFIED 0
    printf '[backup-timer] VERIFIED: exporter completed\n'
    ;;
  75)
    # A skip is deliberately distinguishable from a verified backup.  It is
    # not a systemd failure because a concurrent exporter is an expected,
    # safe condition; freshness remains enforced by verify_backup_timer.sh.
    write_status SKIPPED_ACTIVE_EXPORT 75
    printf '[backup-timer] SKIPPED_ACTIVE_EXPORT: another exporter owns the lock\n'
    ;;
  *)
    write_status FAILED "$rc"
    exit "$rc"
    ;;
esac
