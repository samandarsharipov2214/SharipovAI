from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from dashboard.admin_secure_app import create_admin_secure_app
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


def _set_auth_env(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ADMIN_USERNAME", "Samandar2212")
    monkeypatch.setenv("ADMIN_PASSWORD", "AdminPassword2026!")
    monkeypatch.setenv("AUTH_SECRET", "test-secret")
    monkeypatch.setenv("AUTH_USERS_FILE", str(tmp_path / "users.json"))
    monkeypatch.setenv("AUTH_ACCESS_REQUESTS_FILE", str(tmp_path / "access_requests.json"))
    monkeypatch.setenv("AUTH_SECURITY_EVENTS_FILE", str(tmp_path / "security_events.json"))
    monkeypatch.setenv("AUTH_LOGIN_ATTEMPTS_FILE", str(tmp_path / "login_attempts.json"))


def _login_admin(client: TestClient):
    login = client.post(
        "/login",
        data={"username": "Samandar2212", "password": "AdminPassword2026!"},
        follow_redirects=False,
    )
    assert login.status_code == 303
    assert "sharipovai_session" in client.cookies, {
        "set_cookie": login.headers.get("set-cookie"),
        "cookies": dict(client.cookies),
    }
    return login


def test_admin_can_open_security_center(tmp_path: Path, monkeypatch) -> None:
    _set_auth_env(tmp_path, monkeypatch)
    app = create_admin_secure_app(runner_factory=FakeRunner)
    client = TestClient(app)

    _login_admin(client)

    security = client.get("/security")
    assert security.status_code == 200
    assert "Кибер-безопасность" in security.text

    role = client.get("/api/auth/role").json()
    assert role["role"] == "admin"
    assert role["admin"] is True


def test_regular_user_cannot_open_security_center(tmp_path: Path, monkeypatch) -> None:
    _set_auth_env(tmp_path, monkeypatch)
    app = create_admin_secure_app(runner_factory=FakeRunner)

    admin_client = TestClient(app)
    user_client = TestClient(app)

    register = user_client.post(
        "/register",
        data={"username": "pilot03", "contact": "@pilot03", "reason": "Need access"},
    )
    assert register.status_code in {200, 202}, register.text

    login = _login_admin(admin_client)
    access_response = admin_client.get("/api/security/access-requests")
    access_payload = access_response.json()
    assert access_response.status_code == 200, {
        "body": access_response.text,
        "cookies": dict(admin_client.cookies),
        "login_set_cookie": login.headers.get("set-cookie"),
    }
    assert "requests" in access_payload, {
        "payload": access_payload,
        "cookies": dict(admin_client.cookies),
        "login_set_cookie": login.headers.get("set-cookie"),
    }
    assert access_payload["requests"], access_payload
    request_id = access_payload["requests"][0]["id"]
    approved = admin_client.post(f"/api/security/access-requests/{request_id}/approve").json()
    temporary_password = approved["temporary_password"]

    login = user_client.post(
        "/login",
        data={"username": "pilot03", "password": temporary_password},
        follow_redirects=False,
    )
    assert login.status_code == 303

    changed = user_client.post(
        "/change-password",
        data={
            "current_password": temporary_password,
            "new_password": "PilotPassword2026!",
            "repeat_password": "PilotPassword2026!",
        },
        follow_redirects=False,
    )
    assert changed.status_code == 303

    security = user_client.get("/security")
    assert security.status_code == 403
    assert "Доступ запрещён" in security.text

    api_security = user_client.get("/api/security/access-requests")
    assert api_security.status_code == 403
    assert api_security.json()["error"] == "admin_required"

    home = user_client.get("/")
    assert home.status_code == 200

    role = user_client.get("/api/auth/role").json()
    assert role["role"] == "user"
    assert role["admin"] is False
