"""Crash-hardening tests for dashboard, auth, stress lab, and Telegram edges."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from dashboard import create_app
from learning_engine import LearningSummary
from runner import RunnerOutput
import telegram_bot


def test_private_api_requires_auth_when_auth_is_enabled(monkeypatch) -> None:
    """Protected APIs should reject unauthenticated users in real dashboard mode."""

    monkeypatch.setenv("SHARIPOVAI_DISABLE_AUTH", "0")
    client = TestClient(create_app())

    response = client.get("/api/run")

    assert response.status_code == 401
    assert response.json() == {"error": "authentication_required"}


def test_access_request_is_recorded_without_creating_password_user(monkeypatch, tmp_path: Path) -> None:
    """Registration should create a security access request instead of crashing."""

    requests_file = tmp_path / "access_requests.json"
    events_file = tmp_path / "security_events.json"
    users_file = tmp_path / "users.json"
    monkeypatch.setenv("AUTH_ACCESS_REQUESTS_FILE", str(requests_file))
    monkeypatch.setenv("AUTH_SECURITY_EVENTS_FILE", str(events_file))
    monkeypatch.setenv("AUTH_USERS_FILE", str(users_file))
    monkeypatch.setenv("AUTH_ALLOW_REGISTRATION", "1")
    monkeypatch.setenv("SHARIPOVAI_DISABLE_AUTH", "0")

    client = TestClient(create_app())
    response = client.post(
        "/register",
        data={
            "username": "crash_user",
            "contact": "@crash_user",
            "reason": "Need controlled access test",
        },
    )

    assert response.status_code == 202
    assert "Запрос доступа отправлен" in response.text
    payload = json.loads(requests_file.read_text(encoding="utf-8"))
    assert payload["requests"][0]["username"] == "crash_user"
    assert payload["requests"][0]["status"] == "pending_security_review"
    assert not users_file.exists()


def test_stress_lab_handles_bad_numeric_inputs_safely() -> None:
    """Malformed stress-lab numbers should fall back safely instead of crashing."""

    client = TestClient(create_app(runner_factory=_runner_factory))
    response = client.post(
        "/api/stress-lab/run",
        json={
            "scenario": "custom_scenario",
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


def test_chat_endpoint_handles_empty_payload() -> None:
    """The chat endpoint should answer safely when message text is missing."""

    client = TestClient(create_app(runner_factory=_runner_factory))
    response = client.post("/api/chat/message", json={})

    assert response.status_code == 200
    payload = response.json()
    assert "reply" in payload
    assert "run" in payload
    assert payload["run"]["decision"] == "BUY"


def test_telegram_ignores_message_without_chat(monkeypatch) -> None:
    """Malformed Telegram updates without a chat id should not call the API."""

    called = False

    def fake_send_message(*args, **kwargs) -> None:  # noqa: ANN002, ANN003
        nonlocal called
        called = True

    monkeypatch.setattr(telegram_bot, "send_message", fake_send_message)

    telegram_bot.handle_message({"text": "/start"})

    assert called is False


class _FakeRunner:
    """Fake runner for crash-hardening tests."""

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
                recommendations=["More data required."],
            ),
            report="Crash hardening runner completed.",
            reason="Crash hardening decision reason.",
            consensus="UNANIMOUS",
            consensus_agreement=100.0,
            paper_pnl=0.0,
            open_positions=1,
        )


def _runner_factory() -> _FakeRunner:
    """Return a fake runner."""

    return _FakeRunner()
