"""Telegram health/self-test helpers for SharipovAI."""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any

TELEGRAM_API_TIMEOUT = 20.0
_LAST_SUCCESSFUL_WEBHOOK_PROBE_AT = 0


def telegram_health() -> dict[str, Any]:
    """Return honest Telegram health without exposing or logging the bot token."""
    global _LAST_SUCCESSFUL_WEBHOOK_PROBE_AT

    token = os.getenv("BOT_TOKEN", "").strip()
    webapp_url = (
        os.getenv("WEBAPP_URL", "").strip()
        or os.getenv("TELEGRAM_WEBAPP_URL", "").strip()
    ).rstrip("/")
    checks: dict[str, Any] = {
        "bot_token_configured": bool(token),
        "webapp_url_configured": bool(webapp_url),
        "webapp_url": webapp_url,
        "webhook_endpoint": "/telegram/webhook",
        "expected_webhook_url": f"{webapp_url}/telegram/webhook" if webapp_url else None,
        "mode": "webhook",
    }
    if not token:
        return _with_verdict(checks, "waiting_env", "BOT_TOKEN не настроен.")

    get_me = _telegram(token, "getMe")
    webhook_info = _telegram(token, "getWebhookInfo")
    checks["telegram_get_me"] = get_me
    checks["webhook_info"] = webhook_info
    bot_ok = bool(get_me.get("ok"))
    webhook_api_ok = bool(webhook_info.get("ok"))
    webhook_result = webhook_info.get("result", {}) if isinstance(webhook_info, dict) else {}
    current_url = str(webhook_result.get("url") or "")
    expected_url = str(checks.get("expected_webhook_url") or "")
    webhook_ok = bool(webhook_api_ok and expected_url and current_url == expected_url)
    last_error = str(webhook_result.get("last_error_message") or "")
    last_error_date = _positive_int_or_zero(webhook_result.get("last_error_date"))
    now = int(time.time())
    last_error_age = max(0, now - last_error_date) if last_error_date else None
    grace_seconds = _bounded_int(
        "TELEGRAM_WEBHOOK_ERROR_MAX_AGE_SECONDS",
        default=300,
        minimum=30,
        maximum=86_400,
    )
    previous_success = _LAST_SUCCESSFUL_WEBHOOK_PROBE_AT
    error_old_by_age = bool(
        last_error_date
        and last_error_age is not None
        and last_error_age > grace_seconds
    )
    error_predates_success = bool(last_error_date and previous_success > last_error_date)
    stale_error = bool(
        last_error
        and last_error_date
        and webhook_ok
        and bot_ok
        and (error_old_by_age or error_predates_success)
    )
    current_error = bool(last_error and not stale_error)
    checks.update(
        {
            "webhook_api_ok": webhook_api_ok,
            "webhook_url_matches": webhook_ok,
            "last_error_date": last_error_date or None,
            "last_error_age_seconds": last_error_age,
            "webhook_error_grace_seconds": grace_seconds,
            "last_error_predates_success": error_predates_success,
            "stale_webhook_error_ignored": stale_error,
            "last_error_is_current": current_error,
            # A matching URL is not yet a successful health probe when Telegram
            # still reports a fresh delivery error.
            "successful_probe_at": previous_success or None,
        }
    )

    if not bot_ok:
        return _with_verdict(checks, "telegram_error", "BOT_TOKEN есть, но Telegram getMe не отвечает успешно.")
    if not webapp_url:
        return _with_verdict(checks, "waiting_env", "WEBAPP_URL не настроен.")
    if not webhook_ok:
        return _with_verdict(checks, "webhook_not_set", "Webhook не установлен на текущий WEBAPP_URL.")
    if current_error:
        return _with_verdict(checks, "webhook_error", f"Telegram сообщает свежую ошибку webhook: {last_error}")

    # Record success only after all current failure conditions have been cleared
    # or the historical error is independently proven stale.
    _LAST_SUCCESSFUL_WEBHOOK_PROBE_AT = now
    checks["successful_probe_at"] = now
    if stale_error:
        checks["historical_last_error_message"] = last_error
    return _with_verdict(checks, "working", "Telegram bot работает через текущий webhook.")


def telegram_health_score(health: dict[str, Any] | None = None) -> int:
    """Return a compact health score for audits."""
    health = health or telegram_health()
    return telegram_health_score_no_recursion(str(health.get("verdict", "unknown")))


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
        "webhook_not_set": "Проверить текущий webhook URL и повторно установить его безопасным операторским действием.",
        "waiting_env": "Проверить BOT_TOKEN и WEBAPP_URL в защищённой runtime-конфигурации.",
        "webhook_error": "Проверить last_error_date и обработку webhook в журнале без вывода токена.",
        "telegram_error": "Проверить BOT_TOKEN без его публикации и убедиться, что токен принадлежит текущему боту.",
    }
    return fixes.get(verdict, "Проверить Telegram health evidence.")


def _telegram(token: str, method: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Call Telegram without third-party request logging that may expose tokens."""
    body = json.dumps(payload or {}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/{method}",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=TELEGRAM_API_TIMEOUT) as response:
            data = json.loads(response.read().decode("utf-8"))
            return data if isinstance(data, dict) else {"ok": False, "raw": data}
    except urllib.error.HTTPError as exc:
        return {"ok": False, "error": f"HTTPError: {exc.code}"}
    except Exception as exc:  # pragma: no cover - external service
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def _positive_int_or_zero(value: Any) -> int:
    try:
        parsed = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return parsed if parsed > 0 else 0


def _bounded_int(name: str, *, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return min(max(value, minimum), maximum)


__all__ = ["telegram_health", "telegram_health_score"]
