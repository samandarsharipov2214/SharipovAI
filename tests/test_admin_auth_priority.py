from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from dashboard import create_app
from dashboard.admin_auth_compat import _split_signed_session


def test_session_signature_split_is_binary_safe() -> None:
    payload = b"pilot03:1784239000:nonce"
    signature = b"." + bytes(range(1, 31)) + b"."

    decoded_payload, decoded_signature = _split_signed_session(
        payload + b"." + signature
    )

    assert decoded_payload == payload
    assert decoded_signature == signature
    assert len(decoded_signature) == 32


def test_configured_admin_is_not_shadowed_by_pending_user(tmp_path: Path, monkeypatch) -> None:
    users_file = tmp_path / "users.json"
    users_file.write_text(
        json.dumps(
            {
                "samandar2212": {
                    "active": False,
                    "role": "pending",
                    "password_hash": "not-the-admin-password",
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("SHARIPOVAI_USERS_FILE", str(users_file))
    monkeypatch.setenv("SHARIPOVAI_ACCESS_REQUESTS_FILE", str(tmp_path / "access_requests.json"))
    monkeypatch.setenv("SHARIPOVAI_SECURITY_EVENTS_FILE", str(tmp_path / "security_events.jsonl"))
    monkeypatch.setenv("ADMIN_USERNAME", "Samandar2212")
    monkeypatch.setenv("ADMIN_PASSWORD", "CorrectPassword2026!")
    monkeypatch.setenv("AUTH_SECRET", "admin-priority-test-secret")
    monkeypatch.setenv("SHARIPOVAI_DISABLE_AUTH", "0")

    client = TestClient(create_app())
    response = client.post(
        "/login",
        data={
            "username": "Samandar2212",
            "password": "CorrectPassword2026!",
            "next": "/api/auth/me",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/api/auth/me"
    me = client.get("/api/auth/me").json()
    assert me["authenticated"] is True
    assert me["username"] == "samandar2212"


def test_pending_non_admin_user_remains_blocked(tmp_path: Path, monkeypatch) -> None:
    users_file = tmp_path / "users.json"
    users_file.write_text(
        json.dumps(
            {
                "pending_user": {
                    "active": False,
                    "role": "pending",
                    "password_hash": "unused",
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("SHARIPOVAI_USERS_FILE", str(users_file))
    monkeypatch.setenv("SHARIPOVAI_SECURITY_EVENTS_FILE", str(tmp_path / "security_events.jsonl"))
    monkeypatch.setenv("ADMIN_USERNAME", "Samandar2212")
    monkeypatch.setenv("ADMIN_PASSWORD", "CorrectPassword2026!")
    monkeypatch.setenv("AUTH_SECRET", "admin-priority-test-secret")
    monkeypatch.setenv("SHARIPOVAI_DISABLE_AUTH", "0")

    client = TestClient(create_app())
    response = client.post(
        "/login",
        data={"username": "pending_user", "password": "anything"},
        follow_redirects=False,
    )

    assert response.status_code == 401
