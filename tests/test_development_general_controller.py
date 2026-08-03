from __future__ import annotations

import json
from pathlib import Path

import pytest

import development_control.general_controller as module
from development_control.general_controller import DevelopmentChangeController


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
    return DevelopmentChangeController(
        state_file=tmp_path / "decisions.json",
        queue_dir=tmp_path / "queue",
    )


def proposal(path: str = "app/service.py") -> dict[str, object]:
    return {
        "error": "test_service failed",
        "patch": patch(path),
        "changed_files": [path],
        "test_results": "1 focused test passed after patch",
    }


def test_full_owner_approved_lifecycle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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

    reviewed = service.security_review(submitted.decision_id)
    assert reviewed.status == "security_approved"
    assert reviewed.security_verdict == {"allowed": True, "reasons": []}

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
    assert approved.status == "owner_approved"
    assert approved.approval_token == ""

    queued = service.queue_host_application(approved.decision_id)
    assert queued.status == "queued_for_host"
    queue_file = tmp_path / "queue" / f"{approved.decision_id}.json"
    queued_payload = json.loads(queue_file.read_text(encoding="utf-8"))
    assert queued_payload["owner_actor_id"] == "12345"
    assert queued_payload["security_verdict"]["allowed"] is True

    completed = service.record_host_result(approved.decision_id, {"status": "applied", "tests": "passed"})
    assert completed.status == "host_succeeded"
    assert completed.host_result["tests"] == "passed"


def test_security_guard_blocks_protected_patch(tmp_path: Path) -> None:
    service = controller(tmp_path)
    submitted = service.submit_proposal(proposal("deploy/vps/docker-compose.yml"))

    reviewed = service.security_review(submitted.decision_id)

    assert reviewed.status == "security_blocked"
    assert reviewed.security_verdict["allowed"] is False
    with pytest.raises(RuntimeError, match="allowed Security Guard"):
        service.request_owner_approval(reviewed.decision_id)


def test_wrong_actor_or_token_cannot_approve(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_OWNER_ID", "12345")
    monkeypatch.setattr(module, "send_development_approval", lambda decision: {"ok": True, "result": {"chat": {"id": 12345}}})
    service = controller(tmp_path)
    decision = service.request_owner_approval(service.security_review(service.submit_proposal(proposal()).decision_id).decision_id)

    with pytest.raises(PermissionError, match="configured Telegram owner"):
        service.decide(decision.decision_id, True, "999", "12345", decision.approval_token, "bad actor")
    with pytest.raises(PermissionError, match="invalid or expired"):
        service.decide(decision.decision_id, True, "12345", "12345", "wrong", "bad token")


def test_rejection_is_terminal_and_never_queues(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_OWNER_ID", "12345")
    monkeypatch.setattr(module, "send_development_approval", lambda decision: {"ok": True, "result": {"chat": {"id": 12345}}})
    service = controller(tmp_path)
    decision = service.request_owner_approval(service.security_review(service.submit_proposal(proposal()).decision_id).decision_id)

    rejected = service.decide(decision.short_id, False, "12345", "12345", decision.approval_token, "unsafe scope")

    assert rejected.status == "rejected"
    with pytest.raises(RuntimeError, match="explicit owner approval"):
        service.queue_host_application(rejected.decision_id)
