"""Telegram bot for SharipovAI.

Supports webhook mode through dashboard.telegram_webhook_api on Render and
optional local polling when run directly. Secrets must come from environment
variables only: BOT_TOKEN and WEBAPP_URL.
"""

from __future__ import annotations

import html
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from ai_chat_orchestrator import answer_chat
from ai_evidence import system_scoreboard
from learning_engine_v2 import learning_state
from news_monitor.agents import run_news_agents
from news_monitor.analyzer import analyzed_news_payload
from system_ai_auditor import audit_system_ai
from trading_intelligence import market_regime, trade_gate

API_TIMEOUT = 35.0
SUBSCRIBERS_FILE = Path(os.getenv("TELEGRAM_SUBSCRIBERS_FILE", "data/telegram_subscribers.json"))
STATE_FILE = Path(os.getenv("TELEGRAM_STATE_FILE", "data/telegram_state.json"))
DIARY_FILE = Path(os.getenv("TELEGRAM_DIARY_FILE", "data/telegram_decision_diary.json"))
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


def _safe_html(text: object) -> str:
    return html.escape(str(text), quote=False)


def _clip(text: str, limit: int = 3900) -> str:
    text = str(text)
    if len(text) <= limit:
        return text
    return text[: limit - 80] + "\n\n…ответ сокращён. Открой Mini App/страницу отчёта для полного вывода."


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def send_message(chat_id: int, text: str, keyboard: dict[str, Any] | None = None) -> None:
    payload: dict[str, Any] = {"chat_id": chat_id, "text": _clip(text), "parse_mode": "HTML", "disable_web_page_preview": True}
    if keyboard:
        payload["reply_markup"] = keyboard
    telegram("sendMessage", payload)


def answer_callback(callback_id: str, text: str = "") -> None:
    telegram("answerCallbackQuery", {"callback_query_id": callback_id, "text": text})


def main_keyboard() -> dict[str, Any]:
    rows: list[list[dict[str, Any]]] = [
        [{"text": "🟢 Что сейчас?", "callback_data": "now"}, {"text": "🌅 Утро", "callback_data": "morning"}],
        [{"text": "📰 Новости", "callback_data": "news"}, {"text": "⚠️ Риск", "callback_data": "risk"}],
        [{"text": "🚦 Можно торговать?", "callback_data": "trade"}, {"text": "❓ Почему?", "callback_data": "why"}],
        [{"text": "🤖 Все ИИ", "callback_data": "audit"}, {"text": "📊 AI Scoreboard", "callback_data": "scoreboard"}],
        [{"text": "🛠 Что улучшить", "callback_data": "improve"}, {"text": "📒 Дневник", "callback_data": "diary"}],
        [{"text": "🧠 Learning", "callback_data": "learning"}, {"text": "📚 Научи", "callback_data": "teach"}],
        [{"text": "💼 Портфель", "callback_data": "portfolio"}, {"text": "🧾 Комиссии", "callback_data": "costs"}],
        [{"text": "🚨 STOP AI", "callback_data": "stop_ai"}, {"text": "📡 Статус", "callback_data": "status"}],
    ]
    if webapp_url():
        rows.append([{"text": "🚀 Открыть Mini App", "web_app": {"url": webapp_url()}}])
    return {"inline_keyboard": rows}


