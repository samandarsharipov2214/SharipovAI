from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from dashboard import create_app
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
    monkeypatch.setenv("AUTH_ALLOW_REGISTRATION", "1")
    monkeypatch.setenv("SHARIPOVAI_DISABLE_AUTH", "1")
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    monkeypatch.delenv("AUTH_SECRET", raising=False)
    app = create_app(runner_factory=FakeRunner)
    client = TestClient(app)

    registered = client.post(
        "/register",
        data={"username": "pilot02", "contact": "@pilot02", "reason": "Need access"},
    )
    assert registered.status_code == 202
    requests = client.get("/api/security/access-requests").json()["requests"]
    assert len(requests) == 1
    request_id = requests[0]["id"]
    approved = client.post(f"/api/security/access-requests/{request_id}/approve").json()
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
