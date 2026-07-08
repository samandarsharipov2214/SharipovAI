"""Regression tests for AI-bot related chat questions."""

from __future__ import annotations

from fastapi.testclient import TestClient

from dashboard import create_app
from learning_engine import LearningSummary
from runner import RunnerOutput


def test_chat_answers_ai_bot_status_question_with_bot_list() -> None:
    """Questions about working bots should return bot status, not identity fallback."""

    client = TestClient(create_app(runner_factory=_runner_factory))
    response = client.post("/api/chat/message", json={"message": "какие боты работают?"})

    assert response.status_code == 200
    reply = response.json()["reply"]
    assert "работает" in reply
    assert "AI-ботов" in reply
    assert "General Controller" in reply
    assert "Market Agent" in reply
    assert "Risk Engine" in reply
    assert "Требуют внимания" in reply
    assert "не просто кнопочный бот" not in reply


class _FakeRunner:
    """Fake runner for AI-bot chat tests."""

    def run(self) -> RunnerOutput:
        """Return deterministic runner output."""

        return RunnerOutput(
            decision="BUY",
            confidence=88.0,
            risk_level="LOW",
            portfolio_value=10000.0,
            paper_cash=9500.0,
            paper_equity=10000.0,
            learning_summary=LearningSummary(
                total_trades=1,
                wins=1,
                losses=0,
                win_rate=100.0,
                average_profit=0.0,
                average_loss=0.0,
                best_trade=0.0,
                worst_trade=0.0,
                recommendations=["Keep demo mode enabled."],
            ),
            report="SharipovAI runner completed.",
            reason="Test decision reason.",
            consensus="UNANIMOUS",
            consensus_agreement=100.0,
            paper_pnl=0.0,
            open_positions=1,
        )


def _runner_factory() -> _FakeRunner:
    """Return fake runner."""

    return _FakeRunner()
