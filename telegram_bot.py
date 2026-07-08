"""Simple Telegram bot worker for SharipovAI.

Runs with long polling and uses the Telegram Bot HTTP API directly.
No aiogram dependency is required, so Render can build it with the same web dependencies.
"""

from __future__ import annotations

import os
import time
from typing import Any

import httpx

API_TIMEOUT = 35.0


def bot_token() -> str:
    """Return the Telegram bot token from environment variables.

    The token is validated at runtime instead of import time so tests and tooling
    can safely import this module without a real secret.
    """

    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("BOT_TOKEN is not set in Render Environment Variables")
    return token


def webapp_url() -> str:
    """Return the configured Mini App URL, if available."""

    return os.getenv("WEBAPP_URL", "").strip()


def base_url() -> str:
    """Return the Telegram Bot API base URL."""

    return f"https://api.telegram.org/bot{bot_token()}"


def telegram(method: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Call a Telegram Bot API method."""

    with httpx.Client(timeout=API_TIMEOUT) as client:
        response = client.post(f"{base_url()}/{method}", json=payload or {})
        response.raise_for_status()
        return response.json()


def main_keyboard() -> dict[str, Any]:
    """Build the main inline keyboard."""

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
                {"text": "🤖 AI чат тут", "callback_data": "ai_chat"},
            ],
        ]
    )
    return {"inline_keyboard": rows}


def send_message(chat_id: int, text: str, keyboard: dict[str, Any] | None = None) -> None:
    """Send a Telegram message."""

    payload: dict[str, Any] = {"chat_id": chat_id, "text": text}
    if keyboard:
        payload["reply_markup"] = keyboard
    telegram("sendMessage", payload)


def answer_callback(callback_id: str, text: str = "") -> None:
    """Acknowledge a Telegram callback query."""

    telegram("answerCallbackQuery", {"callback_query_id": callback_id, "text": text})


def bot_ai_reply(message: str) -> str:
    """Return a useful in-Telegram AI reply without forcing Mini App navigation."""

    text = message.strip().lower()
    if not text:
        return "Напиши вопрос прямо сюда: портфель, рынок, риск, новости, комиссии или почему AI принял решение."
    if any(word in text for word in ("портфель", "баланс", "сумма", "деньги", "pnl", "позици")):
        return (
            "💼 Демо-портфель SharipovAI:\n"
            "Баланс: 10,000.00 USDT\n"
            "Кэш: 9,500.00 USDT\n"
            "PnL: 0.00 USDT\n"
            "Открытых позиций: 1\n\n"
            "Это Paper Trading/sandbox. Реальные деньги не используются."
        )
    if any(word in text for word in ("рынок", "btc", "битко", "анализ", "куп")):
        return (
            "📊 Рыночный режим: WATCH/DEMO.\n"
            "AI смотрит цену, новости, риск, согласие агентов и комиссии. "
            "Покупка не должна считаться прибыльной, пока прибыль после комиссии не положительная."
        )
    if any(word in text for word in ("риск", "опас", "просад", "безопас", "лимит")):
        return (
            "⚠️ Риск сейчас: LOW в демо-режиме.\n"
            "Лимиты: риск на сделку 2%, максимальная просадка 10%. "
            "Если риск растёт, AI блокирует BUY и переходит в WATCH."
        )
    if any(word in text for word in ("комисс", "fee", "доход", "прибыл", "убыт")):
        return (
            "🧾 Комиссии учитываются как расход/убыток.\n"
            "AI считает entry fee + exit fee, gross result и net result after fees. "
            "Если комиссия съедает прибыль, сделка помечается как Do not trade."
        )
    if any(word in text for word in ("новост", "источник", "слух", "довер")):
        return (
            "📰 Новости учитываются только после проверки источников. "
            "Соцсети не используются отдельно: нужен минимум 2 независимых подтверждения."
        )
    if any(word in text for word in ("почему", "решение", "объясни", "ии", "ai")):
        return (
            "🤖 AI-логика: сначала рынок и новости, потом риск, затем комиссии и только после этого решение. "
            "Сейчас режим безопасный: demo/sandbox, реальные ордера заблокированы."
        )
    return (
        f"Я понял: «{message}».\n\n"
        "Можешь писать прямо сюда без Mini App. Спроси: «портфель», «риск», «рынок», "
        "«комиссии», «новости» или «почему решение»."
    )


def handle_message(message: dict[str, Any]) -> None:
    """Handle an incoming Telegram message update."""

    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    text = str(message.get("text") or "").strip()
    if not chat_id:
        return

    if text.startswith("/start"):
        send_message(
            chat_id,
            "👋 Добро пожаловать в SharipovAI!\n\nТеперь со мной можно общаться прямо в Telegram. Mini App — это дополнительный экран, не обязательный.",
            main_keyboard(),
        )
    elif text.startswith("/help"):
        send_message(
            chat_id,
            "Команды: /start, /help\n\nПиши прямо сюда: портфель, рынок, риск, комиссии, новости или почему AI принял решение.",
            main_keyboard(),
        )
    else:
        send_message(chat_id, bot_ai_reply(text), main_keyboard())


def handle_callback(callback: dict[str, Any]) -> None:
    """Handle an incoming Telegram callback query update."""

    callback_id = callback.get("id")
    message = callback.get("message") or {}
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    data = callback.get("data")
    if callback_id:
        answer_callback(callback_id)
    if not chat_id:
        return
    if data == "overview":
        send_message(chat_id, bot_ai_reply("портфель"), main_keyboard())
    elif data == "portfolio":
        send_message(chat_id, bot_ai_reply("портфель баланс pnl"), main_keyboard())
    elif data == "risk":
        send_message(chat_id, bot_ai_reply("риск"), main_keyboard())
    elif data == "ai_chat":
        send_message(chat_id, "🤖 AI чат работает прямо здесь. Напиши мне вопрос сообщением — Mini App открывать не обязательно.", main_keyboard())


def poll() -> None:
    """Run Telegram long polling."""

    telegram("deleteWebhook", {"drop_pending_updates": True})
    offset = 0
    print("SharipovAI Telegram bot worker started")
    while True:
        try:
            data = telegram("getUpdates", {"timeout": 30, "offset": offset})
            for update in data.get("result", []):
                offset = max(offset, int(update["update_id"]) + 1)
                if "message" in update:
                    handle_message(update["message"])
                if "callback_query" in update:
                    handle_callback(update["callback_query"])
        except Exception as exc:
            print(f"Telegram polling error: {exc}")
            time.sleep(5)


if __name__ == "__main__":
    poll()
