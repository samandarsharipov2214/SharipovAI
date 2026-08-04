"""Dashboard API for the canonical DB-backed News Intelligence network.

All compatibility functions route to the same ``NewsAgentNetwork`` and
``ProjectDatabase``. News delivery to Decision Quality, Risk, Portfolio and
Learning is a shared-database contract, not a separate message-bus thread.
"""
from __future__ import annotations

from collections.abc import Callable
from html import escape
from typing import Any

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import HTMLResponse

from news_intelligence.network import NewsAgentNetwork
from storage import ProjectDatabase, list_json_items

_NETWORK: NewsAgentNetwork | None = None
_DATABASE: ProjectDatabase | None = None


def _database_for(app: FastAPI | None = None) -> ProjectDatabase:
    global _DATABASE
    database = getattr(getattr(app, "state", None), "project_database", None)
    if not isinstance(database, ProjectDatabase):
        database = _DATABASE or ProjectDatabase()
        database.initialize()
        if app is not None:
            app.state.project_database = database
    _DATABASE = database
    return database


def _same_database(left: Any, right: Any) -> bool:
    left_dsn = str(getattr(left, "dsn", "") or "")
    right_dsn = str(getattr(right, "dsn", "") or "")
    return bool(left_dsn and right_dsn and left_dsn == right_dsn)


def _network_for(app: FastAPI | None = None) -> NewsAgentNetwork:
    global _NETWORK
    database = _database_for(app)
    attached = getattr(getattr(app, "state", None), "news_agent_network", None)
    if isinstance(attached, NewsAgentNetwork) and _same_database(attached.database, database):
        _NETWORK = attached
        return attached

    if isinstance(attached, NewsAgentNetwork):
        try:
            attached.stop()
        except Exception:
            pass

    if _NETWORK is None or not _same_database(getattr(_NETWORK, "database", None), database):
        _NETWORK = NewsAgentNetwork(database=database)
    if app is not None:
        app.state.news_agent_network = _NETWORK
    return _NETWORK


def refresh_news_if_stale(*, app: FastAPI | None = None, **_: Any) -> dict[str, Any]:
    """Compatibility alias that observes canonical freshness without a GET mutation."""

    snapshot = network_status(run_due=False, app=app)
    return {
        "status": "fresh" if snapshot.get("status") == "ok" else "degraded",
        "canonical_owner": "news_intelligence",
        "synthetic_fallback_used": False,
        "mutation_performed": False,
    }


def network_status(*, run_due: bool = False, app: FastAPI | None = None) -> dict[str, Any]:
    network = _network_for(app)
    if run_due:
        network.cycle()
    return _status(network, _database_for(app))


def bridge_status(*, app: FastAPI | None = None) -> dict[str, Any]:
    return _bridge_status(_database_for(app))


def start_agent_network(*, app: FastAPI | None = None) -> dict[str, Any]:
    _network_for(app).start()
    return {"status": "started", "canonical_owner": "news_intelligence"}


def start_agent_bridge(*, app: FastAPI | None = None) -> dict[str, Any]:
    return {"status": "ready", **bridge_status(app=app)}


def agent_detail(agent_id: str, *, run_now: bool = False, app: FastAPI | None = None) -> dict[str, Any]:
    network = _network_for(app)
    if run_now:
        network.cycle(source_id=agent_id)
    return {"status": "ok", "agent": network.agent_snapshot(agent_id)}


def run_agent(agent_id: str, *, app: FastAPI | None = None) -> dict[str, Any]:
    network = _network_for(app)
    cycle = network.cycle(source_id=agent_id)
    return {
        "status": "ok",
        "cycle": cycle,
        "agent": network.agent_snapshot(agent_id),
        "bridge": bridge_events(app=app),
    }


def run_due_agents(*, force: bool = False, app: FastAPI | None = None) -> dict[str, Any]:
    cycle = _network_for(app).cycle()
    ran = int(cycle.get("ran", cycle.get("fetched_sources", 0)) or 0) if isinstance(cycle, dict) else 0
    return {"status": "ok", "ran": ran, "force": bool(force), "cycle": cycle}


def bridge_events(*, app: FastAPI | None = None) -> dict[str, Any]:
    payload = bridge_status(app=app)
    return {
        "status": payload.get("status", "ok"),
        "delivery_mode": "shared_database",
        "consumer_active": bool(payload.get("consumer_active")),
        "sent": None,
        "sent_count_semantics": "not_applicable_shared_database",
        **payload,
    }


def install_news_agent_network_api(app: FastAPI) -> None:
    if getattr(app.state, "news_agent_network_api_installed", False):
        return
    app.state.news_agent_network_api_installed = True
    network = _network_for(app)

    _register_event(app, "startup", network.start)
    _register_event(app, "shutdown", network.stop)

    @app.get("/api/news-agents/status")
    def news_agents_status() -> dict[str, Any]:
        refresh_news_if_stale(app=app, reason="api_news_agents_status")
        payload = network_status(run_due=False, app=app)
        payload["bridge"] = bridge_status(app=app)
        return payload

    @app.get("/api/news-agents")
    def news_agents() -> dict[str, Any]:
        return news_agents_status()

    @app.get("/api/news-agents/{agent_id}")
    def news_agent(agent_id: str) -> dict[str, Any]:
        try:
            return agent_detail(agent_id, run_now=False, app=app)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/news-agents/{agent_id}/run")
    def news_agent_run(agent_id: str) -> dict[str, Any]:
        try:
            result = run_agent(agent_id, app=app)
            if not isinstance(result, dict):
                raise TypeError("run_agent must return a mapping")
            if "bridge" not in result:
                result = {**result, "bridge": bridge_events(app=app)}
            return result
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/news-agents/run-all")
    def news_agents_run_all(payload: dict[str, Any] | None = Body(default=None)) -> dict[str, Any]:
        force = bool((payload or {}).get("force", False))
        return {
            **run_due_agents(force=force, app=app),
            "network": network_status(run_due=False, app=app),
        }

    @app.post("/api/news-agents/bridge")
    def news_agents_bridge() -> dict[str, Any]:
        return bridge_events(app=app)

    @app.get("/news-agents", response_class=HTMLResponse)
    def news_agents_page() -> HTMLResponse:
        return HTMLResponse(_render(news_agents_status()))


