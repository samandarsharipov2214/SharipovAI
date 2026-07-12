"""Dashboard API for canonical DB-backed News Intelligence with legacy app compatibility."""
from __future__ import annotations

from html import escape
from typing import Any

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import HTMLResponse

from news_intelligence.network import NewsAgentNetwork
from news_monitor.agent_bridge import bridge_events, bridge_status, start_agent_bridge
from news_monitor.agent_network import (
    agent_detail,
    network_status,
    run_agent,
    run_due_agents,
    start_agent_network,
)
from news_monitor.news_autorun import refresh_news_if_stale
from storage import ProjectDatabase, list_json_items


def install_news_agent_network_api(app: FastAPI) -> None:
    if getattr(app.state, "news_agent_network_api_installed", False):
        return
    app.state.news_agent_network_api_installed = True
    database = getattr(app.state, "project_database", None)
    if isinstance(database, ProjectDatabase):
        _install_canonical(app, database)
    else:
        _install_legacy(app)


def _install_canonical(app: FastAPI, database: ProjectDatabase) -> None:
    network = NewsAgentNetwork(database=database)
    app.state.news_agent_network = network

    @app.on_event("startup")
    def news_agent_network_startup() -> None:
        network.start()

    @app.on_event("shutdown")
    def news_agent_network_shutdown() -> None:
        network.stop()

    @app.get("/api/news-agents/status")
    def news_agents_status() -> dict[str, Any]:
        return _status(network, database)

    @app.get("/api/news-agents")
    def news_agents() -> dict[str, Any]:
        return news_agents_status()

    @app.get("/api/news-agents/{agent_id}")
    def news_agent(agent_id: str) -> dict[str, Any]:
        try:
            return {"status": "ok", **network.agent_snapshot(agent_id)}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/news-agents/{agent_id}/run")
    def news_agent_run(agent_id: str) -> dict[str, Any]:
        try:
            result = network.cycle(source_id=agent_id)
            return {"status": "ok", "cycle": result, **network.agent_snapshot(agent_id)}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/news-agents/run-all")
    def news_agents_run_all(payload: dict[str, Any] | None = Body(default=None)) -> dict[str, Any]:
        del payload
        return {"status": "ok", "cycle": network.cycle(), "network": _status(network, database)}

    @app.post("/api/news-agents/bridge")
    def news_agents_bridge() -> dict[str, Any]:
        return _bridge_status(database)

    @app.get("/news-agents", response_class=HTMLResponse)
    def news_agents_page() -> HTMLResponse:
        return HTMLResponse(_render(_status(network, database)))


def _install_legacy(app: FastAPI) -> None:
    """Keep independently-created FastAPI test/tools apps working without a DB."""
    @app.on_event("startup")
    def news_agent_network_startup() -> None:
        app.state.news_agent_network = start_agent_network()
        app.state.news_agent_bridge = start_agent_bridge()

    @app.get("/api/news-agents/status")
    def news_agents_status() -> dict[str, Any]:
        refresh_news_if_stale(reason="news_agent_network_status")
        payload = network_status(run_due=True)
        payload["bridge"] = bridge_status()
        return payload

    @app.get("/api/news-agents")
    def news_agents() -> dict[str, Any]:
        return news_agents_status()

    @app.get("/api/news-agents/{agent_id}")
    def news_agent(agent_id: str) -> dict[str, Any]:
        return agent_detail(agent_id, run_now=False)

    @app.post("/api/news-agents/{agent_id}/run")
    def news_agent_run(agent_id: str) -> dict[str, Any]:
        refresh_news_if_stale(reason=f"news_agent_manual:{agent_id}")
        result = run_agent(agent_id)
        result["bridge"] = bridge_events()
        return result

    @app.post("/api/news-agents/run-all")
    def news_agents_run_all(payload: dict[str, Any] | None = Body(default=None)) -> dict[str, Any]:
        refresh_news_if_stale(reason="news_agent_manual_all")
        result = run_due_agents(force=bool((payload or {}).get("force", True)))
        result["bridge"] = bridge_events()
        return result

    @app.post("/api/news-agents/bridge")
    def news_agents_bridge() -> dict[str, Any]:
        return bridge_events()

    @app.get("/news-agents", response_class=HTMLResponse)
    def news_agents_page() -> HTMLResponse:
        refresh_news_if_stale(reason="news_agent_page")
        payload = network_status(run_due=True)
        payload["bridge"] = bridge_status()
        return HTMLResponse(_render(payload))


