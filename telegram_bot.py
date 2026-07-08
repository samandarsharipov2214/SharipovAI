"""Telegram bot for SharipovAI.

This file supports both:
- webhook mode through dashboard.telegram_webhook_api on Render;
- optional local polling when run directly.

The bot does not contain secrets. BOT_TOKEN and WEBAPP_URL must come from Render
environment variables.
"""

from __future__ import annotations

import html
import json
import os
import time
from pathlib import Path
from typing import Any

import httpx

from ai_chat_orchestrator import answer_chat
from ai_evidence import system_scoreboard
from learning_engine_v2 import learning_state
from news_monitor.agents import run_news_agents
from system_ai_auditor import audit_system_ai
from trading_intelligence import trade_gate

API_TIMEOUT = 35.0
SUBSCRIBERS_FILE = Path(os.getenv("TELEGRAM_SUBSCRIBERS_FILE", "data/telegram_subscribers.json"))
STATE_FILE = Path(os.getenv("TELEGRAM_STATE_FILE", "data/telegram_state.json"))
NOTIFY_INTERVAL_SECONDS = int(os.getenv("TELEGRAM_NOTIFY_INTERVAL_SECONDS", "3600"))


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
        return data if isinstance(data, dict) else {"ok": False, "raw": data}


def _safe_html(text: str) -> str:
    return html.escape(str(text), quote=False)


def _clip(text: str, limit: int = 3900) -> str:
    text = str(text)
    if len(text) <= limit:
        return text
    return text[: limit - 80] + "\n\n…ответ сокращён. Открой Mini App/страницу отчёта для полного вывода."


def send_message(chat_id: int, text: str, keyboard: dict[str, Any] | None = None) -> None:
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "text": _clip(text),
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if keyboard:
        payload["reply_markup"] = keyboard
    telegram("sendMessage", payload)


def answer_callback(callback_id: str, text: str = "") -> None:
    telegram("answerCallbackQuery", {"callback_query_id": callback_id, "text": text})


def main_keyboard() -> dict[str, Any]:
    rows: list[list[dict[str, Any]]] = [
        [{"text": "🤖 AI чат", "callback_data": "ai_chat"}, {"text": "📡 Статус", "callback_data": "status"}],
        [{"text": "📰 Новости", "callback_data": "news"}, {"text": "⚠️ Риск", "callback_data": "risk"}],
        [{"text": "🚦 Можно торговать?", "callback_data": "trade"}, {"text": "🤖 Все ИИ", "callback_data": "audit"}],
        [{"text": "📊 AI Scoreboard", "callback_data": "scoreboard"}, {"text": "🧠 Learning", "callback_data": "learning"}],
        [{"text": "💼 Портфель", "callback_data": "portfolio"}, {"text": "🧾 Комиссии", "callback_data": "costs"}],
        [{"text": "🔔 Уведомления", "callback_data": "notifications"}],
    ]
    if webapp_url():
        rows.append([{"text": "🚀 Открыть Mini App", "web_app": {"url": webapp_url()}}])
    return {"inline_keyboard": rows}


