"""Dashboard API and UI for the specialized News AI network."""

from __future__ import annotations

from html import escape
from typing import Any

from fastapi import Body, FastAPI
from fastapi.responses import HTMLResponse

from news_monitor.agent_network import (
    AGENTS,
    agent_detail,
    network_status,
    run_agent,
    run_due_agents,
    start_agent_network,
)
from news_monitor.news_autorun import refresh_news_if_stale


def install_news_agent_network_api(app: FastAPI) -> None:
    if getattr(app.state, "news_agent_network_api_installed", False):
        return
    app.state.news_agent_network_api_installed = True

    @app.on_event("startup")
    def news_agent_network_startup() -> None:
        app.state.news_agent_network = start_agent_network()

    @app.get("/api/news-agents/status")
    def news_agents_status() -> dict[str, Any]:
        refresh_news_if_stale(reason="news_agent_network_status")
        return network_status(run_due=True)

    @app.get("/api/news-agents")
    def news_agents() -> dict[str, Any]:
        return news_agents_status()

    @app.get("/api/news-agents/{agent_id}")
    def news_agent(agent_id: str) -> dict[str, Any]:
        return agent_detail(agent_id, run_now=False)

    @app.post("/api/news-agents/{agent_id}/run")
    def news_agent_run(agent_id: str) -> dict[str, Any]:
        refresh_news_if_stale(reason=f"news_agent_manual:{agent_id}")
        return run_agent(agent_id)

    @app.post("/api/news-agents/run-all")
    def news_agents_run_all(payload: dict[str, Any] | None = Body(default=None)) -> dict[str, Any]:
        refresh_news_if_stale(reason="news_agent_manual_all")
        return run_due_agents(force=bool((payload or {}).get("force", True)))

    @app.get("/news-agents", response_class=HTMLResponse)
    def news_agents_page() -> HTMLResponse:
        refresh_news_if_stale(reason="news_agent_page")
        return HTMLResponse(_render(network_status(run_due=True)))


def _render(payload: dict[str, Any]) -> str:
    agents = payload.get("agents", [])
    cards = "".join(_agent_card(agent) for agent in agents)
    coordinator = payload.get("coordinator", {})
    return f"""<!doctype html><html lang='ru'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>SharipovAI · News Agents</title><style>{_css()}</style></head><body><main><section class='hero'><span class='pill'>{escape(str(payload.get('status')))}</span><h1>Specialized News AI Network</h1><p>Каждый агент имеет собственный цикл, память, freshness, ошибки и маршруты к другим органам AI.</p><p><a href='/api/news-agents/status'>JSON status</a> · <a href='/api/social-news/rss/refresh'>Refresh RSS</a> · <a href='/realtime-status'>Realtime Status</a></p></section><section class='grid'>{cards}</section><section class='panel'><h2>World News Coordinator</h2><pre>{escape(str(coordinator))}</pre></section><script>setTimeout(()=>location.reload(),30000)</script></main></body></html>"""


def _agent_card(agent: dict[str, Any]) -> str:
    status = str(agent.get("status", "unknown"))
    cls = "ok" if status == "active" else "warn" if status in {"stale", "waiting_credentials"} else "bad"
    return f"""<article class='card'><div class='row'><h2>{escape(str(agent.get('name')))}</h2><span class='{cls}'>{escape(status)}</span></div><p>{escape(str(agent.get('mission', '')))}</p><div class='stats'><div><small>Health</small><b>{agent.get('health_score', 0)}%</b></div><div><small>Источники</small><b>{agent.get('source_count', 0)}</b></div><div><small>Материалы</small><b>{agent.get('item_count', 0)}</b></div><div><small>Память</small><b>{agent.get('memory_count', 0)}</b></div><div><small>Freshness</small><b>{agent.get('data_freshness_seconds')}</b></div><div><small>События</small><b>{agent.get('events_emitted', 0)}</b></div></div><p><b>Последнее действие:</b> {escape(str(agent.get('last_action', '')))}</p><p><b>Маршруты:</b> {escape(', '.join(agent.get('routes_to', [])))}</p><p><a href='/api/news-agents/{escape(str(agent.get('id')))}'>Открыть память/события</a></p></article>"""


def _css() -> str:
    return "body{margin:0;background:#07111f;color:#eef4ff;font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif}main{max-width:1280px;margin:auto;padding:18px}.hero,.panel,.card{background:#111827;border:1px solid #263245;border-radius:20px;padding:18px;margin:12px 0}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:12px}.row{display:flex;justify-content:space-between;gap:12px;align-items:center}.stats{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}.stats div{background:#0b1220;border-radius:12px;padding:10px}.stats small{display:block;color:#9db0cc}.stats b{font-size:18px}.pill,.ok,.warn,.bad{border-radius:999px;padding:5px 9px;font-weight:800}.pill,.ok{background:#10b981;color:#03130d}.warn{background:#f59e0b;color:#120a02}.bad{background:#ef4444;color:white}a{color:#60a5fa;font-weight:800}pre{white-space:pre-wrap}"
