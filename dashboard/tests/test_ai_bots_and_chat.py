"""Regression tests for AI bots center and dashboard chat answers."""
from __future__ import annotations

from fastapi.testclient import TestClient

from dashboard import create_app
from learning_engine import LearningSummary
from runner import RunnerOutput


def test_ai_bots_page_renders_supervisor_and_agents(monkeypatch) -> None:
    monkeypatch.setenv("SHARIPOVAI_DISABLE_AUTH", "1")
    client = TestClient(create_app(runner_factory=_runner_factory))
    response = client.get("/ai-bots?lang=ru")

    assert response.status_code == 200
    assert "AI-боты" in response.text
    assert "Генеральный контролёр AI" in response.text
    assert "Market Agent" in response.text
    assert "News Agent" in response.text
    assert "Risk Engine" in response.text
    assert "Security Guard" in response.text
    assert "Список ботов и их работа" in response.text


def test_ai_bots_api_returns_truthful_supervisor_summary(monkeypatch) -> None:
    monkeypatch.setenv("SHARIPOVAI_DISABLE_AUTH", "1")
    client = TestClient(create_app(runner_factory=_runner_factory))
    response = client.get("/api/ai-bots")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] in {"ok", "warning"}
    supervisor = payload["supervisor"]
    assert supervisor["name"] in {"General Controller", "Генеральный контролёр AI"}
    assert payload["summary"]["total_bots"] == len(payload["bots"]) == 9
    assert 0 <= payload["summary"]["active"] <= payload["summary"]["total_bots"]
    assert any(bot["name"] == "Market Agent" for bot in payload["bots"])
    assert any(bot["name"] == "Security Guard" for bot in payload["bots"])
    if payload["status"] == "warning":
        assert payload["summary"]["active"] < payload["summary"]["total_bots"]


def test_chat_answers_identity_like_ai_assistant(monkeypatch) -> None:
    monkeypatch.setenv("SHARIPOVAI_DISABLE_AUTH", "1")
    client = TestClient(create_app(runner_factory=_runner_factory))
    response = client.post("/api/chat/message", json={"message": "ты ИИ или бот?"})

    assert response.status_code == 200
    reply = response.json()["reply"]
    assert "SharipovAI" in reply
    assert "AI-помощник" in reply
    assert "не просто кнопочный бот" in reply
    assert "Я могу ответить конкретно по торговле" not in reply


def test_chat_answers_what_was_bought_with_trade_details(monkeypatch) -> None:
    monkeypatch.setenv("SHARIPOVAI_DISABLE_AUTH", "1")
    client = TestClient(create_app(runner_factory=_runner_factory))
    response = client.post("/api/chat/message", json={"message": "что купил?"})

    assert response.status_code == 200
    reply = response.json()["reply"]
    assert "открыты покупки" in reply
    assert "BTC/USDT" in reply
    assert "SOL/USDT" in reply
    assert "ETH/USDT" in reply
    assert "Реальные деньги не использовались" in reply


def test_chat_answers_unknown_question_with_system_state(monkeypatch) -> None:
    monkeypatch.setenv("SHARIPOVAI_DISABLE_AUTH", "1")
    client = TestClient(create_app(runner_factory=_runner_factory))
    response = client.post("/api/chat/message", json={"message": "что происходит вообще?"})

    assert response.status_code == 200
    reply = response.json()["reply"]
    assert "Я понял твой вопрос" in reply
    assert "виртуальный баланс" in reply
    assert "Я могу ответить конкретно по торговле" not in reply


class _FakeRunner:
    def run(self) -> RunnerOutput:
        return RunnerOutput(
            decision="BUY",
            confidence=99.9,
            risk_level="LOW",
            portfolio_value=10000.0,
            paper_cash=9500.0,
            paper_equity=10000.0,
            learning_summary=LearningSummary(
                total_trades=3,
                wins=2,
                losses=1,
                win_rate=67.0,
                average_profit=41.8,
                average_loss=-18.3,
                best_trade=52.4,
                worst_trade=-18.3,
                recommendations=["Keep demo mode enabled."],
            ),
            report="SharipovAI runner completed.",
            reason="Market Agent, News Agent and Risk Engine confirmed a demo BUY setup.",
            consensus="UNANIMOUS",
            consensus_agreement=100.0,
            paper_pnl=0.0,
            open_positions=2,
        )


def _runner_factory() -> _FakeRunner:
    return _FakeRunner()
