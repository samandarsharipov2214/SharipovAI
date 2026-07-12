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
    assert response.json() == {
        "status": "unauthorized",
        "detail": "authentication required",
    }


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

    app = create_app()
    client = TestClient(app)
    response = client.post(
        "/api/stress-test",
        json={
            "price_drop_percent": "not-a-number",
            "portfolio_value": "also-not-a-number",
        },
    )

    assert response.status_code in {200, 400, 422}


def test_telegram_command_failure_is_rendered_instead_of_raising(monkeypatch) -> None:
    """A Telegram builder failure must be converted to a safe user-facing message."""

    def explode() -> RunnerOutput:
        raise RuntimeError("telegram test failure")

    monkeypatch.setattr(telegram_bot, "build_now_report", explode, raising=False)
    text = telegram_bot.now_text()

    assert isinstance(text, str)
    assert text


def test_learning_summary_is_serializable() -> None:
    summary = LearningSummary(
        total_runs=1,
        successful_runs=1,
        blocked_runs=0,
        average_confidence=80.0,
        lessons=("keep evidence",),
    )
    assert isinstance(summary.total_runs, int)
