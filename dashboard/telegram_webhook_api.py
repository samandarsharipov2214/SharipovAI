"""Telegram webhook endpoints for SharipovAI.

Render starts the web app with uvicorn, so long polling in telegram_bot.py does
not run automatically. Webhook mode lets Telegram deliver updates directly to
this FastAPI app.
"""

from __future__ import annotations

import html
import os
from typing import Any

import httpx
from fastapi import Body, FastAPI
from fastapi.responses import HTMLResponse

from telegram_bot import handle_callback, handle_message, main_keyboard, send_message, setup_bot_commands

TELEGRAM_API_TIMEOUT = 20.0


def install_telegram_webhook_api(app: FastAPI) -> None:
    """Install Telegram bot webhook and management endpoints."""

    if getattr(app.state, "telegram_webhook_api_installed", False):
        return
    app.state.telegram_webhook_api_installed = True

    @app.get("/api/telegram/status")
    def telegram_status() -> dict[str, Any]:
        return _telegram_status()

    @app.get("/telegram-check", response_class=HTMLResponse)
    def telegram_check_page() -> HTMLResponse:
        return HTMLResponse(_render_telegram_check(_telegram_status()))

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


def _telegram_status() -> dict[str, Any]:
    token = _bot_token()
    status: dict[str, Any] = {
        "status": "ok" if token else "missing_token",
        "bot_token_configured": bool(token),
        "webapp_url": _webapp_url(),
        "webhook_endpoint": "/telegram/webhook",
        "mode": "webhook",
        "set_webhook_url": "/api/telegram/set-webhook",
        "delete_webhook_url": "/api/telegram/delete-webhook",
    }
    if token:
        status["telegram_get_me"] = _telegram("getMe")
        status["webhook_info"] = _telegram("getWebhookInfo")
    return status


def _render_telegram_check(status: dict[str, Any]) -> str:
    get_me = status.get("telegram_get_me", {}) if isinstance(status, dict) else {}
    bot = get_me.get("result", {}) if isinstance(get_me, dict) else {}
    webhook = status.get("webhook_info", {}) if isinstance(status, dict) else {}
    webhook_result = webhook.get("result", {}) if isinstance(webhook, dict) else {}
    token_ok = "ДА" if status.get("bot_token_configured") else "НЕТ"
    webapp = html.escape(str(status.get("webapp_url") or "не задан"))
    username = html.escape(str(bot.get("username") or "неизвестно"))
    webhook_url = html.escape(str(webhook_result.get("url") or "не установлен"))
    pending = html.escape(str(webhook_result.get("pending_update_count", 0)))
    last_error = html.escape(str(webhook_result.get("last_error_message") or "нет"))
    return f"""<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>SharipovAI · Telegram Check</title><style>body{{margin:0;background:#070b12;color:#eef4ff;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}}main{{padding:18px;max-width:900px;margin:auto}}.card{{background:#111827;border:1px solid #243044;border-radius:18px;padding:16px;margin:12px 0;box-shadow:0 20px 60px rgba(0,0,0,.25)}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px}}.stat{{background:#0b1220;border:1px solid #1f2a3d;border-radius:14px;padding:12px}}small{{display:block;color:#8ea2c4}}b{{font-size:22px}}a{{color:#60a5fa;font-weight:800}}.ok{{display:inline-block;background:#10b981;color:#03130d;border-radius:999px;padding:7px 12px;font-weight:900}}.warn{{display:inline-block;background:#f59e0b;color:#120a02;border-radius:999px;padding:7px 12px;font-weight:900}}</style></head><body><main><section class="card"><span class="ok">TELEGRAM CHECK</span><h1>Проверка Telegram Bot</h1><p>Эта страница нужна после финального деплоя. Сначала проверь статус, потом один раз нажми set-webhook.</p><p><a href="/">Главная</a> · <a href="/api/telegram/status">JSON status</a> · <a href="/api/telegram/set-webhook">Set webhook</a> · <a href="/api/telegram/delete-webhook">Delete webhook</a></p></section><section class="card"><div class="grid"><div class="stat"><small>BOT_TOKEN</small><b>{token_ok}</b></div><div class="stat"><small>Bot username</small><b>@{username}</b></div><div class="stat"><small>Mode</small><b>webhook</b></div><div class="stat"><small>Pending updates</small><b>{pending}</b></div></div></section><section class="card"><h2>Webhook</h2><p><small>WEBAPP_URL</small>{webapp}</p><p><small>Webhook URL</small>{webhook_url}</p><p><small>Last error</small>{last_error}</p></section><section class="card"><h2>После деплоя порядок такой</h2><ol><li>Открыть эту страницу.</li><li>Убедиться, что BOT_TOKEN = ДА и WEBAPP_URL правильный.</li><li>Нажать <b>Set webhook</b>.</li><li>Написать боту /start.</li><li>Проверить команды /status /trade /audit /scoreboard.</li></ol></section></main></body></html>"""


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
