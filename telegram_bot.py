"""Simple Telegram bot worker for SharipovAI.

Runs with long polling and uses the Telegram Bot HTTP API directly.
No aiogram dependency is required, so Render can build it with the same web dependencies.
"""

from __future__ import annotations

import os
import time
from typing import Any

import httpx

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
WEBAPP_URL = os.getenv("WEBAPP_URL", "").strip()
API_TIMEOUT = 35.0

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set in Render Environment Variables")

BASE_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"


def telegram(method: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    with httpx.Client(timeout=API_TIMEOUT) as client:
        response = client.post(f"{BASE_URL}/{method}", json=payload or {})
        response.raise_for_status()
        return response.json()


def main_keyboard() -> dict[str, Any]:
    rows: list[list[dict[str, Any]]] = []
    if WEBAPP_URL:
        rows.append([{"text": "🚀 Открыть SharipovAI", "web_app": {"url": WEBAPP_URL}}])
    rows.append([
        {"text": "📊 Обзор", "callback_data": "overview"},
        {"text": "🤖 AI чат", "callback_data": "ai_chat"},
    ])
    return {"inline_keyboard": rows}


def send_message(chat_id: int, text: str, keyboard: dict[str, Any] | None = None) -> None:
    payload: dict[str, Any] = {"chat_id": chat_id, "text": text}
    if keyboard:
        payload["reply_markup"] = keyboard
    telegram("sendMessage", payload)


def answer_callback(callback_id: str, text: str = "") -> None:
    telegram("answerCallbackQuery", {"callback_query_id": callback_id, "text": text})


def handle_message(message: dict[str, Any]) -> None:
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    text = str(message.get("text") or "").strip()
    if not chat_id:
        return

    if text.startswith("/start"):
        send_message(
            chat_id,
            "👋 Добро пожаловать в SharipovAI!\n\nЯ AI-помощник для анализа рынка, сделок и контроля риска.",
            main_keyboard(),
        )
    elif text.startswith("/help"):
        send_message(chat_id, "Команды: /start, /help\n\nСайт, Telegram и будущий iOS-клиент работают через один backend.")
    else:
        send_message(chat_id, "Принял. Напиши /start, чтобы открыть меню SharipovAI.", main_keyboard())


def handle_callback(callback: dict[str, Any]) -> None:
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
        send_message(chat_id, "📊 Обзор доступен в SharipovAI Dashboard. Открой кнопку Mini App.", main_keyboard())
    elif data == "ai_chat":
        send_message(chat_id, "🤖 AI чат скоро будет связан с основным backend.", main_keyboard())


def poll() -> None:
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
