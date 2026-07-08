"""Public health/check/news endpoints for iPhone-friendly verification."""

from __future__ import annotations

from html import escape
from typing import Any

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from news_monitor.agents import run_news_agents
from news_monitor.ai_auditor import audit_news_ai
from news_monitor.analyzer import analyzed_news_payload
from news_monitor.sources import sources_payload


def install_public_check_api(app: FastAPI) -> None:
    """Install public AI check, audit, and live news endpoints."""

    if getattr(app.state, "public_check_api_installed", False):
        return
    app.state.public_check_api_installed = True

    @app.get("/api/check-ai")
    def check_ai() -> dict[str, object]:
        sources = sources_payload()
        agents = run_news_agents()
        news = analyzed_news_payload()
        supervisor = agents.get("supervisor", {}) if isinstance(agents, dict) else {}
        return {
            "status": "ok",
            "service": "SharipovAI",
            "message": "SharipovAI backend работает. News Supervisor и под-AI доступны.",
            "news_supervisor": supervisor,
            "agent_count": supervisor.get("agent_count", 0),
            "total_sources": sources.get("total", 0),
            "source_categories": sorted((sources.get("by_category") or {}).keys()),
            "hot_news": news.get("items", [])[:8],
            "agents": agents.get("agents", []) if isinstance(agents, dict) else [],
            "audit_url": "/ai-audit",
            "next_urls": {"news_live": "/news-live", "ai_audit": "/ai-audit", "mini_app": "/", "sources": "/api/social-news/sources", "agents": "/api/social-news/agents", "supervisor": "/api/social-news/supervisor"},
        }

    @app.get("/api/ai-audit")
    def ai_audit_api() -> dict[str, object]:
        """Run AI auditor interview."""

        return audit_news_ai()

    @app.get("/ai-audit", response_class=HTMLResponse)
    def ai_audit_page() -> HTMLResponse:
        """Show AI auditor interview report."""

        return HTMLResponse(_render_audit_page())

    @app.get("/check-ai", response_class=HTMLResponse)
    def check_ai_page() -> HTMLResponse:
        return HTMLResponse(_render_ai_page(title="Проверка ИИ", mode="check"))

    @app.get("/news-live", response_class=HTMLResponse)
    def news_live_page() -> HTMLResponse:
        return HTMLResponse(_render_ai_page(title="Новости SharipovAI", mode="news"))

    @app.get("/api/news-live")
    def news_live_api() -> dict[str, object]:
        sources = sources_payload()
        agents = run_news_agents()
        news = analyzed_news_payload()
        return {
            "status": "ok",
            "sources": {"total": sources.get("total", 0), "categories": sorted((sources.get("by_category") or {}).keys())},
            "supervisor": agents.get("supervisor", {}),
            "agents": agents.get("agents", []),
            "hot_news": news.get("items", [])[:12],
            "summary": news.get("summary", {}),
        }


def _render_audit_page() -> str:
    audit = audit_news_ai()
    auditor = audit.get("auditor", {}) if isinstance(audit, dict) else {}
    interviews = list(audit.get("interviews", [])) if isinstance(audit, dict) else []
    rows = "".join(_audit_row(item) for item in interviews)
    actions = "".join(f"<li>{escape(str(action))}</li>" for action in audit.get("priority_actions", []))
    return f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>SharipovAI · AI Audit</title><style>
