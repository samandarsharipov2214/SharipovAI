"""Public health/check endpoints for iPhone-friendly verification."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from news_monitor.agents import run_news_agents
from news_monitor.sources import sources_payload


def install_public_check_api(app: FastAPI) -> None:
    """Install public AI check endpoints."""

    if getattr(app.state, "public_check_api_installed", False):
        return
    app.state.public_check_api_installed = True

    @app.get("/api/check-ai")
    def check_ai() -> dict[str, object]:
        """Return compact system check for SharipovAI."""

        sources = sources_payload()
        agents = run_news_agents()
        supervisor = agents.get("supervisor", {}) if isinstance(agents, dict) else {}
        return {
            "status": "ok",
            "service": "SharipovAI",
            "message": "SharipovAI backend работает. News Supervisor и под-AI доступны.",
            "news_supervisor": supervisor,
            "agent_count": supervisor.get("agent_count", 0),
            "total_sources": sources.get("total", 0),
            "source_categories": sorted((sources.get("by_category") or {}).keys()),
            "agents": agents.get("agents", []) if isinstance(agents, dict) else [],
            "next_urls": {
                "mini_app": "/",
                "sources": "/api/social-news/sources",
                "agents": "/api/social-news/agents",
                "supervisor": "/api/social-news/supervisor",
            },
        }

    @app.get("/check-ai", response_class=HTMLResponse)
    def check_ai_page() -> HTMLResponse:
        """Return simple mobile page to verify AI without API tools."""

        sources = sources_payload()
        agents = run_news_agents()
        supervisor = agents.get("supervisor", {}) if isinstance(agents, dict) else {}
        rows = "".join(
            f"<tr><td><b>{agent.get('name')}</b><small>{agent.get('responsibility')}</small></td>"
            f"<td>{agent.get('status')}</td><td>{agent.get('health_score')}%</td>"
            f"<td>{agent.get('source_count')}</td><td>{agent.get('average_credibility_percent')}%</td></tr>"
            for agent in agents.get("agents", [])
        )
        return HTMLResponse(
            f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>SharipovAI · Проверка ИИ</title>
  <style>
    body{{margin:0;background:#070b12;color:#eef4ff;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}}
    main{{padding:18px;max-width:980px;margin:auto}}
    .card{{background:#111827;border:1px solid #243044;border-radius:18px;padding:16px;margin:12px 0;box-shadow:0 20px 60px rgba(0,0,0,.25)}}
    h1{{font-size:28px;margin:0 0 8px}} h2{{font-size:20px;margin:0 0 10px}}
    .ok{{display:inline-block;background:#10b981;color:#03130d;border-radius:999px;padding:7px 12px;font-weight:800}}
    .grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}}
    .stat{{background:#0b1220;border:1px solid #1f2a3d;border-radius:14px;padding:12px}}
    .stat small{{display:block;color:#8ea2c4}} .stat b{{font-size:22px}}
    table{{width:100%;border-collapse:collapse}} td,th{{padding:10px;border-bottom:1px solid #243044;text-align:left;vertical-align:top}} small{{display:block;color:#8ea2c4;margin-top:4px}}
    a{{color:#60a5fa}} .warn{{color:#fbbf24}}
  </style>
</head>
<body>
<main>
  <section class="card">
    <span class="ok">BACKEND LIVE</span>
    <h1>SharipovAI работает</h1>
    <p>Эта страница проверяет главный News Supervisor AI и под-AI без Postman, без команд и без сложных ссылок.</p>
  </section>
  <section class="card">
    <h2>{supervisor.get('name', 'Main News Supervisor AI')}</h2>
    <div class="grid">
      <div class="stat"><small>Решение</small><b>{supervisor.get('decision', 'UNKNOWN')}</b></div>
      <div class="stat"><small>Под-AI</small><b>{supervisor.get('agent_count', 0)}</b></div>
      <div class="stat"><small>Источников</small><b>{sources.get('total', 0)}</b></div>
      <div class="stat"><small>Средняя достоверность</small><b>{supervisor.get('average_credibility_percent', 0)}%</b></div>
    </div>
    <p>{supervisor.get('assessment', '')}</p>
  </section>
  <section class="card">
    <h2>Подсистемные AI</h2>
    <table><thead><tr><th>AI</th><th>Статус</th><th>Health</th><th>Источники</th><th>Достоверность</th></tr></thead><tbody>{rows}</tbody></table>
  </section>
  <section class="card">
    <h2>Быстрые проверки</h2>
    <p><a href="/api/check-ai">/api/check-ai</a></p>
    <p><a href="/api/social-news/sources">/api/social-news/sources</a></p>
    <p><a href="/api/social-news/agents">/api/social-news/agents</a></p>
    <p><a href="/api/social-news/supervisor">/api/social-news/supervisor</a></p>
    <p class="warn">Если здесь всё работает, а Mini App старый — сделай Render Manual Deploy и перезапусти Telegram Mini App.</p>
  </section>
</main>
</body>
</html>"""
        )
