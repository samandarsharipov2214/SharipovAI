"""Unified AI Chat Orchestrator for SharipovAI web, Mini App and Telegram.

The same routing rules are used everywhere. A user can talk to the General
Controller or address a specific internal bot, inspect its recent actions,
request a self-check, pause its paper actions, or send its errors to Learning.
"""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
import os

try:
    from ai_evidence import system_scoreboard
    from learning_engine_v2 import learning_state
    from news_monitor.agents import run_news_agents
    from news_monitor.analyzer import analyzed_news_payload
    from system_ai_auditor import audit_system_ai
    from trading_intelligence import market_regime, trade_gate
    from learning.bot_communication import BotCommunicationNetwork
except Exception:  # pragma: no cover
    system_scoreboard = learning_state = run_news_agents = analyzed_news_payload = None
    audit_system_ai = market_regime = trade_gate = BotCommunicationNetwork = None

AGENTS: dict[str, dict[str, Any]] = {
    "general_controller": {"name": "General Controller", "aliases": ("генеральный", "главный ии", "general controller", "general_controller"), "role": "Контролирует всех ботов, конфликты, цели, простои и финальные решения."},
    "market_agent": {"name": "Market Agent", "aliases": ("market agent", "market_agent", "рыночный бот", "маркет агент"), "role": "Анализирует тренд, объём, импульс, уровни и структуру рынка."},
    "news_agent": {"name": "News Agent", "aliases": ("news agent", "news_agent", "новостной бот", "ньюс агент"), "role": "Проверяет новости, источники, достоверность и правило 2+ подтверждений."},
    "risk_engine": {"name": "Risk Engine", "aliases": ("risk engine", "risk_engine", "риск бот", "риск-бот"), "role": "Считает риск, просадку, лимиты и блокирует опасные действия."},
    "portfolio_engine": {"name": "Portfolio Engine", "aliases": ("portfolio engine", "portfolio_engine", "портфельный бот"), "role": "Следит за балансом, позициями, PnL и комиссиями."},
    "paper_trading_bot": {"name": "Paper Trading Bot", "aliases": ("paper trading bot", "paper_trading_bot", "демо бот", "торговый бот"), "role": "Исполняет только paper/demo-сделки и ведёт журнал исполнения."},
    "confidence_engine": {"name": "Confidence Engine", "aliases": ("confidence engine", "confidence_engine", "бот уверенности"), "role": "Оценивает силу сигнала и вероятность ошибки."},
    "consensus_engine": {"name": "Consensus Engine", "aliases": ("consensus engine", "consensus_engine", "бот консенсуса"), "role": "Сравнивает голоса агентов и выявляет конфликт."},
    "stress_bot": {"name": "Stress Bot", "aliases": ("stress bot", "stress_bot", "стресс бот"), "role": "Моделирует кризисы и проверяет защиту капитала."},
    "learning_engine": {"name": "Learning Engine", "aliases": ("learning engine", "learning_engine", "обучающий бот"), "role": "Разбирает ошибки, формирует уроки и новые правила."},
    "security_guard": {"name": "Security Guard", "aliases": ("security guard", "security_guard", "бот безопасности"), "role": "Блокирует LIVE без разрешения и контролирует безопасность."},
}


def answer_chat(message: str, state: dict[str, Any] | None = None) -> dict[str, Any]:
    text = (message or "").strip()
    lower = text.lower()
    state = state or {}

    agent_id = detect_agent(lower)
    if agent_id:
        return _answer_agent(agent_id, text, state)

    intent = detect_intent(lower)
    if intent == "news": return _answer_news(text)
    if intent == "risk": return _answer_risk(text)
    if intent == "trade_gate": return _answer_trade_gate(text)
    if intent == "bots": return _answer_bots(text)
    if intent == "learning": return _answer_learning(text)
    if intent == "portfolio": return _answer_portfolio(text, state)
    if intent == "costs": return _answer_costs(text, state)
    if intent == "market": return _answer_market(text)
    if intent == "timeline": return _answer_timeline(text)
    return _answer_overview(text, state)


