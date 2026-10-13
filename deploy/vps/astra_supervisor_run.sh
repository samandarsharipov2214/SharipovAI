#!/usr/bin/env bash
# Bounded host runner.  It never mutates production state.
set -Eeuo pipefail
umask 077

APP_DIR=${SHARIPOVAI_REPO_DIR:-/opt/sharipovai-repo}
STATE_DIR=${ASTRA_SUPERVISOR_STATE_DIR:-/var/lib/sharipovai/astra-supervisor}
LOCK=${ASTRA_SUPERVISOR_LOCK_FILE:-/run/lock/sharipovai-astra-supervisor.lock}
STATE="$STATE_DIR/astra_state.json"
STATUS="$STATE_DIR/ASTRA_STATUS.md"
RESULT="$STATE_DIR/paper_execution_diagnosis.json"

install -d -m 0700 "$STATE_DIR" /run/lock
exec 9>"$LOCK"
flock -n 9 || exit 0
export ASTRA_SUPERVISOR_PID=$$
export ASTRA_SUPERVISOR_OWNER="systemd:${INVOCATION_ID:-manual}:$$"

# Hold shared locks for the whole diagnostic so backup/deploy cannot begin
# midway through a supposedly idle window. Existing locks are never removed.
if [[ -f "$APP_DIR/deploy/vps/backups/.export.lock" ]]; then
    exec 8<"$APP_DIR/deploy/vps/backups/.export.lock"
    flock -sn 8 || export ASTRA_MAINTENANCE_BUSY=backup_export
else
    export ASTRA_MAINTENANCE_BUSY=backup_lock_unavailable
fi
exec 7>>"${ASTRA_DEPLOY_LOCK_FILE:-/run/lock/sharipovai-deploy.lock}"
flock -sn 7 || export ASTRA_MAINTENANCE_BUSY=deployment

codex_args=()
if [[ "${ASTRA_CODEX_AUTOMATION:-0}" == 1 && -n "${CODEX_ACCESS_TOKEN:-}" ]]; then
    codex_args+=(--codex-available)
fi
action=$(python3 "$APP_DIR/tools/astra_supervisor.py" --state "$STATE" --status "$STATUS" "${codex_args[@]}")
if ! python3 - "$action" <<'PY'
import json,sys
raise SystemExit(0 if json.loads(sys.argv[1]).get("action") in {"RUN_LOCAL", "RUN_CODEX"} else 1)
PY
then
    exit 0
fi

task=$(python3 - "$action" <<'PY'
import json,sys
print(json.loads(sys.argv[1])["task_id"])
PY
)
lease=$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["lease_id"])' "$action")
RESULT="$STATE_DIR/$task.json"
record_failure() {
    rc=$?
    trap - EXIT
    if (( rc != 0 )); then
        python3 - "$RESULT" "$rc" <<'PY'
import json,sys
with open(sys.argv[1], 'w', encoding='utf-8') as stream:
    json.dump({'status': 'FAILED', 'reason': 'runner_exit:' + sys.argv[2],
               'output': sys.argv[1]+'.tmp'}, stream)
PY
        python3 "$APP_DIR/tools/astra_supervisor.py" --state "$STATE" --status "$STATUS" \
            --complete "$task" --lease-id "$lease" --result "$RESULT" >/dev/null || true
    fi
    exit "$rc"
}
trap record_failure EXIT
case "$task" in
  paper_execution_diagnosis|paper_root_cause_audit)
    script=/app/scripts/astra_paper_diagnose.py
    [[ "$task" != paper_root_cause_audit ]] || script=/app/scripts/astra_paper_audit.py
    tmp="$RESULT.tmp"
    rm -f "$tmp"
    # The production service hardening intentionally prevents the runtime user
    # from reading the deployment checkout mounted at /workspace.  Execute the
    # immutable application copy packaged in the running image instead.
    timeout 90s docker exec -i sharipovai python "$script" >"$tmp" 2>"$RESULT.stderr"
    python3 - "$tmp" "$RESULT" <<'PY'
import json,os,sys
src,dst=sys.argv[1:]
value=json.load(open(src, encoding="utf-8"))
assert value["status"] == "VERIFIED" and value["read_only"] is True
os.replace(src,dst)
PY
    python3 "$APP_DIR/tools/astra_supervisor.py" --state "$STATE" --status "$STATUS" --complete "$task" --lease-id "$lease" --result "$RESULT" >/dev/null
    ;;
  codex-*)
    # Only a deliberately queued task file may start a bounded Codex session.
    # The scoped credential is injected by systemd; this script never reads,
    # copies, prints, or persists it.
    prompt="$STATE_DIR/tasks/$task.md"
    log="$STATE_DIR/$task.log"
    test -r "$prompt"
    if timeout 150s /root/.local/bin/codex exec --skip-git-repo-check --sandbox workspace-write <"$prompt" >"$log" 2>&1; then
        status=VERIFIED
    else
        status=FAILED
    fi
    python3 - "$log" "$RESULT" "$status" <<'PY'
import json,os,sys
log,result,status=sys.argv[1:]
os.replace(log, log + '.completed')
with open(result, 'w', encoding='utf-8') as handle:
    json.dump({'status': status, 'output': log + '.completed'}, handle)
PY
    python3 "$APP_DIR/tools/astra_supervisor.py" --state "$STATE" --status "$STATUS" --complete "$task" --lease-id "$lease" --result "$RESULT" --codex-available >/dev/null
    ;;
  *)
    # Never leave an unknown claimed task marked RUNNING.  A future runner may
    # add a handler, but the current attempt must close its durable lease with
    # an explicit checkpoint rather than relying on a later timeout.
    python3 - "$RESULT" "$task" <<'PY'
import json,sys
with open(sys.argv[1], 'w', encoding='utf-8') as handle:
    json.dump({'status': 'FAILED', 'output': 'unsupported_local_task:' + sys.argv[2]}, handle)
PY
    python3 "$APP_DIR/tools/astra_supervisor.py" --state "$STATE" --status "$STATUS" --complete "$task" --lease-id "$lease" --result "$RESULT" >/dev/null
    trap - EXIT
    exit 64
    ;;
esac