def setup_bot_commands() -> None:
    commands = [
        {"command": "start", "description": "Главное меню SharipovAI"},
        {"command": "now", "description": "Что делать сейчас"},
        {"command": "morning", "description": "Утренний отчёт"},
        {"command": "status", "description": "Проверка Telegram/webhook/AI"},
        {"command": "ai", "description": "AI чат через внутренних ботов"},
        {"command": "news", "description": "Что сегодня произошло"},
        {"command": "risk", "description": "Почему рисковано"},
        {"command": "trade", "description": "Можно ли сейчас торговать"},
        {"command": "why", "description": "Почему такое решение"},
        {"command": "check_ai", "description": "Проверить всех ИИ"},
        {"command": "audit", "description": "Полный аудит всех ИИ"},
        {"command": "scoreboard", "description": "Кто live/demo/waiting_api"},
        {"command": "learning", "description": "Чему научился ИИ"},
        {"command": "improve", "description": "Что улучшить"},
        {"command": "explain", "description": "Объяснить термин простыми словами"},
        {"command": "teach", "description": "Урок трейдинга"},
        {"command": "diary", "description": "Дневник решений"},
        {"command": "stop_ai", "description": "Экстренно заблокировать действия"},
        {"command": "resume_ai", "description": "Снять STOP для demo-анализа"},
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
    data = read_json(STATE_FILE, {"modes": {}, "stop_ai": False, "stop_reason": ""})
    if not isinstance(data.get("modes"), dict):
        data["modes"] = {}
    data.setdefault("stop_ai", False)
    data.setdefault("stop_reason", "")
    return data


def save_state(data: dict[str, Any]) -> None:
    write_json(STATE_FILE, data)


def set_mode(chat_id: int, mode: str) -> None:
    data = load_state()
    data.setdefault("modes", {})[str(chat_id)] = mode
    save_state(data)


def get_mode(chat_id: int) -> str:
    return str(load_state().get("modes", {}).get(str(chat_id), "ai"))


def set_stop_ai(enabled: bool, reason: str = "") -> None:
    data = load_state()
    data["stop_ai"] = bool(enabled)
    data["stop_reason"] = reason
    save_state(data)


def stop_ai_enabled() -> bool:
    return bool(load_state().get("stop_ai", False))


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
        "bybit_costs": {"best_trade_venue": {"best": {"product": "spot", "liquidity": "maker", "round_trip_fee": 2.0, "break_even_move_percent": 0.02}}, "estimated_saving_vs_worst": 18.4},
        "trades": [
            {"asset": "BTC/USDT", "side": "BUY", "status": "OPEN", "net_pnl": 44.28},
            {"asset": "SOL/USDT", "side": "BUY", "status": "OPEN", "net_pnl": 29.1},
            {"asset": "ETH/USDT", "side": "SELL", "status": "CLOSED", "net_pnl": -21.75},
        ],
    }


def _record_decision(kind: str, decision: str, reason: str) -> None:
    data = read_json(DIARY_FILE, {"items": []})
    items = list(data.get("items", []))
    items.append({"time": _now_iso(), "kind": kind, "decision": decision, "reason": reason})
    data["items"] = items[-80:]
    write_json(DIARY_FILE, data)


def start_text() -> str:
    return (
        "👋 <b>SharipovAI Telegram запущен</b>\n\n"
        "Бот теперь работает как личный AI-диспетчер. Он спрашивает внутренних ботов, а не отвечает заглушкой.\n\n"
        "Главное:\n"
        "/now — что делать сейчас\n"
        "/morning — утренний отчёт\n"
        "/trade — можно ли торговать\n"
        "/why — почему такое решение\n"
        "/improve — что улучшить\n"
        "/stop_ai — экстренно всё остановить\n\n"
        "Можно писать обычным текстом: «Что сегодня произошло?», «Почему рисковано?», «Можно покупать BTC?»"
    )


def status_text() -> str:
    token_ok = bool(os.getenv("BOT_TOKEN", "").strip())
    url = webapp_url() or "не задан"
    stop = load_state()
    return (
        "📡 <b>Telegram Status</b>\n\n"
        f"BOT_TOKEN: <b>{'настроен' if token_ok else 'НЕ НАСТРОЕН'}</b>\n"
        f"WEBAPP_URL: <b>{_safe_html(url)}</b>\n"
        "Режим: <b>webhook через FastAPI</b>\n"
        "AI Chat Orchestrator: <b>подключён</b>\n"
        f"STOP AI: <b>{'ВКЛЮЧЁН' if stop.get('stop_ai') else 'выключен'}</b>\n\n"
        "После финального деплоя: /telegram-check → Set webhook → /start."
    )


