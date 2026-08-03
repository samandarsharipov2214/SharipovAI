"""Telegram owner approval messages and callbacks for development changes."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Mapping
from urllib import parse as urlparse
from urllib import request as urlrequest


@dataclass(frozen=True, slots=True)
class DevelopmentCallback:
    action: str
    short_id: str
    token: str = ""


def send_development_approval(decision: Any, *, bot_token: str | None = None, owner_id: str | None = None) -> dict[str, Any]:
    token = (bot_token or os.getenv("BOT_TOKEN", "")).strip()
    chat_id = str(owner_id or os.getenv("TELEGRAM_OWNER_ID", "")).strip()
    if not token or not chat_id:
        raise RuntimeError("BOT_TOKEN and TELEGRAM_OWNER_ID are required")

    payload = decision.to_dict() if hasattr(decision, "to_dict") else dict(decision)
    short_id = str(payload["decision_id"])[:12]
    approval_token = str(payload.get("approval_token", ""))
    proposal = payload.get("proposal", {}) if isinstance(payload.get("proposal"), dict) else {}
    verdict = payload.get("security_verdict", {}) if isinstance(payload.get("security_verdict"), dict) else {}
    files = proposal.get("changed_files") or proposal.get("files") or []
    tests = proposal.get("test_results") or proposal.get("tests") or "не указаны"
    error = proposal.get("error") or proposal.get("failure") or proposal.get("summary") or "не указана"
    reasons = verdict.get("reasons") or []
    verdict_text = "ALLOW" if verdict.get("allowed") is True else "BLOCK"
    text = (
        "🛠 SharipovAI — предложение исправления\n\n"
        f"ID: {short_id}\n"
        f"Ошибка: {error}\n"
        f"Файлы: {', '.join(map(str, files)) if files else 'не указаны'}\n"
        f"Тесты: {tests}\n"
        f"Security Guard: {verdict_text}\n"
        f"Причины: {'; '.join(map(str, reasons)) if reasons else 'нет'}\n\n"
        "Патч не будет применён без вашего решения."
    )[:3900]
    keyboard = {
        "inline_keyboard": [
            [
                {"text": "✅ Применить", "callback_data": f"devfix:a:{short_id}:{approval_token}"},
                {"text": "❌ Отклонить", "callback_data": f"devfix:r:{short_id}:{approval_token}"},
            ],
            [{"text": "ℹ️ Подробнее", "callback_data": f"devfix:i:{short_id}"}],
        ]
    }
    encoded = urlparse.urlencode({
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": "true",
        "reply_markup": json.dumps(keyboard, ensure_ascii=False, separators=(",", ":")),
    }).encode("utf-8")
    request = urlrequest.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=encoded, method="POST")
    with urlrequest.urlopen(request, timeout=15) as response:
        result = json.loads(response.read().decode("utf-8"))
    if not isinstance(result, dict) or result.get("ok") is not True:
        raise RuntimeError(f"Telegram rejected approval message: {result!r}")
    return result


def parse_development_callback(data: str) -> DevelopmentCallback:
    parts = str(data).split(":")
    if len(parts) == 3 and parts[0] == "devfix" and parts[1] == "i":
        return DevelopmentCallback("info", _short_id(parts[2]))
    if len(parts) == 4 and parts[0] == "devfix" and parts[1] in {"a", "r"}:
        token = parts[3].strip()
        if not token or len(token) > 64:
            raise ValueError("invalid development callback token")
        return DevelopmentCallback("approve" if parts[1] == "a" else "reject", _short_id(parts[2]), token)
    raise ValueError("unsupported development callback")


def handle_development_callback(callback_query: Mapping[str, Any], *, controller: Any | None = None) -> dict[str, Any]:
    """Validate and execute one Telegram inline callback.

    The existing bot can call this from its callback dispatcher. The function
    does not apply a patch; an approval only changes the persisted decision to
    ``owner_approved``. Host application remains a separate queued operation.
    """
    from development_control.general_controller import DevelopmentChangeController

    query = dict(callback_query)
    callback = parse_development_callback(str(query.get("data", "")))
    actor_id = str((query.get("from") or {}).get("id", ""))
    message = query.get("message") or {}
    chat_id = str((message.get("chat") or {}).get("id", ""))
    active_controller = controller or DevelopmentChangeController()

    if callback.action == "info":
        decision = active_controller.get(callback.short_id)
        return {"status": "info", "decision": decision.to_dict()}

    approved = callback.action == "approve"
    decision = active_controller.decide(
        callback.short_id,
        approved,
        actor_id,
        chat_id,
        callback.token,
        "telegram_inline_approve" if approved else "telegram_inline_reject",
    )
    return {"status": decision.status, "decision": decision.to_dict()}


def _short_id(value: str) -> str:
    clean = str(value).strip().lower()
    if len(clean) != 12 or any(character not in "0123456789abcdef" for character in clean):
        raise ValueError("invalid development decision short id")
    return clean


__all__ = [
    "DevelopmentCallback",
    "handle_development_callback",
    "parse_development_callback",
    "send_development_approval",
]
