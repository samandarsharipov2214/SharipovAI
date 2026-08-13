from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import development_control.general_controller as module
from development_control.general_controller import DevelopmentChangeController
from storage import ProjectDatabase

BASE_SHA = "a" * 40


def patch(path: str = "app/service.py") -> str:
    return (
        f"diff --git a/{path} b/{path}\n"
        "index 1111111..2222222 100644\n"
        f"--- a/{path}\n"
        f"+++ b/{path}\n"
        "@@ -1 +1 @@\n"
        "-VALUE = 1\n"
        "+VALUE = 2\n"
    )


def controller(tmp_path: Path) -> DevelopmentChangeController:
    database = ProjectDatabase(f"sqlite:///{tmp_path / 'governance.db'}")
    return DevelopmentChangeController(database=database, queue_dir=tmp_path / ".self_healing")


def proposal(path: str = "app/service.py") -> dict[str, object]:
    return {
        "error": "test_service failed",
        "patch": patch(path),
        "changed_files": [path],
        "test_results": "1 focused test passed after patch",
        "base_sha": BASE_SHA,
        "target_branch": "main",
        "source": "unit-test",
    }


def test_full_owner_approved_lifecycle_uses_sql_ledger(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TELEGRAM_OWNER_ID", "12345")
    monkeypatch.setattr(
        module,
        "send_development_approval",
        lambda decision: {"ok": True, "result": {"message_id": 7, "chat": {"id": 12345}}},
    )
    service = controller(tmp_path)

    submitted = service.submit_proposal(proposal())
    assert submitted.status == "submitted"
    assert len(submitted.decision_id) == 64
    assert submitted.approval_token
    assert service.database.get_agent_fix(submitted.fix_id) is not None

    reviewed = service.security_review(submitted.decision_id)
    assert reviewed.status == "security_approved"
    assert reviewed.security_verdict["allowed"] is True

    awaiting = service.request_owner_approval(reviewed.decision_id)
    assert awaiting.status == "awaiting_owner"
    token = awaiting.approval_token

    approved = service.decide(
        awaiting.short_id,
        True,
        actor_id="12345",
        chat_id="12345",
        token=token,
        reason="telegram approval",
    )
    assert approved.status == "approved"
    assert approved.approval_token == ""

    queued = service.queue_host_application(approved.decision_id)
    assert queued.status == "approved"
    runtime = tmp_path / ".self_healing"
    manifest = json.loads((runtime / "approved_patch.json").read_text(encoding="utf-8"))
    assert manifest == {
        "decision_id": approved.decision_id,
        "base_sha": BASE_SHA,
        "patch_sha256": hashlib.sha256(patch().encode("utf-8")).hexdigest(),
        "patch_container_path": str(runtime / f"approved-{approved.decision_id}.patch"),
    }
    assert (runtime / "action").read_text(encoding="utf-8").strip() == "apply_approved_patch"

    persisted = service.database.get_agent_decision(approved.decision_id)
    assert persisted is not None
    assert persisted["status"] == "approved"
    assert persisted["security_verdict"] == "allow"
    events = service.database.list_agent_decision_events(approved.decision_id)
    assert [event["event_type"] for event in events] == [
        "submitted",
        "security_approved",
        "owner_approval_requested",
        "owner_approved",
        "queued_for_host",
    ]


def test_security_guard_blocks_protected_patch(tmp_path: Path) -> None:
    service = controller(tmp_path)
    submitted = service.submit_proposal(proposal("deploy/vps/docker-compose.yml"))

    reviewed = service.security_review(submitted.decision_id)

    assert reviewed.status == "security_blocked"
    assert reviewed.security_verdict["allowed"] is False
    with pytest.raises(RuntimeError, match="allowed Security Guard"):
        service.request_owner_approval(reviewed.decision_id)


def test_wrong_actor_or_token_cannot_approve(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TELEGRAM_OWNER_ID", "12345")
    monkeypatch.setattr(
        module,
        "send_development_approval",
        lambda decision: {"ok": True, "result": {"chat": {"id": 12345}}},
    )
    service = controller(tmp_path)
    submitted = service.submit_proposal(proposal())
    reviewed = service.security_review(submitted.decision_id)
    decision = service.request_owner_approval(reviewed.decision_id)

    with pytest.raises(PermissionError, match="configured Telegram owner"):
        service.decide(decision.decision_id, True, "999", "12345", decision.approval_token, "bad actor")
    with pytest.raises(PermissionError, match="invalid or expired"):
        service.decide(decision.decision_id, True, "12345", "12345", "wrong", "bad token")


def test_rejection_is_terminal_and_never_queues(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TELEGRAM_OWNER_ID", "12345")
    monkeypatch.setattr(
        module,
        "send_development_approval",
        lambda decision: {"ok": True, "result": {"chat": {"id": 12345}}},
    )
    service = controller(tmp_path)
    submitted = service.submit_proposal(proposal())
    reviewed = service.security_review(submitted.decision_id)
    decision = service.request_owner_approval(reviewed.decision_id)

    rejected = service.decide(
        decision.short_id,
        False,
        "12345",
        "12345",
        decision.approval_token,
        "unsafe scope",
    )

    assert rejected.status == "rejected"
    with pytest.raises(RuntimeError, match="explicit owner approval"):
        service.queue_host_application(rejected.decision_id)


def test_critical_action_requires_matching_owner_approval_and_is_one_shot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TELEGRAM_OWNER_ID", "12345")
    monkeypatch.setattr(
        module,
        "send_development_approval",
        lambda decision: {"ok": True, "result": {"chat": {"id": 12345}}},
    )
    service = controller(tmp_path)
    submitted = service.submit_critical_action(
        "restore_database",
        reason="integrity check failed",
        base_sha=BASE_SHA,
        details={"candidate": "verified"},
    )
    reviewed = service.security_review(submitted.decision_id)
    awaiting = service.request_owner_approval(reviewed.decision_id)

    with pytest.raises(PermissionError, match="configured Telegram owner"):
        service.decide(awaiting.decision_id, True, "999", "12345", awaiting.approval_token, "no")
    approved = service.decide(
        awaiting.decision_id, True, "12345", "12345", awaiting.approval_token, "approved"
    )
    queued = service.queue_host_application(approved.decision_id)
    payload = json.loads((tmp_path / ".self_healing" / "action.json").read_text(encoding="utf-8"))
    assert payload["action"] == "restore_database"
    assert payload["approval_decision_id"] == queued.decision_id

    with pytest.raises(PermissionError, match="does not match"):
        service.claim_critical_action(queued.decision_id, "git_revert")
    claimed = service.claim_critical_action(queued.decision_id, "restore_database")
    assert claimed.status == "executing"
    with pytest.raises(RuntimeError, match="one-shot"):
        service.claim_critical_action(queued.decision_id, "restore_database")

    completed = service.record_host_result(
        claimed.decision_id,
        {"status": "success", "action": "restore_database"},
    )
    assert completed.status == "applied"
    assert completed.host_result == {
        "status": "success",
        "action": "restore_database",
    }
    assert [event["event_type"] for event in service.database.list_agent_decision_events(claimed.decision_id)][-2:] == [
        "critical_action_claimed",
        "host_applied",
    ]
