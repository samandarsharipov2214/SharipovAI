"""AI Chat Orchestrator for SharipovAI.

The Mini App chat should not answer from a static fallback. It should route the
user question to the right AI subsystem and summarize that subsystem's data.
"""

from __future__ import annotations

from typing import Any

try:
    from ai_evidence import system_scoreboard
    from learning_engine_v2 import learning_state
    from news_monitor.agents import run_news_agents
    from news_monitor.analyzer import analyzed_news_payload
    from system_ai_auditor import audit_system_ai
    from trading_intelligence import market_regime, trade_gate
except Exception:  # pragma: no cover - safe runtime fallback
    system_scoreboard = None  # type: ignore[assignment]
    learning_state = None  # type: ignore[assignment]
    run_news_agents = None  # type: ignore[assignment]
    analyzed_news_payload = None  # type: ignore[assignment]
    audit_system_ai = None  # type: ignore[assignment]
    market_regime = None  # type: ignore[assignment]
    trade_gate = None  # type: ignore[assignment]


def answer_chat(message: str, state: dict[str, Any] | None = None) -> dict[str, Any]:
    """Route a chat question to the right AI subsystem."""

    text = (message or "").strip()
    lower = text.lower()
    state = state or {}
    intent = detect_intent(lower)

    if intent == "news":
        return _answer_news(text)
    if intent == "risk":
        return _answer_risk(text)
    if intent == "trade_gate":
        return _answer_trade_gate(text)
    if intent == "bots":
        return _answer_bots(text)
    if intent == "learning":
        return _answer_learning(text)
    if intent == "portfolio":
        return _answer_portfolio(text, state)
    if intent == "costs":
        return _answer_costs(text, state)
    if intent == "market":
        return _answer_market(text)
    return _answer_overview(text, state)


def detect_intent(lower: str) -> str:
    """Detect which subsystem should answer."""

    if any(word in lower for word in ("сегодня", "произош", "новост", "что случ", "главное", "обсужд")):
        return "news"
    if any(word in lower for word in ("покуп", "купить", "продать", "лонг", "шорт", "торговать", "войти", "сделк")):
        return "trade_gate"
    if any(word in lower for word in ("риск", "опас", "почему наблюдать", "почему нельзя", "почему рискован")):
        return "risk"
    if any(word in lower for word in ("бот", "ии", "агент", "работает", "живой", "аудит", "кто не")):
        return "bots"
    if any(word in lower for word in ("науч", "обуч", "ошиб", "урок", "learning")):
        return "learning"
    if any(word in lower for word in ("портфель", "баланс", "pnl", "прибыл", "убыт", "позици")):
        return "portfolio"
    if any(word in lower for word in ("комисс", "выгод", "bybit", "безубыт", "fee", "спред")):
        return "costs"
    if any(word in lower for word in ("рынок", "режим", "тренд", "паник", "волат")):
        return "market"
    return "overview"


def _answer_news(question: str) -> dict[str, Any]:
    news = _safe_call(analyzed_news_payload, {})
    agents = _safe_call(run_news_agents, {})
    items = list(news.get("items", []))[:5] if isinstance(news, dict) else []
    summary = news.get("summary", {}) if isinstance(news, dict) else {}
    supervisor = agents.get("supervisor", {}) if isinstance(agents, dict) else {}
    lines = ["News Supervisor проверил новости."]
    if items:
        lines.append("Главное сейчас:")
        for item in items[:4]:
            title = item.get("title", "Новость")
            source = item.get("source_name", "источник")
            credibility = item.get("credibility_percent", item.get("trust_score", 0))
            lines.append(f"• {title} — {source}, достоверность {credibility}%")
    else:
        lines.append("Свежих заголовков пока нет. Нужно обновить RSS/источники.")
    if summary:
        lines.append(f"Средняя достоверность: {summary.get('average_credibility_percent', 0)}%. Нужно подтверждение: {summary.get('needs_confirmation', 0)}.")
    if supervisor:
        lines.append(f"Решение Supervisor: {supervisor.get('decision', 'WATCH')}.")
    return {"status": "ok", "intent": "news", "source_ai": "News Supervisor AI", "reply": "\n".join(lines), "data": {"summary": summary, "items": items, "supervisor": supervisor}}


def _answer_risk(question: str) -> dict[str, Any]:
    gate = _safe_call(trade_gate, {})
    regime = gate.get("market_regime", {}) if isinstance(gate, dict) else {}
    blockers = gate.get("blockers", []) if isinstance(gate, dict) else []
    warnings = gate.get("warnings", []) if isinstance(gate, dict) else []
    lines = ["Risk Engine и Trade Gate проверили ситуацию."]
    lines.append(str(gate.get("human_answer", "Риск нельзя оценить: Trade Gate недоступен.")))
    lines.append(f"Режим рынка: {regime.get('regime', 'unknown')}. Уровень риска: {regime.get('risk_level', 'unknown')}.")
    if blockers:
        lines.append("Главные блокеры:")
        lines.extend(f"• {item}" for item in blockers[:4])
    if warnings:
        lines.append("Предупреждения:")
        lines.extend(f"• {item}" for item in warnings[:3])
    return {"status": "ok", "intent": "risk", "source_ai": "Risk Engine AI + Trade Gate", "reply": "\n".join(lines), "data": gate}


def _answer_trade_gate(question: str) -> dict[str, Any]:
    gate = _safe_call(trade_gate, {})
    lines = ["Trade Decision AI спросил Risk Engine, Market Regime AI и News Supervisor."]
    lines.append(str(gate.get("human_answer", "Trade Gate недоступен.")))
    lines.append(f"Решение: {gate.get('decision', 'UNKNOWN')}. Demo: {'да' if gate.get('can_trade_demo') else 'нет'}. LIVE: {'да' if gate.get('can_trade_live') else 'нет'}.")
    if gate.get("blockers"):
        lines.append("Почему нельзя/опасно:")
        lines.extend(f"• {item}" for item in gate.get("blockers", [])[:4])
    return {"status": "ok", "intent": "trade_gate", "source_ai": "Trade Decision AI", "reply": "\n".join(lines), "data": gate}


