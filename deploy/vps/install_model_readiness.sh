#!/usr/bin/env bash
# Install only from the deployed checkout; preserve the one-shot canonical plan.
set -Eeuo pipefail
umask 077
APP_DIR=${APP_DIR:-/opt/sharipovai-repo}
cd "$APP_DIR"
expected=$(git rev-parse HEAD)
require_reviewed_inputs() {
  [[ "$(git rev-parse HEAD)" == "$expected" ]] || { echo 'readiness checkout changed' >&2; return 1; }
  [[ -z "$(git status --porcelain --untracked-files=all)" ]] || { echo 'readiness requires a clean committed checkout' >&2; return 1; }
  git diff --quiet "$expected" -- deploy/vps docs/paper-next-model-specification.json
}
require_reviewed_inputs
docker exec -i sharipovai python - "$expected" <<'PY'
import os,sys
from storage import ProjectChangeLedger, ProjectDatabase
assert os.environ['SHARIPOVAI_BUILD_SHA']==sys.argv[1]
assert os.environ['EXECUTION_KILL_SWITCH']=='1' and os.environ['EXCHANGE_MODE']=='sandbox'
db=ProjectDatabase()
ledger=ProjectChangeLedger(db)
ledger.create_change(change_id='paper-readiness-install-'+sys.argv[1][:12], actor='astra',
 summary='Install six-hour non-Codex metadata checker and one-shot continuation',
 operations=[{'kind':'configuration','ownership':'managed','path':'deploy/vps/systemd/'+name}
 for name in ('sharipovai-model-readiness.service','sharipovai-model-readiness.timer','sharipovai-model-continuation.service')],
 metadata={'rollback':'disable readiness timer; preserve canonical plan and consumed request state',
           'scope':'host systemd units; no runtime trade policy change'})
PY
mark_failed() {
  local status="$1" line="$2"
  trap - ERR
  docker exec -i sharipovai python - "$expected" "$status" "$line" <<'FAILURE_PY' || true
import sys
from storage import ProjectChangeLedger, ProjectDatabase
ledger = ProjectChangeLedger(ProjectDatabase())
identity = 'paper-readiness-install-' + sys.argv[1][:12]
current = ledger.get_change(identity)
if current and current['status'] in ('planned', 'applied'):
    ledger.set_status(identity, 'failed', actor='astra', verification={
        'installer_exit_status': int(sys.argv[2]), 'installer_line': int(sys.argv[3])})
FAILURE_PY
  exit "$status"
}
trap 'mark_failed "$?" "$LINENO"' ERR
docker exec -i sharipovai python - <<'PY'
import json,time
from pathlib import Path
from storage import ProjectDatabase
from scripts.paper_forecast_readiness import register
from learning_engine.forecast_readiness import NAMESPACE
db=ProjectDatabase();template=json.loads(Path('docs/paper-next-model-specification.json').read_text())
existing=db.get_json(NAMESPACE,'plan')
if existing:
 assert all(existing['value'].get(k)==v for k,v in template.items())
 assert db.get_json(NAMESPACE,'state')
else:
 register(db,now_ms=int(time.time()*1000),template=template)
PY
for name in sharipovai-model-readiness.service sharipovai-model-readiness.timer sharipovai-model-continuation.service; do
  require_reviewed_inputs
  install -m 0644 "deploy/vps/systemd/$name" "/etc/systemd/system/$name"
  git show "$expected:deploy/vps/systemd/$name" | cmp - "/etc/systemd/system/$name"
done
require_reviewed_inputs
systemctl daemon-reload
# Finish the initial check under the service lock before the timer can elapse.
initial_status=0
bash deploy/vps/model_readiness_check.sh || initial_status=$?
if (( initial_status != 0 && initial_status != 75 )); then
  (exit "$initial_status")
fi
systemctl enable --now sharipovai-model-readiness.timer
systemctl is-enabled --quiet sharipovai-model-readiness.timer
require_reviewed_inputs
docker exec -i sharipovai python - "$expected" "$initial_status" <<'PY'
import sys
from storage import ProjectChangeLedger,ProjectDatabase
db=ProjectDatabase();ledger=ProjectChangeLedger(db);identity='paper-readiness-install-'+sys.argv[1][:12]
ledger.set_status(identity,'applied',actor='astra')
state=db.get_json('paper_forecast_readiness','state')['value']
result = state.get('last_result') if int(sys.argv[2]) == 0 else None
assert state['trigger_status'] in ('not_requested', 'requested_once')
if int(sys.argv[2]) == 0:
 assert isinstance(result, dict), 'successful initial check has no durable result'
# This verifies installation, not data readiness or a skipped diagnostic.
ledger.set_status(identity,'verified',actor='astra',verification={
 'scope':'timer installation', 'timer_enabled':True,
 'initial_check_status':'COMPLETED' if result is not None else 'DEFERRED',
 'canonical_metadata_check':result,
 'continuation_requests':int(state['trigger_status']=='requested_once')})
print('READINESS_INSTALLATION=VERIFIED INITIAL_CHECK=' + ('COMPLETED' if result is not None else 'DEFERRED'))
PY
trap - ERR
