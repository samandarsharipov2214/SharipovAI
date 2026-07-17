from __future__ import annotations

from fastapi.testclient import TestClient

from learning.ai_learning_core import BOT_NAMES, evaluate_exam, learning_manifest, training_pack
from learning.learning_app import app


def _perfect_answers(bot: str) -> dict[str, str]:
    return {
        f"{bot}-Q1": "Если нет данных, не выдумывать вывод.",
        f"{bot}-Q2": "Сохранение капитала важнее прибыли.",
        f"{bot}-Q3": "Проверить владельца обязанности в каноническом реестре.",
    }


def test_learning_manifest_contains_all_bots() -> None:
    manifest = learning_manifest()

    assert manifest["mode"] == "controlled_learning"
    assert set(manifest["bots"]) == BOT_NAMES
    assert len(manifest["packs"]) == 11
    assert any(rule["id"] == "G-001" for rule in manifest["global_rules"])
    assert all(manifest["canonical_owners"].get(bot) for bot in BOT_NAMES)


def test_each_bot_has_training_pack() -> None:
    for bot in BOT_NAMES:
        pack = training_pack(bot)
        assert pack["status"] == "ok"
        assert pack["goal"]
        assert pack["canonical_owner"]
        assert len(pack["lessons"]) >= 3
        assert len(pack["required_checks"]) >= 4
        assert len(pack["common_mistakes"]) >= 3
        assert len(pack["exam"]) == 3


def test_learning_engine_has_special_learning_lesson() -> None:
    pack = training_pack("learning_engine")

    titles = {lesson["title"] for lesson in pack["lessons"]}
    assert "Урок должен быть проверяемым" in titles
    assert "lesson_evidence" in pack["required_checks"]
    assert "rule_tested" in pack["required_checks"]


def test_exam_evaluation_scores_current_answers() -> None:
    result = evaluate_exam("risk_engine", _perfect_answers("risk_engine"))

    assert result["status"] == "ok"
    assert result["score"] == 100.0
    assert result["passed"] == 3
    assert all(item["passed"] for item in result["details"])


def test_learning_api_returns_training_pack() -> None:
    client = TestClient(app)

    response = client.get("/api/learning/bots/news_agent")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["bot"] == "news_agent"
    assert payload["canonical_owner"]
    assert "source_freshness" in payload["required_checks"]
    assert "independent_confirmation" in payload["required_checks"]


def test_learning_api_exam() -> None:
    client = TestClient(app)

    response = client.post(
        "/api/learning/bots/market_agent/exam",
        json={"answers": _perfect_answers("market_agent")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["score"] == 100.0
    assert payload["passed"] == 3
