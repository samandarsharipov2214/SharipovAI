"""Telegram bot for SharipovAI.

Production mode is webhook through dashboard.telegram_webhook_api.
Polling is opt-in only with TELEGRAM_POLLING_ENABLED=1 so a Render worker cannot
fight the webhook by accident.

Important discipline: demo/paper protects Samandar's real funds, but every AI
answer must treat the simulated capital as if it were real capital. No careless
"it's only demo" behavior.
"""

from __future__ import annotations

import html
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

import httpx

from sharipovai_constitution import constitution_snapshot, now_iso, paper_realism_state

API_TIMEOUT = 20.0
SUBSCRIBERS_FILE = Path(os.getenv("TELEGRAM_SUBSCRIBERS_FILE", "data/telegram_subscribers.json"))
STATE_FILE = Path(os.getenv("TELEGRAM_STATE_FILE", "data/telegram_state.json"))
DIARY_FILE = Path(os.getenv("TELEGRAM_DIARY_FILE", "data/telegram_decision_diary.json"))
NOTIFY_INTERVAL_SECONDS = int(os.getenv("TELEGRAM_NOTIFY_INTERVAL_SECONDS", "3600"))
STARTED_AT = now_iso()
STARTED_MONOTONIC = time.monotonic()


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


def _uptime_seconds() -> int:
    return int(time.monotonic() - STARTED_MONOTONIC)