def orchestrated_reply(message: str) -> str:
    answer = answer_chat(message, _demo_state())
    source = answer.get("source_ai", "AI Chat Orchestrator")
    reply = str(answer.get("reply", "SharipovAI пока не смог собрать ответ."))
    return f"<b>{_safe_html(source)}</b>\n\n{_safe_html(reply)}"


def now_text() -> str:
    gate = trade_gate()
    regime = gate.get("market_regime", {})
    news = analyzed_news_payload()
    summary = news.get("summary", {}) if isinstance(news, dict) else {}
    decision = str(gate.get("decision", "WATCH"))
    action = "НЕ входить. Наблюдать." if decision == "BLOCK" else "Только DEMO. LIVE запрещён." if decision == "DEMO_ONLY" else "DEMO можно, LIVE запрещён."
    if stop_ai_enabled():
        decision = "STOP_AI"
        action = "Все действия заблокированы. Разрешён только анализ."
    _record_decision("now", decision, action)
    lines = [
        "🟢 <b>Что делать сейчас?</b>",
        "",
        f"Решение: <b>{_safe_html(decision)}</b>",
        f"Действие: <b>{_safe_html(action)}</b>",
        f"Режим рынка: <b>{_safe_html(regime.get('regime', 'unknown'))}</b>",
        f"Риск: <b>{_safe_html(regime.get('risk_level', 'unknown'))}</b>",
        f"Новости: средняя достоверность <b>{summary.get('average_credibility_percent', 0)}%</b>",
    ]
    blockers = gate.get("blockers", []) or []
    if blockers:
        lines.append("\n<b>Почему осторожно:</b>")
        lines.extend(f"• {_safe_html(item)}" for item in blockers[:4])
    lines.append("\nСледующий шаг: /why или /trade")
    return "\n".join(lines)


def morning_text() -> str:
    gate = trade_gate()
    regime = market_regime()
    news = analyzed_news_payload()
    audit = audit_system_ai()
    scoreboard = audit.get("scoreboard", {})
    counts = scoreboard.get("counts", {}) if isinstance(scoreboard, dict) else {}
    summary = news.get("summary", {}) if isinstance(news, dict) else {}
    items = list(news.get("items", []))[:3] if isinstance(news, dict) else []
    lines = [
        "🌅 <b>Утренний отчёт SharipovAI</b>",
        "",
        f"Рынок: <b>{_safe_html(regime.get('regime', 'unknown'))}</b>",
        f"Риск: <b>{_safe_html(regime.get('risk_level', 'unknown'))}</b>",
        f"Trade Gate: <b>{_safe_html(gate.get('decision', 'UNKNOWN'))}</b>",
        f"AI: live {counts.get('live', 0)}, demo {counts.get('demo', 0)}, ждут API {counts.get('waiting_api', 0)}",
        f"Новости: достоверность {summary.get('average_credibility_percent', 0)}%, нужно подтвердить {summary.get('needs_confirmation', 0)}",
    ]
    if items:
        lines.append("\n<b>Главные новости:</b>")
        for item in items:
            lines.append(f"• {_safe_html(item.get('title', 'Новость'))}")
    lines.append("\nГлавное действие: не гнаться за сделкой. Сначала /trade и /why.")
    _record_decision("morning", str(gate.get("decision", "UNKNOWN")), "Утренний отчёт сформирован")
    return "\n".join(lines)


