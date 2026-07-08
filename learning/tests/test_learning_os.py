from __future__ import annotations

from fastapi.testclient import TestClient

from learning.ai_learning_core import BOT_NAMES
from learning.learning_memory import LearningMemory
from learning.learning_os_app import app
from learning.learning_os_core import close_learning_gap, learning_os_snapshot


def test_learning_memory_records_mistake_and_lesson(tmp_path) -> None:
    memory = LearningMemory(tmp_path / "learning.sqlite3")

    result = memory.record_mistake(
        bot="risk_engine",
        domain="risk",
        mistake="acted without source",
        consequence="confidence was too high",
    )
    snapshot = memory.snapshot()

    assert result["status"] == "ok"
    assert result["lesson"]["status"] == "ok"
    assert snapshot["mistake_count"] == 1
    assert snapshot["lesson_count"] == 1
    assert memory.lessons_for_bot("risk_engine")


def test_close_learning_gap_seeds_all_bots(tmp_path) -> None:
    memory = LearningMemory(tmp_path / "learning.sqlite3")

    result = close_learning_gap(memory)

    assert result["status"] == "ok"
    assert result["seeded"] == len(BOT_NAMES)
    assert result["snapshot"]["summary"]["bot_count"] == len(BOT_NAMES)
    assert result["snapshot"]["summary"]["ready"] == len(BOT_NAMES)


def test_learning_os_snapshot_combines_all_layers(tmp_path) -> None:
    memory = LearningMemory(tmp_path / "learning.sqlite3")
    close_learning_gap(memory)

    snapshot = learning_os_snapshot(memory)

    assert snapshot["status"] == "ok"
    assert snapshot["system"] == "SharipovAI Learning OS"
    assert "persistent_learning_memory" in snapshot["closed_gaps"]
    assert snapshot["financial_knowledge"]["domain_count"] >= 8
    assert snapshot["source_discovery"]["plan_count"] == len(BOT_NAMES)
    assert snapshot["summary"]["learning_gap_closed"] is True


def test_learning_os_api_and_dashboard(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("LEARNING_MEMORY_DB", str(tmp_path / "learning.sqlite3"))
    client = TestClient(app)

    close_response = client.post("/api/learning-os/close-gap")
    assert close_response.status_code == 200
    assert close_response.json()["status"] == "ok"

    snapshot_response = client.get("/api/learning-os/snapshot")
    assert snapshot_response.status_code == 200
    assert snapshot_response.json()["summary"]["bot_count"] == len(BOT_NAMES)

    bot_response = client.get("/api/learning-os/bots/risk_engine")
    assert bot_response.status_code == 200
    assert bot_response.json()["bot"] == "risk_engine"

    page_response = client.get("/learning-os")
    assert page_response.status_code == 200
    assert "Самообучение SharipovAI" in page_response.text


def test_learning_os_mistake_api(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("LEARNING_MEMORY_DB", str(tmp_path / "learning.sqlite3"))
    client = TestClient(app)

    response = client.post(
        "/api/learning-os/mistakes",
        json={"bot": "news_agent", "domain": "regulation", "mistake": "trusted rumor", "consequence": "bad confidence"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["lesson"]["status"] == "ok"