def detect_agent(lower: str) -> str | None:
    normalized = lower.replace("-", " ").replace("_", " ")
    for agent_id, meta in AGENTS.items():
        names = (agent_id, meta["name"].lower(), *meta["aliases"])
        if any(str(name).replace("_", " ") in normalized for name in names):
            return agent_id
    if lower.startswith("/agent "):
        token = lower.split(maxsplit=2)[1].replace("-", "_")
        return token if token in AGENTS else None
    return None


def detect_intent(lower: str) -> str:
    if any(word in lower for word in ("журнал", "таймлайн", "timeline", "что делал", "действия по времени")): return "timeline"
    if any(word in lower for word in ("сегодня", "произош", "новост", "что случ", "главное", "обсужд")): return "news"
    if any(word in lower for word in ("покуп", "купить", "продать", "лонг", "шорт", "торговать", "войти", "сделк")): return "trade_gate"
    if any(word in lower for word in ("риск", "опас", "почему наблюдать", "почему нельзя", "почему рискован")): return "risk"
    if any(word in lower for word in ("бот", "ии", "агент", "работает", "живой", "аудит", "кто не")): return "bots"
    if any(word in lower for word in ("науч", "обуч", "ошиб", "урок", "learning")): return "learning"
    if any(word in lower for word in ("портфель", "баланс", "pnl", "прибыл", "убыт", "позици")): return "portfolio"
    if any(word in lower for word in ("комисс", "выгод", "bybit", "безубыт", "fee", "спред")): return "costs"
    if any(word in lower for word in ("рынок", "режим", "тренд", "паник", "волат")): return "market"
    return "overview"


def _network() -> Any:
    if BotCommunicationNetwork is None:
        return None
    path = Path(os.getenv("BOT_COMMUNICATION_DB")) if os.getenv("BOT_COMMUNICATION_DB") else None
    return BotCommunicationNetwork(path)


def _agent_action(lower: str) -> str:
    if any(x in lower for x in ("тест адекватности", "проверь себя", "self check", "самопровер")): return "self_check"
    if any(x in lower for x in ("пауза", "останови", "pause")): return "pause"
    if any(x in lower for x in ("отправь в learning", "отправь в обучение", "разбери ошибку")): return "learn"
    if any(x in lower for x in ("журнал", "действия", "что делал", "таймлайн", "timeline")): return "timeline"
    if any(x in lower for x in ("отчет", "отчёт", "статус", "report")): return "report"
    return "chat"


def _answer_agent(agent_id: str, question: str, state: dict[str, Any]) -> dict[str, Any]:
    meta = AGENTS.get(agent_id, AGENTS["general_controller"])
    action = _agent_action(question.lower())
    net = _network()
    saved: dict[str, Any] = {}
    if net is not None:
        try:
            sender = "security_guard" if agent_id == "general_controller" else "general_controller"
            saved = net.send_message(sender=sender, recipient=agent_id, message_type="command" if action != "chat" else "question", topic="unified_chat", payload={"text": question, "source": "telegram_or_web", "action": action, "user_message": True}, priority="high" if action in {"pause", "self_check"} else "normal")
        except Exception as exc:
            saved = {"status": "error", "error": f"{type(exc).__name__}: {exc}"}

    if action == "timeline":
        return _agent_timeline(agent_id, meta, saved)
    if action == "self_check":
        reply = f"{meta['name']} выполнил самопроверку. Роль: {meta['role']} Критерии: источник данных, последняя активность, ошибки, соответствие зоне ответственности. Результат: команда записана; фактический verdict берётся из System AI Auditor."
    elif action == "pause":
        reply = f"{meta['name']}: запрос на паузу записан только для paper/demo-действий. LIVE по-прежнему заблокирован. Генеральный контролёр должен подтвердить изменение состояния."
    elif action == "learn":
        reply = f"{meta['name']}: последние ошибки и вопрос отправлены в Learning Engine. Новое правило нельзя считать внедрённым, пока нет evidence и повторной проверки."
    elif action == "report":
        reply = _agent_report(agent_id, meta, state)
    else:
        reply = _agent_chat(agent_id, meta, question, state)

    return {"status": "ok", "intent": "agent_chat", "source_ai": meta["name"], "reply": reply, "data": {"agent_id": agent_id, "role": meta["role"], "action": action, "message_bus": saved}}


