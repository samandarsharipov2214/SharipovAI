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


def test_admin_can_approve_access_request_and_created_user_can_login(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("AUTH_USERS_FILE", str(tmp_path / "users.json"))
    monkeypatch.setenv("AUTH_ACCESS_REQUESTS_FILE", str(tmp_path / "access_requests.json"))
    monkeypatch.setenv("AUTH_SECURITY_EVENTS_FILE", str(tmp_path / "security_events.json"))
    dashboard_app = importlib.import_module("dashboard.app")
    monkeypatch.setattr(dashboard_app, "_is_admin_request", lambda request: True)
    app = create_app(runner_factory=FakeRunner)
    client = TestClient(app)

    register_response = client.post(
        "/register",
        data={
            "username": "pilot01",
            "contact": "@pilot01",
            "reason": "Need SharipovAI access",
        },
    )
    assert register_response.status_code == 202

    requests_response = client.get("/api/security/access-requests")
    assert requests_response.status_code == 200
    request_id = requests_response.json()["requests"][0]["id"]

    approve_response = client.post(f"/api/security/access-requests/{request_id}/approve")
    assert approve_response.status_code == 200
    approve_payload = approve_response.json()
    assert approve_payload["status"] == "ok"
    assert approve_payload["temporary_password"]

    login_response = client.post(
        "/login",
        data={"username": "pilot01", "password": approve_payload["temporary_password"]},
        follow_redirects=False,
    )
    assert login_response.status_code == 303
    assert "sharipovai_session" in login_response.headers.get("set-cookie", "")
