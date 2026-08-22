from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

import dashboard.telegram_webhook_api as telegram_api


class _FakeSession:
    def __init__(self, user):
        self.user = user
        self.closed = False

    def scalar(self, _statement):
        return self.user

    def close(self):
        self.closed = True


def _app(monkeypatch) -> FastAPI:
    monkeypatch.setattr(telegram_api, "_auto_configure_webhook", lambda: {"status": "disabled"})
    app = FastAPI()
    telegram_api.install_telegram_webhook_api(app)
    return app


def test_extracts_supported_telegram_actor_ids():
    assert telegram_api._telegram_update_user_id({"message": {"from": {"id": 101}}}) == 101
    assert telegram_api._telegram_update_user_id({"callback_query": {"from": {"id": "202"}}}) == 202
    assert telegram_api._telegram_update_user_id({"message": {"from": {"id": 0}}}) is None
    assert telegram_api._telegram_update_user_id({"message": {"from": {"id": "bad"}}}) is None
    assert telegram_api._telegram_update_user_id({"message": {"chat": {"id": 303}}}) is None


def test_approved_identity_requires_active_canonical_user(monkeypatch):
    binding = SimpleNamespace(canonical_user_id="user-1")
    monkeypatch.setattr(telegram_api, "get_telegram_identity_binding", lambda user_id: binding)

    active_session = _FakeSession(SimpleNamespace(id="user-1", is_active=True))
    monkeypatch.setattr(telegram_api, "SessionLocal", lambda: active_session)
    assert telegram_api._approved_telegram_user_id({"message": {"from": {"id": 101}}}) == "user-1"
    assert active_session.closed is True

    inactive_session = _FakeSession(SimpleNamespace(id="user-1", is_active=False))
    monkeypatch.setattr(telegram_api, "SessionLocal", lambda: inactive_session)
    assert telegram_api._approved_telegram_user_id({"message": {"from": {"id": 101}}}) is None
    assert inactive_session.closed is True


def test_unbound_or_malformed_identity_fails_closed(monkeypatch):
    monkeypatch.setattr(telegram_api, "get_telegram_identity_binding", lambda _user_id: None)
    assert telegram_api._approved_telegram_user_id({"message": {"from": {"id": 101}}}) is None

    def malformed(_user_id):
        raise RuntimeError("malformed binding")

    monkeypatch.setattr(telegram_api, "get_telegram_identity_binding", malformed)
    assert telegram_api._approved_telegram_user_id({"message": {"from": {"id": 101}}}) is None


def test_owner_deploy_bypass_is_narrow_and_requires_exact_persisted_owner(monkeypatch):
    checked = []
    monkeypatch.setattr(
        telegram_api,
        "is_exact_owner",
        lambda actor_id, chat_id: checked.append((actor_id, chat_id)) or (actor_id, chat_id) == (101, 202),
    )

    deploy = {"message": {"from": {"id": 101}, "chat": {"id": 202}, "text": "/deploy"}}
    status = {"message": {"from": {"id": 101}, "chat": {"id": 202}, "text": "/deploy_status"}}
    whoami = {"message": {"from": {"id": 101}, "chat": {"id": 202}, "text": "/whoami"}}
    normal = {"message": {"from": {"id": 101}, "chat": {"id": 202}, "text": "/start"}}
    confirm = {
        "callback_query": {
            "from": {"id": 101},
            "data": "deploy:confirm:token",
            "message": {"chat": {"id": 202}},
        }
    }
    foreign = {"message": {"from": {"id": 999}, "chat": {"id": 202}, "text": "/deploy"}}

    assert telegram_api._owner_deploy_control_update(deploy) is True
    assert telegram_api._owner_deploy_control_update(status) is True
    assert telegram_api._owner_deploy_control_update(whoami) is True
    assert telegram_api._owner_deploy_control_update(confirm) is True
    assert telegram_api._owner_deploy_control_update(normal) is False
    assert telegram_api._owner_deploy_control_update(foreign) is False
    assert (101, 202) in checked
    assert (999, 202) in checked


def test_webhook_claims_but_does_not_dispatch_unapproved_actor(monkeypatch):
    app = _app(monkeypatch)
    monkeypatch.setattr(telegram_api, "_webhook_secret", lambda: "secret")
    monkeypatch.setattr(telegram_api, "_approved_telegram_user_id", lambda _update: None)
    monkeypatch.setattr(telegram_api, "_owner_deploy_control_update", lambda _update: False)

    claims = []
    processed = []
    monkeypatch.setattr(telegram_api, "claim_telegram_update", lambda update_id: claims.append(update_id) or True)
    monkeypatch.setattr(telegram_api, "_process_update_safely", lambda update: processed.append(update))

    with TestClient(app) as client:
        response = client.post(
            "/telegram/webhook",
            json={"update_id": 7001, "message": {"from": {"id": 101}, "text": "hello"}},
            headers={"X-Telegram-Bot-Api-Secret-Token": "secret"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "ignored": True,
        "reason": "telegram_user_not_approved",
        "update_id": 7001,
        "adapter": "shared_website_system",
    }
    assert claims == [7001]
    assert processed == []


def test_webhook_queues_only_approved_actor(monkeypatch):
    app = _app(monkeypatch)
    monkeypatch.setattr(telegram_api, "_webhook_secret", lambda: "secret")
    monkeypatch.setattr(telegram_api, "_approved_telegram_user_id", lambda _update: "user-1")
    monkeypatch.setattr(telegram_api, "_owner_deploy_control_update", lambda _update: False)

    claims = []
    processed = []
    monkeypatch.setattr(telegram_api, "claim_telegram_update", lambda update_id: claims.append(update_id) or True)
    monkeypatch.setattr(telegram_api, "_process_update_safely", lambda update: processed.append(update))

    payload = {"update_id": 7002, "message": {"from": {"id": 101}, "text": "hello"}}
    with TestClient(app) as client:
        response = client.post(
            "/telegram/webhook",
            json=payload,
            headers={"X-Telegram-Bot-Api-Secret-Token": "secret"},
        )

    assert response.status_code == 200
    assert response.json()["queued"] is True
    assert claims == [7002]
    assert processed == [payload]


def test_webhook_queues_owner_deploy_control_without_canonical_binding(monkeypatch):
    app = _app(monkeypatch)
    monkeypatch.setattr(telegram_api, "_webhook_secret", lambda: "secret")
    monkeypatch.setattr(telegram_api, "_approved_telegram_user_id", lambda _update: None)
    monkeypatch.setattr(telegram_api, "_owner_deploy_control_update", lambda _update: True)

    claims = []
    processed = []
    monkeypatch.setattr(telegram_api, "claim_telegram_update", lambda update_id: claims.append(update_id) or True)
    monkeypatch.setattr(telegram_api, "_process_update_safely", lambda update: processed.append(update))

    payload = {
        "update_id": 7003,
        "message": {"from": {"id": 101}, "chat": {"id": 202}, "text": "/deploy"},
    }
    with TestClient(app) as client:
        response = client.post(
            "/telegram/webhook",
            json=payload,
            headers={"X-Telegram-Bot-Api-Secret-Token": "secret"},
        )

    assert response.status_code == 200
    assert response.json()["queued"] is True
    assert claims == [7003]
    assert processed == [payload]