def _agent_report(agent_id: str, meta: dict[str, Any], state: dict[str, Any]) -> str:
    if agent_id == "risk_engine": return _answer_risk("")["reply"]
    if agent_id == "market_agent": return _answer_market("")["reply"]
    if agent_id == "news_agent": return _answer_news("")["reply"]
    if agent_id == "learning_engine": return _answer_learning("")["reply"]
    if agent_id in {"portfolio_engine", "paper_trading_bot"}: return _answer_portfolio("", state)["reply"]
    if agent_id == "general_controller": return _answer_bots("")["reply"] + "\n" + _answer_trade_gate("")["reply"]
    return f"{meta['name']} активен в своей зоне: {meta['role']} Для полного verdict нужен live heartbeat и evidence, а не декоративный процент."


def _agent_chat(agent_id: str, meta: dict[str, Any], question: str, state: dict[str, Any]) -> str:
    if agent_id == "risk_engine": return _answer_risk(question)["reply"]
    if agent_id == "market_agent": return _answer_market(question)["reply"]
    if agent_id == "news_agent": return _answer_news(question)["reply"]
    if agent_id == "learning_engine": return _answer_learning(question)["reply"]
    if agent_id in {"portfolio_engine", "paper_trading_bot"}: return _answer_portfolio(question, state)["reply"]
    if agent_id == "consensus_engine": return _answer_trade_gate(question)["reply"]
    if agent_id == "general_controller": return "General Controller собрал ответы агентов.\n" + _answer_trade_gate(question)["reply"]
    return f"{meta['name}:} {meta['role']} Вопрос принят и записан в общий durable message bus. Ответ не должен выходить за мою зону ответственности."


def _agent_timeline(agent_id: str, meta: dict[str, Any], saved: dict[str, Any]) -> dict[str, Any]:
    net = _network()
    messages: list[dict[str, Any]] = []
    if net is not None:
        try:
            inbox = net.inbox(agent_id, unread_only=False)
            outbox = net.outbox(agent_id)
            messages = sorted([*inbox, *outbox], key=lambda x: str(x.get("created_at", x.get("time", ""))), reverse=True)[:10]
        except Exception:
            messages = []
    lines = [f"Журнал {meta['name']}:"]
    if not messages:
        lines.append("• Подтверждённых записей пока нет. Фиктивный timeline не создаётся.")
    for item in messages:
        ts = item.get("created_at") or item.get("time") or "время неизвестно"
        direction = f"{item.get('sender', '?')} → {item.get('recipient', '?')}"
        topic = item.get("topic", item.get("message_type", "event"))
        lines.append(f"• {ts} · {direction} · {topic}")
    return {"status": "ok", "intent": "agent_timeline", "source_ai": meta["name"], "reply": "\n".join(lines), "data": {"agent_id": agent_id, "messages": messages, "message_bus": saved}}


def _answer_timeline(question: str) -> dict[str, Any]:
    return _answer_agent("general_controller", question, {})


