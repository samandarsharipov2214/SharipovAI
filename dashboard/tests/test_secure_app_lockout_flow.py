from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from dashboard.secure_app import create_secure_app
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


def test_secure_app_blocks_login_after_repeated_failures(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ADMIN_USERNAME", "Samandar2212")
    monkeypatch.setenv("ADMIN_PASSWORD", "CorrectPassword2026!")
    monkeypatch.setenv("AUTH_SECRET", "test-secret")
    monkeypatch.setenv("AUTH_LOGIN_ATTEMPTS_FILE", str(tmp_path / "login_attempts.json"))
    monkeypatch.setenv("AUTH_SECURITY_EVENTS_FILE", str(tmp_path / "security_events.json"))
    monkeypatch.setenv("AUTH_MAX_FAILED_ATTEMPTS", "3")
    monkeypatch.setenv("AUTH_LOCK_SECONDS", "60")

    app = create_secure_app(runner_factory=FakeRunner)
    client = TestClient(app)

    first = client.post("/login", data={"username": "Samandar2212", "password": "bad-1"})
    second = client.post("/login", data={"username": "Samandar2212", "password": "bad-2"})
    third = client.post("/login", data={"username": "Samandar2212", "password": "bad-3"})

    assert first.status_code == 401
    assert second.status_code == 401
    assert third.status_code == 423
    assert "заблокирован" in third.text.lower()

    locked_even_with_correct_password = client.post(
        "/login",
        data={"username": "Samandar2212", "password": "CorrectPassword2026!"},
    )
    assert locked_even_with_correct_password.status_code == 423

    status = client.get("/api/security/login-attempts").json()
    user_state = status["attempts"]["users"]["samandar2212"]
    assert status["status"] == "ok"
    assert user_state["locked"] is True
    assert user_state["failed_attempts"] == 3
    assert user_state["seconds_left"] > 0