def _status(network: NewsAgentNetwork, database: ProjectDatabase) -> dict[str, Any]:
    snapshot = network.snapshot()
    snapshot["status"] = "ok" if snapshot.get("database_backed") else "warning"
    snapshot["bridge"] = _bridge_status(database)
    snapshot["canonical_owner"] = "news_intelligence"
    snapshot["synthetic_fallback_used"] = False
    return snapshot


def _bridge_status(database: ProjectDatabase) -> dict[str, Any]:
    return {
        "status": "ok",
        "database_backed": True,
        "memory_records": len(list_json_items(database, "news_memory")),
        "event_records": len(list_json_items(database, "news_events")),
        "routes_to": ["decision_quality", "risk_engine", "portfolio_engine", "learning_engine"],
    }


def _render(payload: dict[str, Any]) -> str:
    agents = payload.get("agents", [])
    cards = "".join(_agent_card(agent) for agent in agents)
    bridge = payload.get("bridge", {})
    canonical = payload.get("canonical_owner") == "news_intelligence"
    heading = "News Intelligence" if canonical else "Specialized News AI Network"
    description = (
        "Источники, память и события используют общую ProjectDatabase. Синтетические новости запрещены."
        if canonical
        else "Каждый агент имеет собственный цикл, память, freshness, ошибки и маршруты к другим органам AI."
    )
    return f"""<!doctype html><html lang='ru'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>SharipovAI · News Intelligence</title><style>{_css()}</style></head><body><main><section class='hero'><span class='pill'>{escape(str(payload.get('status')))}</span><h1>{heading}</h1><p>{description}</p><p><a href='/api/news-agents/status'>JSON status</a> · <a href='/realtime-status'>Realtime Status</a></p></section><section class='panel'><h2>Общая память и связь</h2><p>Материалы: <b>{escape(str(bridge.get('memory_records', bridge.get('last_sent_count', 0))))}</b> · DB-backed: <b>{escape(str(bridge.get('database_backed', False)))}</b></p></section><section class='grid'>{cards}</section><script>setTimeout(()=>location.reload(),30000)</script></main></body></html>"""


def _agent_card(agent: dict[str, Any]) -> str:
    status = str(agent.get("status", "unknown"))
    cls = "ok" if status in {"active", "ok", "healthy"} else "warn" if status in {"idle", "stale", "waiting_credentials"} else "bad"
    agent_id = str(agent.get("source_id") or agent.get("id") or "unknown")
    name = str(agent.get("name") or agent.get("source_name") or agent_id)
    mission = escape(str(agent.get("mission", "")))
    return f"""<article class='card'><div class='row'><h2>{escape(name)}</h2><span class='{cls}'>{escape(status)}</span></div><p>{mission}</p><p><b>ID:</b> {escape(agent_id)}</p><p><b>Последнее действие:</b> {escape(str(agent.get('last_action') or agent.get('last_error') or 'ожидание'))}</p><p><a href='/api/news-agents/{escape(agent_id)}'>Открыть Evidence</a></p></article>"""


def _css() -> str:
    return "body{margin:0;background:#07111f;color:#eef4ff;font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif}main{max-width:1280px;margin:auto;padding:18px}.hero,.panel,.card{background:#111827;border:1px solid #263245;border-radius:20px;padding:18px;margin:12px 0}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:12px}.row{display:flex;justify-content:space-between;gap:12px;align-items:center}.pill,.ok,.warn,.bad{border-radius:999px;padding:5px 9px;font-weight:800}.pill,.ok{background:#10b981;color:#03130d}.warn{background:#f59e0b;color:#120a02}.bad{background:#ef4444;color:white}a{color:#60a5fa;font-weight:800}"


__all__ = [
    "install_news_agent_network_api",
    "refresh_news_if_stale",
    "network_status",
    "bridge_status",
    "start_agent_network",
    "start_agent_bridge",
    "agent_detail",
    "run_agent",
    "run_due_agents",
    "bridge_events",
]
