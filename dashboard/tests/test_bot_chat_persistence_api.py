from __future__ import annotations

from fastapi.testclient import TestClient

from dashboard.app import create_app


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
