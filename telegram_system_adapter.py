"""Telegram adapter backed by the same services and state as the SharipovAI website.

Telegram, Mini App and website share the same orchestrator and paper state.
Every section opens its own contextual controls instead of repeating the main menu.
"""
from __future__ import annotations

import html
import os
from typing import Any
from urllib.parse import urlparse

import httpx

from ai_chat_orchestrator import answer_chat
from dashboard.demo_api import _load as load_shared_state
from telegram_deploy_control import (
    cancel_confirmation,
    claim_owner,
    confirm_deployment,
    deployment_keyboard,
    identity_message,
    prepare_confirmation,
    status_message,
)

API_TIMEOUT = 20.0
CANONICAL_WEBAPP_URL = "https://85-137-88-17.sslip.io"


def _token() -> str:
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("BOT_TOKEN is not configured")
    return token


def _webapp_url() -> str:
    configured = os.getenv("WEBAPP_URL", "").strip().rstrip("/")
    if not configured:
        return CANONICAL_WEBAPP_URL
    try:
        host = (urlparse(configured).hostname or "").lower()
    except ValueError:
        host = ""
    if configured != CANONICAL_WEBAPP_URL or host.endswith(".onrender.com") or host == "render.com":
        return CANONICAL_WEBAPP_URL
    return configured


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


def _webapp_button() -> list[dict[str, Any]]:
    return [{"text": "🚀 Открыть SharipovAI", "web_app": {"url": _webapp_url()}}]


def main_keyboard(actor_id: int | None = None, chat_id: int | None = None) -> dict[str, Any]:
    rows = [
        [{"text": "🏠 Mission Control", "callback_data": "overview"}, {"text": "🤖 AI-боты", "callback_data": "bots"}],
        [{"text": "⚠️ Risk Center", "callback_data": "risk"}, {"text": "💼 Сделки", "callback_data": "trades"}],
        [{"text": "🧠 Learning", "callback_data": "learning"}, {"text": "📊 Reports", "callback_data": "reports"}],
        [{"text": "🧪 Stress Lab", "callback_data": "stress"}, {"text": "📒 Timeline", "callback_data": "timeline"}],
    ]
    rows.extend(deployment_keyboard(actor_id, chat_id))
    rows.append(_webapp_button())
    return {"inline_keyboard": rows}


def _back_keyboard(extra: list[list[dict[str, Any]]] | None = None, actor_id: int | None = None, chat_id: int | None = None) -> dict[str, Any]:
    rows = list(extra or [])
    rows.append([{"text": "⬅️ Главное меню", "callback_data": "menu"}])
    rows.extend(deployment_keyboard(actor_id, chat_id))
    rows.append(_webapp_button())
    return {"inline_keyboard": rows}


def stress_keyboard(actor_id: int | None = None, chat_id: int | None = None) -> dict[str, Any]:
    return _back_keyboard([
        [{"text": "📉 BTC −10%", "callback_data": "stress:btc10"}, {"text": "📉 BTC −20%", "callback_data": "stress:btc20"}],
        [{"text": "💥 Market −50%", "callback_data": "stress:market50"}, {"text": "📰 News Panic", "callback_data": "stress:news"}],
        [{"text": "🏦 Биржа недоступна", "callback_data": "stress:exchange"}, {"text": "🌐 Интернет пропал", "callback_data": "stress:network"}],
        [{"text": "🦢 Black Swan", "callback_data": "stress:black_swan"}, {"text": "📋 Последний результат", "callback_data": "stress:last"}],
    ], actor_id, chat_id)


def bots_keyboard(actor_id: int | None = None, chat_id: int | None = None) -> dict[str, Any]:
    return _back_keyboard([
        [{"text": "🧭 General Controller", "callback_data": "agent:general"}],
        [{"text": "📈 Market Agent", "callback_data": "agent:market"}, {"text": "📰 News Agent", "callback_data": "agent:news"}],
        [{"text": "🛡 Risk Engine", "callback_data": "agent:risk"}, {"text": "💼 Portfolio Engine", "callback_data": "agent:portfolio"}],
        [{"text": "🧠 Learning Engine", "callback_data": "agent:learning"}, {"text": "🧪 Stress Bot", "callback_data": "agent:stress"}],
        [{"text": "🔐 Security Guard", "callback_data": "agent:security"}, {"text": "✅ Проверить всех", "callback_data": "bots:check"}],
    ], actor_id, chat_id)


def risk_keyboard(actor_id: int | None = None, chat_id: int | None = None) -> dict[str, Any]:
    return _back_keyboard([
        [{"text": "🟢 Консервативный", "callback_data": "risk:safe"}, {"text": "🟡 Умеренный", "callback_data": "risk:normal"}],
        [{"text": "🔴 Агрессивный", "callback_data": "risk:pro"}, {"text": "🛑 Emergency Stop", "callback_data": "risk:stop"}],
        [{"text": "📋 Полный отчёт", "callback_data": "risk:report"}, {"text": "✅ Тест адекватности", "callback_data": "risk:check"}],
    ], actor_id, chat_id)