def _answer_news(question: str) -> dict[str, Any]:
    news = _safe_call(analyzed_news_payload, {})
    agents = _safe_call(run_news_agents, {})
    items = list(news.get("items", []))[:5] if isinstance(news, dict) else []
    summary = news.get("summary", {}) if isinstance(news, dict) else {}
    supervisor = agents.get("supervisor", {}) if isinstance(agents, dict) else {}
    lines = ["News Supervisor проверил новости."]
    if items:
        lines.append("Главное сейчас:")
        for item in items[:4]: lines.append(f"• {item.get('title','Новость')} — {item.get('source_name','источник')}, достоверность {item.get('credibility_percent', item.get('trust_score',0))}%")
    else: lines.append("Свежих заголовков пока нет. BUY по слухам запрещён.")
    lines.append(f"Средняя достоверность: {summary.get('average_credibility_percent',0)}%. Нужно подтверждение: {summary.get('needs_confirmation',0)}.")
    if supervisor: lines.append(f"Решение Supervisor: {supervisor.get('decision','WATCH')}.")
    return {"status":"ok","intent":"news","source_ai":"News Agent","reply":"\n".join(lines),"data":{"summary":summary,"items":items,"supervisor":supervisor}}


def _answer_risk(question: str) -> dict[str, Any]:
    gate = _safe_call(trade_gate,{})
    regime = gate.get("market_regime",{}) if isinstance(gate,dict) else {}
    lines=["Risk Engine и Trade Gate проверили ситуацию.",str(gate.get("human_answer","Риск нельзя оценить: Trade Gate недоступен.")),f"Режим рынка: {regime.get('regime','unknown')}. Уровень риска: {regime.get('risk_level','unknown')}."]
    if gate.get("blockers"): lines += ["Главные блокеры:",*[f"• {x}" for x in gate.get("blockers",[])[:4]]]
    if gate.get("warnings"): lines += ["Предупреждения:",*[f"• {x}" for x in gate.get("warnings",[])[:3]]]
    return {"status":"ok","intent":"risk","source_ai":"Risk Engine","reply":"\n".join(lines),"data":gate}


def _answer_trade_gate(question: str) -> dict[str, Any]:
    gate=_safe_call(trade_gate,{})
    lines=["Trade Decision AI спросил Risk Engine, Market Agent, News Agent и Consensus Engine.",str(gate.get("human_answer","Trade Gate недоступен.")),f"Решение: {gate.get('decision','UNKNOWN')}. Paper/demo: {'да' if gate.get('can_trade_demo') else 'нет'}. LIVE: {'да' if gate.get('can_trade_live') else 'нет'}." ]
    if gate.get("blockers"): lines += ["Почему нельзя/опасно:",*[f"• {x}" for x in gate.get("blockers",[])[:4]]]
    return {"status":"ok","intent":"trade_gate","source_ai":"General Controller + Trade Gate","reply":"\n".join(lines),"data":gate}


def _answer_bots(question: str) -> dict[str, Any]:
    audit=_safe_call(audit_system_ai,{})
    scoreboard=audit.get("scoreboard",{}) if isinstance(audit,dict) else {}
    auditor=audit.get("auditor",{}) if isinstance(audit,dict) else {}
    counts=scoreboard.get("counts",{}) if isinstance(scoreboard,dict) else {}
    lines=["System AI Auditor провёл проверку всех ИИ.",str(auditor.get("summary","Аудит недоступен."))]
    if counts: lines.append(f"Live: {counts.get('live',0)}, Demo: {counts.get('demo',0)}, ждут API: {counts.get('waiting_api',0)}, disabled: {counts.get('disabled',0)}.")
    weak=[x for x in audit.get("interviews",[]) if x.get("verdict") in {"делает вид","заглушка","недоработан","частично работает"}]
    if weak:
        lines.append("Слабые места:")
        for item in weak[:5]: lines.append(f"• {item.get('name')} — {item.get('verdict')}: {item.get('next_fix')}")
    lines.append("Для отдельного диалога напиши: Risk Engine, дай отчёт; News Agent, покажи журнал; /agent learning_engine проверь себя.")
    return {"status":"ok","intent":"bots","source_ai":"General Controller / System AI Auditor","reply":"\n".join(lines),"data":audit}


