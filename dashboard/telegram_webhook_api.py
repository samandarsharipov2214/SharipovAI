"""Secure Telegram webhook and Mini App authentication for SharipovAI."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from typing import Any
from urllib.parse import parse_qsl, urlparse

import httpx
from fastapi import BackgroundTasks, Body, FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse

from telegram_system_adapter import CANONICAL_WEBAPP_URL, handle_callback, handle_message, main_keyboard, send_message, setup_bot_commands
from telegram_health import telegram_health

TELEGRAM_API_TIMEOUT = 20.0
MINIAPP_MAX_AGE_SECONDS = int(os.getenv("TELEGRAM_INIT_DATA_MAX_AGE", "3600"))


def install_telegram_webhook_api(app: FastAPI) -> None:
    if getattr(app.state, "telegram_webhook_api_installed", False):
        return
    app.state.telegram_webhook_api_installed = True

    @app.on_event("startup")
    def telegram_auto_configure_webhook() -> None:
        app.state.telegram_webhook_autoconfigure = _auto_configure_webhook()

    @app.get("/api/telegram/status")
    def telegram_status() -> dict[str, Any]:
        result = _telegram_status()
        result["auto_configure"] = getattr(app.state, "telegram_webhook_autoconfigure", None)
        result["integration"] = {"website_core": True, "shared_demo_state": True, "shared_ai_chat_orchestrator": True, "shared_bot_network": True, "adapter": "telegram_system_adapter"}
        return result

    @app.get("/api/telegram/self-test")
    def telegram_self_test() -> dict[str, Any]:
        result = telegram_health()
        result["system_adapter"] = "telegram_system_adapter"
        return result

    @app.post("/telegram/webhook")
    async def telegram_webhook(background_tasks: BackgroundTasks, update: dict[str, Any] = Body(default_factory=dict), x_telegram_bot_api_secret_token: str | None = Header(default=None)) -> dict[str, Any]:
        expected = _webhook_secret()
        if not expected or not hmac.compare_digest(x_telegram_bot_api_secret_token or "", expected):
            raise HTTPException(status_code=403, detail="invalid_webhook_secret")
        if not isinstance(update, dict) or "update_id" not in update:
            raise HTTPException(status_code=400, detail="invalid_telegram_update")
        background_tasks.add_task(_process_update_safely, update)
        return {"ok": True, "queued": True, "adapter": "shared_website_system"}

    @app.get("/api/telegram/set-webhook")
    def set_webhook_get() -> JSONResponse:
        return JSONResponse(status_code=405, content={"status": "method_not_allowed", "use": "POST /api/telegram/set-webhook with X-SharipovAI-Admin"})

    @app.post("/api/telegram/set-webhook")
    def set_webhook_post(x_sharipovai_admin: str | None = Header(default=None)) -> dict[str, Any]:
        _require_admin_token(x_sharipovai_admin)
        result = _set_webhook()
        app.state.telegram_webhook_autoconfigure = result
        return result

    @app.get("/api/telegram/delete-webhook")
    def delete_webhook_get() -> JSONResponse:
        return JSONResponse(status_code=405, content={"status": "method_not_allowed", "use": "POST /api/telegram/delete-webhook with X-SharipovAI-Admin"})

    @app.post("/api/telegram/delete-webhook")
    def delete_webhook_post(x_sharipovai_admin: str | None = Header(default=None)) -> dict[str, Any]:
        _require_admin_token(x_sharipovai_admin)
        return _delete_webhook()

    @app.post("/api/telegram/test-message")
    def telegram_test_message(payload: dict[str, Any] | None = Body(default=None), x_sharipovai_admin: str | None = Header(default=None)) -> dict[str, Any]:
        _require_admin_token(x_sharipovai_admin)
        chat_id = (payload or {}).get("chat_id")
        if not chat_id:
            raise HTTPException(status_code=400, detail="chat_id_required")
        send_message(int(chat_id), "✅ Telegram подключён к ядру сайта SharipovAI.", main_keyboard())
        return {"status": "ok", "sent": True, "adapter": "shared_website_system"}

    @app.post("/api/telegram/miniapp-auth")
    def miniapp_auth(payload: dict[str, Any] | None = Body(default=None)) -> dict[str, Any]:
        init_data = str((payload or {}).get("init_data", ""))
        validation = validate_miniapp_init_data(init_data)
        if not validation["ok"]:
            raise HTTPException(status_code=401, detail=validation["error"])
        return {"status": "ok", "authenticated": True, "user": validation.get("user"), "auth_date": validation.get("auth_date")}


def validate_miniapp_init_data(init_data: str) -> dict[str, Any]:
    token = _bot_token()
    if not token:
        return {"ok": False, "error": "BOT_TOKEN_missing"}
    if not init_data:
        return {"ok": False, "error": "init_data_missing"}
    try:
        pairs = dict(parse_qsl(init_data, keep_blank_values=True, strict_parsing=True))
    except ValueError:
        return {"ok": False, "error": "init_data_malformed"}
    received_hash = pairs.pop("hash", "")
    pairs.pop("signature", None)
    if not received_hash:
        return {"ok": False, "error": "hash_missing"}
    data_check_string = "\n".join(f"{key}={pairs[key]}" for key in sorted(pairs))
    secret_key = hmac.new(b"WebAppData", token.encode("utf-8"), hashlib.sha256).digest()
    calculated = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(received_hash, calculated):
        return {"ok": False, "error": "invalid_hash"}
    try:
        auth_date = int(pairs.get("auth_date", "0"))
    except ValueError:
        return {"ok": False, "error": "invalid_auth_date"}
    now = int(time.time())
    if auth_date <= 0 or abs(now - auth_date) > MINIAPP_MAX_AGE_SECONDS:
        return {"ok": False, "error": "init_data_expired"}
    user: dict[str, Any] | None = None
    if pairs.get("user"):
        try:
            parsed = json.loads(pairs["user"])
            user = parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return {"ok": False, "error": "invalid_user_json"}
    return {"ok": True, "auth_date": auth_date, "user": user, "query_id": pairs.get("query_id")}


def _process_update_safely(update: dict[str, Any]) -> None:
    try:
        if isinstance(update.get("message"), dict):
            handle_message(update["message"])
        if isinstance(update.get("callback_query"), dict):
            handle_callback(update["callback_query"])
    except Exception as exc:
        print(f"Telegram webhook processing error: {type(exc).__name__}: {exc}", flush=True)


def _auto_configure_webhook() -> dict[str, Any]:
    enabled = os.getenv("TELEGRAM_AUTO_SET_WEBHOOK", "1").strip().lower()
    if enabled in {"0", "false", "no", "off"}:
        return {"status": "disabled"}
    if not _bot_token():
        return {"status": "skipped", "reason": "BOT_TOKEN_missing"}
    return _set_webhook()


def _set_webhook() -> dict[str, Any]:
    webhook_url = f"{_webapp_url()}/telegram/webhook"
    commands = _safe_setup_commands()
    menu_button = _set_canonical_webapp_menu()
    payload = {"url": webhook_url, "secret_token": _webhook_secret(), "drop_pending_updates": False, "allowed_updates": ["message", "callback_query"], "max_connections": 20}
    result = _telegram("setWebhook", payload)
    return {"status": "ok" if result.get("ok") and menu_button.get("ok") else "error", "webhook_url": webhook_url, "webapp_url": _webapp_url(), "secret_token_configured": True, "set_webhook": result, "commands": commands, "menu_button": menu_button, "adapter": "shared_website_system"}


def _delete_webhook() -> dict[str, Any]:
    result = _telegram("deleteWebhook", {"drop_pending_updates": False})
    return {"status": "ok" if result.get("ok") else "error", "delete_webhook": result}


def _telegram_status() -> dict[str, Any]:
    token = _bot_token()
    result: dict[str, Any] = {"status": "ok" if token else "missing_token", "bot_token_configured": bool(token), "webapp_url": _webapp_url(), "canonical_webapp_url": CANONICAL_WEBAPP_URL, "render_blocked": True, "webhook_endpoint": "/telegram/webhook", "webhook_secret_configured": bool(_webhook_secret()), "mode": "webhook", "miniapp_auth": "/api/telegram/miniapp-auth"}
    if token:
        result["telegram_get_me"] = _telegram("getMe")
        result["webhook_info"] = _telegram("getWebhookInfo")
        result["menu_button"] = _telegram("getChatMenuButton")
    return result


def _set_canonical_webapp_menu() -> dict[str, Any]:
    return _telegram("setChatMenuButton", {"menu_button": {"type": "web_app", "text": "Открыть SharipovAI", "web_app": {"url": _webapp_url()}}})


def _safe_setup_commands() -> dict[str, Any]:
    try:
        setup_bot_commands()
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def _telegram(method: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    token = _bot_token()
    if not token:
        return {"ok": False, "error": "BOT_TOKEN_missing"}
    try:
        with httpx.Client(timeout=TELEGRAM_API_TIMEOUT) as client:
            response = client.post(f"https://api.telegram.org/bot{token}/{method}", json=payload or {})
            data = response.json()
            if response.is_error:
                return {"ok": False, "status_code": response.status_code, "telegram": data}
            return data if isinstance(data, dict) else {"ok": False, "raw": data}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def _bot_token() -> str:
    return os.getenv("BOT_TOKEN", "").strip()


def _webapp_url() -> str:
    configured = os.getenv("WEBAPP_URL", "").strip().rstrip("/")
    if not configured:
        return CANONICAL_WEBAPP_URL
    try:
        host = (urlparse(configured).hostname or "").lower()
    except ValueError:
        host = ""
    if configured != CANONICAL_WEBAPP_URL or host.endswith(".onrender.com") or host == "render.com":
        return CANONICAL_WEBAPP_URL
    return configured


def _webhook_secret() -> str:
    configured = os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip()
    if configured:
        return configured
    source = os.getenv("AUTH_SECRET", "").strip() or _bot_token()
    return hashlib.sha256(f"sharipovai-webhook:{source}".encode("utf-8")).hexdigest()


def _admin_token() -> str:
    return os.getenv("TELEGRAM_ADMIN_SECRET", "").strip() or os.getenv("AUTH_SECRET", "").strip()


def _require_admin_token(provided: str | None) -> None:
    expected = _admin_token()
    if not expected:
        raise HTTPException(status_code=503, detail="TELEGRAM_ADMIN_SECRET_or_AUTH_SECRET_missing")
    if not hmac.compare_digest(provided or "", expected):
        raise HTTPException(status_code=403, detail="admin_token_invalid")
