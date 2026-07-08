"""Telegram webhook endpoints for SharipovAI.

Render starts the web app with uvicorn, so long polling in telegram_bot.py does
not run automatically. Webhook mode lets Telegram deliver updates directly to
this FastAPI app.
"""

from __future__ import annotations

import os
from typing import Any

import httpx
from fastapi import Body, FastAPI

from telegram_bot import handle_callback, handle_message, main_keyboard, send_message, setup_bot_commands

TELEGRAM_API_TIMEOUT = 20.0


def install_telegram_webhook_api(app: FastAPI) -> None:
    """Install Telegram bot webhook and management endpoints."""

    if getattr(app.state, "telegram_webhook_api_installed", False):
        return
    app.state.telegram_webhook_api_installed = True

    @app.get("/api/telegram/status")
    def telegram_status() -> dict[str, Any]:
        token = _bot_token()
        status: dict[str, Any] = {
            "status": "ok" if token else "missing_token",
            "bot_token_configured": bool(token),
            "webapp_url": _webapp_url(),
            "webhook_endpoint": "/telegram/webhook",
            "mode": "webhook",
        }
        if token:
            status["telegram_get_me"] = _telegram("getMe")
            status["webhook_info"] = _telegram("getWebhookInfo")
        return status

    @app.post("/telegram/webhook")
    async def telegram_webhook(update: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        """Receive one Telegram update."""

        if "message" in update:
            handle_message(update["message"])
        if "callback_query" in update:
            handle_callback(update["callback_query"])
        return {"ok": True}

    @app.get("/api/telegram/set-webhook")
    def set_webhook_get() -> dict[str, Any]:
        return _set_webhook()

    @app.post("/api/telegram/set-webhook")
    def set_webhook_post() -> dict[str, Any]:
        return _set_webhook()

    @app.get("/api/telegram/delete-webhook")
    def delete_webhook_get() -> dict[str, Any]:
        return _delete_webhook()

    @app.post("/api/telegram/delete-webhook")
    def delete_webhook_post() -> dict[str, Any]:
        return _delete_webhook()

    @app.post("/api/telegram/test-message")
    def telegram_test_message(payload: dict[str, Any] | None = Body(default=None)) -> dict[str, Any]:
        payload = payload or {}
        chat_id = payload.get("chat_id")
        if not chat_id:
            return {"status": "error", "error": "chat_id_required"}
        send_message(int(chat_id), "✅ SharipovAI Telegram webhook работает. AI Chat Orchestrator подключён.", main_keyboard())
        return {"status": "ok", "sent": True}


def _bot_token() -> str:
    return os.getenv("BOT_TOKEN", "").strip()


def _webapp_url() -> str:
    return os.getenv("WEBAPP_URL", "").strip().rstrip("/")


def _telegram(method: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    token = _bot_token()
    if not token:
        return {"ok": False, "error": "BOT_TOKEN is missing"}
    try:
        with httpx.Client(timeout=TELEGRAM_API_TIMEOUT) as client:
            response = client.post(f"https://api.telegram.org/bot{token}/{method}", json=payload or {})
            data = response.json()
            return data if isinstance(data, dict) else {"ok": False, "raw": data}
    except Exception as exc:  # pragma: no cover - network/runtime safety
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def _set_webhook() -> dict[str, Any]:
    base = _webapp_url()
    if not _bot_token():
        return {"status": "error", "error": "BOT_TOKEN is missing in Render env"}
    if not base:
        return {"status": "error", "error": "WEBAPP_URL is missing in Render env"}
    webhook_url = f"{base}/telegram/webhook"
    commands_result = _safe_setup_commands()
    result = _telegram("setWebhook", {"url": webhook_url, "drop_pending_updates": False, "allowed_updates": ["message", "callback_query"]})
    return {"status": "ok" if result.get("ok") else "error", "webhook_url": webhook_url, "set_webhook": result, "commands": commands_result}


def _delete_webhook() -> dict[str, Any]:
    result = _telegram("deleteWebhook", {"drop_pending_updates": False})
    return {"status": "ok" if result.get("ok") else "error", "delete_webhook": result}


def _safe_setup_commands() -> dict[str, Any]:
    try:
        setup_bot_commands()
        return {"ok": True}
    except Exception as exc:  # pragma: no cover
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
