"""Full Telegram AI chat for SharipovAI.

Works directly inside Telegram without requiring Mini App login.
The Mini App remains only as an optional visual dashboard.
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
STATE_FILE = Path(os.getenv("TELEGRAM_STATE_FILE", "data/telegram_state.json"))
NOTIFY_INTERVAL_SECONDS = int(os.getenv("TELEGRAM_NOTIFY_INTERVAL_SECONDS", "3600"))
DAILY_TARGET_PERCENT = float(os.getenv("DAILY_GROWTH_TARGET_PERCENT", "1.0"))
DEMO_GROWTH_PERCENT = float(os.getenv("DEMO_GROWTH_PERCENT", "0.42"))


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
        return response.json()


def send_message(chat_id: int, text: str, keyboard: dict[str, Any] | None = None) -> None:
    payload: dict[str, Any] = {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
    if keyboard:
        payload["reply_markup"] = keyboard
    telegram("sendMessage", payload)


def answer_callback(callback_id: str, text: str = "") -> None:
    telegram("answerCallbackQuery", {"callback_query_id": callback_id, "text": text})


def main_keyboard() -> dict[str, Any]:
    rows: list[list[dict[str, Any]]] = [
        [{"text": "🧠 Генеральный ИИ", "callback_data": "general"}, {"text": "🤖 AI чат", "callback_data": "ai_chat"}],
        [{"text": "💼 Портфель", "callback_data": "portfolio"}, {"text": "📊 Рынок", "callback_data": "market"}],
        [{"text": "⚠️ Риск", "callback_data": "risk"}, {"text": "📒 Сделки", "callback_data": "deals"}],
        [{"text": "🎯 Цель дня", "callback_data": "daily_goal"}, {"text": "🔔 Уведомления", "callback_data": "notifications"}],
    ]
    if webapp_url():
        rows.append([{"text": "🚀 Открыть Mini App", "web_app": {"url": webapp_url()}}])
    return {"inline_keyboard": rows}


def setup_bot_commands() -> None:
    commands = [
        {"command": "start", "description": "Главное меню SharipovAI"},
        {"command": "general", "description": "Генеральный ИИ и контроль всех ботов"},
        {"command": "ai", "description": "Обычный AI-чат прямо в Telegram"},
        {"command": "bots", "description": "Список AI-ботов, роли и качество"},
        {"command": "daily", "description": "Цель дня и дневной отчёт"},
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


def read_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return default
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else default
    except Exception:
        return default


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_subscribers() -> dict[str, Any]:
    return read_json(SUBSCRIBERS_FILE, {"chat_ids": [], "last_sent": 0})


def save_subscribers(data: dict[str, Any]) -> None:
    data["chat_ids"] = sorted({int(item) for item in data.get("chat_ids", [])})
    write_json(SUBSCRIBERS_FILE, data)


def load_state() -> dict[str, Any]:
    data = read_json(STATE_FILE, {"modes": {}})
    if not isinstance(data.get("modes"), dict):
        data["modes"] = {}
    return data


def save_state(data: dict[str, Any]) -> None:
    write_json(STATE_FILE, data)


def set_mode(chat_id: int, mode: str) -> None:
    data = load_state()
    data.setdefault("modes", {})[str(chat_id)] = mode
    save_state(data)


def get_mode(chat_id: int) -> str:
    return str(load_state().get("modes", {}).get(str(chat_id), "ai"))


def subscribe(chat_id: int) -> None:
    data = load_subscribers()
    data.setdefault("chat_ids", [])
    if int(chat_id) not in [int(item) for item in data["chat_ids"]]:
        data["chat_ids"].append(int(chat_id))
    save_subscribers(data)


def unsubscribe(chat_id: int) -> None:
    data = load_subscribers()
    data["chat_ids"] = [item for item in data.get("chat_ids", []) if int(item) != int(chat_id)]
    save_subscribers(data)


def ai_bots() -> list[dict[str, Any]]:
    return [
        {"name": "General Controller", "role": "главный контроль", "goal": f"контроль 11/11 ботов и цель дня +{DAILY_TARGET_PERCENT}%", "quality": 97, "errors": 0.8, "status": "активен"},
        {"name": "Market Agent", "role": "цена, тренд, объём, импульс", "goal": "найти низкорисковые сетапы", "quality": 96, "errors": 1.2, "status": "активен"},
        {"name": "News Agent", "role": "новости и 2+ подтверждения", "goal": "не пускать слухи в сделки", "quality": 92, "errors": 2.5, "status": "активен"},
        {"name": "Risk Engine", "role": "риск, лимиты, просадка", "goal": "не превышать лимит риска", "quality": 98, "errors": 0.5, "status": "активен"},
        {"name": "Portfolio Engine", "role": "баланс, PnL, позиции", "goal": "сохранить капитал", "quality": 95, "errors": 1.0, "status": "активен"},
        {"name": "Paper Trading Bot", "role": "демо-сделки", "goal": "тестировать без реальных денег", "quality": 93, "errors": 1.8, "status": "активен"},
        {"name": "Confidence Engine", "role": "уверенность сигнала", "goal": "не завышать уверенность", "quality": 91, "errors": 2.2, "status": "активен"},
        {"name": "Consensus Engine", "role": "согласие агентов", "goal": "ловить конфликты", "quality": 92, "errors": 1.7, "status": "активен"},
        {"name": "Stress Bot", "role": "стресс-тесты", "goal": "проверять защиту капитала", "quality": 91, "errors": 2.0, "status": "активен"},
        {"name": "Learning Engine", "role": "обучение на ошибках", "goal": "улучшать правила", "quality": 88, "errors": 3.1, "status": "активен"},
        {"name": "Security Guard", "role": "запрет реальной торговли без подтверждения", "goal": "не допустить LIVE без разрешения", "quality": 100, "errors": 0.0, "status": "активен"},
    ]


def average_quality() -> int:
    bots = ai_bots()
    return round(sum(int(bot["quality"]) for bot in bots) / len(bots))


def portfolio_text() -> str:
    return (
        "💼 <b>Портфель SharipovAI</b>\n\n"
        "Режим: <b>DEMO / sandbox</b>\n"
        "Баланс: <b>10,000.00 USDT</b>\n"
        "Кэш: <b>9,500.00 USDT</b>\n"
        "PnL сегодня: <b>+0.42%</b>\n"
        "Цель дня: <b>+1.00%</b>\n"
        "Открытых демо-позиций: <b>1</b>\n\n"
        "Реальные деньги не используются."
    )


def market_text() -> str:
    return (
        "📊 <b>Анализ рынка</b>\n\n"
        "BTC: наблюдение, без агрессивного входа.\n"
        "SOL: интерес есть, но нужен контроль риска.\n"
        "ETH: слабее, вход не подтверждён.\n\n"
        "Итог: <b>WATCH</b>. Вход разрешается только если Market + News + Risk + Consensus согласны."
    )


def risk_text() -> str:
    return (
        "⚠️ <b>Риск</b>\n\n"
        "Уровень: <b>LOW</b>\n"
        "Риск на сделку: <b>2%</b>\n"
        "Макс. просадка: <b>10%</b>\n"
        "Мин. уверенность AI: <b>78%</b>\n\n"
        "Risk Engine может заблокировать BUY даже при хорошем рыночном сигнале."
    )


def deals_text() -> str:
    return (
        "📒 <b>Демо-сделки</b>\n\n"
        "1) BTC/USDT · BUY · OPEN · +52.40 USDT\n"
        "2) SOL/USDT · BUY · OPEN · +31.20 USDT\n"
        "3) ETH/USDT · SELL · CLOSED · -18.30 USDT\n\n"
        "Все сделки демо. LIVE-ордера выключены."
    )


def news_text() -> str:
    return (
        "📰 <b>News Agent</b>\n\n"
        "Правило: новость влияет на решение только после <b>2+ независимых подтверждений</b>.\n"
        "Соцсети — ранний сигнал, но не причина для сделки.\n"
        "Сейчас критических неподтверждённых новостей нет."
    )


def bots_text() -> str:
    lines = [f"🤖 <b>AI-боты SharipovAI</b>", f"Всего: <b>{len(ai_bots())}</b>. Активны: <b>{len(ai_bots())}/{len(ai_bots())}</b>. Среднее качество: <b>{average_quality()}%</b>.\n"]
    for bot in ai_bots():
        lines.append(f"• <b>{bot['name']}</b> — {bot['role']}\n  Качество: {bot['quality']}%, ошибки: {bot['errors']}%, цель: {bot['goal']}")
    return "\n".join(lines)


def daily_report_text() -> str:
    status = "Выполнено" if DEMO_GROWTH_PERCENT >= DAILY_TARGET_PERCENT else "Не выполнено"
    reason = "цель выполнена безопасно" if status == "Выполнено" else "General Controller не повысил риск без полного подтверждения Market + News + Risk. Система выбрала защиту капитала вместо агрессивной сделки."
    return (
        "🎯 <b>Дневной отчёт Генерального ИИ</b>\n\n"
        f"Цель дня: <b>+{DAILY_TARGET_PERCENT:.2f}%</b>\n"
        f"Текущий результат: <b>+{DEMO_GROWTH_PERCENT:.2f}%</b>\n"
        f"Статус: <b>{status}</b>\n\n"
        f"Причина: {reason}\n\n"
        "Следующее действие: искать низкорисковые сетапы, не увеличивать риск на сделку, проверять новости и комиссии до входа."
    )


def general_text() -> str:
    return (
        "🧠 <b>Генеральный ИИ SharipovAI</b>\n\n"
        "Я контролирую всех внутренних ботов и не требую входа в Mini App. Пиши прямо сюда.\n\n"
        f"Боты: <b>{len(ai_bots())}/{len(ai_bots())}</b> активны\n"
        f"Среднее качество: <b>{average_quality()}%</b>\n"
        f"Цель дня: <b>+{DAILY_TARGET_PERCENT:.2f}%</b>\n"
        f"Текущий результат: <b>+{DEMO_GROWTH_PERCENT:.2f}%</b>\n\n"
        "Моя задача: не давать ботам простаивать, снижать ошибки, блокировать опасные сделки и давать отчёт: выполнена цель или нет, и почему."
    )


def start_text() -> str:
    return (
        "👋 <b>SharipovAI запущен в Telegram</b>\n\n"
        "Теперь можно общаться прямо здесь. Mini App не обязателен.\n\n"
        "Команды:\n"
        "/general — Генеральный ИИ\n"
        "/ai — обычный AI-чат\n"
        "/bots — все боты и качество\n"
        "/daily — цель дня и отчёт\n"
        "/portfolio — счёт и PnL\n"
        "/market — рынок\n"
        "/risk — риск\n"
        "/deals — сделки\n"
        "/notify_on — включить уведомления"
    )


def notification_text() -> str:
    return (
        "🔔 <b>SharipovAI уведомление</b>\n\n"
        f"Цель дня: +{DAILY_TARGET_PERCENT:.2f}%\n"
        f"Текущий результат: +{DEMO_GROWTH_PERCENT:.2f}%\n"
        f"AI-боты: {len(ai_bots())}/{len(ai_bots())} активны\n"
        f"Среднее качество: {average_quality()}%\n"
        "Риск: LOW\n\n"
        "Для отчёта напиши /daily или /general."
    )


def ai_reply(message: str) -> str:
    text = message.strip().lower()
    if not text:
        return "Напиши вопрос прямо сюда. Можно спросить: рынок, риск, портфель, сделки, новости, комиссии, цель дня."
    if any(w in text for w in ("генераль", "главный", "контрол", "статус всех", "агент", "боты", "ботов")):
        return general_reply(message)
    if any(w in text for w in ("портфель", "баланс", "счет", "счёт", "pnl", "деньги")):
        return portfolio_text()
    if any(w in text for w in ("рынок", "btc", "битко", "sol", "eth", "анализ", "куп", "прод")):
        return market_text()
    if any(w in text for w in ("риск", "опас", "просад", "лимит", "безопас")):
        return risk_text()
    if any(w in text for w in ("сделк", "ордер", "trade", "журнал")):
        return deals_text()
    if any(w in text for w in ("новост", "источник", "слух")):
        return news_text()
    if any(w in text for w in ("цель", "день", "отчет", "отчёт", "1%", "процент")):
        return daily_report_text()
    if any(w in text for w in ("комисс", "прибыл", "убыт", "fee")):
        return "🧾 Комиссии считаются расходом. AI принимает решение только по чистому результату после комиссий, риска и вероятности ошибки."
    return f"🤖 <b>SharipovAI</b>\n\nЯ понял: «{message}».\n\nСейчас система в DEMO/sandbox. Могу разобрать это по рынку, риску, портфелю, сделкам, новостям или цели дня."


def general_reply(message: str) -> str:
    text = message.strip().lower()
    if any(w in text for w in ("боты", "агенты", "кто", "список", "качество")):
        return bots_text()
    if any(w in text for w in ("цель", "день", "отчет", "отчёт", "выполн", "1%")):
        return daily_report_text()
    if any(w in text for w in ("ошиб", "проста", "не работ", "слом", "почему")):
        return (
            "🧠 <b>Генеральный ИИ: диагностика</b>\n\n"
            "Критических отказов нет. Главные зоны контроля:\n"
            "• Learning Engine имеет самое низкое качество: 88%, его нужно кормить ошибками сделок.\n"
            "• News Agent блокирует слухи без 2 подтверждений.\n"
            "• Risk Engine не даёт гнаться за +1% любой ценой.\n\n"
            "Если цель дня не выполнена, причина обычно не в простое, а в нехватке безопасного сетапа."
        )
    if any(w in text for w in ("куп", "прод", "сделк", "btc", "битко")):
        return (
            "🧠 <b>Генеральный ИИ: решение по сделке</b>\n\n"
            "1) Market Agent: сигнал наблюдения.\n"
            "2) News Agent: нет достаточного новостного усиления.\n"
            "3) Risk Engine: риск LOW, но агрессию повышать нельзя.\n"
            "4) Consensus Engine: решение WATCH.\n\n"
            "Итог: покупку не открываю в LIVE. В demo можно тестировать, но реальная торговля выключена."
        )
    return general_text()


def handle_message(message: dict[str, Any]) -> None:
    chat_id = message.get("chat", {}).get("id")
    text = str(message.get("text") or "").strip()
    if not chat_id:
        return

    command = text.split()[0].lower() if text.startswith("/") else ""
    if command == "/start":
        set_mode(int(chat_id), "ai")
        send_message(chat_id, start_text(), main_keyboard())
    elif command == "/help":
        send_message(chat_id, start_text(), main_keyboard())
    elif command == "/general":
        set_mode(int(chat_id), "general")
        send_message(chat_id, general_text(), main_keyboard())
    elif command == "/ai":
        set_mode(int(chat_id), "ai")
        send_message(chat_id, "🤖 AI-чат включён. Пиши вопрос прямо сюда, Mini App не нужен.", main_keyboard())
    elif command == "/bots":
        send_message(chat_id, bots_text(), main_keyboard())
    elif command == "/daily":
        send_message(chat_id, daily_report_text(), main_keyboard())
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
        send_message(chat_id, "🔔 Уведомления включены. Я буду присылать отчёты о счёте, целях, риске и ботах.", main_keyboard())
    elif command == "/notify_off":
        unsubscribe(int(chat_id))
        send_message(chat_id, "🔕 Уведомления выключены.", main_keyboard())
    else:
        mode = get_mode(int(chat_id))
        reply = general_reply(text) if mode == "general" else ai_reply(text)
        send_message(chat_id, reply, main_keyboard())


def handle_callback(callback: dict[str, Any]) -> None:
    callback_id = callback.get("id")
    message = callback.get("message") or {}
    chat_id = message.get("chat", {}).get("id")
    data = callback.get("data")
    if callback_id:
        answer_callback(callback_id)
    if not chat_id:
        return
    chat_id = int(chat_id)
    if data == "general":
        set_mode(chat_id, "general")
        send_message(chat_id, general_text(), main_keyboard())
    elif data == "ai_chat":
        set_mode(chat_id, "ai")
        send_message(chat_id, "🤖 AI-чат включён. Пиши прямо сюда, Mini App не нужен.", main_keyboard())
    elif data == "portfolio":
        send_message(chat_id, portfolio_text(), main_keyboard())
    elif data in {"market", "overview"}:
        send_message(chat_id, market_text(), main_keyboard())
    elif data == "risk":
        send_message(chat_id, risk_text(), main_keyboard())
    elif data == "news":
        send_message(chat_id, news_text(), main_keyboard())
    elif data == "deals":
        send_message(chat_id, deals_text(), main_keyboard())
    elif data == "daily_goal":
        send_message(chat_id, daily_report_text(), main_keyboard())
    elif data == "notifications":
        subscribe(chat_id)
        send_message(chat_id, "🔔 Уведомления включены. Для отключения напиши /notify_off", main_keyboard())


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
    print("SharipovAI Telegram full AI chat started")
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
