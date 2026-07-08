"""Tests for Mini App visible sections."""

from __future__ import annotations

from fastapi.testclient import TestClient

from dashboard import create_app
from learning_engine import LearningSummary
from runner import RunnerOutput


def test_mini_app_has_tabs_and_ai_bot_monitor() -> None:
    """Mini App must keep core tabs and AI bot monitoring visible."""

    response = TestClient(create_app(runner_factory=_runner_factory)).get("/?lang=ru")

    assert response.status_code == 200
    text = response.text
    assert "Разделы Mini App" in text
    assert "data-mini-tab=\"overview-section\"" in text
    assert "data-mini-tab=\"chat-section\"" in text
    assert "data-mini-tab=\"bots-section\"" in text
    assert "data-mini-tab=\"risk-section\"" in text
    assert "data-mini-tab=\"trades-section\"" in text
    assert "data-mini-tab=\"exchange-section\"" in text
    assert "Мониторинг AI-ботов" in text
    assert "id=\"bots-total\"" in text
    assert "id=\"bot-list\"" in text
    assert "Установить demo balance" not in text
    assert "Установить демо-баланс" in text


def test_mini_app_live_js_loads_ai_bots_and_demo_state() -> None:
    """Mini App controller must load demo state and AI bot status APIs."""

    response = TestClient(create_app(runner_factory=_runner_factory)).get("/static/mini-app-live.js")

    assert response.status_code == 200
    text = response.text
    assert "/api/demo/state" in text
    assert "/api/demo/chat" in text
    assert "/api/ai-bots" in text
    assert "Установить демо-баланс" in text


class _FakeRunner:
    """Fake runner for mini app tests."""

    def run(self) -> RunnerOutput:
        """Return deterministic output."""

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
                recommendations=[],
            ),
            report="OK",
            reason="OK",
            consensus="UNANIMOUS",
            consensus_agreement=100.0,
            paper_pnl=0.0,
            open_positions=1,
        )


def _runner_factory() -> _FakeRunner:
    """Return fake runner."""

    return _FakeRunner()