def send_message(chat_id: int, text: str, keyboard: dict[str, Any] | None = None) -> None:
    payload: dict[str, Any] = {
        "chat_id": int(chat_id),
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
        [{"text": "🟢 Сейчас: решение", "callback_data": "now"}, {"text": "🌅 Утро", "callback_data": "morning"}],
        [{"text": "📰 Новости + источники", "callback_data": "news"}, {"text": "⚠️ Риск", "callback_data": "risk"}],
        [{"text": "🚦 Торговать?", "callback_data": "trade"}, {"text": "❓ Почему?", "callback_data": "why"}],
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
        {"command": "now", "description": "Текущее решение: рынок, риск, следующий шаг"},
        {"command": "morning", "description": "Утренний отчёт"},
        {"command": "status", "description": "Проверка Telegram/webhook/AI"},
        {"command": "ai", "description": "AI чат через внутренних ботов"},
        {"command": "news", "description": "Новости с источниками и временем"},
        {"command": "risk", "description": "Почему рисковано"},
        {"command": "trade", "description": "Можно ли сейчас торговать"},
        {"command": "why", "description": "Почему такое решение"},
        {"command": "check_ai", "description": "Проверить всех ИИ"},
        {"command": "audit", "description": "Полный аудит всех ИИ"},
        {"command": "scoreboard", "description": "Кто live/paper/waiting_api"},
        {"command": "learning", "description": "Чему научился ИИ"},
        {"command": "improve", "description": "Что улучшить"},
        {"command": "explain", "description": "Объяснить термин простыми словами"},
        {"command": "teach", "description": "Урок трейдинга"},
        {"command": "diary", "description": "Дневник решений"},
        {"command": "stop_ai", "description": "Экстренно заблокировать действия"},
        {"command": "resume_ai", "description": "Снять STOP для анализа"},
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
    trades = [
        {"asset": "BTC/USDT", "side": "BUY", "status": "OPEN", "net_pnl": 44.28, "fee": 8.12, "lesson": "position managed with real-capital discipline"},
        {"asset": "SOL/USDT", "side": "BUY", "status": "OPEN", "net_pnl": 29.10, "fee": 2.10, "lesson": "small size because volatility is high"},
        {"asset": "ETH/USDT", "side": "SELL", "status": "CLOSED", "net_pnl": -21.75, "fee": 3.45, "lesson": "entry was early; Learning must tighten volume confirmation"},
    ]
    pnl = round(sum(float(trade["net_pnl"]) for trade in trades), 2)
    fees = round(sum(float(trade["fee"]) for trade in trades), 2)
    return paper_realism_state(
        {
            "mode": "PAPER_REALISM",
            "decision": "WATCH",
            "risk_level": "LOW",
            "equity": round(10000 + pnl, 2),
            "cash": 9500.0,
            "net_pnl": pnl,
            "total_fees": fees,
            "trades": trades,
            "exchange_status": {"mode": "sandbox", "seriousness": "real_capital_training"},
            "online_monitoring": {"mode": "paper_realism", "live_execution_enabled": False, "real_orders_blocked": True, "risk_treated_as_real": True},
            "decision_journal": [
                {"time": now_iso(), "agent": "General Controller", "action": "не разрешил относиться к paper/demo как к игре"},
                {"time": now_iso(), "agent": "Risk Engine", "action": "пересчитал риск как при реальном капитале"},
                {"time": now_iso(), "agent": "Learning Engine", "action": "принял ETH-ошибку как реальный урок"},
            ],
        }
    )


def _record_decision(kind: str, decision: str, reason: str) -> None:
    data = read_json(DIARY_FILE, {"items": []})
    items = list(data.get("items", []))
    items.append({"time": _now_iso(), "kind": kind, "decision": decision, "reason": reason, "capital_mode": "paper_realism"})
    data["items"] = items[-80:]
    write_json(DIARY_FILE, data)


def _safe_build(title: str, builder: Callable[[], str]) -> str:
    try:
        return builder()
    except Exception as exc:
        return (
            f"⚠️ <b>{_safe_html(title)}</b>\n\n"
            f"Один внутренний модуль упал: <b>{_safe_html(type(exc).__name__)}</b>. "
            "Бот живой, webhook живой. Ошибка записана в Render logs и должна уйти в Learning/Evidence.\n\n"
            "Попробуй /start, /status или /trade."
        )


def start_text() -> str:
    return (
        "👋 <b>SharipovAI Telegram запущен</b>\n\n"
        "Режим: <b>paper-realism</b>. Это безопасная среда для Самандара, но AI обязан думать как при реальном капитале.\n\n"
        "Главное:\n"
        "/now — текущее решение: рынок, риск, следующий шаг\n"
        "/news — новости с источниками и временем\n"
        "/trade — можно ли торговать\n"
        "/why — почему такое решение\n"
        "/audit — аудит всех ИИ\n"
        "/status — статус Telegram\n\n"
        "Конституция: никаких фейковых журналов, скрытия ошибок и отношения «это всего лишь демо»."
    )


def status_text() -> str:
    token_ok = bool(os.getenv("BOT_TOKEN", "").strip())
    url = webapp_url() or "не задан"
    stop = load_state()
    constitution = constitution_snapshot()
    return (
        "📡 <b>Telegram Status</b>\n\n"
        f"BOT_TOKEN: <b>{'настроен' if token_ok else 'НЕ НАСТРОЕН'}</b>\n"
        f"WEBAPP_URL: <b>{_safe_html(url)}</b>\n"
        "Режим: <b>webhook через FastAPI</b>\n"
        "Capital mode: <b>paper_realism</b>\n"
        f"Uptime: <b>{_uptime_seconds()} сек.</b>\n"
        f"STOP AI: <b>{'ВКЛЮЧЁН' if stop.get('stop_ai') else 'выключен'}</b>\n"
        f"Конституция: <b>{_safe_html(constitution.get('version'))}</b>\n\n"
        "Demo защищает реальные деньги, но ошибки, комиссии, риск и обучение считаются серьёзно."
    )


def orchestrated_reply(message: str) -> str:
    def build() -> str:
        from ai_chat_orchestrator import answer_chat

        answer = answer_chat(message, _demo_state())
        source = answer.get("source_ai", "AI Chat Orchestrator")
        reply = str(answer.get("reply", "SharipovAI пока не смог собрать ответ."))
        return f"<b>{_safe_html(source)}</b>\n\n{_safe_html(reply)}\n\n<i>Paper-realism: ответ оценивается как тренировка реального капитала.</i>"

    return _safe_build("AI Chat Orchestrator", build)


def news_text() -> str:
    def build() -> str:
        from news_monitor.analyzer import analyzed_news_payload

        news = analyzed_news_payload()
        summary = news.get("summary", {}) if isinstance(news, dict) else {}
        items = list(news.get("items", [])) if isinstance(news, dict) else []
        lines = [
            "📰 <b>Новости: источники и время</b>",
            "",
            f"Проверено: <b>{_safe_html(now_iso())}</b>",
            f"Средняя достоверность: <b>{_safe_html(summary.get('average_credibility_percent', 0))}%</b>",
            f"Нужно подтверждение: <b>{_safe_html(summary.get('needs_confirmation', 0))}</b>",
            "",
        ]
        if not items:
            lines.append("Новостей пока нет. BUY по слухам запрещён.")
        for idx, item in enumerate(items[:5], start=1):
            title = item.get("title") or item.get("headline") or "Новость"
            source = item.get("source_name") or item.get("source") or "unknown"
            credibility = item.get("credibility_percent", item.get("credibility", 0))
            lines.append(f"{idx}. <b>{_safe_html(title)}</b>\nИсточник: {_safe_html(source)} · доверие {credibility}%")
        lines.append("\nПравило: один источник не даёт разрешение на сделку.")
        return "\n".join(lines).strip()

    return _safe_build("Новости", build)


def now_text() -> str:
    def build() -> str:
        from news_monitor.analyzer import analyzed_news_payload
        from trading_intelligence import trade_gate

        gate = trade_gate()
        regime = gate.get("market_regime", {})
        news = analyzed_news_payload()
        summary = news.get("summary", {}) if isinstance(news, dict) else {}
        decision = "STOP_AI" if stop_ai_enabled() else str(gate.get("decision", "WATCH"))
        action = "Все действия заблокированы. Разрешён только анализ." if stop_ai_enabled() else str(gate.get("human_answer", "Наблюдать. LIVE запрещён."))
        _record_decision("now", decision, action)
        return "\n".join([
            "🟢 <b>Текущее решение SharipovAI</b>",
            "",
            f"Время проверки: <b>{_safe_html(now_iso())}</b>",
            f"Решение: <b>{_safe_html(decision)}</b>",
            f"Действие: <b>{_safe_html(action)}</b>",
            f"Режим рынка: <b>{_safe_html(regime.get('regime', 'unknown'))}</b>",
            f"Риск: <b>{_safe_html(regime.get('risk_level', 'unknown'))}</b>",
            f"Новости: достоверность <b>{_safe_html(summary.get('average_credibility_percent', 0))}%</b>, нужно подтверждение: <b>{_safe_html(summary.get('needs_confirmation', 0))}</b>",
            "",
            "Paper-realism: это безопасно для реальных денег, но решение считается как тренировка настоящего капитала.",
            "Следующий шаг: /news или /why.",
        ])

    return _safe_build("Текущее решение", build)


def morning_text() -> str:
    def build() -> str:
        from news_monitor.analyzer import analyzed_news_payload
        from system_ai_auditor import audit_system_ai
        from trading_intelligence import market_regime, trade_gate

        gate = trade_gate()
        regime = market_regime()
        news = analyzed_news_payload()
        audit = audit_system_ai()
        scoreboard = audit.get("scoreboard", {})
        counts = scoreboard.get("counts", {}) if isinstance(scoreboard, dict) else {}
        summary = news.get("summary", {}) if isinstance(news, dict) else {}
        return "\n".join([
            "🌅 <b>Отчёт SharipovAI</b>",
            "",
            f"Создан: <b>{_safe_html(now_iso())}</b>",
            f"Рынок: <b>{_safe_html(regime.get('regime', 'unknown'))}</b>",
            f"Риск: <b>{_safe_html(regime.get('risk_level', 'unknown'))}</b>",
            f"Trade Gate: <b>{_safe_html(gate.get('decision', 'UNKNOWN'))}</b>",
            f"AI: live {counts.get('live', 0)}, paper/demo {counts.get('demo', 0)}, ждут API {counts.get('waiting_api', 0)}",
            f"Новости: достоверность {summary.get('average_credibility_percent', 0)}%, нужно подтверждение {summary.get('needs_confirmation', 0)}",
            "",
            "Главное: не гнаться за сделкой. Ошибка в paper-realism считается реальным уроком.",
        ])

    return _safe_build("Отчёт SharipovAI", build)


def trade_text() -> str:
    def build() -> str:
        from trading_intelligence import trade_gate

        gate = trade_gate()
        blockers = gate.get("blockers", []) or []
        warnings = gate.get("warnings", []) or []
        regime = gate.get("market_regime", {})
        decision = "STOP_AI" if stop_ai_enabled() else str(gate.get("decision", "UNKNOWN"))
        lines = [
            "🚦 <b>Можно ли сейчас торговать?</b>",
            "",
            f"Время проверки: <b>{_safe_html(now_iso())}</b>",
            f"Решение: <b>{_safe_html(decision)}</b>",
            f"PAPER/DEMO: <b>{'НЕТ' if stop_ai_enabled() else 'ДА' if gate.get('can_trade_demo') else 'НЕТ'}</b>",
            "LIVE: <b>НЕТ</b>",
            f"Режим рынка: <b>{_safe_html(regime.get('regime', 'unknown'))}</b>",
            "",
            _safe_html("Все действия заблокированы STOP AI." if stop_ai_enabled() else str(gate.get("human_answer", ""))),
        ]
        if blockers:
            lines.append("\n<b>Блокеры:</b>")
            lines.extend(f"• {_safe_html(item)}" for item in blockers[:5])
        if warnings:
            lines.append("\n<b>Предупреждения:</b>")
            lines.extend(f"• {_safe_html(item)}" for item in warnings[:3])
        lines.append("\nКонституция: paper/demo не игрушка; риск, комиссия и ошибка считаются серьёзно.")
        _record_decision("trade", decision, str(gate.get("human_answer", "")))
        return "\n".join(lines)

    return _safe_build("Trade Gate", build)


def why_text() -> str:
    return orchestrated_reply("почему такое решение по рынку и риску, объясни простыми словами")


def audit_text() -> str:
    def build() -> str:
        from system_ai_auditor import audit_system_ai

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
            f"Конституция: <b>{_safe_html(constitution_snapshot().get('version'))}</b>",
        ]
        if weak:
            lines.append("\n<b>Что требует внимания:</b>")
            for item in weak[:8]:
                lines.append(f"• <b>{_safe_html(item.get('name', 'AI'))}</b> — {_safe_html(item.get('verdict'))}")
        lines.append("\nТребование: любой demo/paper-модуль обязан вести журнал как при реальном капитале.")
        return "\n".join(lines)

    return _safe_build("Аудит всех ИИ", build)


