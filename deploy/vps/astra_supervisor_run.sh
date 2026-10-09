#!/usr/bin/env bash
# Bounded host runner.  It never mutates production state.
set -Eeuo pipefail
umask 077

APP_DIR=${SHARIPOVAI_REPO_DIR:-/opt/sharipovai-repo}
STATE_DIR=${ASTRA_SUPERVISOR_STATE_DIR:-/var/lib/sharipovai/astra-supervisor}
LOCK=/run/lock/sharipovai-astra-supervisor.lock
STATE="$STATE_DIR/astra_state.json"
STATUS="$STATE_DIR/ASTRA_STATUS.md"
RESULT="$STATE_DIR/paper_execution_diagnosis.json"

install -d -m 0700 "$STATE_DIR" /run/lock
exec 9>"$LOCK"
flock -n 9 || exit 0

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
case "$task" in
  paper_execution_diagnosis)
    tmp="$RESULT.tmp"
    rm -f "$tmp"
    # The production service hardening intentionally prevents the runtime user
    # from reading the deployment checkout mounted at /workspace.  Execute the
    # immutable application copy packaged in the running image instead.
    timeout 90s docker exec -i sharipovai python /app/scripts/astra_paper_diagnose.py >"$tmp"
    python3 - "$tmp" "$RESULT" <<'PY'
import json,os,sys
src,dst=sys.argv[1:]
value=json.load(open(src, encoding="utf-8"))
assert value["status"] == "VERIFIED" and value["read_only"] is True
os.replace(src,dst)
PY
    python3 "$APP_DIR/tools/astra_supervisor.py" --state "$STATE" --status "$STATUS" --complete "$task" --result "$RESULT" >/dev/null
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
    python3 "$APP_DIR/tools/astra_supervisor.py" --state "$STATE" --status "$STATUS" --complete "$task" --result "$RESULT" --codex-available >/dev/null
    ;;
  *)
    exit 64
    ;;
esac
