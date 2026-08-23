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
from fastapi import BackgroundTasks, Body, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select

from telegram_deploy_control import expected_bootstrap_owner, is_exact_owner, persisted_owner
from telegram_system_adapter import CANONICAL_WEBAPP_URL, handle_callback, handle_message, main_keyboard, send_message, setup_bot_commands
from telegram_health import telegram_health
from dashboard.admin_guard import require_admin
from dashboard.auth_saas import ensure_same_origin, get_current_user, issue_access_token, serialize_user, set_auth_cookie
from dashboard.db_saas import SessionLocal
from dashboard.models_saas import User
from dashboard.telegram_identity import TelegramIdentityConflict, bind_telegram_identity, get_telegram_identity_binding
from dashboard.telegram_update_idempotency import claim_telegram_update

TELEGRAM_API_TIMEOUT = 20.0
MINIAPP_MAX_AGE_SECONDS = int(os.getenv("TELEGRAM_INIT_DATA_MAX_AGE", "3600"))
_BOT_USERNAME_CACHE: str | None = None
_BOT_USERNAME_RESOLVED = False


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
        try:
            update_id = int(update["update_id"])
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="invalid_telegram_update_id")
        if not claim_telegram_update(update_id):
            return {"ok": True, "duplicate": True, "update_id": update_id, "adapter": "shared_website_system"}

        if (
            _approved_telegram_user_id(update) is None
            and not _owner_deploy_control_update(update)
            and not _owner_bootstrap_claim_update(update)
        ):
            return {
                "ok": True,
                "ignored": True,
                "reason": "telegram_user_not_approved",
                "update_id": update_id,
                "adapter": "shared_website_system",
            }

        # Проверяем, не development callback ли это
        if 'callback_query' in update:
            from telegram_development_control import handle_development_callback
            callback_data = update['callback_query'].get('data', '')
            if callback_data.startswith('devfix:'):
                handle_development_callback(update['callback_query'])
                return {'ok': True, 'handled': 'development_callback'}
        background_tasks.add_task(_process_update_safely, update)
        return {"ok": True, "queued": True, "adapter": "shared_website_system"}

    @app.get("/api/telegram/set-webhook")
    def set_webhook_get() -> JSONResponse:
        return JSONResponse(status_code=405, content={"status": "method_not_allowed", "use": "POST /api/telegram/set-webhook as an authenticated admin"})

    @app.post("/api/telegram/set-webhook")
    def set_webhook_post(request: Request) -> dict[str, Any]:
        require_admin(request)
        result = _set_webhook()
        app.state.telegram_webhook_autoconfigure = result
        return result

    @app.get("/api/telegram/delete-webhook")
    def delete_webhook_get() -> JSONResponse:
        return JSONResponse(status_code=405, content={"status": "method_not_allowed", "use": "POST /api/telegram/delete-webhook as an authenticated admin"})

    @app.post("/api/telegram/delete-webhook")
    def delete_webhook_post(request: Request) -> dict[str, Any]:
        require_admin(request)
        return _delete_webhook()

    @app.post("/api/telegram/test-message")
    def telegram_test_message(request: Request, payload: dict[str, Any] | None = Body(default=None)) -> dict[str, Any]:
        require_admin(request)
        chat_id = (payload or {}).get("chat_id")
        if not chat_id:
            raise HTTPException(status_code=400, detail="chat_id_required")
        send_message(int(chat_id), "✅ Telegram подключён к ядру сайта SharipovAI.", main_keyboard())
        return {"status": "ok", "sent": True, "adapter": "shared_website_system"}

    @app.post("/api/telegram/miniapp-auth")
    def miniapp_auth(request: Request, payload: dict[str, Any] | None = Body(default=None)) -> JSONResponse:
        ensure_same_origin(request)
        init_data = str((payload or {}).get("init_data", ""))
        validation = validate_miniapp_init_data(init_data)
        if not validation["ok"]:
            raise HTTPException(status_code=401, detail=validation["error"])
        telegram_user = validation.get("user")
        if not isinstance(telegram_user, dict):
            raise HTTPException(status_code=401, detail="telegram_user_missing")
        try:
            telegram_user_id = int(telegram_user.get("id"))
        except (TypeError, ValueError):
            raise HTTPException(status_code=401, detail="invalid_telegram_user_id")
        if telegram_user_id <= 0:
            raise HTTPException(status_code=401, detail="invalid_telegram_user_id")

        db = SessionLocal()
        try:
            current_user = get_current_user(request, db)
            binding = get_telegram_identity_binding(telegram_user_id)
            if binding is None:
                if current_user is None:
                    raise HTTPException(status_code=403, detail="telegram_identity_not_linked")
                try:
                    bind_telegram_identity(telegram_user_id, str(current_user.id))
                except TelegramIdentityConflict:
                    raise HTTPException(status_code=409, detail="telegram_identity_conflict")
                canonical_user = current_user
            else:
                canonical_user = db.scalar(select(User).where(User.id == binding.canonical_user_id))
                if not canonical_user or not canonical_user.is_active:
                    raise HTTPException(status_code=403, detail="telegram_identity_not_approved")
                if current_user is not None and str(current_user.id) != str(canonical_user.id):
                    raise HTTPException(status_code=409, detail="telegram_identity_conflict")

            response = JSONResponse(
                {
                    "status": "ok",
                    "authenticated": True,
                    "user": serialize_user(canonical_user),
                    "telegram_user": telegram_user,
                    "auth_date": validation.get("auth_date"),
                }
            )
            set_auth_cookie(response, issue_access_token(canonical_user))
            return response
        finally:
            db.close()


