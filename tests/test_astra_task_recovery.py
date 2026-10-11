import json
import os
from pathlib import Path

import pytest

from tools import astra_supervisor as s


def test_completion_cli_never_claims_the_next_task(tmp_path, monkeypatch, capsys):
    state = s.default_state()
    state['tasks'].append(dict(state['tasks'][0], id='paper_root_cause_audit'))
    action = s.next_action(state, {'safe': True})
    p = tmp_path/'state.json'; r=tmp_path/'result.json'
    s.write_state(p, state); r.write_text('{"status":"VERIFIED"}')
    monkeypatch.setattr(s, 'resource_state', lambda: {'safe': True})
    assert s.main(['--state', str(p), '--status', str(tmp_path/'status.md'), '--complete', action['task_id'],
                   '--lease-id', action['lease_id'], '--result', str(r)]) == 0
    after = s.read_state(p)
    assert after['tasks'][0]['status'] == 'VERIFIED'
    assert after['tasks'][1]['status'] == 'PENDING'
    assert 'lease_id' not in after['tasks'][1]


@pytest.mark.parametrize('failure', ['crash','reboot','pid_reuse','terminal_close'])
def test_dead_owner_recovery_and_fenced_result(failure, monkeypatch):
    state = s.default_state(); first = s.next_action(state, {'safe': True}); task=state['tasks'][0]
    identity=dict(task['owner_identity'])
    if failure == 'reboot': identity['boot_id']='new-boot'
    elif failure == 'pid_reuse': identity['start_ticks']='different-start'
    else: identity=None
    monkeypatch.setattr(s, 'process_identity', lambda pid: identity)
    assert s.recover_expired_leases(state) == [task['id']]
    assert task['attempts'] == 1
    second = s.next_action(state, {'safe': True})
    with pytest.raises(ValueError, match='stale'):
        s.complete(state, task['id'], {'status':'VERIFIED'}, lease_id=first['lease_id'])
    s.complete(state, task['id'], {'status':'VERIFIED'}, lease_id=second['lease_id'])
    assert task['attempts'] == 2 and task['status'] == 'VERIFIED'


def test_crashes_consume_retry_budget_and_live_owner_is_never_duplicated(monkeypatch):
    state=s.default_state(); task=state['tasks'][0]
    s.next_action(state, {'safe':True})
    assert s.recover_expired_leases(state, now=10**12) == []
    assert s.next_action(state, {'safe':True})['reason'] == 'active_claim'
    monkeypatch.setattr(s, 'process_identity', lambda pid: None)
    s.recover_expired_leases(state)
    s.next_action(state, {'safe':True})
    s.recover_expired_leases(state, now=10**12)
    assert task['status'] == 'FAILED' and task['attempts']==2
    assert s.next_action(state, {'safe':True})['reason']=='unresolved_tasks'


def test_verified_dependencies_and_no_auth_do_not_starve_local_work():
    state=s.default_state(); task=state['tasks'][0]
    task['depends_on']=['production_acceptance:sha']
    assert s.next_action(state, {'safe':True})['reason']=='dependencies_unverified'
    state['verified_dependencies']={'production_acceptance:sha': {'evidence':'receipt'}}
    state['tasks'].insert(0, dict(id='codex-blocked', status='PENDING', attempts=0, max_attempts=2, requires_codex=True))
    assert s.next_action(state, {'safe':True})['task_id']==task['id']


def test_runner_has_actual_audit_handler_and_shared_maintenance_locks():
    text=(Path(__file__).resolve().parents[1]/'deploy/vps/astra_supervisor_run.sh').read_text()
    assert '/app/scripts/astra_paper_audit.py' in text
    assert 'flock -sn 8' in text and 'flock -sn 7' in text
    assert '--lease-id "$lease"' in text


def test_model_readiness_queues_development_without_launching_codex():
    root=Path(__file__).resolve().parents[1]
    source=(root/'deploy/vps/model_continuation.sh').read_text()
    unit=(root/'deploy/vps/systemd/sharipovai-model-continuation.service').read_text()
    assert 'enqueue_codex_task' in source and 'codex-model-readiness' in source
    assert 'dangerously-bypass' not in source and 'codex exec' not in source
    assert 'TimeoutStartSec=60' in unit


def test_enqueue_cli_does_not_create_an_unexecuted_claim(tmp_path, monkeypatch):
    monkeypatch.setattr(s, 'resource_state', lambda: {'safe':True})
    path=tmp_path/'state.json'
    s.main(['--state',str(path),'--status',str(tmp_path/'status.md'),'--enqueue-codex','codex-next'])
    assert all(t['status']=='PENDING' and 'lease_id' not in t for t in s.read_state(path)['tasks'])