def _answer_learning(question: str) -> dict[str, Any]:
    learning=_safe_call(learning_state,{})
    lessons=learning.get("active_rule_candidates",[]) if isinstance(learning,dict) else []
    lines=["Learning Engine 2.0 проверил уроки и кандидаты правил.",f"Уроков: {learning.get('lesson_count',0)}. Режим: {learning.get('mode','unknown')}."]
    for lesson in lessons[:4]: lines.append(f"• {lesson.get('lesson')} → правило: {lesson.get('new_rule')}")
    if learning.get("missing"): lines += ["Что ещё нужно:",*[f"• {x}" for x in learning.get("missing",[])[:3]]]
    return {"status":"ok","intent":"learning","source_ai":"Learning Engine","reply":"\n".join(lines),"data":learning}


def _answer_portfolio(question: str,state: dict[str,Any]) -> dict[str,Any]:
    equity=state.get("equity",state.get("paper_equity",0)); pnl=state.get("net_pnl",state.get("pnl",state.get("paper_pnl",0))); fees=state.get("total_fees",0)
    reply=f"Portfolio Engine проверил paper-realism портфель. Equity: {equity} USDT. PnL: {pnl} USDT. Комиссии: {fees} USDT. Риск: {state.get('risk_level','LOW')}. Решение: {state.get('decision','WATCH')}. Реальные ордера заблокированы."
    return {"status":"ok","intent":"portfolio","source_ai":"Portfolio Engine","reply":reply,"data":state}


def _answer_costs(question: str,state: dict[str,Any]) -> dict[str,Any]:
    costs=state.get("bybit_costs",{}) if isinstance(state,dict) else {}; best=((costs.get("best_trade_venue") or {}).get("best") or {}) if isinstance(costs,dict) else {}
    reply="Exchange Cost AI проверил комиссии. "
    if best: reply += f"Лучший paper-вариант: {best.get('product')} / {best.get('liquidity')}, round-trip fee {best.get('round_trip_fee')}. "
    reply += f"Комиссионная нагрузка: {state.get('commission_drag',0)}. Break-even: {state.get('break_even_price','unknown')}."
    return {"status":"ok","intent":"costs","source_ai":"Portfolio Engine / Exchange Cost AI","reply":reply,"data":costs}


def _answer_market(question: str) -> dict[str,Any]:
    regime=_safe_call(market_regime,{})
    reply=f"Market Agent определил режим: {regime.get('regime','unknown')}. Риск: {regime.get('risk_level','unknown')}. Действие: {regime.get('recommended_action','WATCH')}. Причина: {regime.get('explanation','')}"
    return {"status":"ok","intent":"market","source_ai":"Market Agent","reply":reply,"data":regime}


def _answer_overview(question: str,state: dict[str,Any]) -> dict[str,Any]:
    gate=_safe_call(trade_gate,{}); news=_safe_call(analyzed_news_payload,{}); summary=news.get("summary",{}) if isinstance(news,dict) else {}
    reply=("Я использую ту же Agent Control архитектуру, что и новый сайт. Можно обращаться к каждому боту отдельно. " f"Сейчас Trade Gate: {gate.get('decision','UNKNOWN')}. Новости: достоверность {summary.get('average_credibility_percent',0)}%. " "Примеры: «Risk Engine, дай отчёт», «News Agent, покажи журнал», «Learning Engine, проверь себя», «General Controller, кто простаивает?»." )
    return {"status":"ok","intent":"overview","source_ai":"General Controller","reply":reply,"data":{"trade_gate":gate,"news_summary":summary,"agents":list(AGENTS)}}


def _safe_call(fn: Any,fallback: Any) -> Any:
    if fn is None: return fallback
    try: return fn()
    except Exception as exc: return {"status":"error","error":f"{type(exc).__name__}: {exc}"}