def improve_text() -> str:
    def build() -> str:
        from system_ai_auditor import audit_system_ai

        audit = audit_system_ai()
        actions = list(audit.get("priority_actions", []))[:7]
        lines = ["🛠 <b>Что улучшить в SharipovAI</b>", ""]
        if actions:
            for idx, action in enumerate(actions, start=1):
                lines.append(f"{idx}. {_safe_html(action)}")
        else:
            lines.append("Критических улучшений не найдено, но нужно продолжать live-проверки.")
        lines.append("\nДобавлено правило: paper-realism, last_seen, last_action, Evidence/Learning для ошибок.")
        return "\n".join(lines)

    return _safe_build("Что улучшить", build)


def scoreboard_text() -> str:
    def build() -> str:
        from ai_evidence import system_scoreboard
        from news_monitor.agents import run_news_agents

        news_report = run_news_agents()
        scoreboard = system_scoreboard(list(news_report.get("agents", [])))
        counts = scoreboard.get("counts", {})
        agents = scoreboard.get("agents", [])
        lines = [
            "📊 <b>AI Scoreboard</b>",
            "",
            f"Проверено: <b>{_safe_html(now_iso())}</b>",
            f"Всего AI: <b>{scoreboard.get('total', 0)}</b>",
            f"Live: <b>{counts.get('live', 0)}</b>",
            f"Paper/demo: <b>{counts.get('demo', 0)}</b>",
            f"Ждут API: <b>{counts.get('waiting_api', 0)}</b>",
            f"Disabled: <b>{counts.get('disabled', 0)}</b>",
            f"Средний proof score: <b>{scoreboard.get('average_proof_score', 0)}</b>",
        ]
        weak = [item for item in agents if item.get("real_data_status") in {"waiting_api", "disabled"} or int(item.get("proof_score", 0)) < 55]
        if weak:
            lines.append("\n<b>Главные слабые места:</b>")
            for item in weak[:8]:
                lines.append(f"• <b>{_safe_html(item.get('name'))}</b> — {_safe_html(item.get('honesty_label'))}, proof {item.get('proof_score')}")
        return "\n".join(lines)

    return _safe_build("AI Scoreboard", build)


