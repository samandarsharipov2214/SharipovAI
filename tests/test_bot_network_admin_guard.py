from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

import dashboard.admin_guard as admin_guard
import dashboard.auth_saas as auth_saas
import dashboard.bot_communication_api as bot_api
import dashboard.db_saas as db_saas
import learning.bot_communication_app as standalone_bot_api


class _FakeNetwork:
    def __init__(self) -> None:
        self.sent: dict[str, Any] | None = None
        self.broadcasted: dict[str, Any] | None = None
        self.marked_read: str | None = None

    def send_message(self, **kwargs: Any) -> dict[str, Any]:
        self.sent = kwargs
        return {"status": "ok", "message_id": "MSG-1", "thread_id": "THR-1"}

    def broadcast(self, **kwargs: Any) -> dict[str, Any]:
        self.broadcasted = kwargs
        return {"status": "ok", "thread_id": "THR-2", "sent": 1, "results": []}

    def request_consensus(self, **kwargs: Any) -> dict[str, Any]:
        return {"status": "ok", "thread_id": "THR-3", **kwargs}

    def health(self) -> dict[str, Any]:
        return {"status": "ok", "responsibilities": {}}

    def communication_matrix(self) -> dict[str, Any]:
        return {"status": "ok"}

    def inbox(self, *_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        return []

    def outbox(self, *_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        return []

    def thread(self, thread_id: str) -> dict[str, Any]:
        return {"status": "ok", "thread_id": thread_id, "messages": []}

    def mark_read(self, message_id: str) -> dict[str, Any]:
        self.marked_read = message_id
        return {"status": "ok", "message_id": message_id}

    def get_message_by_dedupe_key(self, _dedupe_key: str) -> dict[str, Any]:
        return {"status": "not_found"}


def _client(monkeypatch: pytest.MonkeyPatch, network: _FakeNetwork, *, base_url: str = "http://testserver") -> TestClient:
    app = FastAPI()
    monkeypatch.setattr(bot_api, "BotCommunicationNetwork", lambda _path=None: network)
    bot_api.install_bot_communication_api(app)
    return TestClient(app, base_url=base_url)


def _deny(_request: Any) -> str:
    raise HTTPException(status_code=403, detail={"status": "forbidden"})


def _request(path: str = "/api/bot-network/messages") -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": path,
            "headers": [],
            "scheme": "https",
            "server": ("example.test", 443),
            "client": ("127.0.0.1", 12345),
        }
    )


def test_bot_network_mutations_require_admin(monkeypatch: pytest.MonkeyPatch) -> None:
    network = _FakeNetwork()
    monkeypatch.setattr(bot_api, "require_admin", _deny)
    client = _client(monkeypatch, network)

    requests = [
        ("/api/bot-network/messages", {"recipient": "learning_engine"}),
        ("/api/bot-network/broadcast", {"recipients": ["learning_engine"]}),
        ("/api/bot-network/consensus", {"question": "check"}),
        ("/api/bot-network/chat", {"bot": "risk_engine", "message": "pause"}),
        ("/api/bot-network/agent/risk_engine/self-check", None),
        ("/api/bot-network/agent/risk_engine/pause", None),
        ("/api/bot-network/agent/risk_engine/learn", None),
    ]
    for path, payload in requests:
        response = client.post(path, json=payload) if payload is not None else client.post(path)
        assert response.status_code == 403, path


def test_non_privileged_bot_chat_does_not_require_admin(monkeypatch: pytest.MonkeyPatch) -> None:
    network = _FakeNetwork()
    routed: dict[str, object] = {}

    def fake_answer(_message, state, **kwargs):
        routed["state"] = state
        routed.update(kwargs)
        return {"reply": "ok", "source_ai": "Risk Engine", "intent": "agent_chat", "data": {}}

    monkeypatch.setattr(bot_api, "require_admin", _deny)
    monkeypatch.setattr(bot_api, "answer_chat", fake_answer)
    monkeypatch.setattr(
        network,
        "reply",
        lambda **_kwargs: {"status": "ok", "message_id": "MSG-2", "thread_id": "THR-1"},
        raising=False,
    )
    client = _client(monkeypatch, network)

    response = client.post(
        "/api/bot-network/chat",
        json={
            "bot": "risk_engine",
            "message": "покажи текущий риск",
            "state": {"equity": 999_999, "api_key": "client-injection"},
        },
    )

    assert response.status_code == 200
    assert routed["intelligent"] is True
    assert routed["persist_bus"] is False
    assert routed["state"].get("equity") != 999_999
    assert "api_key" not in routed["state"]