def trade_text() -> str:
    gate = trade_gate()
    blockers = gate.get("blockers", []) or []
    warnings = gate.get("warnings", []) or []
    decision = "STOP_AI" if stop_ai_enabled() else str(gate.get("decision", "UNKNOWN"))
    lines = [
        "🚦 <b>Можно ли сейчас торговать?</b>",
        "",
        f"Решение: <b>{_safe_html(decision)}</b>",
        f"DEMO: <b>{'НЕТ' if stop_ai_enabled() else 'ДА' if gate.get('can_trade_demo') else 'НЕТ'}</b>",
        "LIVE: <b>НЕТ</b>",
        "",
        _safe_html("Все действия заблокированы STOP AI." if stop_ai_enabled() else str(gate.get("human_answer", ""))),
    ]
    if blockers:
        lines.append("\n<b>Блокеры:</b>")
        lines.extend(f"• {_safe_html(item)}" for item in blockers[:5])
    if warnings:
        lines.append("\n<b>Предупреждения:</b>")
        lines.extend(f"• {_safe_html(item)}" for item in warnings[:3])
    _record_decision("trade", decision, str(gate.get("human_answer", "")))
    return "\n".join(lines)


def why_text() -> str:
    gate = trade_gate()
    regime = gate.get("market_regime", {})
    blockers = gate.get("blockers", []) or []
    warnings = gate.get("warnings", []) or []
    lines = [
        "❓ <b>Почему такое решение?</b>",
        "",
        f"Trade Gate: <b>{_safe_html(gate.get('decision', 'UNKNOWN'))}</b>",
        f"Market Regime AI: <b>{_safe_html(regime.get('regime', 'unknown'))}</b>",
        f"Risk level: <b>{_safe_html(regime.get('risk_level', 'unknown'))}</b>",
    ]
    if stop_ai_enabled():
        lines.append("• STOP AI включён: любые действия заблокированы.")
    if blockers:
        lines.append("\n<b>Главные причины:</b>")
        lines.extend(f"• {_safe_html(item)}" for item in blockers[:5])
    if warnings:
        lines.append("\n<b>Предупреждения:</b>")
        lines.extend(f"• {_safe_html(item)}" for item in warnings[:3])
    lines.append("\nИтог: SharipovAI должен чаще говорить WAIT/BLOCK, чем рисковать ради красивой сделки.")
    return "\n".join(lines)


def audit_text() -> str:
    audit = audit_system_ai()
    auditor = audit.get("auditor", {})
    weak = [item for item in audit.get("interviews", []) if item.get("verdict") in {"делает вид", "заглушка", "недоработан", "частично работает"}]
    lines = ["🤖 <b>Аудит всех ИИ</b>", "", _safe_html(str(auditor.get("summary", ""))), "", f"Работают: <b>{auditor.get('working', 0)} / {auditor.get('total', 0)}</b>", f"Proof score: <b>{auditor.get('average_proof_score', 0)}</b>"]
    if weak:
        lines.append("\n<b>Что требует внимания:</b>")
        for item in weak[:8]:
            lines.append(f"• <b>{_safe_html(item.get('name', 'AI'))}</b> — {_safe_html(item.get('verdict'))}")
    return "\n".join(lines)


def improve_text() -> str:
    audit = audit_system_ai()
    actions = list(audit.get("priority_actions", []))[:7]
    lines = ["🛠 <b>Что улучшить в SharipovAI</b>", ""]
    if actions:
        for idx, action in enumerate(actions, start=1):
            lines.append(f"{idx}. {_safe_html(action)}")
    else:
        lines.append("Критических улучшений не найдено, но нужно продолжать live-проверки.")
    lines.append("\nМой приоритет: Telegram webhook → live data status → Learning Engine → Backtest/Paper pipeline.")
    return "\n".join(lines)


