from __future__ import annotations

import json
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


def test_login_page_points_to_access_request(monkeypatch) -> None:
    monkeypatch.setenv("SHARIPOVAI_DISABLE_AUTH", "1")
    app = create_app(runner_factory=FakeRunner)
    client = TestClient(app)

    response = client.get("/login")

    assert response.status_code == 200
    assert "Вход в SharipovAI" in response.text
    assert "Запросить доступ" in response.text
    assert "ADMIN_USERNAME" not in response.text
    assert "AUTH_USERS_FILE" not in response.text


def test_web2_shell_exposes_the_existing_logout_route() -> None:
    web2_shell = Path(__file__).parents[1] / "static" / "web2" / "index.html"

    html = web2_shell.read_text(encoding="utf-8")

    assert '<a class="action" href="/logout">Выйти</a>' in html


def test_register_creates_security_access_request(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("AUTH_ACCESS_REQUESTS_FILE", str(tmp_path / "access_requests.json"))
    monkeypatch.setenv("AUTH_SECURITY_EVENTS_FILE", str(tmp_path / "security_events.json"))
    monkeypatch.setenv("AUTH_USERS_FILE", str(tmp_path / "users.json"))
    monkeypatch.setenv("AUTH_ALLOW_REGISTRATION", "1")
    monkeypatch.setenv("SHARIPOVAI_DISABLE_AUTH", "1")
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    monkeypatch.delenv("AUTH_SECRET", raising=False)
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
    assert "\u0417\u0430\u044f\u0432\u043a\u0430 \u043f\u0440\u0438\u043d\u044f\u0442\u0430" in response.text

    api_response = client.get("/api/security/access-requests")
    assert api_response.status_code == 200
    payload = api_response.json()
    assert payload["status"] == "ok"
    assert payload["requests"][0]["username"] == "testuser"
    assert payload["requests"][0]["contact"] == "@testuser"
    assert payload["requests"][0]["reason"] == "Need dashboard access"
    assert payload["requests"][0]["status"] == "pending"
    assert payload["requests"][0]["created_at"] > 0
    assert "password" not in payload["requests"][0]


def test_register_accepts_legacy_client_without_context(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("AUTH_ACCESS_REQUESTS_FILE", str(tmp_path / "access_requests.json"))
    monkeypatch.setenv("AUTH_SECURITY_EVENTS_FILE", str(tmp_path / "security_events.json"))
    monkeypatch.setenv("AUTH_USERS_FILE", str(tmp_path / "users.json"))
    monkeypatch.setenv("AUTH_ALLOW_REGISTRATION", "1")
    monkeypatch.setenv("SHARIPOVAI_DISABLE_AUTH", "1")
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    monkeypatch.delenv("AUTH_SECRET", raising=False)
    client = TestClient(create_app(runner_factory=FakeRunner))

    response = client.post("/register", data={"username": "legacy-client"})

    assert response.status_code == 202
    record = client.get("/api/security/access-requests").json()["requests"][0]
    assert record["username"] == "legacy-client"
    assert record["contact"] == ""
    assert record["reason"] == ""
    assert record["status"] == "pending"


def test_access_requests_api_reads_legacy_record_without_context(tmp_path: Path, monkeypatch) -> None:
    requests_file = tmp_path / "access_requests.json"
    requests_file.write_text(
        json.dumps({"requests": [{"id": "REQ-old", "username": "legacy", "status": "pending", "created_at": 1}]}),
        encoding="utf-8",
    )
    monkeypatch.setenv("AUTH_ACCESS_REQUESTS_FILE", str(requests_file))
    monkeypatch.setenv("SHARIPOVAI_DISABLE_AUTH", "1")
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    monkeypatch.delenv("AUTH_SECRET", raising=False)

    response = TestClient(create_app(runner_factory=FakeRunner)).get("/api/security/access-requests")

    assert response.status_code == 200
    assert response.json()["requests"][0]["username"] == "legacy"
