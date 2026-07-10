"""SharipovAI Telegram bot: direct AI chat, commands and optional Mini App."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import httpx

API_TIMEOUT = 25.0
SUBSCRIBERS_FILE = Path(os.getenv("TELEGRAM_SUBSCRIBERS_FILE", "data/telegram_subscribers.json"))
STATE_FILE = Path(os.getenv("TELEGRAM_STATE_FILE", "data/telegram_state.json"))


def bot_token() -> str:
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("BOT_TOKEN is not set in Render Environment Variables")
    return token


def webapp_url() -> str:
    return os.getenv("WEBAPP_URL", "").strip().rstrip("/")


def base_url() -> str:
    return f"https://api.telegram.org/bot{bot_token()}"


def telegram(method: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    with httpx.Client(timeout=API_TIMEOUT) as client:
        response = client.post(f"{base_url()}/{method}", json=payload or {})
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, dict) else {"ok": False}


def send_message(chat_id: int, text: str, keyboard: dict[str, Any] | None = None) -> None:
    payload: dict[str, Any] = {"chat_id": int(chat_id), "text": text[:3900], "parse_mode": "HTML", "disable_web_page_preview": True}
    if keyboard:
        payload["reply_markup"] = keyboard
    telegram("sendMessage", payload)


def answer_callback(callback_id: str, text: str = "") -> None:
    telegram("answerCallbackQuery", {"callback_query_id": callback_id, "text": text})


def main_keyboard() -> dict[str, Any]:
    rows: list[list[dict[str, Any]]] = []
    if webapp_url():
        rows.append([{"text": "🚀 Открыть Mini App", "web_app": {"url": webapp_url()}}])
    rows.extend([
        [{"text": "🏠 Обзор", "callback_data": "overview"}, {"text": "💼 Портфель", "callback_data": "portfolio"}],
        [{"text": "⚠️ Риск", "callback_data": "risk"}, {"text": "🤖 AI чат", "callback_data": "ai_chat"}],
        [{"text": "🧠 Генеральный ИИ", "callback_data": "general"}, {"text": "📒 Сделки", "callback_data": "deals"}],
        [{"text": "📰 Новости", "callback_data": "news"}, {"text": "🎯 Отчёт дня", "callback_data": "daily"}],
    ])
    return {"inline_keyboard": rows}


def setup_bot_commands() -> None:
    commands = [
        {"command":"start","description":"Главное меню SharipovAI"},
        {"command":"ai","description":"AI чат прямо в Telegram"},
        {"command":"general","description":"Генеральный ИИ"},
        {"command":"portfolio","description":"Портфель и баланс"},
        {"command":"risk","description":"Риск"},
        {"command":"deals","description":"Сделки"},
        {"command":"news","description":"Новости"},
        {"command":"daily","description":"Дневной отчёт"},
        {"command":"notify_on","description":"Включить уведомления"},
        {"command":"notify_off","description":"Выключить уведомления"},
    ]
    telegram("setMyCommands", {"commands": commands})


def _read(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else default
        return data if isinstance(data, dict) else default
    except Exception:
        return default


def _write(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def set_mode(chat_id: int, mode: str) -> None:
    state = _read(STATE_FILE, {"modes": {}})
    state.setdefault("modes", {})[str(chat_id)] = mode
    _write(STATE_FILE, state)


def get_mode(chat_id: int) -> str:
    return str(_read(STATE_FILE, {"modes": {}}).get("modes", {}).get(str(chat_id), "ai"))


def subscribe(chat_id: int) -> None:
    data = _read(SUBSCRIBERS_FILE, {"chat_ids": []})
    ids = {int(x) for x in data.get("chat_ids", [])}; ids.add(int(chat_id)); data["chat_ids"] = sorted(ids); _write(SUBSCRIBERS_FILE, data)


def unsubscribe(chat_id: int) -> None:
    data = _read(SUBSCRIBERS_FILE, {"chat_ids": []})
    data["chat_ids"] = [int(x) for x in data.get("chat_ids", []) if int(x) != int(chat_id)]; _write(SUBSCRIBERS_FILE, data)


def start_text() -> str:
    return (
        "👋 <b>Добро пожаловать в SharipovAI</b>\n\n"
        "Теперь можно общаться прямо в Telegram — Mini App не обязателен.\n\n"
        "Напиши вопрос обычным сообщением или используй команды:\n"
        "/general — Генеральный ИИ\n/portfolio — баланс\n/risk — риск\n/deals — сделки\n/news — новости\n/daily — отчёт дня"
    )


def portfolio_text() -> str:
    return "💼 <b>Paper Trading портфель</b>\n\nБаланс: <b>10,000.00 USDT</b>\nРежим: <b>Paper Trading</b>\nОткрытых позиций: 0\nРеальные деньги не используются."


def risk_text() -> str:
    return "⚠️ <b>Риск сейчас: LOW</b>\n\nRisk Engine контролирует лимиты, просадку и блокирует опасные сделки."


def deals_text() -> str:
    return "📒 <b>Сделки</b>\n\nАктивных виртуальных сделок сейчас нет. Комиссии и net PnL учитываются."


def news_text() -> str:
    return "📰 <b>Новости</b>\n\nNews Agent требует 2+ независимых подтверждения перед влиянием новости на сделку."


def daily_text() -> str:
    return "🎯 <b>Дневной отчёт</b>\n\nЦель: +1%\nСтатус: не выполнена безопасно\nПричина: Risk Engine не повышал риск без подтверждения."


def general_text() -> str:
    return "🧠 <b>Генеральный ИИ</b>\n\nКонтролирую Market, News, Risk, Portfolio, Learning и Security Guard. Все критические решения объясняются."


def bot_ai_reply(message: str) -> str:
    text = message.lower().strip()
    if "портфель" in text or "баланс" in text:
        return portfolio_text()
    if "риск" in text:
        return risk_text()
    if "сдел" in text or "куп" in text or "прод" in text:
        return deals_text()
    if "новост" in text:
        return news_text()
    if "генераль" in text or "бот" in text or "агент" in text:
        return general_text()
    if "день" in text or "отч" in text or "цель" in text:
        return daily_text()
    return f"🤖 <b>SharipovAI</b>\n\nЯ понял: «{message}». Могу ответить про портфель, риск, сделки, новости и работу AI-ботов."


def handle_message(message: dict[str, Any]) -> None:
    chat_id = message.get("chat", {}).get("id")
    text = str(message.get("text") or "").strip()
    if not chat_id:
        return
    command = text.split()[0].lower() if text.startswith("/") else ""
    if command == "/start":
        send_message(chat_id, start_text(), main_keyboard())
    elif command == "/general":
        set_mode(int(chat_id), "general"); send_message(chat_id, general_text(), main_keyboard())
    elif command == "/ai":
        set_mode(int(chat_id), "ai"); send_message(chat_id, "🤖 AI чат включён. Пиши прямо сюда.", main_keyboard())
    elif command == "/portfolio": send_message(chat_id, portfolio_text(), main_keyboard())
    elif command == "/risk": send_message(chat_id, risk_text(), main_keyboard())
    elif command == "/deals": send_message(chat_id, deals_text(), main_keyboard())
    elif command == "/news": send_message(chat_id, news_text(), main_keyboard())
    elif command == "/daily": send_message(chat_id, daily_text(), main_keyboard())
    elif command == "/notify_on": subscribe(int(chat_id)); send_message(chat_id, "🔔 Уведомления включены.", main_keyboard())
    elif command == "/notify_off": unsubscribe(int(chat_id)); send_message(chat_id, "🔕 Уведомления выключены.", main_keyboard())
    else: send_message(chat_id, general_text() if get_mode(int(chat_id)) == "general" else bot_ai_reply(text), main_keyboard())


def handle_callback(callback: dict[str, Any]) -> None:
    callback_id = callback.get("id")
    chat_id = (callback.get("message") or {}).get("chat", {}).get("id")
    data = callback.get("data")
    if callback_id: answer_callback(callback_id)
    if not chat_id: return
    mapping = {"overview":start_text,"portfolio":portfolio_text,"risk":risk_text,"ai_chat":lambda:"🤖 AI чат включён. Пиши прямо сюда.","general":general_text,"deals":deals_text,"news":news_text,"daily":daily_text}
    if data == "ai_chat": set_mode(int(chat_id), "ai")
    if data == "general": set_mode(int(chat_id), "general")
    send_message(chat_id, mapping.get(str(data), start_text)(), main_keyboard())


def poll() -> None:
    telegram("deleteWebhook", {"drop_pending_updates": True})
    setup_bot_commands()
    offset = 0
    print("SharipovAI Telegram bot started", flush=True)
    while True:
        try:
            data = telegram("getUpdates", {"timeout": 30, "offset": offset})
            for update in data.get("result", []):
                offset = max(offset, int(update["update_id"]) + 1)
                if "message" in update: handle_message(update["message"])
                if "callback_query" in update: handle_callback(update["callback_query"])
        except Exception as exc:
            print(f"Telegram polling error: {exc}", flush=True)
            time.sleep(5)


if __name__ == "__main__":
    poll()
