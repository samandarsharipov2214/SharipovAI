"""Telegram adapter backed by the same services and state as the SharipovAI website.

Telegram, Mini App and website share the same orchestrator and paper state.
Every section opens its own contextual controls instead of repeating the main menu.
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


def _webapp_button() -> list[dict[str, Any]]:
    if not _webapp_url():
        return []
    return [{"text": "🚀 Открыть SharipovAI", "web_app": {"url": _webapp_url()}}]


def main_keyboard() -> dict[str, Any]:
    rows = [
        [{"text": "🏠 Mission Control", "callback_data": "overview"}, {"text": "🤖 AI-боты", "callback_data": "bots"}],
        [{"text": "⚠️ Risk Center", "callback_data": "risk"}, {"text": "💼 Сделки", "callback_data": "trades"}],
        [{"text": "🧠 Learning", "callback_data": "learning"}, {"text": "📊 Reports", "callback_data": "reports"}],
        [{"text": "🧪 Stress Lab", "callback_data": "stress"}, {"text": "📒 Timeline", "callback_data": "timeline"}],
    ]
    webapp = _webapp_button()
    if webapp:
        rows.append(webapp)
    return {"inline_keyboard": rows}


def _back_keyboard(extra: list[list[dict[str, Any]]] | None = None) -> dict[str, Any]:
    rows = list(extra or [])
    rows.append([{"text": "⬅️ Главное меню", "callback_data": "menu"}])
    webapp = _webapp_button()
    if webapp:
        rows.append(webapp)
    return {"inline_keyboard": rows}


def stress_keyboard() -> dict[str, Any]:
    return _back_keyboard([
        [{"text": "📉 BTC −10%", "callback_data": "stress:btc10"}, {"text": "📉 BTC −20%", "callback_data": "stress:btc20"}],
        [{"text": "💥 Market −50%", "callback_data": "stress:market50"}, {"text": "📰 News Panic", "callback_data": "stress:news"}],
        [{"text": "🏦 Биржа недоступна", "callback_data": "stress:exchange"}, {"text": "🌐 Интернет пропал", "callback_data": "stress:network"}],
        [{"text": "🦢 Black Swan", "callback_data": "stress:black_swan"}, {"text": "📋 Последний результат", "callback_data": "stress:last"}],
    ])


def bots_keyboard() -> dict[str, Any]:
    return _back_keyboard([
        [{"text": "🧭 General Controller", "callback_data": "agent:general"}],
        [{"text": "📈 Market Agent", "callback_data": "agent:market"}, {"text": "📰 News Agent", "callback_data": "agent:news"}],
        [{"text": "🛡 Risk Engine", "callback_data": "agent:risk"}, {"text": "💼 Portfolio Engine", "callback_data": "agent:portfolio"}],
        [{"text": "🧠 Learning Engine", "callback_data": "agent:learning"}, {"text": "🧪 Stress Bot", "callback_data": "agent:stress"}],
        [{"text": "🔐 Security Guard", "callback_data": "agent:security"}, {"text": "✅ Проверить всех", "callback_data": "bots:check"}],
    ])


def risk_keyboard() -> dict[str, Any]:
    return _back_keyboard([
        [{"text": "🟢 Консервативный", "callback_data": "risk:safe"}, {"text": "🟡 Умеренный", "callback_data": "risk:normal"}],
        [{"text": "🔴 Агрессивный", "callback_data": "risk:pro"}, {"text": "🛑 Emergency Stop", "callback_data": "risk:stop"}],
        [{"text": "📋 Полный отчёт", "callback_data": "risk:report"}, {"text": "✅ Тест адекватности", "callback_data": "risk:check"}],
    ])


def learning_keyboard() -> dict[str, Any]:
    return _back_keyboard([
        [{"text": "❌ Последние ошибки", "callback_data": "learning:errors"}, {"text": "✅ Исправленные ошибки", "callback_data": "learning:fixed"}],
        [{"text": "🧩 Новые правила", "callback_data": "learning:rules"}, {"text": "🔁 Повторяющиеся ошибки", "callback_data": "learning:repeated"}],
        [{"text": "🧪 Проверить Learning", "callback_data": "learning:check"}],
    ])


def reports_keyboard() -> dict[str, Any]:
    return _back_keyboard([
        [{"text": "📅 Сегодня", "callback_data": "reports:day"}, {"text": "📆 Неделя", "callback_data": "reports:week"}],
        [{"text": "🗓 Месяц", "callback_data": "reports:month"}, {"text": "🤖 По ботам", "callback_data": "reports:bots"}],
        [{"text": "💸 Комиссии", "callback_data": "reports:fees"}, {"text": "📉 Просадка", "callback_data": "reports:drawdown"}],
    ])


def timeline_keyboard() -> dict[str, Any]:
    return _back_keyboard([
        [{"text": "🧭 General Controller", "callback_data": "timeline:general"}],
        [{"text": "📈 Market", "callback_data": "timeline:market"}, {"text": "📰 News", "callback_data": "timeline:news"}],
        [{"text": "🛡 Risk", "callback_data": "timeline:risk"}, {"text": "🧠 Learning", "callback_data": "timeline:learning"}],
        [{"text": "🧪 Stress", "callback_data": "timeline:stress"}, {"text": "🔐 Security", "callback_data": "timeline:security"}],
    ])


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
        "Выбери раздел ниже. Внутри каждого раздела теперь есть собственные действия."
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
        f"Exchange mode: <b>{_safe((state.get('exchange_status') or {}).get('mode', 'sandbox'))}</b>\n"
        "LIVE execution: <b>заблокирован</b>"
    )


def _section_intro(section: str) -> tuple[str, dict[str, Any]]:
    mapping: dict[str, tuple[str, dict[str, Any]]] = {
        "bots": ("🤖 <b>AI Agent Control</b>\n\nВыбери конкретного бота, запроси его состояние или проверь всех.", bots_keyboard()),
        "risk": ("⚠️ <b>Risk Center</b>\n\nВыбери профиль, запроси отчёт, проверь Risk Engine или используй Emergency Stop.", risk_keyboard()),
        "learning": ("🧠 <b>Learning Engine</b>\n\nПосмотри найденные ошибки, исправления, новые правила и повторяющиеся проблемы.", learning_keyboard()),
        "reports": ("📊 <b>Reports</b>\n\nВыбери период или отдельный вид аналитики.", reports_keyboard()),
        "stress": ("🧪 <b>Stress Lab</b>\n\nВыбери кризисный сценарий. Stress Bot смоделирует реакцию системы без реальных ордеров.", stress_keyboard()),
        "timeline": ("📒 <b>Decision Timeline</b>\n\nВыбери бота и посмотри его действия по времени.", timeline_keyboard()),
    }
    return mapping[section]


def handle_message(message: dict[str, Any]) -> None:
    chat_id = message.get("chat", {}).get("id")
    text = str(message.get("text") or "").strip()
    if not chat_id:
        return
    command = text.split()[0].lower() if text.startswith("/") else ""
    keyboard = main_keyboard()
    if command == "/start":
        answer = _overview()
    elif command == "/status":
        answer = _status()
    elif command in {"/bots", "/risk", "/learning", "/reports", "/stress", "/timeline"}:
        section = command[1:]
        answer, keyboard = _section_intro(section)
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
    }.get(code, "General Controller")


def _stress_question(code: str) -> str:
    return {
        "btc10": "Stress Bot, запусти стресс-сценарий BTC падение 10 процентов и покажи капитал до и после, просадку и защитные действия",
        "btc20": "Stress Bot, запусти стресс-сценарий BTC падение 20 процентов и покажи капитал до и после, просадку и защитные действия",
        "market50": "Stress Bot, запусти сценарий обвала всего рынка на 50 процентов",
        "news": "Stress Bot, запусти сценарий паники в новостях и покажи реакцию News Agent и Risk Engine",
        "exchange": "Stress Bot, смоделируй недоступность биржи и покажи защитные действия",
        "network": "Stress Bot, смоделируй потерю интернета и покажи безопасное поведение системы",
        "black_swan": "Stress Bot, запусти Black Swan сценарий и покажи максимально безопасную реакцию",
        "last": "Stress Bot, покажи последний стресс-тест, его итог и журнал действий",
    }.get(code, "Stress Bot, покажи последний стресс-тест")


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

    keyboard = main_keyboard()
    if data in {"menu", "overview"}:
        answer = _overview()
    elif data in {"bots", "risk", "learning", "reports", "stress", "timeline"}:
        answer, keyboard = _section_intro(data)
    elif data == "trades":
        answer = _trades()
    elif data.startswith("agent:"):
        name = _agent_name(data.split(":", 1)[1])
        answer = _reply(f"{name}, дай подробный отчёт: состояние, последние действия, ошибки, текущая задача и тест адекватности")
        keyboard = _back_keyboard([[{"text": "📒 Журнал этого бота", "callback_data": f"timeline:{data.split(':',1)[1]}"}], [{"text": "✅ Проверить адекватность", "callback_data": f"agentcheck:{data.split(':',1)[1]}"}]])
    elif data == "bots:check":
        answer = _reply("General Controller, проверь всех AI-ботов: активность, простои, ошибки и адекватность")
        keyboard = bots_keyboard()
    elif data.startswith("agentcheck:"):
        name = _agent_name(data.split(":", 1)[1])
        answer = _reply(f"{name}, проведи тест адекватности и честно укажи ограничения")
        keyboard = bots_keyboard()
    elif data.startswith("timeline:"):
        name = _agent_name(data.split(":", 1)[1])
        answer = _reply(f"{name}, покажи журнал действий по времени: что сделал, кому отправил команду и какой получил результат")
        keyboard = timeline_keyboard()
    elif data.startswith("stress:"):
        answer = _reply(_stress_question(data.split(":", 1)[1]))
        keyboard = stress_keyboard()
    elif data.startswith("risk:"):
        action = data.split(":", 1)[1]
        prompts = {
            "safe": "Risk Engine, включи консервативный профиль только для demo и объясни новые лимиты",
            "normal": "Risk Engine, включи умеренный профиль только для demo и объясни лимиты",
            "pro": "Risk Engine, оцени агрессивный профиль, но не включай LIVE и перечисли опасности",
            "stop": "Security Guard и Risk Engine, покажите состояние Emergency Stop и заблокируйте новые demo-входы при критическом риске",
            "report": "Risk Engine, дай полный отчёт Risk Center",
            "check": "Risk Engine, проведи тест адекватности и проверь лимиты",
        }
        answer = _reply(prompts.get(action, prompts["report"]))
        keyboard = risk_keyboard()
    elif data.startswith("learning:"):
        action = data.split(":", 1)[1]
        prompts = {
            "errors": "Learning Engine, покажи последние найденные ошибки",
            "fixed": "Learning Engine, покажи исправленные ошибки и доказательства",
            "rules": "Learning Engine, покажи новые правила после обучения",
            "repeated": "Learning Engine, покажи повторяющиеся ошибки",
            "check": "Learning Engine, проведи самопроверку и оцени адекватность своих выводов",
        }
        answer = _reply(prompts.get(action, prompts["errors"]))
        keyboard = learning_keyboard()
    elif data.startswith("reports:"):
        action = data.split(":", 1)[1]
        prompts = {
            "day": "General Controller, дай отчёт за сегодня",
            "week": "General Controller, дай отчёт за неделю",
            "month": "General Controller, дай отчёт за месяц",
            "bots": "General Controller, дай отчёт по вкладу и ошибкам каждого бота",
            "fees": "Portfolio Engine, дай отчёт по комиссиям и чистому PnL",
            "drawdown": "Risk Engine, дай отчёт по максимальной просадке и защите капитала",
        }
        answer = _reply(prompts.get(action, prompts["day"]))
        keyboard = reports_keyboard()
    else:
        answer = _overview()

    send_message(int(chat_id), answer, keyboard)
