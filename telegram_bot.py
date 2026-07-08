"""Telegram bot worker for SharipovAI.

The bot works directly in Telegram chat and also opens the Mini App.
It uses long polling and Telegram Bot HTTP API directly.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import httpx

API_TIMEOUT = 35.0
SUBSCRIBERS_FILE = Path(os.getenv("TELEGRAM_SUBSCRIBERS_FILE", "data/telegram_subscribers.json"))
NOTIFY_INTERVAL_SECONDS = int(os.getenv("TELEGRAM_NOTIFY_INTERVAL_SECONDS", "3600"))


def bot_token() -> str:
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("BOT_TOKEN is not set in Render Environment Variables")
    return token


def webapp_url() -> str:
    return os.getenv("WEBAPP_URL", "").strip()


def base_url() -> str:
    return f"https://api.telegram.org/bot{bot_token()}"


def telegram(method: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    with httpx.Client(timeout=API_TIMEOUT) as client:
        response = client.post(f"{base_url()}/{method}", json=payload or {})
        response.raise_for_status()
        return response.json()


def main_keyboard() -> dict[str, Any]:
    rows: list[list[dict[str, Any]]] = []
    url = webapp_url()
    if url:
        rows.append([{"text": "🚀 Открыть Mini App", "web_app": {"url": url}}])
    rows.extend(
        [
            [
                {"text": "💼 Портфель", "callback_data": "portfolio"},
                {"text": "📊 Рынок", "callback_data": "market"},
            ],
            [
                {"text": "⚠️ Риск", "callback_data": "risk"},
                {"text": "📰 Новости", "callback_data": "news"},
            ],
            [
                {"text": "📒 Сделки", "callback_data": "deals"},
                {"text": "🔔 Уведомления", "callback_data": "notifications"},
            ],
        ]
    )
    return {"inline_keyboard": rows}


def send_message(chat_id: int, text: str, keyboard: dict[str, Any] | None = None) -> None:
    payload: dict[str, Any] = {"chat_id": chat_id, "text": text}
    if keyboard:
        payload["reply_markup"] = keyboard
    telegram("sendMessage", payload)


def answer_callback(callback_id: str, text: str = "") -> None:
    telegram("answerCallbackQuery", {"callback_query_id": callback_id, "text": text})


def setup_bot_commands() -> None:
    commands = [
        {"command": "start", "description": "Главное меню SharipovAI"},
        {"command": "portfolio", "description": "Состояние счёта и PnL"},
        {"command": "market", "description": "Краткий анализ рынка"},
        {"command": "risk", "description": "Риск и лимиты"},
        {"command": "deals", "description": "Журнал сделок"},
        {"command": "news", "description": "Новости и источники"},
        {"command": "notify_on", "description": "Включить уведомления"},
        {"command": "notify_off", "description": "Выключить уведомления"},
        {"command": "help", "description": "Как пользоваться ботом"},
    ]
    telegram("setMyCommands", {"commands": commands})


def load_subscribers() -> dict[str, Any]:
    if not SUBSCRIBERS_FILE.exists():
        return {"chat_ids": [], "last_sent": 0}
    try:
        data = json.loads(SUBSCRIBERS_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return {"chat_ids": list(set(data.get("chat_ids", []))), "last_sent": int(data.get("last_sent", 0))}
    except Exception:
        pass
    return {"chat_ids": [], "last_sent": 0}


def save_subscribers(data: dict[str, Any]) -> None:
    SUBSCRIBERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SUBSCRIBERS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def subscribe(chat_id: int) -> None:
    data = load_subscribers()
    chat_ids = set(int(item) for item in data.get("chat_ids", []))
    chat_ids.add(int(chat_id))
    data["chat_ids"] = sorted(chat_ids)
    save_subscribers(data)


def unsubscribe(chat_id: int) -> None:
    data = load_subscribers()
    data["chat_ids"] = [item for item in data.get("chat_ids", []) if int(item) != int(chat_id)]
    save_subscribers(data)


def portfolio_text() -> str:
    return (
        "💼 Состояние демо-счёта SharipovAI\n\n"
        "Баланс: 10,000.00 USDT\n"
        "Кэш: 9,500.00 USDT\n"
        "PnL: 0.00 USDT\n"
        "Открытых позиций: 1\n"
        "Режим: Paper Trading / sandbox\n\n"
        "Реальные деньги не используются."
    )


def market_text() -> str:
    return (
        "📊 Анализ рынка\n\n"
        "Режим AI: WATCH/DEMO\n"
        "BTC: наблюдение\n"
        "SOL: повышенный интерес\n"
        "ETH: без агрессивного входа\n\n"
        "AI не считает сделку хорошей, если прибыль после комиссии отрицательная."
    )


def risk_text() -> str:
    return (
        "⚠️ Риск\n\n"
        "Текущий риск: LOW\n"
        "Риск на сделку: 2%\n"
        "Макс. просадка: 10%\n"
        "Мин. уверенность AI: 78%\n\n"
        "Если риск растёт, AI блокирует BUY и переходит в WATCH."
    )


def deals_text() -> str:
    return (
        "📒 Журнал сделок\n\n"
        "Пока активен демо-режим.\n"
        "Пример: BTC/USDT · WATCH · без реального ордера\n\n"
        "Когда AI откроет demo-сделку, бот сможет прислать уведомление прямо сюда."
    )


def news_text() -> str:
    return (
        "📰 Новости\n\n"
        "AI учитывает новости только после проверки источников.\n"
        "Правило: минимум 2 независимых подтверждения.\n"
        "Соцсети — только ранний сигнал, не причина для сделки."
    )


def notification_text() -> str:
    return (
        "🔔 SharipovAI уведомление\n\n"
        "Счёт: 10,000.00 USDT\n"
        "PnL: 0.00 USDT\n"
        "Риск: LOW\n"
        "Сделки: реальная торговля выключена, demo/sandbox активен.\n\n"
        "Напиши /portfolio, /market, /risk, /deals или /news."
    )


def bot_ai_reply(message: str) -> str:
    text = message.strip().lower()
    if not text:
        return "Напиши вопрос прямо сюда: портфель, рынок, риск, новости, сделки, комиссии или почему AI принял решение."
    if any(word in text for word in ("портфель", "баланс", "сумма", "деньги", "pnl", "позици", "счет", "счёт")):
        return portfolio_text()
    if any(word in text for word in ("рынок", "btc", "битко", "анализ", "куп", "прод")):
        return market_text()
    if any(word in text for word in ("риск", "опас", "просад", "безопас", "лимит")):
        return risk_text()
    if any(word in text for word in ("сделк", "ордер", "trade", "журнал")):
        return deals_text()
    if any(word in text for word in ("новост", "источник", "слух", "довер")):
        return news_text()
    if any(word in text for word in ("комисс", "fee", "доход", "прибыл", "убыт")):
        return "🧾 Комиссии учитываются как расход. AI смотрит net result after fees, а не только рост цены."
    if any(word in text for word in ("почему", "решение", "объясни", "ии", "ai")):
        return "🤖 AI-логика: рынок → новости → риск → комиссии → решение. Сейчас режим безопасный: demo/sandbox."
    return f"Я понял: «{message}».\n\nМожешь писать прямо сюда. Команды: /portfolio, /market, /risk, /deals, /news, /notify_on."


def start_text() -> str:
    return (
        "👋 Добро пожаловать в SharipovAI!\n\n"
        "Теперь со мной можно общаться прямо в Telegram. Mini App — дополнительный экран, не обязательный.\n\n"
        "Команды:\n"
        "/portfolio — счёт и PnL\n"
        "/market — анализ рынка\n"
        "/risk — риск и лимиты\n"
        "/deals — сделки\n"
        "/news — новости\n"
        "/notify_on — включить уведомления\n"
        "/notify_off — выключить уведомления"
    )


def handle_message(message: dict[str, Any]) -> None:
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    text = str(message.get("text") or "").strip()
    if not chat_id:
        return

    command = text.split()[0].lower() if text.startswith("/") else ""
    if command == "/start":
        send_message(chat_id, start_text(), main_keyboard())
    elif command == "/help":
        send_message(chat_id, start_text(), main_keyboard())
    elif command == "/portfolio":
        send_message(chat_id, portfolio_text(), main_keyboard())
    elif command == "/market":
        send_message(chat_id, market_text(), main_keyboard())
    elif command == "/risk":
        send_message(chat_id, risk_text(), main_keyboard())
    elif command == "/deals":
        send_message(chat_id, deals_text(), main_keyboard())
    elif command == "/news":
        send_message(chat_id, news_text(), main_keyboard())
    elif command == "/notify_on":
        subscribe(int(chat_id))
        send_message(chat_id, "🔔 Уведомления включены. Я буду присылать состояние счёта, риск и сделки.", main_keyboard())
    elif command == "/notify_off":
        unsubscribe(int(chat_id))
        send_message(chat_id, "🔕 Уведомления выключены.", main_keyboard())
    else:
        send_message(chat_id, bot_ai_reply(text), main_keyboard())


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
    if data == "portfolio":
        send_message(chat_id, portfolio_text(), main_keyboard())
    elif data == "market" or data == "overview":
        send_message(chat_id, market_text(), main_keyboard())
    elif data == "risk":
        send_message(chat_id, risk_text(), main_keyboard())
    elif data == "news":
        send_message(chat_id, news_text(), main_keyboard())
    elif data == "deals":
        send_message(chat_id, deals_text(), main_keyboard())
    elif data == "notifications":
        subscribe(int(chat_id))
        send_message(chat_id, "🔔 Уведомления включены. Для отключения напиши /notify_off", main_keyboard())
    elif data == "ai_chat":
        send_message(chat_id, "🤖 AI чат работает прямо здесь. Просто напиши сообщение — Mini App открывать не обязательно.", main_keyboard())


def maybe_send_notifications() -> None:
    data = load_subscribers()
    now = int(time.time())
    if now - int(data.get("last_sent", 0)) < NOTIFY_INTERVAL_SECONDS:
        return
    chat_ids = [int(item) for item in data.get("chat_ids", [])]
    if not chat_ids:
        return
    for chat_id in chat_ids:
        try:
            send_message(chat_id, notification_text(), main_keyboard())
        except Exception as exc:
            print(f"Notification error for {chat_id}: {exc}")
    data["last_sent"] = now
    save_subscribers(data)


def poll() -> None:
    telegram("deleteWebhook", {"drop_pending_updates": True})
    setup_bot_commands()
    offset = 0
    print("SharipovAI Telegram bot worker started")
    while True:
        try:
            maybe_send_notifications()
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