def test_agent_chat_rate_limit_blocks_before_persistence(monkeypatch: pytest.MonkeyPatch) -> None:
    network = _FakeNetwork()
    monkeypatch.setattr(bot_api, "allow_intelligence_request", lambda _key: False)
    client = _client(monkeypatch, network)

    response = client.post(
        "/api/bot-network/chat",
        json={"bot": "risk_engine", "message": "покажи текущий риск"},
    )

    assert response.status_code == 429
    assert response.json() == {"detail": {"status": "agent_chat_rate_limited"}}
    assert network.sent is None


def test_message_provenance_is_server_derived(monkeypatch: pytest.MonkeyPatch) -> None:
    network = _FakeNetwork()
    monkeypatch.setattr(bot_api, "require_admin", lambda _request: "owner-admin")
    client = _client(monkeypatch, network)

    response = client.post(
        "/api/bot-network/messages",
        json={
            "sender": "general_controller",
            "recipient": "learning_engine",
            "payload": {"requested_by": "spoofed-user", "value": 7},
        },
    )

    assert response.status_code == 200
    assert network.sent is not None
    assert network.sent["payload"] == {"requested_by": "owner-admin", "value": 7}


def test_broadcast_provenance_is_server_derived(monkeypatch: pytest.MonkeyPatch) -> None:
    network = _FakeNetwork()
    monkeypatch.setattr(bot_api, "require_admin", lambda _request: "owner-admin")
    client = _client(monkeypatch, network)

    response = client.post(
        "/api/bot-network/broadcast",
        json={
            "sender": "general_controller",
            "recipients": ["learning_engine"],
            "payload": {"requested_by": "spoofed-user", "note": "maintenance"},
        },
    )

    assert response.status_code == 200
    assert network.broadcasted is not None
    assert network.broadcasted["payload"] == {
        "requested_by": "owner-admin",
        "note": "maintenance",
    }


def test_consensus_provenance_is_server_derived(monkeypatch: pytest.MonkeyPatch) -> None:
    network = _FakeNetwork()
    monkeypatch.setattr(bot_api, "require_admin", lambda _request: "owner-admin")
    captured: dict[str, Any] = {}

    def fake_execute(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {"status": "ok"}

    monkeypatch.setattr(bot_api, "_execute_consensus", fake_execute)
    monkeypatch.setattr(bot_api, "allow_intelligence_request", lambda _key: True)
    client = _client(monkeypatch, network)

    response = client.post(
        "/api/bot-network/consensus",
        json={
            "topic": "trade",
            "question": "check",
            "participants": ["risk_engine"],
            "requested_by": "spoofed-user",
        },
    )

    assert response.status_code == 200
    assert captured["actor"] == "owner-admin"
    assert captured["question"] == "check"
    assert captured["targets"] == ["risk_engine"]


def test_empty_consensus_participants_use_default_subset(monkeypatch: pytest.MonkeyPatch) -> None:
    network = _FakeNetwork()
    monkeypatch.setattr(bot_api, "require_admin", lambda _request: "owner-admin")
    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        bot_api, "_execute_consensus",
        lambda **kwargs: captured.update(kwargs) or {"status": "ok"},
    )
    monkeypatch.setattr(bot_api, "allow_intelligence_request", lambda _key: True)
    client = _client(monkeypatch, network)

    response = client.post(
        "/api/bot-network/consensus",
        json={"topic": "trade", "question": "check", "participants": []},
    )

    assert response.status_code == 200
    assert captured["targets"] == bot_api.DEFAULT_CONSENSUS_PARTICIPANTS