body{{margin:0;background:#070b12;color:#eef4ff;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}}main{{padding:18px;max-width:1100px;margin:auto}}.card{{background:#111827;border:1px solid #243044;border-radius:18px;padding:16px;margin:12px 0;box-shadow:0 20px 60px rgba(0,0,0,.25)}}.grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}}.stat{{background:#0b1220;border:1px solid #1f2a3d;border-radius:14px;padding:12px}}.stat small{{display:block;color:#8ea2c4}}.stat b{{font-size:22px}}table{{width:100%;border-collapse:collapse}}td,th{{padding:10px;border-bottom:1px solid #243044;text-align:left;vertical-align:top}}small{{display:block;color:#8ea2c4;margin-top:4px}}a{{color:#60a5fa;font-weight:800}}.ok{{display:inline-block;background:#10b981;color:#03130d;border-radius:999px;padding:7px 12px;font-weight:900}}.warn{{display:inline-block;background:#f59e0b;color:#120a02;border-radius:999px;padding:7px 12px;font-weight:900}}.bad{{display:inline-block;background:#ef4444;color:#fff;border-radius:999px;padding:7px 12px;font-weight:900}}@media(max-width:720px){{.grid{{grid-template-columns:1fr}}table{{font-size:13px}}td,th{{padding:8px}}}}
</style></head><body><main>
<section class="card"><span class="ok">AI AUDIT</span><h1>Беседа с ИИ и проверка работоспособности</h1><p>{escape(str(auditor.get('summary', '')))}</p><p><a href="/news-live">Новости</a> · <a href="/check-ai">Проверка ИИ</a> · <a href="/api/ai-audit">JSON аудит</a></p></section>
<section class="card"><h2>{escape(str(auditor.get('name', 'AI Auditor')))}</h2><div class="grid"><div class="stat"><small>Оценка</small><b>{escape(str(auditor.get('overall_grade', 'UNKNOWN')))}</b></div><div class="stat"><small>Работают</small><b>{auditor.get('working', 0)} / {auditor.get('total', 0)}</b></div><div class="stat"><small>Недоработаны</small><b>{auditor.get('underbuilt', 0)}</b></div><div class="stat"><small>Делают вид/заглушки</small><b>{auditor.get('fake_like', 0)}</b></div></div></section>
<section class="card"><h2>Итог беседы с каждым ИИ</h2><table><thead><tr><th>AI</th><th>Вердикт</th><th>Health</th><th>Источники</th><th>Проблемы</th><th>Что делать</th></tr></thead><tbody>{rows}</tbody></table></section>
<section class="card"><h2>Приоритет доработок</h2><ol>{actions}</ol></section>
</main></body></html>"""


def _audit_row(item: dict[str, Any]) -> str:
    verdict = str(item.get("verdict", "unknown"))
    css = "ok" if verdict == "работает" else "bad" if verdict in {"делает вид", "заглушка"} else "warn"
    problems = "<br>".join(escape(str(problem)) for problem in item.get("problems", []))
    return (
        f"<tr><td><b>{escape(str(item.get('name', 'AI')))}</b><small>{escape(str(item.get('id', '')))}</small></td>"
        f"<td><span class='{css}'>{escape(verdict)}</span></td>"
        f"<td>{escape(str(item.get('health_score', 0)))}%</td>"
        f"<td>{escape(str(item.get('source_count', 0)))} / items {escape(str(item.get('item_count', 0)))}</td>"
        f"<td><small>{problems}</small></td>"
        f"<td>{escape(str(item.get('next_fix', '')))}</td></tr>"
    )


def _render_ai_page(*, title: str, mode: str) -> str:
    sources = sources_payload()
    agents = run_news_agents()
    news = analyzed_news_payload()
    supervisor = agents.get("supervisor", {}) if isinstance(agents, dict) else {}
    hot_news = list(news.get("items", []))[:10]
    agent_rows = "".join(_agent_row(agent) for agent in agents.get("agents", []))
    hot_cards = "".join(_news_card(item) for item in hot_news)
    page_title = escape(title)
    badge = "НОВОСТИ LIVE" if mode == "news" else "BACKEND LIVE"
    intro = "Главные обсуждаемые новости и работа всех новостных под-AI." if mode == "news" else "Проверка главного News Supervisor AI и всех под-AI."
    return f"""<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>SharipovAI · {page_title}</title><style>body{{margin:0;background:#070b12;color:#eef4ff;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}}main{{padding:18px;max-width:1080px;margin:auto}}.card{{background:#111827;border:1px solid #243044;border-radius:18px;padding:16px;margin:12px 0;box-shadow:0 20px 60px rgba(0,0,0,.25)}}h1{{font-size:28px;margin:0 0 8px}}h2{{font-size:20px;margin:0 0 10px}}p{{line-height:1.45}}.ok{{display:inline-block;background:#10b981;color:#03130d;border-radius:999px;padding:7px 12px;font-weight:900}}.warn{{display:inline-block;background:#f59e0b;color:#120a02;border-radius:999px;padding:7px 12px;font-weight:900}}.grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}}.stat{{background:#0b1220;border:1px solid #1f2a3d;border-radius:14px;padding:12px}}.stat small{{display:block;color:#8ea2c4}}.stat b{{font-size:22px}}.news-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:10px}}.news{{background:#0b1220;border:1px solid #1f2a3d;border-radius:16px;padding:13px}}.news b{{display:block;margin-bottom:8px}}.news small{{color:#8ea2c4;display:block;line-height:1.4}}table{{width:100%;border-collapse:collapse}}td,th{{padding:10px;border-bottom:1px solid #243044;text-align:left;vertical-align:top}}small{{display:block;color:#8ea2c4;margin-top:4px}}a{{color:#60a5fa;font-weight:800}}.topnav{{display:flex;gap:12px;flex-wrap:wrap;margin-top:12px}}@media(max-width:720px){{.grid{{grid-template-columns:1fr}}table{{font-size:13px}}td,th{{padding:8px}}}}</style></head><body><main><section class="card"><span class="ok">{badge}</span><h1>{page_title}</h1><p>{intro}</p><div class="topnav"><a href="/">Главная</a><a href="/news-live">Новости</a><a href="/check-ai">Проверить ИИ</a><a href="/ai-audit">Беседа с ИИ</a><a href="/api/news-live">JSON</a></div></section><section class="card"><h2>{escape(str(supervisor.get('name', 'Main News Supervisor AI')))}</h2><div class="grid"><div class="stat"><small>Решение</small><b>{escape(str(supervisor.get('decision', 'UNKNOWN')))}</b></div><div class="stat"><small>Под-AI</small><b>{supervisor.get('agent_count', 0)}</b></div><div class="stat"><small>Источников</small><b>{sources.get('total', 0)}</b></div><div class="stat"><small>Средняя достоверность</small><b>{supervisor.get('average_credibility_percent', 0)}%</b></div></div><p>{escape(str(supervisor.get('assessment', '')))}</p></section><section class="card"><h2>Самые обсуждаемые новости</h2><div class="news-grid">{hot_cards}</div></section><section class="card"><h2>Подсистемные News AI-боты</h2><table><thead><tr><th>AI</th><th>Статус</th><th>Health</th><th>Источники</th><th>Достоверность</th></tr></thead><tbody>{agent_rows}</tbody></table></section><section class="card"><h2>Что доказывает, что ИИ живой</h2><p>Если здесь меняются новости, есть источники, есть под-AI и главный Supervisor выдаёт решение — система работает. Для честного аудита открой «Беседа с ИИ».</p><p><a href="/api/social-news/sources">Источники</a> · <a href="/api/social-news/agents">Агенты</a> · <a href="/api/social-news/supervisor">Supervisor</a></p></section></main></body></html>"""


def _agent_row(agent: dict[str, Any]) -> str:
    status = escape(str(agent.get("status", "unknown")))
    badge = "ok" if status == "active" else "warn"
    return f"<tr><td><b>{escape(str(agent.get('name', 'AI')))}</b><small>{escape(str(agent.get('responsibility', '')))}</small></td><td><span class='{badge}'>{status}</span></td><td>{escape(str(agent.get('health_score', 0)))}%</td><td>{escape(str(agent.get('source_count', 0)))}</td><td>{escape(str(agent.get('average_credibility_percent', 0)))}%</td></tr>"


def _news_card(item: dict[str, Any]) -> str:
    title = escape(str(item.get("title", "Новость")))
    source = escape(str(item.get("source_name", "Источник")))
    credibility = escape(str(item.get("credibility_percent", item.get("trust_score", 0))))
    status = escape(str(item.get("verification_status", "наблюдать")))
    risk = escape(str(item.get("error_risk", "средний")))
    action = escape(str(item.get("ai_action", "WATCH")))
    return f"<article class='news'><b>{title}</b><small>{source}</small><small>Достоверность: {credibility}% · {status}</small><small>Риск ошибки: {risk} · AI: {action}</small></article>"
