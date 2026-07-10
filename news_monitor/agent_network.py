"""Autonomous specialized News AI network for SharipovAI.

Each agent has an independent schedule, source ownership, memory, health,
freshness and event output. Only real saved RSS/API items are consumed.
One failed agent is isolated and cannot stop the rest of the network.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .storage import load_news_state

STATE_PATH = Path(os.getenv("NEWS_AGENT_NETWORK_STATE_FILE", "data/news_agent_network.json"))
MEMORY_LIMIT = max(50, int(os.getenv("NEWS_AGENT_MEMORY_LIMIT", "500") or 500))
EVENT_LIMIT = max(100, int(os.getenv("NEWS_AGENT_EVENT_LIMIT", "1000") or 1000))


@dataclass(frozen=True)
class AgentSpec:
    id: str
    name: str
    categories: tuple[str, ...]
    interval_seconds: int
    routes_to: tuple[str, ...]
    mission: str
    source_ids: tuple[str, ...] = ()


AGENTS: tuple[AgentSpec, ...] = (
    AgentSpec("politics_ai", "Politics AI", ("politics_official", "international_official", "regulation_official"), 120, ("economy_ai", "risk_engine", "world_coordinator"), "Политика, правительства, международные организации и регулирование."),
    AgentSpec("world_ai", "World News AI", ("world_news", "international_official"), 120, ("politics_ai", "risk_engine", "world_coordinator"), "Мировые события, конфликты и международная повестка."),
    AgentSpec("economy_ai", "Economy AI", ("macro_official", "world_finance"), 60, ("finance_ai", "crypto_ai", "risk_engine"), "Макроэкономика, центральные банки, инфляция и ставки."),
    AgentSpec("finance_ai", "Finance AI", ("world_finance", "macro_official"), 60, ("crypto_ai", "portfolio_engine", "risk_engine"), "Финансовые рынки, ликвидность и движение капитала."),
    AgentSpec("crypto_ai", "Crypto News AI", ("crypto_news", "exchange", "regulation_official"), 30, ("trading_ai", "risk_engine", "portfolio_engine", "learning_engine"), "Крипторынок, биржи, токены и отраслевые события."),
    AgentSpec("security_ai", "Security News AI", ("security", "tech_security"), 90, ("crypto_ai", "risk_engine", "security_cyber_ai"), "Взломы, уязвимости, инфраструктурные и киберриски."),
    AgentSpec("technology_ai", "Technology AI", ("tech_security",), 180, ("security_ai", "world_coordinator"), "Технологические изменения и инфраструктурные риски."),
    AgentSpec("sports_ai", "Sports News AI", ("sports",), 300, ("world_coordinator",), "Спортивные события, лиги и соревнования."),
    AgentSpec("weather_ai", "Weather & Disaster AI", ("weather", "weather_disaster"), 300, ("risk_engine", "world_coordinator"), "Погода, стихийные бедствия и чрезвычайные события."),
    AgentSpec("health_ai", "Health News AI", (), 600, ("world_coordinator", "risk_engine"), "Глобальное здравоохранение и официальные предупреждения.", ("who_news",)),
    AgentSpec("telegram_news_ai", "Telegram News AI", ("telegram_news",), 60, ("crypto_ai", "world_coordinator"), "Разрешённые Telegram-источники; требует credentials."),
    AgentSpec("x_news_ai", "X News AI", ("x_news",), 60, ("crypto_ai", "world_coordinator"), "Разрешённые X-источники; требует API credentials."),
    AgentSpec("youtube_news_ai", "YouTube News AI", ("youtube_news",), 300, ("world_coordinator",), "YouTube-источники; отделяет мнение от факта."),
)

_LOCK = threading.RLock()
_THREAD: threading.Thread | None = None
_STOP = threading.Event()


def network_enabled() -> bool:
    return os.getenv("NEWS_AGENT_NETWORK_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}


def start_agent_network() -> dict[str, Any]:
    """Bootstrap all agents once, then start the independent scheduler."""

    global _THREAD
    if not network_enabled():
        return {"status": "disabled", "thread_alive": False}
    bootstrap = run_due_agents(force=True)
    if _THREAD and _THREAD.is_alive():
        return {"status": "already_running", "thread_alive": True, "bootstrap": bootstrap}
    _STOP.clear()
    _THREAD = threading.Thread(target=_loop, name="news-agent-network", daemon=True)
    _THREAD.start()
    return {"status": "started", "thread_alive": True, "agent_count": len(AGENTS), "bootstrap": bootstrap}


def stop_agent_network() -> dict[str, Any]:
    _STOP.set()
    return {"status": "stopping", "thread_alive": bool(_THREAD and _THREAD.is_alive())}


def network_status(*, run_due: bool = False) -> dict[str, Any]:
    if run_due:
        run_due_agents()
    state = _load_state()
    agents = list(state.get("agents", {}).values())
    now = int(time.time())
    healthy = [
        agent for agent in agents
        if agent.get("status") == "active"
        and now - int(agent.get("last_run_at", 0) or 0) <= max(600, int(agent.get("interval_seconds", 60)) * 3)
    ]
    attention = [agent for agent in agents if agent.get("status") != "active"]
    expected_noncredential = len([spec for spec in AGENTS if spec.id not in {"telegram_news_ai", "x_news_ai", "youtube_news_ai"}])
    return {
        "status": "ok" if len(healthy) >= expected_noncredential and not state.get("network_error") else "warning",
        "generated_at": now,
        "thread_alive": bool(_THREAD and _THREAD.is_alive()),
        "agent_count": len(AGENTS),
        "initialized_count": len(agents),
        "healthy_count": len(healthy),
        "attention_count": len(attention),
        "agents": sorted(agents, key=lambda item: str(item.get("name"))),
        "events": list(state.get("events", []))[-100:],
        "routes": _routing_map(),
        "coordinator": _coordinator_summary(state),
        "network_error": state.get("network_error"),
        "network_error_at": state.get("network_error_at"),
    }


def run_due_agents(*, force: bool = False) -> dict[str, Any]:
    """Run every due agent, isolating failures per agent."""

    now = int(time.time())
    with _LOCK:
        state = _load_state()
        results: list[dict[str, Any]] = []
        for spec in AGENTS:
            previous = dict(state.get("agents", {}).get(spec.id, {}))
            last_run = int(previous.get("last_run_at", 0) or 0)
            if not force and now - last_run < spec.interval_seconds:
                continue
            try:
                result = _run_agent(spec, state, now)
            except Exception as exc:  # isolate one broken agent
                result = _agent_error(spec, previous, now, exc)
            state.setdefault("agents", {})[spec.id] = result
            results.append(result)
        state["last_network_cycle_at"] = now
        state["events"] = list(state.get("events", []))[-EVENT_LIMIT:]
        state.pop("network_error", None)
        state.pop("network_error_at", None)
        _save_state(state)
    return {"status": "ok", "ran": len(results), "results": results, "generated_at": now}


def agent_detail(agent_id: str, *, run_now: bool = False) -> dict[str, Any]:
    spec = _spec(agent_id)
    if not spec:
        return {"status": "not_found", "agent_id": agent_id}
    if run_now:
        run_agent(agent_id)
    state = _load_state()
    agent = state.get("agents", {}).get(agent_id)
    if not agent:
        run_agent(agent_id)
        state = _load_state()
        agent = state.get("agents", {}).get(agent_id, {})
    memory = [item for item in state.get("memory", []) if item.get("agent_id") == agent_id][-MEMORY_LIMIT:]
    events = [item for item in state.get("events", []) if item.get("agent_id") == agent_id][-100:]
    return {"status": "ok", "agent": agent, "memory": memory, "events": events}


def run_agent(agent_id: str) -> dict[str, Any]:
    spec = _spec(agent_id)
    if not spec:
        return {"status": "not_found", "agent_id": agent_id}
    with _LOCK:
        state = _load_state()
        previous = dict(state.get("agents", {}).get(spec.id, {}))
        now = int(time.time())
        try:
            result = _run_agent(spec, state, now)
        except Exception as exc:
            result = _agent_error(spec, previous, now, exc)
        state.setdefault("agents", {})[spec.id] = result
        state["events"] = list(state.get("events", []))[-EVENT_LIMIT:]
        _save_state(state)
    return {"status": "ok" if result.get("status") != "error" else "error", "agent": result}


def _run_agent(spec: AgentSpec, state: dict[str, Any], now: int) -> dict[str, Any]:
    news_state = load_news_state()
    news = news_state.get("news", {}) if isinstance(news_state.get("news"), dict) else {}
    items = [item for item in news.get("items", []) if isinstance(item, dict)]
    sources_root = news_state.get("sources") or {}
    sources = sources_root.get("sources", []) if isinstance(sources_root, dict) else []
    owned_sources = [source for source in sources if isinstance(source, dict) and _owns_source(spec, source)]
    owned_ids = {str(source.get("id")) for source in owned_sources}
    owned_items = [item for item in items if str(item.get("source_id")) in owned_ids]
    credential_only = bool(owned_sources) and all(bool(source.get("requires_credentials")) for source in owned_sources)
    errors = _source_errors(news_state, owned_ids)
    last_refresh = int(news_state.get("last_refresh_at", 0) or 0)
    freshness = max(0, now - last_refresh) if last_refresh else None
    status = "active"
    if credential_only and not owned_items:
        status = "waiting_credentials"
    elif errors and not owned_items:
        status = "error"
    elif not owned_items:
        status = "stale"
    credibility = round(sum(float(item.get("credibility_percent", 0) or 0) for item in owned_items) / len(owned_items), 1) if owned_items else 0.0
    urgent = [item for item in owned_items if item.get("urgency") == "high"]
    confirmation = [item for item in owned_items if item.get("needs_confirmation")]
    impact_score = round(sum(float(item.get("impact_score", 0) or 0) for item in owned_items), 2)
    health = _health(status, len(owned_sources), len(owned_items), credibility, freshness, len(errors))

    existing_keys = {str(item.get("key")) for item in state.get("memory", [])}
    new_memory: list[dict[str, Any]] = []
    for item in owned_items[:50]:
        key = _memory_key(spec.id, item)
        if key in existing_keys:
            continue
        memory_item = {
            "key": key,
            "agent_id": spec.id,
            "created_at": now,
            "published_at": item.get("published_at"),
            "title": item.get("title"),
            "source_id": item.get("source_id"),
            "credibility_percent": item.get("credibility_percent", 0),
            "urgency": item.get("urgency", "low"),
            "impact": item.get("impact", "neutral"),
            "impact_score": item.get("impact_score", 0),
            "needs_confirmation": bool(item.get("needs_confirmation")),
            "url": item.get("url", ""),
        }
        state.setdefault("memory", []).append(memory_item)
        existing_keys.add(key)
        new_memory.append(memory_item)
    state["memory"] = list(state.get("memory", []))[-MEMORY_LIMIT * len(AGENTS):]
    emitted = _emit_events(spec, new_memory, now, state)
    return {
        "id": spec.id,
        "name": spec.name,
        "mission": spec.mission,
        "status": status,
        "health_score": health,
        "interval_seconds": spec.interval_seconds,
        "last_run_at": now,
        "last_seen": now,
        "data_last_refresh_at": last_refresh,
        "data_freshness_seconds": freshness,
        "source_count": len(owned_sources),
        "item_count": len(owned_items),
        "new_memory_count": len(new_memory),
        "memory_count": len([item for item in state.get("memory", []) if item.get("agent_id") == spec.id]),
        "average_credibility_percent": credibility,
        "high_urgency": len(urgent),
        "needs_confirmation": len(confirmation),
        "aggregate_impact_score": impact_score,
        "routes_to": list(spec.routes_to),
        "events_emitted": emitted,
        "errors": errors,
        "last_action": _last_action(status, len(owned_items), len(new_memory), emitted),
    }


def _emit_events(spec: AgentSpec, new_items: list[dict[str, Any]], now: int, state: dict[str, Any]) -> int:
    emitted = 0
    known = {str(event.get("event_id")) for event in state.get("events", [])}
    for item in new_items[:20]:
        urgent = item.get("urgency") == "high"
        material = abs(float(item.get("impact_score", 0) or 0)) >= 30
        if not urgent and not material and not item.get("needs_confirmation"):
            continue
        event_id = "NE-" + hashlib.sha256(str(item.get("key")).encode("utf-8")).hexdigest()[:20].upper()
        if event_id in known:
            continue
        event = {
            "event_id": event_id,
            "created_at": now,
            "agent_id": spec.id,
            "agent_name": spec.name,
            "title": item.get("title"),
            "source_id": item.get("source_id"),
            "url": item.get("url", ""),
            "impact": item.get("impact", "neutral"),
            "impact_score": item.get("impact_score", 0),
            "credibility_percent": item.get("credibility_percent", 0),
            "needs_confirmation": bool(item.get("needs_confirmation")),
            "routes_to": list(spec.routes_to),
            "action": "BLOCK_AND_VERIFY" if item.get("needs_confirmation") and urgent else "ANALYZE_AND_ROUTE",
        }
        state.setdefault("events", []).append(event)
        known.add(event_id)
        emitted += 1
    return emitted


def _owns_source(spec: AgentSpec, source: dict[str, Any]) -> bool:
    source_id = str(source.get("id", ""))
    category = str(source.get("category", ""))
    return source_id in spec.source_ids or category in spec.categories


def _memory_key(agent_id: str, item: dict[str, Any]) -> str:
    raw = "|".join([
        agent_id,
        str(item.get("source_id", "")),
        str(item.get("url", "")),
        str(item.get("title", "")),
        str(item.get("published_at", "")),
    ])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _source_errors(news_state: dict[str, Any], owned_ids: set[str]) -> list[dict[str, Any]]:
    errors = news_state.get("last_refresh_errors", [])
    if not isinstance(errors, list):
        return []
    normalized: list[dict[str, Any]] = []
    for error in errors:
        if isinstance(error, dict):
            source_id = str(error.get("source_id", ""))
            if not owned_ids or source_id in owned_ids:
                normalized.append(error)
        elif error:
            normalized.append({"source_id": "unknown", "error": str(error)})
    return normalized


def _health(status: str, source_count: int, item_count: int, credibility: float, freshness: int | None, error_count: int) -> int:
    score = 70 + min(source_count * 2, 15) + min(item_count, 10)
    if credibility >= 70:
        score += 8
    score -= {"stale": 30, "waiting_credentials": 40, "error": 45}.get(status, 0)
    if freshness is None or freshness > 900:
        score -= 20
    elif freshness > 300:
        score -= 10
    score -= min(error_count * 3, 15)
    return max(0, min(100, score))


def _last_action(status: str, item_count: int, new_count: int, emitted: int) -> str:
    if status == "active":
        return f"проверил {item_count} материалов, запомнил {new_count} новых и отправил {emitted} событий"
    if status == "waiting_credentials":
        return "ждёт credentials; не выдаёт себя за активный live-agent"
    if status == "error":
        return "обнаружил ошибки своих источников и изолировал их"
    return "источники назначены, но свежих материалов нет"


def _agent_error(spec: AgentSpec, previous: dict[str, Any], now: int, exc: Exception) -> dict[str, Any]:
    return {
        **previous,
        "id": spec.id,
        "name": spec.name,
        "mission": spec.mission,
        "status": "error",
        "health_score": 0,
        "interval_seconds": spec.interval_seconds,
        "last_run_at": now,
        "last_seen": now,
        "routes_to": list(spec.routes_to),
        "errors": [{"error": f"{type(exc).__name__}: {exc}"}],
        "last_action": "внутренняя ошибка изолирована; остальные News AI продолжают работу",
    }


def _spec(agent_id: str) -> AgentSpec | None:
    return next((item for item in AGENTS if item.id == agent_id), None)


def _routing_map() -> dict[str, list[str]]:
    return {spec.id: list(spec.routes_to) for spec in AGENTS}


def _coordinator_summary(state: dict[str, Any]) -> dict[str, Any]:
    agents = list(state.get("agents", {}).values())
    events = list(state.get("events", []))[-100:]
    return {
        "name": "World News Coordinator",
        "status": "active" if agents else "not_started",
        "last_cycle_at": state.get("last_network_cycle_at", 0),
        "agent_count": len(agents),
        "active_agents": len([agent for agent in agents if agent.get("status") == "active"]),
        "stale_agents": [agent.get("name") for agent in agents if agent.get("status") != "active"],
        "events_last_100": len(events),
        "block_and_verify_events": len([event for event in events if event.get("action") == "BLOCK_AND_VERIFY"]),
        "routes": sorted({route for event in events for route in event.get("routes_to", [])}),
    }


def _default_state() -> dict[str, Any]:
    return {"status": "ok", "agents": {}, "memory": [], "events": [], "last_network_cycle_at": 0}


def _load_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return _default_state()
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else _default_state()
    except Exception:
        return _default_state()


def _save_state(state: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = STATE_PATH.with_suffix(STATE_PATH.suffix + ".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(STATE_PATH)


def _loop() -> None:
    while not _STOP.is_set():
        try:
            run_due_agents()
        except Exception as exc:  # only network-level failures reach here
            with _LOCK:
                state = _load_state()
                state["network_error"] = f"{type(exc).__name__}: {exc}"
                state["network_error_at"] = int(time.time())
                _save_state(state)
        _STOP.wait(5)