def scoreboard_text() -> str:
    news_report = run_news_agents()
    scoreboard = system_scoreboard(list(news_report.get("agents", [])))
    counts = scoreboard.get("counts", {})
    agents = scoreboard.get("agents", [])
    lines = ["📊 <b>AI Scoreboard</b>", "", f"Всего AI: <b>{scoreboard.get('total', 0)}</b>", f"Live: <b>{counts.get('live', 0)}</b>", f"Demo: <b>{counts.get('demo', 0)}</b>", f"Ждут API: <b>{counts.get('waiting_api', 0)}</b>", f"Disabled: <b>{counts.get('disabled', 0)}</b>", f"Средний proof score: <b>{scoreboard.get('average_proof_score', 0)}</b>", "", "<b>Главные слабые места:</b>"]
    weak = [item for item in agents if item.get("real_data_status") in {"waiting_api", "disabled"} or int(item.get("proof_score", 0)) < 55]
    for item in weak[:8]:
        lines.append(f"• <b>{_safe_html(item.get('name'))}</b> — {_safe_html(item.get('honesty_label'))}, proof {item.get('proof_score')}")
    return "\n".join(lines)


def learning_text() -> str:
    state = learning_state()
    lessons = state.get("active_rule_candidates", [])
    lines = ["🧠 <b>Learning Engine 2.0</b>", "", f"Уроков: <b>{state.get('lesson_count', 0)}</b>", f"Режим: <b>{_safe_html(state.get('mode', 'unknown'))}</b>"]
    if lessons:
        lines.append("\n<b>Активные уроки:</b>")
        for lesson in lessons[:4]:
            lines.append(f"• {_safe_html(lesson.get('lesson'))}")
    return "\n".join(lines)


def diary_text() -> str:
    data = read_json(DIARY_FILE, {"items": []})
    items = list(data.get("items", []))[-10:]
    lines = ["📒 <b>Дневник решений</b>", ""]
    if not items:
        lines.append("Пока решений нет. Нажми /now или /trade, и я начну вести дневник.")
        return "\n".join(lines)
    for item in reversed(items):
        lines.append(f"• <b>{_safe_html(item.get('kind'))}</b> — {_safe_html(item.get('decision'))}\n  {_safe_html(item.get('reason'))}")
    return "\n".join(lines)


def explain_text(raw: str) -> str:
    term = raw.replace("/explain", "", 1).strip() or "funding rate"
    lower = term.lower()
    explanations = {
        "funding": "Funding rate — это плата между лонгами и шортами. Если funding высокий, толпа стоит в одну сторону, и возможен squeeze.",
        "funding rate": "Funding rate — это плата между лонгами и шортами. Если funding высокий, толпа стоит в одну сторону, и возможен squeeze.",
        "spread": "Spread — разница между ценой покупки и продажи. Чем он выше, тем дороже входить и выходить.",
        "slippage": "Slippage — проскальзывание. Ты хочешь купить по одной цене, а исполняется хуже из-за ликвидности или резкого движения.",
        "drawdown": "Drawdown — просадка капитала от максимума. Главное правило: сначала выжить, потом заработать.",
        "open interest": "Open interest — количество открытых контрактов. Резкий рост может показывать перегрев и риск ликвидаций.",
    }
    answer = next((value for key, value in explanations.items() if key in lower), f"{term} — термин, который нужно объяснить через контекст рынка, риска и комиссии. Спроси подробнее: /explain spread, /explain funding rate, /explain slippage.")
    return f"📚 <b>Объясняю простыми словами</b>\n\n{_safe_html(answer)}"


def teach_text() -> str:
    return (
        "📚 <b>Урок дня</b>\n\n"
        "Почему нельзя покупать на одной новости?\n\n"
        "Новость из Telegram/X может быть ранним сигналом, но она может быть слухом. Поэтому News Supervisor требует подтверждение. Если подтверждений нет, Trade Gate обязан сказать WAIT или BLOCK.\n\n"
        "Правило: лучше пропустить сделку, чем войти на ложной новости."
    )


def portfolio_text() -> str:
    state = _demo_state()
    return f"💼 <b>Portfolio AI</b>\n\nРежим: <b>{state['mode']}</b>\nEquity: <b>{state['equity']:.2f} USDT</b>\nPnL: <b>{state['net_pnl']:.2f} USDT</b>\nКомиссии: <b>{state['total_fees']:.2f} USDT</b>\nLIVE-ордера заблокированы."


