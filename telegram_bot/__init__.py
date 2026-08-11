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
                {"text": "💼 Портфель", "callback_data": "portfolio"},
            ],
            [
                {"text": "⚠️ Риск", "callback_data": "risk"},
                {"text": "🤖 AI чат", "callback_data": "ai_chat"},
            ],
            [
                {"text": "📰 Новости", "callback_data": "news"},
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
    """Do not fabricate state through the retired compatibility package."""

    del message
    return (
        "⚠️ <b>Этот Telegram compatibility-вход отключён.</b>\n\n"
        "Он не является источником состояния SharipovAI и не показывает "
        "demo-баланс, риск или решение. Используйте защищённый webhook/Mini App, "
        "которые читают canonical autonomous-paper runtime."
    )


def handle_message(message: dict[str, Any]) -> None:
    """Reject the legacy update handler without serving a second reality."""

    chat = message.get("chat") if isinstance(message, dict) else {}
    chat_id = int((chat or {}).get("id", 0) or 0)
    text = str(message.get("text", "") if isinstance(message, dict) else "").strip()
    if not chat_id:
        return
    send_message(chat_id, bot_ai_reply(text), main_keyboard())


__all__ = sorted(
    {
        *[name for name in dir(_legacy) if not name.startswith("_")],
        "bot_ai_reply",
        "handle_message",
        "main_keyboard",
        "start_text",
    }
)
