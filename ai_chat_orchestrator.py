"""Unified chat routing for web, Mini App and Telegram."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

try:
    from learning.bot_communication import BotCommunicationNetwork
    from learning_engine_v2 import learning_state
    from news_monitor.agents import run_news_agents
    from news_monitor.analyzer import analyzed_news_payload
    from system_ai_auditor import audit_system_ai
    from trading_intelligence import market_regime, trade_gate
except Exception:  # pragma: no cover
    BotCommunicationNetwork = None
    learning_state = None
    run_news_agents = None
    analyzed_news_payload = None
    audit_system_ai = None
    market_regime = None
    trade_gate = None

AGENTS: dict[str, dict[str, Any]] = {
    "general_controller": {"name": "General Controller", "aliases": ("генеральный", "главный ии", "general controller"), "role": "Контроль всех ботов, конфликтов, целей, простоев и финального решения."},
    "market_agent": {"name": "Market Agent", "aliases": ("market agent", "рыночный бот", "маркет агент"), "role": "Тренд, объём, импульс, уровни и структура рынка."},
    "news_agent": {"name": "News Agent", "aliases": ("news agent", "новостной бот", "ньюс агент"), "role": "Новости, источники, достоверность и правило 2+ подтверждений."},
    "risk_engine": {"name": "Risk Engine", "aliases": ("risk engine", "риск бот", "риск-бот"), "role": "Риск, просадка, лимиты и блокировка опасных действий."},
    "portfolio_engine": {"name": "Portfolio Engine", "aliases": ("portfolio engine", "портфельный бот"), "role": "Баланс, позиции, PnL и комиссии."},
    "paper_trading_bot": {"name": "Paper Trading Bot", "aliases": ("paper trading bot", "демо бот", "торговый бот"), "role": "Paper/demo-исполнение и журнал сделок."},
    "confidence_engine": {"name": "Confidence Engine", "aliases": ("confidence engine", "бот уверенности"), "role": "Сила сигнала и вероятность ошибки."},
    "consensus_engine": {"name": "Consensus Engine", "aliases": ("consensus engine", "бот консенсуса"), "role": "Согласие агентов и выявление конфликтов."},
    "stress_bot": {"name": "Stress Bot", "aliases": ("stress bot", "стресс бот"), "role": "Кризисные сценарии и защита капитала."},
    "learning_engine": {"name": "Learning Engine", "aliases": ("learning engine", "обучающий бот"), "role": "Ошибки, уроки и новые правила."},
    "security_guard": {"name": "Security Guard", "aliases": ("security guard", "бот безопасности"), "role": "Запрет LIVE без разрешения и контроль безопасности."},
}


def answer_chat(message: str, state: dict[str, Any] | None = None) -> dict[str, Any]:
    text = (message or "").strip()
    lower = text.lower()
    state = state or {}
    agent_id = detect_agent(lower)
    if agent_id:
        return _answer_agent(agent_id, text, state)
    intent = detect_intent(lower)
    handlers = {
        "news": lambda: _answer_news(),
        "risk": lambda: _answer_risk(),
        "trade": lambda: _answer_trade(),
        "bots": lambda: _answer_bots(),
        "learning": lambda: _answer_learning(),
        "portfolio": lambda: _answer_portfolio(state),
        "costs": lambda: _answer_costs(state),
        "market": lambda: _answer_market(),
        "timeline": lambda: _answer_agent("general_controller", text, state),
    }
    return handlers.get(intent, lambda: _answer_overview(state))()


def detect_agent(lower: str) -> str | None:
    normalized = lower.replace("-", " ").replace("_", " ")
    if lower.startswith("/agent "):
        parts = lower.split(maxsplit=2)
        if len(parts) > 1:
            candidate = parts[1].replace("-", "_")
            if candidate in AGENTS:
                return candidate
    for agent_id, meta in AGENTS.items():
        names = (agent_id.replace("_", " "), str(meta["name"]).lower(), *meta["aliases"])
        if any(str(name).replace("_", " ") in normalized for name in names):
            return agent_id
    return None


def detect_intent(lower: str) -> str:
    if any(x in lower for x in ("журнал", "таймлайн", "timeline", "что делал", "действия по времени")): return "timeline"
    if any(x in lower for x in ("новост", "что случ", "произош", "главное сегодня")): return "news"
    if any(x in lower for x in ("покуп", "продать", "лонг", "шорт", "торговать", "сделк")): return "trade"
    if any(x in lower for x in ("риск", "опас", "почему нельзя", "почему наблюдать")): return "risk"
    if any(x in lower for x in ("бот", "агент", "аудит", "кто не работает", "все ии")): return "bots"
    if any(x in lower for x in ("науч", "обуч", "ошиб", "урок", "learning")): return "learning"
    if any(x in lower for x in ("портфель", "баланс", "pnl", "прибыл", "убыт", "позици")): return "portfolio"
    if any(x in lower for x in ("комисс", "bybit", "безубыт", "fee", "спред")): return "costs"
    if any(x in lower for x in ("рынок", "тренд", "волат", "режим рынка")): return "market"
    return "overview"


def _network() -> Any:
    if BotCommunicationNetwork is None:
        return None
    db = Path(os.getenv("BOT_COMMUNICATION_DB")) if os.getenv("BOT_COMMUNICATION_DB") else None
    return BotCommunicationNetwork(db)


def _action(lower: str) -> str:
    if any(x in lower for x in ("тест адекватности", "проверь себя", "самопровер", "self check")): return "self_check"
    if any(x in lower for x in ("пауза", "останови", "pause")): return "pause"
    if any(x in lower for x in ("отправь в learning", "отправь в обучение", "разбери ошибку")): return "learn"
    if any(x in lower for x in ("журнал", "таймлайн", "timeline", "что делал", "действия")): return "timeline"
    if any(x in lower for x in ("отчет", "отчёт", "статус", "report")): return "report"
    return "chat"


def _answer_agent(agent_id: str, question: str, state: dict[str, Any]) -> dict[str, Any]:
    meta = AGENTS.get(agent_id, AGENTS["general_controller"])
    action = _action(question.lower())
    saved: dict[str, Any] = {}
    net = _network()
    if net is not None:
        try:
            sender = "security_guard" if agent_id == "general_controller" else "general_controller"
            saved = net.send_message(
                sender=sender,
                recipient=agent_id,
                message_type="command" if action != "chat" else "question",
                topic="unified_chat",
                payload={"text": question, "source": "telegram_or_web", "action": action, "user_message": True},
                priority="high" if action in {"pause", "self_check"} else "normal",
            )
        except Exception as exc:
            saved = {"status": "error", "error": f"{type(exc).__name__}: {exc}"}

    if action == "timeline":
        return _timeline(agent_id, meta, saved)
    if action == "self_check":
        reply = f"{meta['name']} принял команду самопроверки. Проверяются источник данных, last_seen, last_action, ошибки и соответствие роли. Итоговый verdict берётся из System AI Auditor, а не из самооценки бота."
    elif action == "pause":
        reply = f"{meta['name']}: запрос на паузу записан для paper/demo. LIVE уже заблокирован. Генеральный контролёр должен подтвердить смену состояния."
    elif action == "learn":
        reply = f"{meta['name']}: вопрос и последние ошибки отправлены в Learning Engine. Правило считается внедрённым только после evidence и повторного теста."
    elif action == "report":
        reply = _agent_report(agent_id, meta, state)
    else:
        reply = _agent_chat(agent_id, meta, question, state)
    return {"status": "ok", "intent": "agent_chat", "source_ai": meta["name"], "reply": reply, "data": {"agent_id": agent_id, "role": meta["role"], "action": action, "message_bus": saved}}


def _agent_report(agent_id: str, meta: dict[str, Any], state: dict[str, Any]) -> str:
    if agent_id == "risk_engine": return _answer_risk()["reply"]
    if agent_id == "market_agent": return _answer_market()["reply"]
    if agent_id == "news_agent": return _answer_news()["reply"]
    if agent_id == "learning_engine": return _answer_learning()["reply"]
    if agent_id in {"portfolio_engine", "paper_trading_bot"}: return _answer_portfolio(state)["reply"]
    if agent_id in {"general_controller", "consensus_engine"}: return _answer_bots()["reply"] + "\n" + _answer_trade()["reply"]
    return f"{meta['name']} работает в своей зоне: {meta['role']} Для честной оценки нужен heartbeat и evidence, а не декоративный процент."


def _agent_chat(agent_id: str, meta: dict[str, Any], question: str, state: dict[str, Any]) -> str:
    if agent_id == "risk_engine": return _answer_risk()["reply"]
    if agent_id == "market_agent": return _answer_market()["reply"]
    if agent_id == "news_agent": return _answer_news()["reply"]
    if agent_id == "learning_engine": return _answer_learning()["reply"]
    if agent_id in {"portfolio_engine", "paper_trading_bot"}: return _answer_portfolio(state)["reply"]
    if agent_id in {"general_controller", "consensus_engine"}: return _answer_trade()["reply"]
    return f"{meta['name']}: {meta['role']} Вопрос принят и записан в durable message bus. Я не должен отвечать за пределами своей зоны ответственности."


def _timeline(agent_id: str, meta: dict[str, Any], saved: dict[str, Any]) -> dict[str, Any]:
    messages: list[dict[str, Any]] = []
    net = _network()
    if net is not None:
        try:
            messages = sorted(
                [*net.inbox(agent_id, unread_only=False), *net.outbox(agent_id)],
                key=lambda item: str(item.get("created_at", item.get("time", ""))),
                reverse=True,
            )[:10]
        except Exception:
            messages = []
    lines = [f"Журнал {meta['name']}:"]
    if not messages:
        lines.append("• Подтверждённых записей пока нет. Фиктивный timeline не создаётся.")
    for item in messages:
        ts = item.get("created_at") or item.get("time") or "время неизвестно"
        lines.append(f"• {ts} · {item.get('sender','?')} → {item.get('recipient','?')} · {item.get('topic', item.get('message_type','event'))}")
    return {"status": "ok", "intent": "agent_timeline", "source_ai": meta["name"], "reply": "\n".join(lines), "data": {"agent_id": agent_id, "messages": messages, "message_bus": saved}}


def _answer_news() -> dict[str, Any]:
    news = _safe_call(analyzed_news_payload, {})
    agents = _safe_call(run_news_agents, {})
    items = list(news.get("items", []))[:4] if isinstance(news, dict) else []
    summary = news.get("summary", {}) if isinstance(news, dict) else {}
    supervisor = agents.get("supervisor", {}) if isinstance(agents, dict) else {}
    lines = ["News Agent проверил новости и источники."]
    for item in items:
        lines.append(f"• {item.get('title','Новость')} — {item.get('source_name','источник')}, достоверность {item.get('credibility_percent', item.get('trust_score',0))}%")
    if not items: lines.append("Свежих подтверждённых заголовков нет. BUY по слухам запрещён.")
    lines.append(f"Средняя достоверность: {summary.get('average_credibility_percent',0)}%. Нужно подтверждение: {summary.get('needs_confirmation',0)}.")
    if supervisor: lines.append(f"Решение Supervisor: {supervisor.get('decision','WATCH')}.")
    return {"status": "ok", "intent": "news", "source_ai": "News Agent", "reply": "\n".join(lines), "data": {"summary": summary, "items": items}}


def _answer_risk() -> dict[str, Any]:
    gate = _safe_call(trade_gate, {})
    regime = gate.get("market_regime", {}) if isinstance(gate, dict) else {}
    lines = ["Risk Engine и Trade Gate проверили ситуацию.", str(gate.get("human_answer", "Trade Gate недоступен.")), f"Рынок: {regime.get('regime','unknown')}. Риск: {regime.get('risk_level','unknown')}."]
    if gate.get("blockers"): lines += ["Блокеры:", *[f"• {x}" for x in gate.get("blockers", [])[:4]]]
    if gate.get("warnings"): lines += ["Предупреждения:", *[f"• {x}" for x in gate.get("warnings", [])[:3]]]
    return {"status": "ok", "intent": "risk", "source_ai": "Risk Engine", "reply": "\n".join(lines), "data": gate}


def _answer_trade() -> dict[str, Any]:
    gate = _safe_call(trade_gate, {})
    lines = ["General Controller собрал Market, News, Risk и Consensus.", str(gate.get("human_answer", "Trade Gate недоступен.")), f"Решение: {gate.get('decision','UNKNOWN')}. Paper/demo: {'да' if gate.get('can_trade_demo') else 'нет'}. LIVE: {'да' if gate.get('can_trade_live') else 'нет'}." ]
    if gate.get("blockers"): lines += ["Почему нельзя/опасно:", *[f"• {x}" for x in gate.get("blockers", [])[:4]]]
    return {"status": "ok", "intent": "trade", "source_ai": "General Controller + Trade Gate", "reply": "\n".join(lines), "data": gate}


def _answer_bots() -> dict[str, Any]:
    audit = _safe_call(audit_system_ai, {})
    scoreboard = audit.get("scoreboard", {}) if isinstance(audit, dict) else {}
    auditor = audit.get("auditor", {}) if isinstance(audit, dict) else {}
    counts = scoreboard.get("counts", {}) if isinstance(scoreboard, dict) else {}
    lines = ["General Controller и System AI Auditor проверили всех ИИ.", str(auditor.get("summary", "Аудит недоступен."))]
    if counts: lines.append(f"Live: {counts.get('live',0)}, paper/demo: {counts.get('demo',0)}, ждут API: {counts.get('waiting_api',0)}, disabled: {counts.get('disabled',0)}.")
    weak = [x for x in audit.get("interviews", []) if x.get("verdict") in {"делает вид", "заглушка", "недоработан", "частично работает"}]
    if weak:
        lines.append("Требуют внимания:")
        for item in weak[:5]: lines.append(f"• {item.get('name')} — {item.get('verdict')}: {item.get('next_fix')}")
    lines.append("Отдельный чат: «Risk Engine, дай отчёт», «News Agent, покажи журнал», «Learning Engine, проверь себя»." )
    return {"status": "ok", "intent": "bots", "source_ai": "General Controller / System AI Auditor", "reply": "\n".join(lines), "data": audit}


def _answer_learning() -> dict[str, Any]:
    learning = _safe_call(learning_state, {})
    lessons = learning.get("active_rule_candidates", []) if isinstance(learning, dict) else []
    lines = ["Learning Engine проверил уроки.", f"Уроков: {learning.get('lesson_count',0)}. Режим: {learning.get('mode','unknown')}."]
    for lesson in lessons[:4]: lines.append(f"• {lesson.get('lesson')} → {lesson.get('new_rule')}")
    return {"status": "ok", "intent": "learning", "source_ai": "Learning Engine", "reply": "\n".join(lines), "data": learning}


def _answer_portfolio(state: dict[str, Any]) -> dict[str, Any]:
    equity = state.get("equity", state.get("paper_equity", 0))
    pnl = state.get("net_pnl", state.get("pnl", state.get("paper_pnl", 0)))
    reply = f"Portfolio Engine: equity {equity} USDT, PnL {pnl} USDT, комиссии {state.get('total_fees',0)} USDT, риск {state.get('risk_level','LOW')}, решение {state.get('decision','WATCH')}. LIVE заблокирован."
    return {"status": "ok", "intent": "portfolio", "source_ai": "Portfolio Engine", "reply": reply, "data": state}


def _answer_costs(state: dict[str, Any]) -> dict[str, Any]:
    costs = state.get("bybit_costs", {}) if isinstance(state, dict) else {}
    best = ((costs.get("best_trade_venue") or {}).get("best") or {}) if isinstance(costs, dict) else {}
    reply = "Exchange Cost AI проверил комиссии. "
    if best: reply += f"Лучший paper-вариант: {best.get('product')} / {best.get('liquidity')}, round-trip fee {best.get('round_trip_fee')}. "
    reply += f"Комиссионная нагрузка: {state.get('commission_drag',0)}. Break-even: {state.get('break_even_price','unknown')}."
    return {"status": "ok", "intent": "costs", "source_ai": "Portfolio Engine / Exchange Cost AI", "reply": reply, "data": costs}


def _answer_market() -> dict[str, Any]:
    regime = _safe_call(market_regime, {})
    reply = f"Market Agent: режим {regime.get('regime','unknown')}, риск {regime.get('risk_level','unknown')}, действие {regime.get('recommended_action','WATCH')}. Причина: {regime.get('explanation','')}"
    return {"status": "ok", "intent": "market", "source_ai": "Market Agent", "reply": reply, "data": regime}


def _answer_overview(state: dict[str, Any]) -> dict[str, Any]:
    gate = _safe_call(trade_gate, {})
    news = _safe_call(analyzed_news_payload, {})
    summary = news.get("summary", {}) if isinstance(news, dict) else {}
    reply = "Я работаю по той же Agent Control архитектуре, что и новый сайт. Можно обращаться к каждому боту отдельно. " + f"Trade Gate: {gate.get('decision','UNKNOWN')}. Новости: достоверность {summary.get('average_credibility_percent',0)}%. " + "Примеры: «Risk Engine, дай отчёт», «News Agent, покажи журнал», «Learning Engine, проверь себя», «General Controller, кто простаивает?»."
    return {"status": "ok", "intent": "overview", "source_ai": "General Controller", "reply": reply, "data": {"trade_gate": gate, "news_summary": summary, "agents": list(AGENTS)}}


def _safe_call(fn: Any, fallback: Any) -> Any:
    if fn is None:
        return fallback
    try:
        return fn()
    except Exception as exc:
        return {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
