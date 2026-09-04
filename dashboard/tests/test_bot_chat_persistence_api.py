from __future__ import annotations

from fastapi.testclient import TestClient

from dashboard.app import create_app
from memory_engine import MemoryService, MemorySettings
from storage import ProjectDatabase


def test_bot_chat_api_persists_question_and_answer(tmp_path, monkeypatch):
    monkeypatch.setenv("SHARIPOVAI_DISABLE_AUTH", "1")
    monkeypatch.setenv("BOT_COMMUNICATION_DB", str(tmp_path / "bot.sqlite3"))
    client = TestClient(create_app())
    response = client.post("/api/bot-network/chat", json={"bot": "learning_engine", "message": "что с ошибками?"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    thread_id = payload["message"]["thread_id"]
    thread = client.get(f"/api/bot-network/threads/{thread_id}")
    assert thread.status_code == 200
    messages = thread.json()["messages"]
    assert [item["message_type"] for item in messages] == ["question", "answer"]
    health = client.get("/api/bot-network/health").json()
    assert health["message_count"] == 2


def test_bot_chat_api_persists_general_controller_without_self_message(tmp_path, monkeypatch):
    monkeypatch.setenv("SHARIPOVAI_DISABLE_AUTH", "1")
    monkeypatch.setenv("BOT_COMMUNICATION_DB", str(tmp_path / "bot.sqlite3"))
    client = TestClient(create_app())

    response = client.post("/api/bot-network/chat", json={"bot": "General Controller", "message": "проверь всех ботов"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["message"]["status"] == "ok"
    assert payload["answer"]["status"] == "ok"

    thread_id = payload["message"]["thread_id"]
    thread = client.get(f"/api/bot-network/threads/{thread_id}")
    assert thread.status_code == 200
    messages = thread.json()["messages"]
    assert [item["message_type"] for item in messages] == ["question", "answer"]
    assert messages[0]["sender"] == "security_guard"
    assert messages[0]["recipient"] == "general_controller"
    assert messages[1]["sender"] == "general_controller"
    assert messages[1]["recipient"] == "security_guard"
    health = client.get("/api/bot-network/health").json()
    assert health["message_count"] == 2


def test_bot_chat_reuses_existing_memory_without_trusting_it(tmp_path, monkeypatch):
    monkeypatch.setenv("SHARIPOVAI_DISABLE_AUTH", "1")
    monkeypatch.setenv("BOT_COMMUNICATION_DB", str(tmp_path / "bot.sqlite3"))
    captured: list[list[str]] = []

    def fake_answer_chat(_message, _state, **kwargs):
        captured.append(list(kwargs.get("memory_context", [])))
        return {"status": "ok", "reply": "remembered", "source_ai": "Market Agent", "data": {}}

    monkeypatch.setattr("dashboard.bot_communication_api.answer_chat", fake_answer_chat)
    app = create_app()
    memory = MemoryService(
        ProjectDatabase(dsn=f"sqlite:///{tmp_path / 'memory.db'}"),
        settings=MemorySettings(enabled=True, context_injection_enabled=True, extraction_enabled=False),
    )
    memory.initialize()
    app.state.memory_service = memory
    client = TestClient(app)

    first = client.post("/api/bot-network/chat", json={"bot": "market_agent", "message": "мой горизонт неделя"})
    second = client.post("/api/bot-network/chat", json={"bot": "market_agent", "message": "какой мой горизонт?"})

    assert first.status_code == second.status_code == 200
    assert captured[0] == []
    assert captured[1] == ["user: мой горизонт неделя", "assistant: remembered"]
    assert memory.settings.extraction_enabled is False
    assert memory.health()["execution_authority"] is False


def test_memory_failure_does_not_break_or_duplicate_canonical_chat(tmp_path, monkeypatch):
    monkeypatch.setenv("SHARIPOVAI_DISABLE_AUTH", "1")
    monkeypatch.setenv("BOT_COMMUNICATION_DB", str(tmp_path / "bot.sqlite3"))
    app = create_app()

    class BrokenMemory:
        settings = MemorySettings(enabled=True, context_injection_enabled=True)

        def get_recent_dialog(self, **_kwargs):
            raise OSError("database unavailable")

        def record_dialog(self, **_kwargs):
            raise OSError("database unavailable")

    app.state.memory_service = BrokenMemory()
    client = TestClient(app)
    response = client.post("/api/bot-network/chat", json={"bot": "risk_engine", "message": "проверь риск"})

    assert response.status_code == 200
    thread = client.get(f"/api/bot-network/threads/{response.json()['thread_id']}").json()["messages"]
    assert [item["message_type"] for item in thread] == ["question", "answer"]