def learning_text() -> str:
    def build() -> str:
        from learning_engine_v2 import learning_state

        state = learning_state()
        lessons = state.get("active_rule_candidates", [])
        lines = ["🧠 <b>Learning Engine 2.0</b>", "", f"Проверено: <b>{_safe_html(now_iso())}</b>", f"Уроков: <b>{state.get('lesson_count', 0)}</b>", f"Режим: <b>{_safe_html(state.get('mode', 'unknown'))}</b>"]
        for lesson in lessons[:4]:
            lines.append(f"• {_safe_html(lesson.get('lesson'))}")
        lines.append("\nPaper-realism: каждая ошибка считается дорогой, даже если деньги защищены.")
        return "\n".join(lines)

    return _safe_build("Learning Engine", build)


def diary_text() -> str:
    data = read_json(DIARY_FILE, {"items": []})
    items = list(data.get("items", []))[-10:]
    lines = ["📒 <b>Дневник решений</b>", ""]
    if not items:
        lines.append("Пока решений нет. Нажми /now или /trade, и я начну вести дневник paper-realism.")
        return "\n".join(lines)
    for item in reversed(items):
        lines.append(f"• <b>{_safe_html(item.get('time'))}</b> · <b>{_safe_html(item.get('kind'))}</b> — {_safe_html(item.get('decision'))}\n  {_safe_html(item.get('reason'))}")
    return "\n".join(lines)


