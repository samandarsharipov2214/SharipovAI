"""Telegram adapter backed by the same services and state as the SharipovAI website.

The webhook imports this module, so Telegram, Mini App and the website share:
- dashboard.demo_api persistent paper state;
- ai_chat_orchestrator routing;
- Bot Communication Network timelines;
- Trade Gate, Risk, News, Learning and Auditor data.
"""
from __future__ import annotations

import html
import os
from typing import Any, Callable

import httpx

from ai_chat_orchestrator import answer_chat
from dashboard.demo_api import _load as load_shared_state

API_TIMEOUT = 20.0


def _token() -> str:
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("BOT_TOKEN is not configured")
    return token


def _webapp_url() -> str:
    return os.getenv("WEBAPP_URL", "").strip().rstrip("/")


def _telegram(method: str, payload: dict[str, Any]) -> dict[str, Any]:
    with httpx.Client(timeout=API_TIMEOUT) as client:
        response = client.post(f"https://api.telegram.org/bot{_token()}/{method}", json=payload)
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, dict) else {"ok": False}


def send_message(chat_id: int, text: str, keyboard: dict[str, Any] | None = None) -> None:
    payload: dict[str, Any] = {
        "chat_id": int(chat_id),
        "text": str(text)[:4000],
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if keyboard:
        payload["reply_markup"] = keyboard
    _telegram("sendMessage", payload)


def main_keyboard() -> dict[str, Any]:
    rows = [
        [{"text": "🏠 Mission Control", "callback_data": "overview"}, {"text": "🤖 AI-боты", "callback_data": "bots"}],
        [{"text": "⚠️ Risk Center", "callback_data": "risk"}, {"text": "💼 Сделки", "callback_data": "trades"}],
        [{"text": "🧠 Learning", "callback_data": "learning"}, {"text": "📊 Reports", "callback_data": "reports"}],
        [{"text": "🧪 Stress Lab", "callback_data": "stress"}, {"text": "📒 Timeline", "callback_data": "timeline"}],
    ]
    if _webapp_url():
        rows.append([{"text": "🚀 Открыть SharipovAI", "web_app": {"url": _webapp_url()}}])
    return {"inline_keyboard": rows}


def setup_bot_commands() -> None:
    commands = [
        {"command": "start", "description": "Mission Control"},
        {"command": "ai", "description": "Общий AI Copilot"},
        {"command": "bots", "description": "Все AI-боты"},
        {"command": "agent", "description": "Обратиться к отдельному боту"},
        {"command": "timeline", "description": "Журнал действий бота"},
        {"command": "risk", "description": "Risk Center"},
        {"command": "trades", "description": "Сделки и отчёты"},
        {"command": "learning", "description": "Обучение AI"},
        {"command": "reports", "description": "Отчёты"},
        {"command": "stress", "description": "Stress Lab"},
        {"command": "status", "description": "Статус системы"},
    ]
    _telegram("setMyCommands", {"commands": commands})


def _safe(value: Any) -> str:
    return html.escape(str(value), quote=False)


def _reply(question: str) -> str:
    result = answer_chat(question, load_shared_state())
    source = _safe(result.get("source_ai", "SharipovAI"))
    reply = _safe(result.get("reply", "Ответ не сформирован."))
    return f"<b>{source}</b>\n\n{reply}"


def _overview() -> str:
    state = load_shared_state()
    return (
        "🏠 <b>SharipovAI Mission Control</b>\n\n"
        f"Режим: <b>{_safe(state.get('mode', 'PAPER'))}</b>\n"
        f"Equity: <b>{float(state.get('equity', 0)):.2f} USDT</b>\n"
        f"Net PnL: <b>{float(state.get('net_pnl', 0)):.2f} USDT</b>\n"
        f"Комиссии: <b>{float(state.get('total_fees', 0)):.2f} USDT</b>\n"
        f"Открытые позиции: <b>{int(state.get('open_positions', 0))}</b>\n\n"
        "Данные те же, что на сайте и в Mini App."
    )


def _trades() -> str:
    state = load_shared_state()
    trades = list(state.get("trades", []))
    lines = ["💼 <b>Сделки</b>", ""]
    if not trades:
        lines.append("Сделок пока нет.")
    for index, trade in enumerate(trades[-10:], start=max(1, len(trades) - 9)):
        lines.append(
            f"{index}. <b>{_safe(trade.get('symbol', trade.get('asset', 'UNKNOWN')))}</b> "
            f"{_safe(trade.get('side', ''))} · fee {_safe(trade.get('fee', 0))} · "
            f"net PnL {_safe(trade.get('net_pnl', '—'))}"
        )
    lines.append("\nПодробности и графика доступны в том же разделе сайта через кнопку ниже.")
    return "\n".join(lines)


def _status() -> str:
    state = load_shared_state()
    return (
        "📡 <b>Статус интеграции</b>\n\n"
        "Website core: <b>подключён</b>\n"
        "AI Chat Orchestrator: <b>подключён</b>\n"
        "Shared paper state: <b>подключён</b>\n"
        "Bot Communication Network: <b>используется через orchestrator</b>\n"
        f"Exchange mode: <b>{_safe((state.get('exchange_status') or {}).get('mode', 'sandbox'))}</b>\n"
        "LIVE execution: <b>заблокирован</b>"
    )


def handle_message(message: dict[str, Any]) -> None:
    chat_id = message.get("chat", {}).get("id")
    text = str(message.get("text") or "").strip()
    if not chat_id:
        return
    command = text.split()[0].lower() if text.startswith("/") else ""
    if command == "/start":
        answer = _overview()
    elif command == "/status":
        answer = _status()
    elif command == "/bots":
        answer = _reply("проверь всех AI-ботов и покажи кто работает, кто простаивает и кто требует внимания")
    elif command == "/agent":
        question = text.replace("/agent", "", 1).strip() or "General Controller, дай отчёт"
        answer = _reply(question)
    elif command == "/timeline":
        target = text.replace("/timeline", "", 1).strip() or "General Controller"
        answer = _reply(f"{target}, покажи журнал действий и timeline")
    elif command == "/risk":
        answer = _reply("Risk Engine, дай полный отчёт Risk Center")
    elif command == "/trades":
        answer = _trades()
    elif command == "/learning":
        answer = _reply("Learning Engine, покажи ошибки, уроки и новые правила")
    elif command == "/reports":
        answer = _reply("General Controller, дай дневной отчёт по результату, риску, сделкам и ботам")
    elif command == "/stress":
        answer = _reply("Stress Bot, дай отчёт последнего стресс-теста и защитных действий")
    elif command == "/ai":
        answer = "🤖 <b>AI Copilot включён</b>\n\nПиши вопрос напрямую или обращайся к конкретному боту по имени."
    else:
        answer = _reply(text or "покажи текущее состояние системы")
    send_message(int(chat_id), answer, main_keyboard())


def handle_callback(callback: dict[str, Any]) -> None:
    callback_id = callback.get("id")
    chat_id = (callback.get("message") or {}).get("chat", {}).get("id")
    data = str(callback.get("data") or "")
    if callback_id:
        try:
            _telegram("answerCallbackQuery", {"callback_query_id": callback_id})
        except Exception:
            pass
    if not chat_id:
        return
    handlers: dict[str, Callable[[], str]] = {
        "overview": _overview,
        "bots": lambda: _reply("проверь всех AI-ботов"),
        "risk": lambda: _reply("Risk Engine, дай полный отчёт"),
        "trades": _trades,
        "learning": lambda: _reply("Learning Engine, покажи обучение"),
        "reports": lambda: _reply("General Controller, дай дневной отчёт"),
        "stress": lambda: _reply("Stress Bot, покажи последний стресс-тест"),
        "timeline": lambda: _reply("General Controller, покажи журнал действий"),
    }
    send_message(int(chat_id), handlers.get(data, _overview)(), main_keyboard())