def costs_text() -> str:
    return orchestrated_reply("комиссии и выгодно ли сейчас торговать")


def stop_ai_text(reason: str = "Ручная команда из Telegram") -> str:
    set_stop_ai(True, reason)
    _record_decision("stop_ai", "STOP_AI", reason)
    return "🚨 <b>STOP AI включён</b>\n\nВсе торговые действия заблокированы. Разрешены только новости, анализ, аудит и отчёты.\n\nСнять стоп для demo-анализа: /resume_ai"


def resume_ai_text() -> str:
    set_stop_ai(False, "")
    _record_decision("resume_ai", "DEMO_ANALYSIS_ALLOWED", "STOP AI снят только для demo-анализа")
    return "✅ <b>STOP AI снят</b>\n\nРазрешён только demo-анализ. LIVE всё равно запрещён."


def notification_text() -> str:
    gate = trade_gate()
    return f"🔔 <b>SharipovAI уведомление</b>\n\nTrade Gate: <b>{_safe_html(gate.get('decision', 'UNKNOWN'))}</b>\nDemo: <b>{'разрешён' if gate.get('can_trade_demo') else 'запрещён'}</b>\nLIVE: <b>запрещён</b>\n\nДля деталей: /now /trade /why"


def handle_message(message: dict[str, Any]) -> None:
    chat_id = message.get("chat", {}).get("id")
    text = str(message.get("text") or "").strip()
    if not chat_id:
        return
    chat_id = int(chat_id)
    command = text.split()[0].lower() if text.startswith("/") else ""

    if command in {"/start", "/help"}:
        set_mode(chat_id, "ai")
        send_message(chat_id, start_text(), main_keyboard())
    elif command == "/now":
        send_message(chat_id, now_text(), main_keyboard())
    elif command == "/morning":
        send_message(chat_id, morning_text(), main_keyboard())
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
    elif command == "/why":
        send_message(chat_id, why_text(), main_keyboard())
    elif command in {"/audit", "/check_ai"}:
        send_message(chat_id, audit_text(), main_keyboard())
    elif command == "/scoreboard":
        send_message(chat_id, scoreboard_text(), main_keyboard())
    elif command == "/learning":
        send_message(chat_id, learning_text(), main_keyboard())
    elif command == "/improve":
        send_message(chat_id, improve_text(), main_keyboard())
    elif command == "/diary":
        send_message(chat_id, diary_text(), main_keyboard())
    elif command == "/explain":
        send_message(chat_id, explain_text(text), main_keyboard())
    elif command == "/teach":
        send_message(chat_id, teach_text(), main_keyboard())
    elif command == "/stop_ai":
        send_message(chat_id, stop_ai_text(), main_keyboard())
    elif command == "/resume_ai":
        send_message(chat_id, resume_ai_text(), main_keyboard())
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
    mapping = {
        "now": now_text,
        "morning": morning_text,
        "status": status_text,
        "news": lambda: orchestrated_reply("что сегодня произошло"),
        "risk": lambda: orchestrated_reply("почему рисковано"),
        "trade": trade_text,
        "why": why_text,
        "audit": audit_text,
        "scoreboard": scoreboard_text,
        "learning": learning_text,
        "improve": improve_text,
        "diary": diary_text,
        "teach": teach_text,
        "portfolio": portfolio_text,
        "costs": costs_text,
        "stop_ai": stop_ai_text,
    }
    if data == "ai_chat":
        set_mode(chat_id, "ai")
        send_message(chat_id, "🤖 AI-чат включён. Задай вопрос прямо сюда.", main_keyboard())
    elif data == "notifications":
        subscribe(chat_id)
        send_message(chat_id, "🔔 Уведомления включены. Для отключения напиши /notify_off", main_keyboard())
    elif data in mapping:
        send_message(chat_id, mapping[data](), main_keyboard())


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
