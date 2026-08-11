"""Crash-hardening regression tests."""

from __future__ import annotations

from fastapi.testclient import TestClient

import telegram_bot
from dashboard import create_app
from learning_engine import LearningSummary
from runner import RunnerOutput


class _FakeRunner:
    def run(self) -> RunnerOutput:
        return RunnerOutput(
            decision="BUY",
            confidence=95.0,
            risk_level="LOW",
            portfolio_value=10000.0,
            paper_cash=9500.0,
            paper_equity=10000.0,
            learning_summary=LearningSummary(
                total_trades=0,
                wins=0,
                losses=0,
                win_rate=0.0,
                average_profit=0.0,
                average_loss=0.0,
                best_trade=0.0,
                worst_trade=0.0,
                recommendations=[],
            ),
            report="test",
            reason="test",
            consensus="UNANIMOUS",
            consensus_agreement=100.0,
            paper_pnl=0.0,
            open_positions=0,
        )


def _runner_factory() -> _FakeRunner:
    return _FakeRunner()


def test_api_run_survives_runner_failure(monkeypatch) -> None:
    class BrokenRunner:
        def run(self):
            raise RuntimeError("boom")

    monkeypatch.setenv("SHARIPOVAI_DISABLE_AUTH", "1")
    response = TestClient(create_app(runner_factory=BrokenRunner)).get("/api/run")
    assert response.status_code == 200


def test_custom_stress_scenario_sanitizes_invalid_numbers(monkeypatch) -> None:
    monkeypatch.setenv("SHARIPOVAI_DISABLE_AUTH", "1")
    client = TestClient(create_app(runner_factory=_runner_factory))
    response = client.post(
        "/api/stress-test/custom",
        json={
            "starting_virtual_capital": "not-a-number",
            "current_exposure": "bad",
            "maximum_acceptable_drawdown": "bad",
            "price_drop_percent": "bad",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["scenario"] == "custom_scenario"
    assert payload["parameters"]["starting_virtual_capital"] == 10000.0
    assert payload["after"]["capital"] >= 0.0
    assert "risk limit applied" in payload["protective_measures"]


def test_chat_endpoint_handles_empty_payload(monkeypatch) -> None:
    """Missing chat text must not inherit a synthetic BUY from a runner fixture."""

    monkeypatch.setenv("SHARIPOVAI_DISABLE_AUTH", "1")
    client = TestClient(create_app(runner_factory=_runner_factory))
    response = client.post("/api/chat/message", json={})

    assert response.status_code == 200
    payload = response.json()
    assert "reply" in payload
    assert "run" in payload
    assert payload["run"]["decision"] in {"START", "WAIT", "WATCH", "BLOCK"}
    assert payload["run"]["decision"] not in {"BUY", "SELL"}


def test_telegram_ignores_message_without_chat(monkeypatch) -> None:
    """Malformed Telegram updates without a chat id do not call the API."""

    called = False

    def fake_send_message(*args, **kwargs) -> None:  # noqa: ANN002, ANN003
        nonlocal called
        called = True

    monkeypatch.setattr(telegram_bot, "send_message", fake_send_message)

    telegram_bot.handle_message({"text": "/start"})
    assert called is False
