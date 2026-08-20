from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from dashboard import telegram_webhook_api
from dashboard.telegram_update_idempotency import claim_telegram_update
from storage.project_database import ProjectDatabase


def test_claim_telegram_update_is_persistent_and_idempotent(tmp_path) -> None:
    dsn = f"sqlite:///{tmp_path / 'shared.db'}"

    first_process = ProjectDatabase(dsn)
    assert claim_telegram_update(12345, database=first_process) is True
    assert claim_telegram_update(12345, database=first_process) is False

    restarted_process = ProjectDatabase(dsn)
    assert claim_telegram_update(12345, database=restarted_process) is False
    assert claim_telegram_update(12346, database=restarted_process) is True


def test_claim_telegram_update_rejects_negative_ids(tmp_path) -> None:
    database = ProjectDatabase(f"sqlite:///{tmp_path / 'shared.db'}")

    try:
        claim_telegram_update(-1, database=database)
    except ValueError as exc:
        assert str(exc) == "update_id must be non-negative"
    else:  # pragma: no cover - explicit regression failure path
        raise AssertionError("negative Telegram update_id was accepted")


def test_webhook_returns_success_without_requeueing_persisted_duplicate(monkeypatch) -> None:
    app = FastAPI()
    monkeypatch.setattr(telegram_webhook_api, "_auto_configure_webhook", lambda: {"status": "disabled"})
    monkeypatch.setattr(telegram_webhook_api, "_webhook_secret", lambda: "test-secret")
    monkeypatch.setattr(telegram_webhook_api, "claim_telegram_update", lambda update_id: False)
    telegram_webhook_api.install_telegram_webhook_api(app)

    with TestClient(app) as client:
        response = client.post(
            "/telegram/webhook",
            json={"update_id": 777, "message": {"chat": {"id": 1}, "text": "/start"}},
            headers={"X-Telegram-Bot-Api-Secret-Token": "test-secret"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "duplicate": True,
        "update_id": 777,
        "adapter": "shared_website_system",
    }


def test_webhook_rejects_non_integer_update_id_before_queueing(monkeypatch) -> None:
    app = FastAPI()
    monkeypatch.setattr(telegram_webhook_api, "_auto_configure_webhook", lambda: {"status": "disabled"})
    monkeypatch.setattr(telegram_webhook_api, "_webhook_secret", lambda: "test-secret")
    telegram_webhook_api.install_telegram_webhook_api(app)

    with TestClient(app) as client:
        response = client.post(
            "/telegram/webhook",
            json={"update_id": "not-an-int"},
            headers={"X-Telegram-Bot-Api-Secret-Token": "test-secret"},
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "invalid_telegram_update_id"