@pytest.mark.parametrize(
    ("path", "expected_action"),
    [
        ("/api/bot-network/agent/risk_engine/self-check", "self_check"),
        ("/api/bot-network/agent/risk_engine/pause", "pause"),
        ("/api/bot-network/agent/risk_engine/learn", "learn"),
    ],
)
def test_direct_privileged_commands_persist_admin_provenance(
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    expected_action: str,
) -> None:
    network = _FakeNetwork()
    monkeypatch.setattr(bot_api, "require_admin", lambda _request: "owner-admin")
    client = _client(monkeypatch, network)

    response = client.post(path)

    assert response.status_code == 200
    assert network.sent is not None
    assert network.sent["message_type"] == "command"
    assert network.sent["payload"]["action"] == expected_action
    assert network.sent["payload"]["requested_by"] == "owner-admin"


def test_privileged_chat_persists_admin_provenance(monkeypatch: pytest.MonkeyPatch) -> None:
    network = _FakeNetwork()
    monkeypatch.setattr(bot_api, "require_admin", lambda _request: "owner-admin")
    client = _client(monkeypatch, network)

    response = client.post(
        "/api/bot-network/chat",
        json={
            "bot": "risk_engine",
            "message": "pause",
            "state": {"requested_by": "spoofed-user"},
        },
    )

    assert response.status_code == 200
    assert network.sent is not None
    assert network.sent["message_type"] == "command"
    assert network.sent["payload"]["action"] == "pause"
    assert network.sent["payload"]["requested_by"] == "owner-admin"


