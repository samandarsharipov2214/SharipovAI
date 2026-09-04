from __future__ import annotations

import hashlib

from fastapi.testclient import TestClient

from dashboard import create_app
import dashboard.bot_communication_api as bot_api
from learning.ai_learning_core import BOT_NAMES


class DummyRunner:
    def run(self):
        raise RuntimeError("not used")


def test_bot_network_endpoints_installed_in_dashboard(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BOT_COMMUNICATION_DB", str(tmp_path / "bot_network.sqlite3"))
    monkeypatch.setenv("SHARIPOVAI_DISABLE_AUTH", "1")
    monkeypatch.setattr(bot_api, "require_admin", lambda _request: "ci-admin")
    client = TestClient(create_app(runner_factory=DummyRunner))

    health = client.get("/api/bot-network/health")
    assert health.status_code == 200
    assert health.json()["bot_count"] == len(BOT_NAMES)
    assert health.json()["full_mesh_possible"] is True
    assert health.json()["unified_chat"] is True

    sent = client.post(
        "/api/bot-network/messages",
        json={
            "sender": "general_controller",
            "recipient": "learning_engine",
            "message_type": "question",
            "topic": "learning",
            "payload": {"question": "status?"},
        },
    )
    assert sent.status_code == 200
    assert sent.json()["status"] == "ok"

    inbox = client.get("/api/bot-network/inbox/learning_engine?unread_only=true")
    assert inbox.status_code == 200
    assert len(inbox.json()["messages"]) == 1

    page = client.get("/bot-network")
    assert page.status_code == 200
    assert "Связь и контроль AI-ботов" in page.text
    assert "AGENT CONTROL" in page.text
    assert "/api/bot-network/health" in page.text
    assert "/api/bot-network/matrix" in page.text


def test_launch_check_contains_bot_network(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BOT_COMMUNICATION_DB", str(tmp_path / "bot_network.sqlite3"))
    monkeypatch.setenv("SHARIPOVAI_DISABLE_AUTH", "1")
    client = TestClient(create_app(runner_factory=DummyRunner))

    response = client.get("/api/launch-check")

    assert response.status_code == 200
    check_names = {item["name"] for item in response.json()["checks"]}
    assert "Bot Network" in check_names
    assert response.json()["important_urls"]["bot_network"] == "/bot-network"


def test_consensus_executes_agents_and_retry_is_idempotent(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BOT_COMMUNICATION_DB", str(tmp_path / "bot_network.sqlite3"))
    monkeypatch.setenv("SHARIPOVAI_DISABLE_AUTH", "1")
    monkeypatch.setattr(bot_api, "require_admin", lambda _request: "owner-admin")
    monkeypatch.setattr(bot_api, "allow_intelligence_request", lambda _key: True)
    calls: list[str] = []

    def fake_answer(message, _state, **_kwargs):
        agent = message.split(":", 1)[0]
        calls.append(agent)
        return {"status": "ok", "reply": f"opinion:{agent}", "source_ai": agent, "data": {}}

    monkeypatch.setattr(bot_api, "answer_chat", fake_answer)
    client = TestClient(create_app(runner_factory=DummyRunner))
    body = {"question": "Проверить риск?", "participants": ["risk_engine", "market_agent"]}
    headers = {"Idempotency-Key": "consensus-owner-1"}

    first = client.post("/api/bot-network/consensus", json=body, headers=headers)
    second = client.post("/api/bot-network/consensus", json=body, headers=headers)

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert calls.count("risk_engine") == 1
    assert calls.count("market_agent") == 1
    assert calls.count("consensus_engine") == 1
    thread = client.get(f"/api/bot-network/threads/{first.json()['thread_id']}").json()["messages"]
    assert len(thread) == 5
    assert len([item for item in thread if item["message_type"] == "consensus_response"]) == 2
    assert all(item["status"] == "read" for item in thread if item["message_type"] == "consensus_request")
    assert first.json()["execution_authority"] is False


def test_consensus_rejects_unknown_participants(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BOT_COMMUNICATION_DB", str(tmp_path / "bot_network.sqlite3"))
    monkeypatch.setenv("SHARIPOVAI_DISABLE_AUTH", "1")
    monkeypatch.setattr(bot_api, "require_admin", lambda _request: "owner-admin")
    monkeypatch.setattr(bot_api, "allow_intelligence_request", lambda _key: True)
    client = TestClient(create_app(runner_factory=DummyRunner))

    response = client.post(
        "/api/bot-network/consensus",
        json={"question": "test", "participants": ["not_an_agent", "consensus_engine"]},
    )

    assert response.status_code == 422


def test_consensus_retry_terminalizes_response_saved_before_crash(tmp_path, monkeypatch) -> None:
    path = tmp_path / "bot_network.sqlite3"
    monkeypatch.setenv("BOT_COMMUNICATION_DB", str(path))
    monkeypatch.setenv("SHARIPOVAI_DISABLE_AUTH", "1")
    monkeypatch.setattr(bot_api, "require_admin", lambda _request: "owner-admin")
    monkeypatch.setattr(bot_api, "allow_intelligence_request", lambda _key: True)
    calls: list[str] = []

    def fake_answer(message, _state, **_kwargs):
        calls.append(message.split(":", 1)[0])
        return {"status": "ok", "reply": "summary", "source_ai": "Consensus Engine", "data": {}}

    monkeypatch.setattr(bot_api, "answer_chat", fake_answer)
    external_key = "crash-window"
    operation = hashlib.sha256(f"owner-admin\0{external_key}".encode()).hexdigest()[:32]
    bus = bot_api.BotCommunicationNetwork(path)
    request_message = bus.send_message(
        sender="consensus_engine", recipient="risk_engine", message_type="consensus_request",
        topic="risk", payload={"question": "risk?"}, thread_id=f"CNS-{operation.upper()}",
        dedupe_key=f"consensus:{operation}:request:risk_engine",
    )
    bus.send_message(
        sender="risk_engine", recipient="consensus_engine", message_type="consensus_response",
        topic="risk", payload={"reply": "already durable"}, thread_id=request_message["thread_id"],
        dedupe_key=f"consensus:{operation}:response:risk_engine",
    )
    client = TestClient(create_app(runner_factory=DummyRunner))

    response = client.post(
        "/api/bot-network/consensus", headers={"Idempotency-Key": external_key},
        json={"question": "risk?", "participants": ["risk_engine"], "topic": "risk"},
    )

    assert response.status_code == 200
    assert response.json()["responses"] == [{"agent_id": "risk_engine", "reply": "already durable"}]
    assert calls == ["consensus_engine"]
    assert bus.get_message(request_message["message_id"])["message"]["status"] == "read"