def _register_event(app: FastAPI, event: str, handler: Callable[[], None]) -> None:
    add_event_handler = getattr(app, "add_event_handler", None)
    if callable(add_event_handler):
        add_event_handler(event, handler)
        return
    handlers = getattr(getattr(app, "router", None), f"on_{event}", None)
    if isinstance(handlers, list):
        handlers.append(handler)


def _status(network: NewsAgentNetwork, database: ProjectDatabase) -> dict[str, Any]:
    snapshot = network.snapshot()
    runtime_status = str(snapshot.get("status", "stopped"))
    worker_running = runtime_status == "running"
    canonical_database = _same_database(getattr(network, "database", None), database)
    last_error = str(snapshot.get("last_error") or "")
    snapshot["runtime_status"] = runtime_status
    snapshot["worker_running"] = worker_running
    snapshot["status"] = "ok" if worker_running and canonical_database and not last_error else "warning"
    snapshot["database_backed"] = canonical_database
    snapshot["bridge"] = _bridge_status(database)
    snapshot["canonical_owner"] = "news_intelligence"
    snapshot["synthetic_fallback_used"] = False
    return snapshot


def _bridge_status(database: ProjectDatabase) -> dict[str, Any]:
    memory_records = len(list_json_items(database, "news_memory"))
    event_records = len(list_json_items(database, "news_events"))
    return {
        "status": "ok",
        "database_backed": True,
        "delivery_mode": "shared_database",
        "consumer_active": True,
        "memory_records": memory_records,
        "event_records": event_records,
        "sent_count": None,
        "sent_count_semantics": "not_applicable_shared_database",
        "routes_to": ["decision_quality", "risk_engine", "portfolio_engine", "learning_engine"],
    }


def _render(payload: dict[str, Any]) -> str:
    agents = payload.get("agents", [])
    cards = "".join(_agent_card(agent) for agent in agents)
    hub = payload.get("hub", {})
    bridge = payload.get("bridge", {})
    return f"""<!doctype html><html lang='ru'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>SharipovAI · Specialized News AI Network</title><style>{_css()}</style></head><body><main><section class='hero'><span class='pill'>{escape(str(payload.get('status')))}</span><h1>Specialized News AI Network</h1><p>Источники, память и события используют общую ProjectDatabase. Синтетические новости запрещены.</p><p><a href='/api/news-agents/status'>JSON status</a> · <a href='/realtime-status'>Realtime Status</a></p></section><section class='panel'><h2>Общая память</h2><p>Материалы: <b>{escape(str(bridge.get('memory_records', 0)))}</b> · события: <b>{escape(str(bridge.get('event_records', 0)))}</b> · delivery: <b>{escape(str(bridge.get('delivery_mode')))}</b></p><pre>{escape(str(hub))}</pre></section><section class='grid'>{cards}</section><script>setTimeout(()=>location.reload(),30000)</script></main></body></html>"""


def _agent_card(agent: dict[str, Any]) -> str:
    status = str(agent.get("status", "unknown"))
    cls = "ok" if status in {"active", "ok", "healthy"} else "warn" if status in {"idle", "stale"} else "bad"
    agent_id = str(agent.get("source_id") or agent.get("id") or "unknown")
    name = str(agent.get("name") or agent.get("source_name") or agent_id)
    return f"""<article class='card'><div class='row'><h2>{escape(name)}</h2><span class='{cls}'>{escape(status)}</span></div><p><b>ID:</b> {escape(agent_id)}</p><p><b>Последнее действие:</b> {escape(str(agent.get('last_action') or agent.get('last_error') or 'ожидание'))}</p><p><a href='/api/news-agents/{escape(agent_id)}'>Открыть Evidence</a></p></article>"""


def _css() -> str:
    return "body{margin:0;background:#07111f;color:#eef4ff;font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif}main{max-width:1280px;margin:auto;padding:18px}.hero,.panel,.card{background:#111827;border:1px solid #263245;border-radius:20px;padding:18px;margin:12px 0}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:12px}.row{display:flex;justify-content:space-between;gap:12px;align-items:center}.pill,.ok,.warn,.bad{border-radius:999px;padding:5px 9px;font-weight:800}.pill,.ok{background:#10b981;color:#03130d}.warn{background:#f59e0b;color:#120a02}.bad{background:#ef4444;color:white}a{color:#60a5fa;font-weight:800}pre{white-space:pre-wrap}"


__all__ = [
    "agent_detail",
    "bridge_events",
    "bridge_status",
    "install_news_agent_network_api",
    "network_status",
    "refresh_news_if_stale",
    "run_agent",
    "run_due_agents",
    "start_agent_bridge",
    "start_agent_network",
]