def _answer_bots(question: str) -> dict[str, Any]:
    audit = _safe_call(audit_system_ai, {})
    scoreboard = audit.get("scoreboard", {}) if isinstance(audit, dict) else {}
    auditor = audit.get("auditor", {}) if isinstance(audit, dict) else {}
    counts = scoreboard.get("counts", {}) if isinstance(scoreboard, dict) else {}
    lines = ["System AI Auditor провёл проверку всех ИИ."]
    lines.append(str(auditor.get("summary", "Аудит недоступен.")))
    if counts:
        lines.append(f"Live: {counts.get('live', 0)}, Demo: {counts.get('demo', 0)}, ждут API: {counts.get('waiting_api', 0)}, disabled: {counts.get('disabled', 0)}.")
    weak = [item for item in audit.get("interviews", []) if item.get("verdict") in {"делает вид", "заглушка", "недоработан"}]
    if weak:
        lines.append("Слабые места:")
        for item in weak[:5]:
            lines.append(f"• {item.get('name')} — {item.get('verdict')}: {item.get('next_fix')}")
    return {"status": "ok", "intent": "bots", "source_ai": "System AI Auditor", "reply": "\n".join(lines), "data": audit}


def _answer_learning(question: str) -> dict[str, Any]:
    learning = _safe_call(learning_state, {})
    lessons = learning.get("active_rule_candidates", []) if isinstance(learning, dict) else []
    lines = ["Learning Engine 2.0 проверил уроки и кандидаты правил."]
    lines.append(f"Уроков сейчас: {learning.get('lesson_count', 0)}. Режим: {learning.get('mode', 'unknown')}.")
    if lessons:
        lines.append("Активные уроки:")
        for lesson in lessons[:4]:
            lines.append(f"• {lesson.get('lesson')} → правило: {lesson.get('new_rule')}")
    if learning.get("missing"):
        lines.append("Что ещё нужно:")
        lines.extend(f"• {item}" for item in learning.get("missing", [])[:3])
    return {"status": "ok", "intent": "learning", "source_ai": "Learning Engine AI", "reply": "\n".join(lines), "data": learning}


def _answer_portfolio(question: str, state: dict[str, Any]) -> dict[str, Any]:
    equity = state.get("equity", state.get("paper_equity", 0))
    pnl = state.get("net_pnl", state.get("pnl", state.get("paper_pnl", 0)))
    fees = state.get("total_fees", 0)
    decision = state.get("decision", "WATCH")
    risk = state.get("risk_level", "LOW")
    reply = f"Portfolio AI проверил демо-портфель. Equity: {equity} USDT. PnL: {pnl} USDT. Комиссии: {fees} USDT. Риск: {risk}. Решение AI: {decision}. Реальные ордера заблокированы."
    return {"status": "ok", "intent": "portfolio", "source_ai": "Portfolio & Reports AI", "reply": reply, "data": state}


def _answer_costs(question: str, state: dict[str, Any]) -> dict[str, Any]:
    costs = state.get("bybit_costs", {}) if isinstance(state, dict) else {}
    best = ((costs.get("best_trade_venue") or {}).get("best") or {}) if isinstance(costs, dict) else {}
    drag = state.get("commission_drag", 0)
    breakeven = state.get("break_even_price", "unknown")
    reply = "Exchange Cost AI проверил комиссии. "
    if best:
        reply += f"Лучший demo-вариант: {best.get('product')} / {best.get('liquidity')}, round-trip fee {best.get('round_trip_fee')}. "
    reply += f"Комиссионная нагрузка: {drag}. Break-even price: {breakeven}. Сделка выгодна только если движение перекрывает комиссии, spread и slippage."
    return {"status": "ok", "intent": "costs", "source_ai": "Exchange Cost AI", "reply": reply, "data": costs}


def _answer_market(question: str) -> dict[str, Any]:
    regime = _safe_call(market_regime, {})
    reply = f"Market Regime AI определил режим: {regime.get('regime', 'unknown')}. Риск: {regime.get('risk_level', 'unknown')}. Действие: {regime.get('recommended_action', 'WATCH')}. Причина: {regime.get('explanation', '')}"
    return {"status": "ok", "intent": "market", "source_ai": "Market Regime AI", "reply": reply, "data": regime}


def _answer_overview(question: str, state: dict[str, Any]) -> dict[str, Any]:
    gate = _safe_call(trade_gate, {})
    news = _safe_call(analyzed_news_payload, {})
    summary = news.get("summary", {}) if isinstance(news, dict) else {}
    reply = (
        "Я не отвечаю сам от себя: я спрашиваю нужных AI-ботов. "
        f"Сейчас Trade Gate говорит: {gate.get('decision', 'UNKNOWN')}. "
        f"Новости: средняя достоверность {summary.get('average_credibility_percent', 0)}%. "
        "Спроси: 'что сегодня произошло?', 'почему рисковано?', 'можно покупать?', 'какие ИИ не работают?', 'чему ты научился?'."
    )
    return {"status": "ok", "intent": "overview", "source_ai": "AI Chat Orchestrator", "reply": reply, "data": {"trade_gate": gate, "news_summary": summary}}


def _safe_call(fn: Any, fallback: Any) -> Any:
    if fn is None:
        return fallback
    try:
        return fn()
    except Exception as exc:  # pragma: no cover
        return {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
