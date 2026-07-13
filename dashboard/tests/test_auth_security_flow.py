from __future__ import annotations

import importlib
from pathlib import Path

from fastapi.testclient import TestClient

from dashboard.app import create_app
from runner import RunnerOutput


class FakeRunner:
    def run(self) -> RunnerOutput:
        return RunnerOutput(
            decision="BUY BITCOIN",
            confidence=95.0,
            risk_level="LOW",
            portfolio_value=10000.0,
            paper_cash=9500.0,
            paper_equity=10000.0,
            paper_pnl=500.0,
            open_positions=1,
            consensus="UNANIMOUS",
            consensus_agreement=100.0,
            reason="Test runner",
            report="Test report",
        )


def test_login_page_points_to_access_request() -> None:
    app = create_app(runner_factory=FakeRunner)
    client = TestClient(app)

    response = client.get("/login")

    assert response.status_code == 200
    assert "SharipovAI" in response.text
    assert "Запросить доступ" in response.text
    assert "ADMIN_USERNAME" not in response.text
    assert "AUTH_USERS_FILE" not in response.text


def test_register_creates_security_access_request(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("AUTH_ACCESS_REQUESTS_FILE", str(tmp_path / "access_requests.json"))
    monkeypatch.setenv("AUTH_SECURITY_EVENTS_FILE", str(tmp_path / "security_events.json"))
    dashboard_app = importlib.import_module("dashboard.app")
    monkeypatch.setattr(dashboard_app, "_is_admin_request", lambda request: True)
    app = create_app(runner_factory=FakeRunner)
    client = TestClient(app)

    response = client.post(
        "/register",
        data={
            "username": "testuser",
            "contact": "@testuser",
            "reason": "Need dashboard access",
        },
    )

    assert response.status_code == 202
    assert "Запрос доступа отправлен" in response.text

    api_response = client.get("/api/security/access-requests")
    assert api_response.status_code == 200
    payload = api_response.json()
    assert payload["status"] == "ok"
    assert payload["requests"][0]["username"] == "testuser"
    assert payload["requests"][0]["status"] == "pending_security_review"
