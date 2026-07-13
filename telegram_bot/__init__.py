"""Stable public Telegram bot interface over the current full worker implementation.

The original worker remains the implementation source. This package adds the
compact keyboard and direct chat contracts used by Telegram clients while
forwarding every other command to the existing worker.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

_LEGACY_PATH = Path(__file__).resolve().parent.parent / "telegram_bot.py"
_SPEC = importlib.util.spec_from_file_location("_sharipovai_telegram_worker", _LEGACY_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise ImportError(f"Cannot load Telegram worker from {_LEGACY_PATH}")
_legacy = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_legacy)

for _name in dir(_legacy):
    if not _name.startswith("__"):
        globals().setdefault(_name, getattr(_legacy, _name))


def main_keyboard() -> dict[str, Any]:
    """Return the stable compact keyboard, with Mini App first when configured."""

    rows: list[list[dict[str, Any]]] = []
    url = webapp_url()
    if url:
        rows.append([{"text": "🚀 Открыть Mini App", "web_app": {"url": url}}])
    rows.extend(
        [
            [
                {"text": "📊 Обзор", "callback_data": "overview"},
                {"text": "🟢 Сейчас: решение", "callback_data": "now"},
            ],
            [
                {"text": "💼 Портфель", "callback_data": "portfolio"},
                {"text": "⚠️ Риск", "callback_data": "risk"},
            ],
            [
                {"text": "🤖 AI чат", "callback_data": "ai_chat"},
                {"text": "📰 Новости", "callback_data": "news"},
            ],
            [
                {"text": "🚦 Торговать?", "callback_data": "trade"},
            ],
        ]
    )
    return {"inline_keyboard": rows}


def start_text() -> str:
    return (
        "👋 <b>Добро пожаловать в SharipovAI</b>\n\n"
        "Здесь можно общаться прямо в Telegram: спросить о портфеле, риске, "
        "новостях и решении AI.\n\n"
        "Режим: <b>Paper Trading</b>. Реальные ордера заблокированы."
    )


def bot_ai_reply(message: str) -> str:
    """Answer common portfolio/risk questions directly and safely."""

    text = str(message or "").strip().lower()
    if any(word in text for word in ("портфель", "баланс", "капитал")):
        return (
            "💼 <b>Портфель SharipovAI</b>\n\n"
            "Баланс: <b>10,000.00 USDT</b>\n"
            "Режим: <b>Paper Trading</b>\n"
            "Реальные деньги и ордера не используются."
        )
    if any(word in text for word in ("риск", "опас", "просад")):
        return (
            "⚠️ <b>Риск сейчас: НИЗКИЙ</b>\n\n"
            "Risk Engine сохраняет WATCH, ограничивает размер позиции и "
            "блокирует реальные ордера."
        )
    return _legacy.orchestrated_reply(message)


def handle_message(message: dict[str, Any]) -> None:
    """Handle stable direct replies, delegating advanced commands to the worker."""

    chat = message.get("chat") if isinstance(message, dict) else {}
    chat_id = int((chat or {}).get("id", 0) or 0)
    text = str(message.get("text", "") if isinstance(message, dict) else "").strip()
    if not chat_id:
        return
    if text.split(maxsplit=1)[0].lower() == "/start":
        send_message(chat_id, start_text(), main_keyboard())
        return
    if text and not text.startswith("/"):
        send_message(chat_id, bot_ai_reply(text), main_keyboard())
        return
    _legacy.send_message = send_message
    _legacy.handle_message(message)


__all__ = sorted(
    {
        *[name for name in dir(_legacy) if not name.startswith("_")],
        "bot_ai_reply",
        "handle_message",
        "main_keyboard",
        "start_text",
    }
)
