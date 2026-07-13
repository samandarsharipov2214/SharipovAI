"""Crash-hardening tests for dashboard, auth, stress lab, and Telegram edges."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from fastapi.testclient import TestClient

from dashboard import create_app
from learning_engine import LearningSummary
from runner import RunnerOutput
import telegram_bot


def test_private_api_requires_auth_when_auth_is_enabled(monkeypatch) -> None:
    monkeypatch.setenv("SHARIPOVAI_DISABLE_AUTH", "0")
    client = TestClient(create_app())
    response = client.get("/api/run")
    assert response.status_code == 401
    assert response.json() == {
        "status": "unauthorized",
        "detail": "authentication required",
    }


def test_access_request_is_recorded_without_creating_password_user(monkeypatch, tmp_path: Path) -> None:
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
    app = create_app()
    client = TestClient(app)
    response = client.post(
        "/api/stress-lab/run",
        json={
            "price_drop_percent": "not-a-number",
            "starting_virtual_capital": "also-not-a-number",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["capital_before"] == 10000.0
    assert payload["loss_percent"] >= 0


def test_telegram_command_failure_is_rendered_instead_of_raising(monkeypatch) -> None:
    def explode() -> RunnerOutput:
        raise RuntimeError("telegram test failure")

    monkeypatch.setattr(telegram_bot, "build_now_report", explode, raising=False)
    text = telegram_bot.now_text()
    assert isinstance(text, str)
    assert text


def test_learning_summary_is_serializable() -> None:
    summary = LearningSummary(
        total_trades=1,
        wins=1,
        losses=0,
        win_rate=100.0,
        average_profit=1.5,
        average_loss=0.0,
        best_trade=1.5,
        worst_trade=1.5,
        recommendations=["keep evidence"],
    )
    payload = asdict(summary)
    assert payload["total_trades"] == 1
    assert payload["recommendations"] == ["keep evidence"]
