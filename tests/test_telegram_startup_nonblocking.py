"""FastAPI lifespan must complete even when Telegram/network I/O hangs."""
from __future__ import annotations

import threading
import time

from fastapi import FastAPI
from fastapi.testclient import TestClient

import dashboard.telegram_webhook_api as telegram_api


def test_lifespan_completes_when_set_webhook_hangs(monkeypatch) -> None:
    monkeypatch.setenv("BOT_TOKEN", "123456:hanging-telegram-token")
    monkeypatch.setenv("TELEGRAM_AUTO_SET_WEBHOOK", "1")

    release = threading.Event()
    entered = threading.Event()

    def hanging_set_webhook() -> dict[str, object]:
        entered.set()
        if not release.wait(timeout=30):
            return {"status": "timeout"}
        return {"status": "ok"}

    monkeypatch.setattr(telegram_api, "_set_webhook", hanging_set_webhook)
    monkeypatch.setattr(telegram_api, "_telegram", lambda *args, **kwargs: {"ok": True})

    app = FastAPI()
    telegram_api.install_telegram_webhook_api(app)

    started = time.monotonic()
    with TestClient(app) as client:
        elapsed = time.monotonic() - started
        assert elapsed < 2.0
        payload = client.get("/api/telegram/status").json()
        assert payload["auto_configure"] == {"status": "pending"}
        assert payload["integration"]["canonical_paper_state"] is True
        assert payload["integration"]["shared_demo_state"] is False
        assert entered.wait(timeout=1.0)
    release.set()


def test_lifespan_completes_when_set_webhook_raises(monkeypatch) -> None:
    monkeypatch.setenv("BOT_TOKEN", "123456:raising-telegram-token")
    monkeypatch.setenv("TELEGRAM_AUTO_SET_WEBHOOK", "1")

    def exploding_set_webhook() -> dict[str, object]:
        raise RuntimeError("telegram_unreachable")

    monkeypatch.setattr(telegram_api, "_set_webhook", exploding_set_webhook)
    monkeypatch.setattr(telegram_api, "_telegram", lambda *args, **kwargs: {"ok": True})

    app = FastAPI()
    telegram_api.install_telegram_webhook_api(app)

    started = time.monotonic()
    with TestClient(app) as client:
        elapsed = time.monotonic() - started
        assert elapsed < 2.0
        deadline = time.monotonic() + 1.0
        status = None
        while time.monotonic() < deadline:
            status = client.get("/api/telegram/status").json().get("auto_configure")
            if isinstance(status, dict) and status.get("status") == "error":
                break
            time.sleep(0.01)
        assert isinstance(status, dict)
        assert status["status"] == "error"
        assert "telegram_unreachable" in str(status.get("error", ""))