def explain_text(raw: str) -> str:
    term = raw.replace("/explain", "", 1).strip() or "paper realism"
    lower = term.lower()
    explanations = {
        "paper realism": "Paper-realism — это когда реальные деньги защищены, но AI считает риск, ошибки и обучение как при настоящем капитале.",
        "demo": "Demo в SharipovAI — это не игрушка. Это безопасная оболочка для Самандара. AI обязан думать как при реальном риске.",
        "mixed": "Mixed / смешанный рынок — сигналы противоречат друг другу. В таком режиме ИИ обязан ждать подтверждения и не покупать на одной новости.",
        "funding": "Funding rate — это плата между лонгами и шортами. Если funding высокий, толпа стоит в одну сторону, и возможен squeeze.",
        "spread": "Spread — разница между ценой покупки и продажи. Чем он выше, тем дороже входить и выходить.",
        "slippage": "Slippage — проскальзывание. Ты хочешь купить по одной цене, а исполняется хуже из-за ликвидности или резкого движения.",
        "drawdown": "Drawdown — просадка капитала от максимума. Главное правило: сначала выжить, потом заработать.",
    }
    answer = next((value for key, value in explanations.items() if key in lower), f"{term} — термин, который нужно объяснить через контекст рынка, риска и комиссии. Спроси: /explain paper realism, /explain mixed, /explain spread.")
    return f"📚 <b>Объясняю простыми словами</b>\n\n{_safe_html(answer)}"


