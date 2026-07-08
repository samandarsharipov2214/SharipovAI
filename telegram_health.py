"""Telegram health/self-test helpers for SharipovAI."""

from __future__ import annotations

import os
from typing import Any

import httpx

TELEGRAM_API_TIMEOUT = 20.0


def telegram_health() -> dict[str, Any]:
    """Return honest Telegram bot health without exposing secrets."""

    token = os.getenv("BOT_TOKEN", "").strip()
    webapp_url = os.getenv("WEBAPP_URL", "").strip().rstrip("/")
    checks: dict[str, Any] = {
        "bot_token_configured": bool(token),
        "webapp_url_configured": bool(webapp_url),
        "webapp_url": webapp_url,
        "webhook_endpoint": "/telegram/webhook",
        "expected_webhook_url": f"{webapp_url}/telegram/webhook" if webapp_url else None,
        "mode": "webhook",
    }
    if not token:
        return _with_verdict(checks, "waiting_env", "BOT_TOKEN не настроен в Render Environment Variables.")
    get_me = _telegram(token, "getMe")
    webhook_info = _telegram(token, "getWebhookInfo")
    checks["telegram_get_me"] = get_me
    checks["webhook_info"] = webhook_info
    bot_ok = bool(get_me.get("ok"))
    webhook_result = webhook_info.get("result", {}) if isinstance(webhook_info, dict) else {}
    current_url = str(webhook_result.get("url") or "")
    expected_url = str(checks.get("expected_webhook_url") or "")
    webhook_ok = bool(expected_url and current_url == expected_url)
    last_error = str(webhook_result.get("last_error_message") or "")
    if not bot_ok:
        return _with_verdict(checks, "telegram_error", "BOT_TOKEN есть, но Telegram getMe не отвечает успешно.")
    if not webapp_url:
        return _with_verdict(checks, "waiting_env", "WEBAPP_URL не настроен в Render Environment Variables.")
    if last_error:
        return _with_verdict(checks, "webhook_error", f"Telegram сообщает ошибку webhook: {last_error}")
    if not webhook_ok:
        return _with_verdict(checks, "webhook_not_set", "Webhook ещё не установлен на текущий WEBAPP_URL.")
    return _with_verdict(checks, "working", "Telegram bot работает через webhook.")


def telegram_health_score(health: dict[str, Any] | None = None) -> int:
    """Return a compact health score for audits."""

    health = health or telegram_health()
    verdict = str(health.get("verdict", "unknown"))
    if verdict == "working":
        return 95
    if verdict == "webhook_not_set":
        return 70
    if verdict == "waiting_env":
        return 35
    if verdict == "webhook_error":
        return 45
    if verdict == "telegram_error":
        return 25
    return 20


def _with_verdict(checks: dict[str, Any], verdict: str, explanation: str) -> dict[str, Any]:
    checks["status"] = "ok" if verdict == "working" else "attention"
    checks["verdict"] = verdict
    checks["explanation"] = explanation
    checks["health_score"] = telegram_health_score_no_recursion(verdict)
    checks["next_fix"] = _next_fix(verdict)
    return checks


def telegram_health_score_no_recursion(verdict: str) -> int:
    return {"working": 95, "webhook_not_set": 70, "waiting_env": 35, "webhook_error": 45, "telegram_error": 25}.get(verdict, 20)


def _next_fix(verdict: str) -> str:
    fixes = {
        "working": "Ничего не делать: бот принимает сообщения через webhook.",
        "webhook_not_set": "После деплоя открыть /api/telegram/set-webhook один раз.",
        "waiting_env": "Проверить Render Environment Variables: BOT_TOKEN и WEBAPP_URL.",
        "webhook_error": "Открыть /telegram-check и посмотреть last_error_message от Telegram.",
        "telegram_error": "Проверить BOT_TOKEN в Render ENV и что токен принадлежит текущему боту.",
    }
    return fixes.get(verdict, "Открыть /telegram-check и выполнить checklist.")


def _telegram(token: str, method: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        with httpx.Client(timeout=TELEGRAM_API_TIMEOUT) as client:
            response = client.post(f"https://api.telegram.org/bot{token}/{method}", json=payload or {})
            data = response.json()
            return data if isinstance(data, dict) else {"ok": False, "raw": data}
    except Exception as exc:  # pragma: no cover
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
