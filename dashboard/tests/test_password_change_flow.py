from __future__ import annotations

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


def test_user_can_change_temporary_password(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("AUTH_USERS_FILE", str(tmp_path / "users.json"))
    monkeypatch.setenv("AUTH_ACCESS_REQUESTS_FILE", str(tmp_path / "access_requests.json"))
    monkeypatch.setenv("AUTH_SECURITY_EVENTS_FILE", str(tmp_path / "security_events.json"))
    # This test validates the explicit local compatibility flow. Repository CI
    # secrets must not silently turn it into the production admin-only flow.
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    monkeypatch.delenv("AUTH_SECRET", raising=False)
    monkeypatch.delenv("RENDER", raising=False)
    monkeypatch.setenv("ENVIRONMENT", "test")

    app = create_app(runner_factory=FakeRunner)
    client = TestClient(app)

    register_response = client.post(
        "/register",
        data={"username": "pilot02", "contact": "@pilot02", "reason": "Need access"},
    )
    assert register_response.status_code == 202

    requests_response = client.get("/api/security/access-requests")
    assert requests_response.status_code == 200
    requests_payload = requests_response.json()
    assert requests_payload["status"] == "ok"
    assert requests_payload["requests"]
    request_id = requests_payload["requests"][0]["id"]

    approved_response = client.post(f"/api/security/access-requests/{request_id}/approve")
    assert approved_response.status_code == 200
    approved = approved_response.json()
    assert approved["status"] == "ok"
    temporary_password = approved["temporary_password"]

    login_response = client.post(
        "/login",
        data={"username": "pilot02", "password": temporary_password},
        follow_redirects=False,
    )
    assert login_response.status_code == 303
    assert login_response.headers["location"] == "/change-password"

    change_response = client.post(
        "/change-password",
        data={
            "current_password": temporary_password,
            "new_password": "NewStrongPassword2026!",
            "repeat_password": "NewStrongPassword2026!",
        },
        follow_redirects=False,
    )
    assert change_response.status_code == 303
    assert change_response.headers["location"] == "/"

    old_login = client.post(
        "/login",
        data={"username": "pilot02", "password": temporary_password},
        follow_redirects=False,
    )
    assert old_login.status_code == 401

    new_login = client.post(
        "/login",
        data={"username": "pilot02", "password": "NewStrongPassword2026!"},
        follow_redirects=False,
    )
    assert new_login.status_code == 303
    assert new_login.headers["location"] == "/"
