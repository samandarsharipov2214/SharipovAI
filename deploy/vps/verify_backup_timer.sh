#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

APP_DIR=${APP_DIR:-/opt/sharipovai-repo}
MAX_AGE=${BACKUP_MAX_AGE_SECONDS:-3600}
TIMER=sharipovai-backup.timer
SERVICE=sharipovai-backup.service

fail() { printf '[backup-verify] ERROR: %s\n' "$*" >&2; exit 1; }
log() { printf '[backup-verify] %s\n' "$*"; }

[[ "$APP_DIR" == /* && "$APP_DIR" != *$'\n'* && "$APP_DIR" != *'/../'* ]] \
  || fail 'APP_DIR must be a safe absolute path'
[[ "$MAX_AGE" =~ ^[0-9]+$ ]] || fail 'BACKUP_MAX_AGE_SECONDS must be an integer'
(( MAX_AGE > 0 && MAX_AGE <= 3600 )) || fail 'BACKUP_MAX_AGE_SECONDS must be between 1 and 3600'

systemctl is-enabled --quiet "$TIMER" || fail "$TIMER is not enabled"
systemctl is-active --quiet "$TIMER" || fail "$TIMER is not active"
if systemctl is-failed --quiet "$SERVICE"; then
  fail "$SERVICE is failed"
fi

latest=$(readlink -f "$APP_DIR/deploy/vps/backups/latest.tar.gz")
[[ -n "$latest" ]] || fail 'latest backup symlink is missing'
test -s "$latest" || fail 'latest backup archive is missing or empty'
test -s "$latest.sha256" || fail 'latest backup checksum is missing'
(
  cd "$(dirname "$latest")"
  sha256sum -c "$(basename "$latest.sha256")" >/dev/null
) || fail 'latest backup checksum verification failed'

now=$(date +%s)
modified=$(stat -c %Y "$latest")
age=$(( now - modified ))
(( age >= 0 )) || fail 'latest backup timestamp is in the future'
(( age <= MAX_AGE )) || fail "latest verified backup is stale: ${age}s > ${MAX_AGE}s"

next_run=$(systemctl show "$TIMER" --property=NextElapseUSecRealtime --value)
last_trigger=$(systemctl show "$TIMER" --property=LastTriggerUSec --value)
[[ -n "$next_run" ]] || fail 'backup timer has no next scheduled run'
[[ -n "$last_trigger" ]] || fail 'backup timer has no last trigger evidence'

log "timer=active latest=$latest age_seconds=$age max_age_seconds=$MAX_AGE next_run=$next_run"
