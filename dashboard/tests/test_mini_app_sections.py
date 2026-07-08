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


def test_mini_app_has_exchange_commission_monitor() -> None:
    """Mini App must show exchange, fee, commission drag, and break-even fields."""

    response = TestClient(create_app(runner_factory=_runner_factory)).get("/?lang=ru")

    assert response.status_code == 200
    text = response.text
    assert "Биржа и комиссии" in text
    assert "id=\"exchange-mode\"" in text
    assert "id=\"exchange-preview\"" in text
    assert "id=\"exchange-live\"" in text
    assert "id=\"exchange-fees\"" in text
    assert "id=\"exchange-drag\"" in text
    assert "id=\"exchange-breakeven\"" in text
    assert "Реальные ордера заблокированы" in text
    assert "Потери от комиссий" in text


def test_mini_app_live_js_uses_real_tabs_and_no_scroll_anchors() -> None:
    """Mini App tabs should switch panels instead of scrolling down the page."""

    response = TestClient(create_app(runner_factory=_runner_factory)).get("/static/mini-app-live.js")

    assert response.status_code == 200
    text = response.text
    assert "showPanel" in text
    assert "active-panel" in text
    assert "scrollIntoView" not in text
    assert "ensureAllSiteFunctions" in text
    assert "stress-section" in text
    assert "learning-section" in text
    assert "reports-section" in text
    assert "settings-section" in text


def test_mini_app_live_js_is_russian_only_for_exchange_labels() -> None:
    """Mini App exchange labels should be Russian-facing."""

    response = TestClient(create_app(runner_factory=_runner_factory)).get("/static/mini-app-live.js")

    assert response.status_code == 200
    text = response.text
    assert "Предпросмотр" in text
    assert "Реальные сделки" in text
    assert "Песочница" in text
    assert "Расчёт условий" in text
    assert "Движение до безубытка" in text
    assert "Cost AI" not in text
    assert "Break-even move" not in text


def test_mini_app_live_js_loads_ai_bots_demo_state_and_exchange_monitor() -> None:
    """Mini App controller must load demo, bots, and exchange monitoring APIs."""

    response = TestClient(create_app(runner_factory=_runner_factory)).get("/static/mini-app-live.js")

    assert response.status_code == 200
    text = response.text
    assert "/api/demo/state" in text
    assert "/api/demo/chat" in text
    assert "/api/ai-bots" in text
    assert "/api/stress-lab/run" in text
    assert "renderExchangeMonitor" in text
    assert "exchange_status" in text
    assert "online_monitoring" in text
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
