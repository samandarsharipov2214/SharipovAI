from __future__ import annotations

import json
from pathlib import Path

from tools import astra_supervisor as supervisor


def safe_resources() -> dict[str, object]:
    return {"safe": True, "load_1m": 0.1, "memory_available_bytes": 2**30, "disk_free_bytes": 20 * 2**30}


def test_new_queue_runs_local_diagnosis_then_becomes_idle(tmp_path):
    path = tmp_path / "state.json"
    state = supervisor.read_state(path)
    action = supervisor.next_action(state, safe_resources())
    assert action == {"action": "RUN_LOCAL", "reason": "local_task_pending",
                      "task_id": "paper_execution_diagnosis", "needs_codex": False}
    supervisor.complete(state, "paper_execution_diagnosis", {"status": "VERIFIED", "output": "diagnosis.json"})
    assert supervisor.next_action(state, safe_resources())["action"] == "IDLE"


def test_resource_guard_preserves_pending_checkpoint():
    state = supervisor.default_state()
    action = supervisor.next_action(state, {"safe": False, "load_1m": 2.0})
    assert action["reason"] == "resource_guard"
    assert state["tasks"][0]["status"] == "PENDING"


def test_codex_task_waits_for_explicit_automation_authentication():
    state = supervisor.default_state()
    state["tasks"] = [{"id": "fix", "status": "PENDING", "attempts": 0, "max_attempts": 1,
                       "requires_codex": True, "kind": "codex"}]
    action = supervisor.next_action(state, safe_resources())
    assert action == {"action": "WAIT", "reason": "codex_automation_auth_required", "needs_codex": True}
    assert state["tasks"][0]["status"] == "PENDING"


def test_explicitly_queued_codex_task_runs_only_when_automation_is_provisioned():
    state = supervisor.default_state()
    state["tasks"] = [{"id": "codex-safe-fix", "status": "PENDING", "attempts": 0, "max_attempts": 1,
                       "requires_codex": True, "kind": "codex"}]
    action = supervisor.next_action(state, safe_resources(), codex_available=True)
    assert action == {"action": "RUN_CODEX", "reason": "explicit_queued_task",
                      "task_id": "codex-safe-fix", "needs_codex": True}


def test_failed_task_keeps_a_durable_checkpoint_until_its_bounded_retry_budget_is_exhausted():
    state = supervisor.default_state()
    supervisor.complete(state, "paper_execution_diagnosis", {"status": "FAILED", "output": "error.json"})
    task = state["tasks"][0]
    assert task["status"] == "PENDING" and task["checkpoint"] == "error.json"
    supervisor.complete(state, "paper_execution_diagnosis", {"status": "FAILED", "output": "error-2.json"})
    assert state["tasks"][0]["status"] == "FAILED"


def test_queues_only_a_bounded_and_unambiguous_codex_task():
    state = supervisor.default_state()
    supervisor.enqueue_codex_task(state, "codex-investigate-feed")
    task = state["tasks"][-1]
    assert task["requires_codex"] is True and task["max_attempts"] == 2
    try:
        supervisor.enqueue_codex_task(state, "../../unsafe")
    except ValueError as exc:
        assert "invalid" in str(exc)
    else:
        raise AssertionError("unsafe task id accepted")


def test_state_and_status_are_durable(tmp_path):
    state_path, status_path = tmp_path / "state.json", tmp_path / "ASTRA_STATUS.md"
    state = supervisor.default_state()
    supervisor.write_state(state_path, state)
    reloaded = supervisor.read_state(state_path)
    action = supervisor.next_action(reloaded, safe_resources())
    status_path.write_text(supervisor.status_markdown(reloaded, safe_resources(), action))
    assert json.loads(state_path.read_text())["schema"] == 1
    assert "paper_execution_diagnosis" in status_path.read_text()


def test_host_contract_is_bounded_and_has_no_codex_or_production_mutation():
    root = Path(__file__).resolve().parents[1]
    runner = (root / "deploy/vps/astra_supervisor_run.sh").read_text()
    service = (root / "deploy/vps/systemd/sharipovai-astra-supervisor.service").read_text()
    timer = (root / "deploy/vps/systemd/sharipovai-astra-supervisor.timer").read_text()
    assert "flock -n" in runner
    assert "codex exec" in runner and "docker compose" not in runner
    assert "ASTRA_CODEX_AUTOMATION" in runner and "CODEX_ACCESS_TOKEN" in runner
    assert "timeout 150s" in runner
    assert "CPUQuota=25%" in service and "MemoryMax=384M" in service
    assert "RuntimeMaxSec" not in service  # systemd name is TimeoutStartSec for oneshot jobs.
    assert "TimeoutStartSec=3min" in service and "OnBootSec=7min" in timer
    assert "OnUnitInactiveSec=6h" in timer
