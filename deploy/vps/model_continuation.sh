#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
# Readiness hands development to the existing bounded queue. It never starts
# Codex itself or uses an interactive login as an automation identity.
APP_DIR=${SHARIPOVAI_REPO_DIR:-/opt/sharipovai-repo}
STATE_DIR=${ASTRA_SUPERVISOR_STATE_DIR:-/var/lib/sharipovai/astra-supervisor}
mkdir -p -m 0700 "$STATE_DIR/tasks"
exec 9>/run/lock/sharipovai-astra-supervisor.lock
flock -n 9 || exit 75
docker exec sharipovai python -c 'from storage import ProjectDatabase; from learning_engine.forecast_readiness import NAMESPACE; s=ProjectDatabase().get_json(NAMESPACE,"state")["value"]; assert s["trigger_status"]=="requested_once" and s["last_result"]["ready"] is True'
install -m 0600 "$APP_DIR/docs/paper-model-continuation.md" "$STATE_DIR/tasks/codex-model-readiness.md"
PYTHONPATH="$APP_DIR" python3 - "$STATE_DIR" <<'PY'
import sys
from pathlib import Path
from tools.astra_supervisor import read_state, write_state, enqueue_codex_task, status_markdown
root=Path(sys.argv[1]); path=root/'astra_state.json'; state=read_state(path)
task_id='codex-model-readiness'
if not any(t.get('id')==task_id for t in state['tasks']):
    enqueue_codex_task(state, task_id)
write_state(path,state)
(root/'ASTRA_STATUS.md').write_text(status_markdown(state,{},
    {'action':'CHECKPOINT','reason':'model_research_queued_for_supported_authorization'}))
print('QUEUED codex-model-readiness; no Codex session started')
PY