def teach_text() -> str:
    return (
        "📚 <b>Урок дня</b>\n\n"
        "Почему demo нельзя считать игрушкой?\n\n"
        "Если AI привыкает халатно рисковать в paper/demo, он переносит плохую привычку в будущий live. Поэтому SharipovAI обязан считать комиссии, просадку, доказательства и ошибки как при реальном капитале.\n\n"
        "Правило: безопасная среда — да. Безответственное мышление — нет."
    )


def portfolio_text() -> str:
    state = _demo_state()
    return (
        "💼 <b>Portfolio AI</b>\n\n"
        f"Режим: <b>{_safe_html(state['mode'])}</b>\n"
        f"Equity: <b>{state['equity']:.2f} USDT</b>\n"
        f"PnL: <b>{state['net_pnl']:.2f} USDT</b>\n"
        f"Комиссии: <b>{state['total_fees']:.2f} USDT</b>\n"
        "LIVE-ордера заблокированы. Но paper-капитал считается как тренировка реального риска."
    )


def costs_text() -> str:
    return orchestrated_reply("комиссии и выгодно ли сейчас торговать с учётом paper-realism")


def stop_ai_text(reason: str = "Ручная команда из Telegram") -> str:
    set_stop_ai(True, reason)
    _record_decision("stop_ai", "STOP_AI", reason)
    return "🚨 <b>STOP AI включён</b>\n\nВсе торговые действия заблокированы. Разрешены только новости, анализ, аудит и отчёты. Ошибки должны уходить в Learning/Evidence.\n\nСнять стоп для анализа: /resume_ai"


def resume_ai_text() -> str:
    set_stop_ai(False, "")
    _record_decision("resume_ai", "PAPER_ANALYSIS_ALLOWED", "STOP AI снят только для paper-realism анализа")
    return "✅ <b>STOP AI снят</b>\n\nРазрешён только paper/demo-анализ. LIVE всё равно запрещён. Отношение к риску остаётся как к реальному капиталу."


def notification_text() -> str:
    return trade_text()


def handle_message(message: dict[str, Any]) -> None:
    chat_id = message.get("chat", {}).get("id")
    text = str(message.get("text") or "").strip()
    if not chat_id:
        return
    chat_id = int(chat_id)
    command = text.split()[0].lower() if text.startswith("/") else ""
    try:
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
            send_message(chat_id, news_text(), main_keyboard())
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
    except Exception as exc:
        print(f"Telegram handle_message error: {type(exc).__name__}: {exc}")
        try:
            send_message(chat_id, f"⚠️ Бот получил команду, но ответ не отправился: {_safe_html(type(exc).__name__)}. Ошибка должна попасть в Render logs и Learning/Evidence. Попробуй /start или /status.")
        except Exception as send_exc:
            print(f"Telegram error fallback failed: {type(send_exc).__name__}: {send_exc}")


def handle_callback(callback: dict[str, Any]) -> None:
    callback_id = callback.get("id")
    message = callback.get("message") or {}
    chat_id = message.get("chat", {}).get("id")
    data = str(callback.get("data") or "")
    if callback_id:
        try:
            answer_callback(callback_id)
        except Exception as exc:
            print(f"Telegram callback ack error: {type(exc).__name__}: {exc}")
    if not chat_id:
        return
    chat_id = int(chat_id)
    mapping: dict[str, Callable[[], str]] = {
        "now": now_text,
        "morning": morning_text,
        "status": status_text,
        "news": news_text,
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
    if os.getenv("TELEGRAM_POLLING_ENABLED", "0").strip().lower() not in {"1", "true", "yes", "on"}:
        print("SharipovAI Telegram polling disabled; webhook mode is expected.")
        while True:
            time.sleep(3600)
    if os.getenv("TELEGRAM_POLLING_DELETE_WEBHOOK", "1").strip().lower() not in {"0", "false", "no", "off"}:
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