def _telegram_update_user_id(update: dict[str, Any]) -> int | None:
    """Return a native positive Telegram actor id for supported user-originated updates."""

    for key in ("message", "callback_query"):
        envelope = update.get(key)
        if not isinstance(envelope, dict):
            continue
        actor = envelope.get("from")
        if not isinstance(actor, dict):
            continue
        telegram_user_id = actor.get("id")
        if type(telegram_user_id) is not int or telegram_user_id <= 0:
            return None
        return telegram_user_id
    return None


def _telegram_update_chat_id(update: dict[str, Any]) -> int | None:
    """Return a native non-zero chat id for supported message/callback updates."""

    message = update.get("message")
    if not isinstance(message, dict):
        callback = update.get("callback_query")
        message = callback.get("message") if isinstance(callback, dict) else None
    if not isinstance(message, dict):
        return None
    chat = message.get("chat")
    if not isinstance(chat, dict):
        return None
    chat_id = chat.get("id")
    if type(chat_id) is not int or chat_id == 0:
        return None
    return chat_id


def _owner_deploy_control_update(update: dict[str, Any]) -> bool:
    """Allow only the exact persisted Telegram owner to reach deploy control without SaaS binding."""

    actor_id = _telegram_update_user_id(update)
    chat_id = _telegram_update_chat_id(update)
    if actor_id is None or chat_id is None or not is_exact_owner(actor_id, chat_id):
        return False

    message = update.get("message")
    if isinstance(message, dict):
        text = str(message.get("text") or "").strip()
        command = text.split()[0].lower() if text.startswith("/") else ""
        return command in {"/deploy", "/deploy_status", "/whoami"}

    callback = update.get("callback_query")
    if isinstance(callback, dict):
        return str(callback.get("data") or "").startswith("deploy:")
    return False


def _current_bot_username() -> str | None:
    """Resolve the authenticated bot username once, failing closed when unavailable."""

    global _BOT_USERNAME_CACHE, _BOT_USERNAME_RESOLVED
    if _BOT_USERNAME_RESOLVED:
        return _BOT_USERNAME_CACHE

    configured = os.getenv("TELEGRAM_BOT_USERNAME", "").strip().lstrip("@").lower()
    if configured:
        _BOT_USERNAME_CACHE = configured
        _BOT_USERNAME_RESOLVED = True
        return configured

    result = _telegram("getMe")
    payload = result.get("result") if isinstance(result, dict) else None
    username = str(payload.get("username") or "").strip().lstrip("@").lower() if isinstance(payload, dict) else ""
    _BOT_USERNAME_CACHE = username or None
    _BOT_USERNAME_RESOLVED = True
    return _BOT_USERNAME_CACHE


def _normalize_owner_claim_text(text: str) -> str | None:
    """Normalize /claim_owner and the current bot-qualified form; reject foreign suffixes."""

    stripped = str(text or "").strip()
    if not stripped.startswith("/"):
        return None
    parts = stripped.split(maxsplit=1)
    token = parts[0]
    code = parts[1].strip() if len(parts) == 2 else ""
    command, separator, suffix = token.partition("@")
    if command.lower() != "/claim_owner" or not code:
        return None
    if separator:
        bot_username = _current_bot_username()
        if bot_username is None or suffix.strip().lower() != bot_username:
            return None
    return f"/claim_owner {code}"


def _owner_bootstrap_claim_update(update: dict[str, Any]) -> bool:
    """Allow only the configured bootstrap owner to submit /claim_owner before owner.json exists."""

    if persisted_owner() is not None:
        return False
    message = update.get("message")
    if not isinstance(message, dict):
        return False
    actor = message.get("from")
    chat = message.get("chat")
    if not isinstance(actor, dict) or not isinstance(chat, dict):
        return False
    actor_id = actor.get("id")
    chat_id = chat.get("id")
    if type(actor_id) is not int or type(chat_id) is not int or actor_id <= 0 or chat_id == 0:
        return False
    if _normalize_owner_claim_text(str(message.get("text") or "")) is None:
        return False
    expected = expected_bootstrap_owner()
    if expected is None:
        return False
    expected_user_id, expected_chat_id = expected
    return actor_id == expected_user_id and (expected_chat_id is None or chat_id == expected_chat_id)


def _approved_telegram_user_id(update: dict[str, Any]) -> str | None:
    """Resolve a Telegram actor to an active canonical user, fail closed."""

    telegram_user_id = _telegram_update_user_id(update)
    if telegram_user_id is None:
        return None
    try:
        binding = get_telegram_identity_binding(telegram_user_id)
    except (RuntimeError, TypeError, ValueError):
        return None
    if binding is None:
        return None

    db = SessionLocal()
    try:
        canonical_user = db.scalar(select(User).where(User.id == binding.canonical_user_id))
        if canonical_user is None or not canonical_user.is_active:
            return None
        return str(canonical_user.id)
    finally:
        db.close()


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
        message = update.get("message")
        if isinstance(message, dict):
            normalized_claim = _normalize_owner_claim_text(str(message.get("text") or ""))
            if normalized_claim is not None:
                message = {**message, "text": normalized_claim}
            handle_message(message)
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
