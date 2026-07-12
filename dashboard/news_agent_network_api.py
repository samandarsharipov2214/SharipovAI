"""Dashboard API for the canonical DB-backed News Intelligence network."""
from __future__ import annotations

from html import escape
from typing import Any

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import HTMLResponse

from news_intelligence.network import NewsAgentNetwork
from storage import ProjectDatabase, list_json_items


def install_news_agent_network_api(app: FastAPI) -> None:
    if getattr(app.state, "news_agent_network_api_installed", False):
        return
    database = getattr(app.state, "project_database", None)
    if not isinstance(database, ProjectDatabase):
        raise RuntimeError("ProjectDatabase must be installed before News Intelligence")
    app.state.news_agent_network_api_installed = True
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
    hub = payload.get("hub", {})
    bridge = payload.get("bridge", {})
    return f"""<!doctype html><html lang='ru'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>SharipovAI · News Intelligence</title><style>{_css()}</style></head><body><main><section class='hero'><span class='pill'>{escape(str(payload.get('status')))}</span><h1>News Intelligence</h1><p>Источники, память и события используют общую ProjectDatabase. Синтетические новости запрещены.</p><p><a href='/api/news-agents/status'>JSON status</a> · <a href='/realtime-status'>Realtime Status</a></p></section><section class='panel'><h2>Общая память</h2><p>Материалы: <b>{escape(str(bridge.get('memory_records', 0)))}</b> · события: <b>{escape(str(bridge.get('event_records', 0)))}</b> · DB-backed: <b>{escape(str(bridge.get('database_backed')))}</b></p><pre>{escape(str(hub))}</pre></section><section class='grid'>{cards}</section><script>setTimeout(()=>location.reload(),30000)</script></main></body></html>"""


def _agent_card(agent: dict[str, Any]) -> str:
    status = str(agent.get("status", "unknown"))
    cls = "ok" if status in {"active", "ok", "healthy"} else "warn" if status in {"idle", "stale"} else "bad"
    agent_id = str(agent.get("source_id") or agent.get("id") or "unknown")
    name = str(agent.get("name") or agent.get("source_name") or agent_id)
    return f"""<article class='card'><div class='row'><h2>{escape(name)}</h2><span class='{cls}'>{escape(status)}</span></div><p><b>ID:</b> {escape(agent_id)}</p><p><b>Последнее действие:</b> {escape(str(agent.get('last_action') or agent.get('last_error') or 'ожидание'))}</p><p><a href='/api/news-agents/{escape(agent_id)}'>Открыть Evidence</a></p></article>"""


def _css() -> str:
    return "body{margin:0;background:#07111f;color:#eef4ff;font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif}main{max-width:1280px;margin:auto;padding:18px}.hero,.panel,.card{background:#111827;border:1px solid #263245;border-radius:20px;padding:18px;margin:12px 0}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:12px}.row{display:flex;justify-content:space-between;gap:12px;align-items:center}.pill,.ok,.warn,.bad{border-radius:999px;padding:5px 9px;font-weight:800}.pill,.ok{background:#10b981;color:#03130d}.warn{background:#f59e0b;color:#120a02}.bad{background:#ef4444;color:white}a{color:#60a5fa;font-weight:800}pre{white-space:pre-wrap}"


__all__ = ["install_news_agent_network_api"]