def setup_bot_commands() -> None:
    commands = [
        {"command": "start", "description": "Главное меню SharipovAI"},
        {"command": "status", "description": "Проверка Telegram/webhook/AI"},
        {"command": "ai", "description": "AI чат через внутренних ботов"},
        {"command": "news", "description": "Что сегодня произошло"},
        {"command": "risk", "description": "Почему рисковано"},
        {"command": "trade", "description": "Можно ли сейчас торговать"},
        {"command": "audit", "description": "Полный аудит всех ИИ"},
        {"command": "scoreboard", "description": "Кто live/demo/waiting_api"},
        {"command": "learning", "description": "Чему научился ИИ"},
        {"command": "portfolio", "description": "Портфель и PnL"},
        {"command": "costs", "description": "Комиссии и выгодность"},
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


def _demo_state() -> dict[str, Any]:
    return {
        "mode": "DEMO",
        "decision": "WATCH",
        "risk_level": "LOW",
        "equity": 10051.63,
        "cash": 9500.0,
        "pnl": 51.63,
        "net_pnl": 51.63,
        "total_fees": 13.67,
        "commission_drag": 13.67,
        "break_even_price": 67295.4,
        "exchange_status": {"mode": "sandbox"},
        "online_monitoring": {"mode": "sandbox", "live_execution_enabled": False, "real_orders_blocked": True},
        "bybit_costs": {
            "best_trade_venue": {"best": {"product": "spot", "liquidity": "maker", "round_trip_fee": 2.0, "break_even_move_percent": 0.02}},
            "estimated_saving_vs_worst": 18.4,
        },
        "trades": [
            {"asset": "BTC/USDT", "side": "BUY", "status": "OPEN", "net_pnl": 44.28},
            {"asset": "SOL/USDT", "side": "BUY", "status": "OPEN", "net_pnl": 29.1},
            {"asset": "ETH/USDT", "side": "SELL", "status": "CLOSED", "net_pnl": -21.75},
        ],
    }


def start_text() -> str:
    return (
        "👋 <b>SharipovAI Telegram запущен</b>\n\n"
        "Теперь бот должен отвечать не заглушкой, а через внутренних AI-ботов.\n\n"
        "Примеры вопросов:\n"
        "• Что сегодня произошло?\n"
        "• Почему наблюдать?\n"
        "• Можно покупать BTC?\n"
        "• Какие ИИ не работают?\n"
        "• Чему ты научился?\n\n"
        "Команды: /status /news /risk /trade /audit /scoreboard /learning"
    )


def status_text() -> str:
    token_ok = bool(os.getenv("BOT_TOKEN", "").strip())
    url = webapp_url() or "не задан"
    return (
        "📡 <b>Telegram Status</b>\n\n"
        f"BOT_TOKEN: <b>{'настроен' if token_ok else 'НЕ НАСТРОЕН'}</b>\n"
        f"WEBAPP_URL: <b>{_safe_html(url)}</b>\n"
        "Режим: <b>webhook через FastAPI</b>\n"
        "Webhook endpoint: <code>/telegram/webhook</code>\n"
        "AI Chat Orchestrator: <b>подключён</b>\n\n"
        "После финального деплоя открой /api/telegram/set-webhook один раз."
    )


def orchestrated_reply(message: str) -> str:
    answer = answer_chat(message, _demo_state())
    source = answer.get("source_ai", "AI Chat Orchestrator")
    reply = str(answer.get("reply", "SharipovAI пока не смог собрать ответ."))
    return f"<b>{_safe_html(source)}</b>\n\n{_safe_html(reply)}"


def trade_text() -> str:
    gate = trade_gate()
    blockers = gate.get("blockers", []) or []
    warnings = gate.get("warnings", []) or []
    lines = [
        "🚦 <b>Можно ли сейчас торговать?</b>",
        "",
        f"Решение: <b>{_safe_html(str(gate.get('decision', 'UNKNOWN')))}</b>",
        f"DEMO: <b>{'ДА' if gate.get('can_trade_demo') else 'НЕТ'}</b>",
        f"LIVE: <b>{'ДА' if gate.get('can_trade_live') else 'НЕТ'}</b>",
        "",
        _safe_html(str(gate.get("human_answer", ""))),
    ]
    if blockers:
        lines.append("\n<b>Блокеры:</b>")
        lines.extend(f"• {_safe_html(str(item))}" for item in blockers[:5])
    if warnings:
        lines.append("\n<b>Предупреждения:</b>")
        lines.extend(f"• {_safe_html(str(item))}" for item in warnings[:3])
    return "\n".join(lines)


def audit_text() -> str:
    audit = audit_system_ai()
    auditor = audit.get("auditor", {})
    weak = [item for item in audit.get("interviews", []) if item.get("verdict") in {"делает вид", "заглушка", "недоработан", "частично работает"}]
    lines = [
        "🤖 <b>Аудит всех ИИ</b>",
        "",
        _safe_html(str(auditor.get("summary", ""))),
        "",
        f"Работают: <b>{auditor.get('working', 0)} / {auditor.get('total', 0)}</b>",
        f"Proof score: <b>{auditor.get('average_proof_score', 0)}</b>",
    ]
    if weak:
        lines.append("\n<b>Что требует внимания:</b>")
        for item in weak[:8]:
            lines.append(f"• <b>{_safe_html(str(item.get('name', 'AI')))}</b> — {_safe_html(str(item.get('verdict')))}")
    return "\n".join(lines)


def scoreboard_text() -> str:
    news_report = run_news_agents()
    scoreboard = system_scoreboard(list(news_report.get("agents", [])))
    counts = scoreboard.get("counts", {})
    agents = scoreboard.get("agents", [])
    lines = [
        "📊 <b>AI Scoreboard</b>",
        "",
        f"Всего AI: <b>{scoreboard.get('total', 0)}</b>",
        f"Live: <b>{counts.get('live', 0)}</b>",
        f"Demo: <b>{counts.get('demo', 0)}</b>",
        f"Ждут API: <b>{counts.get('waiting_api', 0)}</b>",
        f"Disabled: <b>{counts.get('disabled', 0)}</b>",
        f"Средний proof score: <b>{scoreboard.get('average_proof_score', 0)}</b>",
        "",
        "<b>Главные слабые места:</b>",
    ]
    weak = [item for item in agents if item.get("real_data_status") in {"waiting_api", "disabled"} or int(item.get("proof_score", 0)) < 55]
    for item in weak[:8]:
        lines.append(f"• <b>{_safe_html(str(item.get('name')))}</b> — {_safe_html(str(item.get('honesty_label')))}, proof {item.get('proof_score')}")
    return "\n".join(lines)


def learning_text() -> str:
    state = learning_state()
    lessons = state.get("active_rule_candidates", [])
    lines = [
        "🧠 <b>Learning Engine 2.0</b>",
        "",
        f"Уроков: <b>{state.get('lesson_count', 0)}</b>",
        f"Режим: <b>{_safe_html(str(state.get('mode', 'unknown')))}</b>",
    ]
    if lessons:
        lines.append("\n<b>Активные уроки:</b>")
        for lesson in lessons[:4]:
            lines.append(f"• {_safe_html(str(lesson.get('lesson')))}")
    return "\n".join(lines)


def portfolio_text() -> str:
    state = _demo_state()
    return (
        "💼 <b>Portfolio AI</b>\n\n"
        f"Режим: <b>{state['mode']}</b>\n"
        f"Equity: <b>{state['equity']:.2f} USDT</b>\n"
        f"PnL: <b>{state['net_pnl']:.2f} USDT</b>\n"
        f"Комиссии: <b>{state['total_fees']:.2f} USDT</b>\n"
        "LIVE-ордера заблокированы."
    )


def costs_text() -> str:
    return orchestrated_reply("комиссии и выгодно ли сейчас торговать")


def notification_text() -> str:
    gate = trade_gate()
    return (
        "🔔 <b>SharipovAI уведомление</b>\n\n"
        f"Trade Gate: <b>{_safe_html(str(gate.get('decision', 'UNKNOWN')))}</b>\n"
        f"Demo: <b>{'разрешён' if gate.get('can_trade_demo') else 'запрещён'}</b>\n"
        "LIVE: <b>запрещён</b>\n\n"
        "Для деталей: /trade /status /scoreboard"
    )


def handle_message(message: dict[str, Any]) -> None:
    chat_id = message.get("chat", {}).get("id")
    text = str(message.get("text") or "").strip()
    if not chat_id:
        return
    chat_id = int(chat_id)
    command = text.split()[0].lower() if text.startswith("/") else ""

    if command == "/start":
        set_mode(chat_id, "ai")
        send_message(chat_id, start_text(), main_keyboard())
    elif command == "/help":
        send_message(chat_id, start_text(), main_keyboard())
    elif command == "/status":
        send_message(chat_id, status_text(), main_keyboard())
    elif command == "/ai":
        set_mode(chat_id, "ai")
        send_message(chat_id, "🤖 AI-чат включён. Пиши вопрос: новости, риск, сделка, портфель, комиссии, аудит.", main_keyboard())
    elif command == "/news":
        send_message(chat_id, orchestrated_reply("что сегодня произошло"), main_keyboard())
    elif command == "/risk":
        send_message(chat_id, orchestrated_reply("почему рисковано"), main_keyboard())
    elif command == "/trade":
        send_message(chat_id, trade_text(), main_keyboard())
    elif command == "/audit":
        send_message(chat_id, audit_text(), main_keyboard())
    elif command == "/scoreboard":
        send_message(chat_id, scoreboard_text(), main_keyboard())
    elif command == "/learning":
        send_message(chat_id, learning_text(), main_keyboard())
    elif command == "/portfolio":
        send_message(chat_id, portfolio_text(), main_keyboard())
    elif command == "/costs":
        send_message(chat_id, costs_text(), main_keyboard())
    elif command == "/notify_on":
        subscribe(chat_id)
        send_message(chat_id, "🔔 Уведомления включены.", main_keyboard())
    elif command == "/notify_off":
        unsubscribe(chat_id)
        send_message(chat_id, "🔕 Уведомления выключены.", main_keyboard())
    else:
        send_message(chat_id, orchestrated_reply(text), main_keyboard())


def handle_callback(callback: dict[str, Any]) -> None:
    callback_id = callback.get("id")
    message = callback.get("message") or {}
    chat_id = message.get("chat", {}).get("id")
    data = str(callback.get("data") or "")
    if callback_id:
        answer_callback(callback_id)
    if not chat_id:
        return
    chat_id = int(chat_id)

    if data == "ai_chat":
        set_mode(chat_id, "ai")
        send_message(chat_id, "🤖 AI-чат включён. Задай вопрос прямо сюда.", main_keyboard())
    elif data == "status":
        send_message(chat_id, status_text(), main_keyboard())
    elif data == "news":
        send_message(chat_id, orchestrated_reply("что сегодня произошло"), main_keyboard())
    elif data == "risk":
        send_message(chat_id, orchestrated_reply("почему рисковано"), main_keyboard())
    elif data == "trade":
        send_message(chat_id, trade_text(), main_keyboard())
    elif data == "audit":
        send_message(chat_id, audit_text(), main_keyboard())
    elif data == "scoreboard":
        send_message(chat_id, scoreboard_text(), main_keyboard())
    elif data == "learning":
        send_message(chat_id, learning_text(), main_keyboard())
    elif data == "portfolio":
        send_message(chat_id, portfolio_text(), main_keyboard())
    elif data == "costs":
        send_message(chat_id, costs_text(), main_keyboard())
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
    print("SharipovAI Telegram polling started")
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
