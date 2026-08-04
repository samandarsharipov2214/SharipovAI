from __future__ import annotations

import json
from urllib import parse as urlparse

import pytest

from development_control.general_controller import DevelopmentDecision
from telegram_development_control import (
    handle_development_callback,
    parse_development_callback,
    send_development_approval,
)


class Response:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self) -> bytes:
        return json.dumps({"ok": True, "result": {"message_id": 9, "chat": {"id": 12345}}}).encode()


class Controller:
    def __init__(self, decision: DevelopmentDecision) -> None:
        self.decision = decision
        self.calls = []

    def get(self, short_id: str) -> DevelopmentDecision:
        assert short_id == self.decision.short_id
        return self.decision

    def decide(self, *args):
        self.calls.append(("decide", *args))
        self.decision.status = "approved" if args[1] else "rejected"
        return self.decision

    def queue_host_application(self, decision_id: str) -> DevelopmentDecision:
        self.calls.append(("queue", decision_id))
        return self.decision


def decision() -> DevelopmentDecision:
    identifier = "a" * 64
    return DevelopmentDecision(
        decision_id=identifier,
        short_id=identifier[:12],
        fix_id="fix_" + identifier,
        status="security_approved",
        proposal={
            "error": "test failed",
            "changed_files": ["app/service.py"],
            "test_results": "focused tests passed",
            "patch": "diff --git a/app/service.py b/app/service.py",
        },
        security_verdict={"allowed": True, "reasons": []},
        approval_token="approval-token",
    )


def test_message_contains_required_inline_callbacks(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    def urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["body"] = urlparse.parse_qs(request.data.decode())
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr("telegram_development_control.urlrequest.urlopen", urlopen)

    result = send_development_approval(decision(), bot_token="bot-token", owner_id="12345")

    assert result["ok"] is True
    assert captured["url"].endswith("/botbot-token/sendMessage")
    assert "test failed" in captured["body"]["text"][0]
    keyboard = json.loads(captured["body"]["reply_markup"][0])
    callbacks = [button["callback_data"] for row in keyboard["inline_keyboard"] for button in row]
    assert callbacks == [
        f"devfix:a:{'a' * 12}:approval-token",
        f"devfix:r:{'a' * 12}:approval-token",
        f"devfix:i:{'a' * 12}",
    ]


def test_callback_parser_rejects_invalid_data() -> None:
    assert parse_development_callback(f"devfix:a:{'a' * 12}:token").action == "approve"
    assert parse_development_callback(f"devfix:r:{'a' * 12}:token").action == "reject"
    assert parse_development_callback(f"devfix:i:{'a' * 12}").action == "info"
    with pytest.raises(ValueError):
        parse_development_callback("devfix:a:short:token")
    with pytest.raises(ValueError):
        parse_development_callback(f"devfix:x:{'a' * 12}:token")


def test_callback_handler_queues_after_verified_approval() -> None:
    item = decision()
    service = Controller(item)
    query = {
        "data": f"devfix:a:{item.short_id}:{item.approval_token}",
        "from": {"id": 12345},
        "message": {"chat": {"id": 12345}},
    }

    result = handle_development_callback(query, controller=service)

    assert result["status"] == "queued_for_host"
    assert service.calls == [
        (
            "decide",
            item.short_id,
            True,
            "12345",
            "12345",
            "approval-token",
            "telegram_inline_approve",
        ),
        ("queue", item.decision_id),
    ]


def test_info_callback_is_read_only() -> None:
    item = decision()
    service = Controller(item)
    result = handle_development_callback(
        {
            "data": f"devfix:i:{item.short_id}",
            "from": {"id": 12345},
            "message": {"chat": {"id": 12345}},
        },
        controller=service,
    )
    assert result["status"] == "info"
    assert service.calls == []