def test_privileged_command_bus_failure_returns_structured_error(monkeypatch: pytest.MonkeyPatch) -> None:
    network = _FakeNetwork()

    def _raise(**_kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("db locked")

    monkeypatch.setattr(network, "send_message", _raise)
    monkeypatch.setattr(bot_api, "require_admin", lambda _request: "owner-admin")
    client = _client(monkeypatch, network)

    response = client.post("/api/bot-network/agent/risk_engine/pause")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "persistence_error"
    assert payload["data"]["message_bus"] == {
        "status": "error",
        "error": "RuntimeError: db locked",
    }


def test_shared_admin_guard_accepts_active_canonical_saas_admin(monkeypatch: pytest.MonkeyPatch) -> None:
    class _DB:
        def close(self) -> None:
            return None

    monkeypatch.setenv("JWT_SECRET", "explicit-test-jwt-secret")
    monkeypatch.setattr(db_saas, "SessionLocal", lambda: _DB())
    monkeypatch.setattr(
        auth_saas,
        "get_current_user",
        lambda _request, _db: SimpleNamespace(
            email="saas-admin@example.test",
            role="admin",
            is_active=True,
        ),
    )

    assert admin_guard.require_admin(_request()) == "saas-admin@example.test"


def test_shared_admin_guard_rejects_default_or_missing_canonical_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("JWT_SECRET", raising=False)
    monkeypatch.delenv("AUTH_SECRET", raising=False)
    monkeypatch.delenv("ADMIN_USERNAME", raising=False)
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    monkeypatch.setattr(
        auth_saas,
        "get_current_user",
        lambda _request, _db: SimpleNamespace(email="forged@example.test", role="admin", is_active=True),
    )

    with pytest.raises(HTTPException) as exc_info:
        admin_guard.require_admin(_request())

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == {"status": "auth_not_configured"}


def test_shared_admin_guard_returns_forbidden_for_canonical_non_admin(monkeypatch: pytest.MonkeyPatch) -> None:
    class _DB:
        def close(self) -> None:
            return None

    monkeypatch.setenv("JWT_SECRET", "explicit-test-jwt-secret")
    monkeypatch.setattr(db_saas, "SessionLocal", lambda: _DB())
    monkeypatch.setattr(
        auth_saas,
        "get_current_user",
        lambda _request, _db: SimpleNamespace(
            email="member@example.test",
            role="user",
            is_active=True,
        ),
    )

    with pytest.raises(HTTPException) as exc_info:
        admin_guard.require_admin(_request())

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == {"status": "forbidden"}


def test_bot_network_mutation_blocks_cross_origin_cookie_request(monkeypatch: pytest.MonkeyPatch) -> None:
    network = _FakeNetwork()
    monkeypatch.setattr(bot_api, "require_admin", lambda _request: "owner-admin")
    client = _client(monkeypatch, network, base_url="https://example.test")

    response = client.post(
        "/api/bot-network/agent/risk_engine/pause",
        headers={"Origin": "https://evil.example"},
    )

    assert response.status_code == 403
    assert response.json()["detail"]["status"] == "cross_origin_blocked"


def test_shared_sensitive_guard_blocks_cross_origin_unsafe_request(monkeypatch: pytest.MonkeyPatch) -> None:
    app = FastAPI()
    monkeypatch.setattr(admin_guard, "require_admin", lambda _request: "owner-admin")
    admin_guard.install_sensitive_api_guard(app)

    @app.post("/api/exchange/account/sync")
    def sync_account() -> dict[str, str]:
        return {"status": "ok"}

    client = TestClient(app, base_url="https://example.test")
    response = client.post(
        "/api/exchange/account/sync",
        headers={"Origin": "https://evil.example"},
    )

    assert response.status_code == 403
    assert response.json()["detail"]["status"] == "cross_origin_blocked"


def test_shared_sensitive_guard_allows_same_origin_unsafe_request(monkeypatch: pytest.MonkeyPatch) -> None:
    app = FastAPI()
    monkeypatch.setattr(admin_guard, "require_admin", lambda _request: "owner-admin")
    admin_guard.install_sensitive_api_guard(app)

    @app.post("/api/exchange/account/sync")
    def sync_account() -> dict[str, str]:
        return {"status": "ok"}

    client = TestClient(app, base_url="https://example.test")
    response = client.post(
        "/api/exchange/account/sync",
        headers={"Origin": "https://example.test"},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_standalone_bot_network_mutations_are_retired(monkeypatch: pytest.MonkeyPatch) -> None:
    network = _FakeNetwork()
    monkeypatch.setattr(standalone_bot_api, "network", lambda: network)
    client = TestClient(standalone_bot_api.app)

    requests = [
        ("/api/bot-network/messages", {"recipient": "learning_engine"}),
        ("/api/bot-network/broadcast", {"recipients": ["learning_engine"]}),
        ("/api/bot-network/consensus", {"question": "check"}),
        ("/api/bot-network/messages/MSG-1/read", None),
    ]
    for path, payload in requests:
        response = client.post(path, json=payload) if payload is not None else client.post(path)
        assert response.status_code == 410, path
        assert response.json()["detail"]["status"] == "standalone_mutations_retired"

    assert network.sent is None
    assert network.broadcasted is None
    assert network.marked_read is None


def test_standalone_reads_redact_authenticated_actor_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    network = _FakeNetwork()
    message = {
        "message_id": "MSG-1",
        "payload": {
            "requested_by": "admin@example.test",
            "nested": {"requested_by": "legacy-owner", "value": 1},
        },
    }
    monkeypatch.setattr(network, "inbox", lambda *_args, **_kwargs: [message])
    monkeypatch.setattr(network, "outbox", lambda *_args, **_kwargs: [message])
    monkeypatch.setattr(
        network,
        "thread",
        lambda thread_id: {"status": "ok", "thread_id": thread_id, "messages": [message]},
    )
    monkeypatch.setattr(standalone_bot_api, "network", lambda: network)
    client = TestClient(standalone_bot_api.app)

    for path in (
        "/api/bot-network/inbox/risk_engine",
        "/api/bot-network/outbox/general_controller",
        "/api/bot-network/threads/THR-1",
    ):
        response = client.get(path)
        assert response.status_code == 200
        body = response.json()
        assert "admin@example.test" not in response.text
        assert "legacy-owner" not in response.text
        assert "[redacted]" in response.text
        assert body
