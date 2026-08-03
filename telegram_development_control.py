"""Telegram owner approval messages for development changes."""
from __future__ import annotations

import json
import os
from typing import Any
from urllib import parse as urlparse
from urllib import request as urlrequest


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


__all__ = ["send_development_approval"]
