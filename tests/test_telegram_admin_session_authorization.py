from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import dashboard.telegram_webhook_api as telegram_api


def _client(monkeypatch, admin_guard):
    app = FastAPI()
    monkeypatch.setattr(telegram_api, "require_admin", admin_guard)
    monkeypatch.setattr(telegram_api, "_set_webhook", lambda: {"status": "ok", "set_webhook": {"ok": True}})
    monkeypatch.setattr(telegram_api, "_delete_webhook", lambda: {"status": "ok", "delete_webhook": {"ok": True}})
    monkeypatch.setattr(telegram_api, "send_message", lambda *args, **kwargs: {"ok": True})
    monkeypatch.setattr(telegram_api, "main_keyboard", lambda: {})
    telegram_api.install_telegram_webhook_api(app)
    return TestClient(app)


def test_telegram_admin_header_cannot_replace_authenticated_admin_session(monkeypatch):
    def deny(_request):
        raise HTTPException(status_code=401, detail={"status": "unauthorized"})

    client = _client(monkeypatch, deny)
    headers = {"X-SharipovAI-Admin": "legacy-shared-secret"}

    assert client.post("/api/telegram/set-webhook", headers=headers).status_code == 401
    assert client.post("/api/telegram/delete-webhook", headers=headers).status_code == 401
    assert client.post("/api/telegram/test-message", headers=headers, json={"chat_id": 123}).status_code == 401


def test_authenticated_admin_session_authorizes_telegram_mutations_without_header(monkeypatch):
    actors: list[str] = []

    def allow(_request):
        actors.append("ci-admin")
        return "ci-admin"

    client = _client(monkeypatch, allow)

    assert client.post("/api/telegram/set-webhook").status_code == 200
    assert client.post("/api/telegram/delete-webhook").status_code == 200
    assert client.post("/api/telegram/test-message", json={"chat_id": 123}).status_code == 200
    assert actors == ["ci-admin", "ci-admin", "ci-admin"]


def test_telegram_admin_get_mutations_remain_method_blocked(monkeypatch):
    client = _client(monkeypatch, lambda _request: "ci-admin")

    set_response = client.get("/api/telegram/set-webhook")
    delete_response = client.get("/api/telegram/delete-webhook")

    assert set_response.status_code == 405
    assert delete_response.status_code == 405
