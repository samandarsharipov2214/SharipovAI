from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import dashboard.bot_communication_api as bot_api


class _FakeNetwork:
    def __init__(self) -> None:
        self.sent: dict[str, Any] | None = None
        self.broadcasted: dict[str, Any] | None = None

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


def _client(monkeypatch: pytest.MonkeyPatch, network: _FakeNetwork) -> TestClient:
    app = FastAPI()
    monkeypatch.setattr(bot_api, "BotCommunicationNetwork", lambda _path=None: network)
    bot_api.install_bot_communication_api(app)
    return TestClient(app)


def test_bot_network_mutations_require_admin(monkeypatch: pytest.MonkeyPatch) -> None:
    network = _FakeNetwork()

    def deny(_request: Any) -> str:
        raise HTTPException(status_code=403, detail={"status": "forbidden"})

    monkeypatch.setattr(bot_api, "require_admin", deny)
    client = _client(monkeypatch, network)

    requests = [
        ("/api/bot-network/messages", {"recipient": "learning_engine"}),
        ("/api/bot-network/broadcast", {"recipients": ["learning_engine"]}),
        ("/api/bot-network/consensus", {"question": "check"}),
        ("/api/bot-network/agent/risk_engine/self-check", None),
        ("/api/bot-network/agent/risk_engine/pause", None),
        ("/api/bot-network/agent/risk_engine/learn", None),
    ]
    for path, payload in requests:
        response = client.post(path, json=payload) if payload is not None else client.post(path)
        assert response.status_code == 403, path


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
