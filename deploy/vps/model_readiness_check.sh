#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
APP_DIR=${APP_DIR:-/opt/sharipovai-repo}
exec 9>"${MODEL_READINESS_LOCK_FILE:-/run/lock/sharipovai-model-readiness.lock}"
flock -n 9 || { echo "DEFERRED: readiness check already active"; exit 75; }
# Metadata scans share the same maintenance exclusion as local diagnostics.
backup_lock=${ASTRA_EXPORT_LOCK_FILE:-$APP_DIR/deploy/vps/backups/.export.lock}
[[ -f "$backup_lock" ]] || { echo 'DEFERRED: maintenance lock unavailable'; exit 75; }
exec 8<"$backup_lock"
exec 7>>"${ASTRA_DEPLOY_LOCK_FILE:-/run/lock/sharipovai-deploy.lock}"
flock -sn 8 && flock -sn 7 || { echo 'DEFERRED: backup or deployment active'; exit 75; }
guard_status=0
PYTHONPATH="$APP_DIR" python3 -c 'from tools.astra_supervisor import resource_state; raise SystemExit(0 if resource_state()["safe"] else 75)' || guard_status=$?
if (( guard_status != 0 )); then
  (( guard_status != 75 )) || echo 'DEFERRED: resource guard'
  exit "$guard_status"
fi
result=$(mktemp)
trap 'rm -f "$result"' EXIT
status=0
docker exec sharipovai python -m scripts.paper_forecast_readiness >"$result" || status=$?
cat "$result"
(( status == 0 )) || exit "$status"
# Cooldown is a successful skip, not a fresh scan or a resource retry.
if python3 -c 'import json,sys; r=json.load(open(sys.argv[1])); sys.exit(r.get("reasons") != ["six_hour_cooldown"])' "$result"; then
  echo 'DEFERRED: six-hour cooldown'
  exit 76
fi
# Delivery may have failed because the supervisor lock was held. Re-deliver
# the same idempotent queue item at the next metadata check, never a new run.
if python3 -c 'import json,sys; r=json.load(open(sys.argv[1])); sys.exit(r.get("ready") is not True)' "$result"; then
  systemctl start --no-block sharipovai-model-continuation.service
fi