def learning_keyboard(actor_id: int | None = None, chat_id: int | None = None) -> dict[str, Any]:
    return _back_keyboard([
        [{"text": "❌ Последние ошибки", "callback_data": "learning:errors"}, {"text": "✅ Исправленные ошибки", "callback_data": "learning:fixed"}],
        [{"text": "🧩 Новые правила", "callback_data": "learning:rules"}, {"text": "🔁 Повторяющиеся ошибки", "callback_data": "learning:repeated"}],
        [{"text": "🧪 Проверить Learning", "callback_data": "learning:check"}],
    ], actor_id, chat_id)


def reports_keyboard(actor_id: int | None = None, chat_id: int | None = None) -> dict[str, Any]:
    return _back_keyboard([
        [{"text": "📅 Сегодня", "callback_data": "reports:day"}, {"text": "📆 Неделя", "callback_data": "reports:week"}],
        [{"text": "🗓 Месяц", "callback_data": "reports:month"}, {"text": "🤖 По ботам", "callback_data": "reports:bots"}],
        [{"text": "💸 Комиссии", "callback_data": "reports:fees"}, {"text": "📉 Просадка", "callback_data": "reports:drawdown"}],
    ], actor_id, chat_id)


def timeline_keyboard(actor_id: int | None = None, chat_id: int | None = None) -> dict[str, Any]:
    return _back_keyboard([
        [{"text": "🧭 General Controller", "callback_data": "timeline:general"}],
        [{"text": "📈 Market", "callback_data": "timeline:market"}, {"text": "📰 News", "callback_data": "timeline:news"}],
        [{"text": "🛡 Risk", "callback_data": "timeline:risk"}, {"text": "🧠 Learning", "callback_data": "timeline:learning"}],
        [{"text": "🧪 Stress", "callback_data": "timeline:stress"}, {"text": "🔐 Security", "callback_data": "timeline:security"}],
    ], actor_id, chat_id)


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
        {"command": "deploy", "description": "Обновить SharipovAI"},
        {"command": "deploy_status", "description": "Статус обновления"},
        {"command": "whoami", "description": "Показать Telegram ID"},
        {"command": "claim_owner", "description": "Активировать телефон владельца"},
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
        "Выбери раздел ниже. Mini App открывает основной VPS SharipovAI."
    )


def _trades() -> str:
    state = load_shared_state()
    trades = list(state.get("trades", []))
    lines = ["💼 <b>Сделки</b>", ""]
    if not trades:
        lines.append("Сделок пока нет.")
    for index, trade in enumerate(trades[-10:], start=max(1, len(trades) - 9)):
        lines.append(f"{index}. <b>{_safe(trade.get('symbol', trade.get('asset', 'UNKNOWN')))}</b> {_safe(trade.get('side', ''))} · fee {_safe(trade.get('fee', 0))} · net PnL {_safe(trade.get('net_pnl', '—'))}")
    lines.append("\nПолные карточки сделок и графика доступны в Mini App.")
    return "\n".join(lines)


def _status() -> str:
    state = load_shared_state()
    return (
        "📡 <b>Статус интеграции</b>\n\n"
        "Website core: <b>подключён</b>\nAI Chat Orchestrator: <b>подключён</b>\n"
        "Shared paper state: <b>подключён</b>\nBot Communication Network: <b>подключён</b>\n"
        f"Mini App: <b>{_safe(_webapp_url())}</b>\n"
        f"Exchange mode: <b>{_safe((state.get('exchange_status') or {}).get('mode', 'sandbox'))}</b>\n"
        "LIVE execution: <b>заблокирован</b>"
    )


def _section_intro(section: str, actor_id: int | None = None, chat_id: int | None = None) -> tuple[str, dict[str, Any]]:
    mapping: dict[str, tuple[str, dict[str, Any]]] = {
        "bots": ("🤖 <b>AI Agent Control</b>\n\nВыбери конкретного бота, запроси его состояние или проверь всех.", bots_keyboard(actor_id, chat_id)),
        "risk": ("⚠️ <b>Risk Center</b>\n\nВыбери профиль, запроси отчёт, проверь Risk Engine или используй Emergency Stop.", risk_keyboard(actor_id, chat_id)),
        "learning": ("🧠 <b>Learning Engine</b>\n\nПосмотри найденные ошибки, исправления, новые правила и повторяющиеся проблемы.", learning_keyboard(actor_id, chat_id)),
        "reports": ("📊 <b>Reports</b>\n\nВыбери период или отдельный вид аналитики.", reports_keyboard(actor_id, chat_id)),
        "stress": ("🧪 <b>Stress Lab</b>\n\nВыбери кризисный сценарий. Stress Bot смоделирует реакцию системы без реальных ордеров.", stress_keyboard(actor_id, chat_id)),
        "timeline": ("📒 <b>Decision Timeline</b>\n\nВыбери бота и посмотри его действия по времени.", timeline_keyboard(actor_id, chat_id)),
    }
    return mapping[section]


