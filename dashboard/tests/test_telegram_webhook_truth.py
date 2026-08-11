from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from dashboard import telegram_webhook_api


def test_webhook_secret_is_unavailable_without_real_secret_source(monkeypatch) -> None:
    monkeypatch.delenv("TELEGRAM_WEBHOOK_SECRET", raising=False)
    monkeypatch.delenv("AUTH_SECRET", raising=False)
    monkeypatch.delenv("BOT_TOKEN", raising=False)

    assert telegram_webhook_api._webhook_secret() == ""


def test_telegram_status_reports_canonical_state_not_demo(monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_AUTO_SET_WEBHOOK", "0")
    monkeypatch.delenv("BOT_TOKEN", raising=False)
    monkeypatch.setattr(
        telegram_webhook_api,
        "load_canonical_paper_state",
        lambda: {
            "status": "ok",
            "source_of_truth": "ProjectDatabase/CouncilAuthorizedPaperLoop",
            "database_backed": True,
        },
    )
    app = FastAPI()
    telegram_webhook_api.install_telegram_webhook_api(app)

    with TestClient(app) as client:
        response = client.get("/api/telegram/status")

    assert response.status_code == 200
    integration = response.json()["integration"]
    assert integration["paper_state_status"] == "ok"
    assert integration["paper_state_source"] == "ProjectDatabase/CouncilAuthorizedPaperLoop"
    assert integration["paper_state_database_backed"] is True
    assert integration["shared_demo_state"] is False
