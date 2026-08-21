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
    monkeypatch.setattr(bot_api, "require_admin", _deny)
    monkeypatch.setattr(
        bot_api,
        "answer_chat",
        lambda _message, _state: {"reply": "ok", "source_ai": "Risk Engine", "intent": "agent_chat", "data": {}},
    )
    monkeypatch.setattr(
        network,
        "reply",
        lambda **_kwargs: {"status": "ok", "message_id": "MSG-2", "thread_id": "THR-1"},
        raising=False,
    )
    client = _client(monkeypatch, network)

    response = client.post(
        "/api/bot-network/chat",
        json={"bot": "risk_engine", "message": "покажи текущий риск"},
    )

    assert response.status_code == 200


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
