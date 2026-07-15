from __future__ import annotations

from fastapi.testclient import TestClient

from dashboard import create_app
from learning.ai_learning_core import BOT_NAMES


class DummyRunner:
    def run(self):
        raise RuntimeError("not used")


def test_bot_network_endpoints_installed_in_dashboard(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BOT_COMMUNICATION_DB", str(tmp_path / "bot_network.sqlite3"))
    monkeypatch.setenv("SHARIPOVAI_DISABLE_AUTH", "1")
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
