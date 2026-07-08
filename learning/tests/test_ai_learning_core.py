from __future__ import annotations

from fastapi.testclient import TestClient

from learning.ai_learning_core import BOT_NAMES, evaluate_exam, learning_manifest, training_pack
from learning.learning_app import app


def test_learning_manifest_contains_all_bots() -> None:
    manifest = learning_manifest()

    assert manifest["mode"] == "controlled_learning"
    assert set(manifest["bots"]) == BOT_NAMES
    assert len(manifest["packs"]) == 11
    assert any(rule["id"] == "G-001" for rule in manifest["global_rules"])


def test_each_bot_has_training_pack() -> None:
    for bot in BOT_NAMES:
        pack = training_pack(bot)
        assert pack["status"] == "ok"
        assert pack["goal"]
        assert len(pack["lessons"]) >= 3
        assert len(pack["required_checks"]) >= 4
        assert len(pack["common_mistakes"]) >= 3
        assert len(pack["exam"]) == 3


def test_learning_engine_has_special_learning_lesson() -> None:
    pack = training_pack("learning_engine")

    titles = {lesson["title"] for lesson in pack["lessons"]}
    assert "Урок должен быть проверяемым" in titles
    assert "lesson_created" in pack["required_checks"]
    assert "exam_created" in pack["required_checks"]


def test_exam_evaluation_scores_answers() -> None:
    result = evaluate_exam(
        "risk_engine",
        {
            "risk_engine-Q1": "Нужно понизить уверенность и запросить проверку.",
            "risk_engine-Q2": "Вывод содержит причина и риск.",
            "risk_engine-Q3": "Важнее всего капитал.",
        },
    )

    assert result["status"] == "ok"
    assert result["score"] == 100.0
    assert result["passed"] == 3


def test_learning_api_returns_training_pack() -> None:
    client = TestClient(app)

    response = client.get("/api/learning/bots/news_agent")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["bot"] == "news_agent"
    assert "second_source_checked" in payload["required_checks"]


def test_learning_api_exam() -> None:
    client = TestClient(app)

    response = client.post(
        "/api/learning/bots/market_agent/exam",
        json={
            "answers": {
                "market_agent-Q1": "понизить уверенность",
                "market_agent-Q2": "причина и риск",
                "market_agent-Q3": "капитал",
            }
        },
    )

    assert response.status_code == 200
    assert response.json()["score"] == 100.0