def handle_message(message: dict[str, Any]) -> None:
    chat_id = message.get("chat", {}).get("id")
    actor_id = message.get("from", {}).get("id")
    text = str(message.get("text") or "").strip()
    if not chat_id:
        return
    command = text.split()[0].lower() if text.startswith("/") else ""
    keyboard = main_keyboard(actor_id, chat_id)
    if command == "/start":
        answer = _overview()
    elif command == "/status":
        answer = _status()
    elif command == "/whoami":
        answer = identity_message(actor_id, chat_id)
    elif command == "/claim_owner":
        code = text.replace("/claim_owner", "", 1).strip()
        answer, keyboard = claim_owner(int(actor_id or 0), int(chat_id), code)
    elif command == "/deploy":
        answer, keyboard = prepare_confirmation(int(actor_id or 0), int(chat_id))
    elif command == "/deploy_status":
        answer, keyboard = status_message(actor_id, chat_id)
    elif command in {"/bots", "/risk", "/learning", "/reports", "/stress", "/timeline"}:
        section = command[1:]
        answer, keyboard = _section_intro(section, actor_id, chat_id)
    elif command == "/agent":
        question = text.replace("/agent", "", 1).strip() or "General Controller, дай отчёт"
        answer = _reply(question)
    elif command == "/trades":
        answer = _trades()
    elif command == "/ai":
        answer = "🤖 <b>AI Copilot включён</b>\n\nПиши вопрос напрямую или обращайся к конкретному боту по имени."
    else:
        answer = _reply(text or "покажи текущее состояние системы")
    send_message(int(chat_id), answer, keyboard)


def _agent_name(code: str) -> str:
    return {
        "general": "General Controller", "market": "Market Agent", "news": "News Agent",
        "risk": "Risk Engine", "portfolio": "Portfolio Engine", "learning": "Learning Engine",
        "stress": "Stress Bot", "security": "Security Guard",
    }.get(code, code)


def _callback_answer(data: str, actor_id: int, chat_id: int) -> tuple[str, dict[str, Any]]:
    if data == "deploy:prepare":
        return prepare_confirmation(actor_id, chat_id)
    if data.startswith("deploy:confirm:"):
        return confirm_deployment(actor_id, chat_id, data.split(":", 2)[2])
    if data == "deploy:cancel":
        return cancel_confirmation(actor_id)
    if data == "deploy:status":
        return status_message(actor_id, chat_id)
    if data in {"menu", "overview"}:
        return _overview(), main_keyboard(actor_id, chat_id)
    if data in {"bots", "risk", "learning", "reports", "stress", "timeline"}:
        return _section_intro(data, actor_id, chat_id)
    if data.startswith("agent:"):
        name = _agent_name(data.split(":", 1)[1])
        return _reply(f"{name}, дай текущий отчёт и укажи риски"), _back_keyboard(actor_id=actor_id, chat_id=chat_id)
    if data.startswith("risk:"):
        action = data.split(":", 1)[1]
        return _reply(f"Risk Engine: выполни безопасный анализ команды {action}. Реальные ордера запрещены."), risk_keyboard(actor_id, chat_id)
    if data.startswith("learning:"):
        action = data.split(":", 1)[1]
        return _reply(f"Learning Engine: покажи {action} по общей базе SharipovAI."), learning_keyboard(actor_id, chat_id)
    if data.startswith("reports:"):
        action = data.split(":", 1)[1]
        return _reply(f"Сформируй отчёт SharipovAI: {action}. Используй общую базу и не выдумывай данные."), reports_keyboard(actor_id, chat_id)
    if data.startswith("stress:"):
        action = data.split(":", 1)[1]
        return _reply(f"Stress Bot: смоделируй сценарий {action} без реальных ордеров."), stress_keyboard(actor_id, chat_id)
    if data.startswith("timeline:"):
        action = data.split(":", 1)[1]
        return _reply(f"Покажи timeline модуля {action} по общей базе SharipovAI."), timeline_keyboard(actor_id, chat_id)
    if data == "trades":
        return _trades(), _back_keyboard(actor_id=actor_id, chat_id=chat_id)
    return _reply(data), _back_keyboard(actor_id=actor_id, chat_id=chat_id)


def handle_callback(callback: dict[str, Any]) -> None:
    callback_id = callback.get("id")
    message = callback.get("message") or {}
    chat_id = message.get("chat", {}).get("id")
    actor_id = callback.get("from", {}).get("id")
    data = str(callback.get("data") or "")
    if callback_id:
        try:
            _telegram("answerCallbackQuery", {"callback_query_id": callback_id})
        except Exception:
            pass
    if not chat_id:
        return
    text, keyboard = _callback_answer(data, int(actor_id or 0), int(chat_id))
    send_message(int(chat_id), text, keyboard)
