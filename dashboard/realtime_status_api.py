"""Unified realtime status API for SharipovAI.

Every live surface must show the same truth. Reading this endpoint must not
fabricate agent activity or decorative quality percentages.
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from agent_health import build_agent_health_snapshot
from news_monitor.agent_bridge import bridge_status
from news_monitor.agent_network import network_status
from news_monitor.news_autorun import news_autorun_status, refresh_news_if_stale
from news_monitor.storage import load_news_state
from paper_activity_autorun import paper_activity_autorun_status
from paper_activity_engine import PaperActivityEngine
from sharipovai_constitution import constitution_snapshot, now_iso
from telegram_health import telegram_health

STARTED_AT = int(time.time())


def install_realtime_status_api(app: FastAPI) -> None:
    if getattr(app.state, "realtime_status_api_installed", False):
        return
    app.state.realtime_status_api_installed = True

    @app.get("/api/realtime/status")
    def realtime_status() -> dict[str, Any]:
        return build_realtime_status()

    @app.get("/api/agent-health")
    def agent_health() -> dict[str, Any]:
        return build_agent_health_snapshot()

    @app.get("/realtime-status", response_class=HTMLResponse)
    def realtime_status_page() -> HTMLResponse:
        return HTMLResponse(_render(build_realtime_status()))


def build_realtime_status() -> dict[str, Any]:
    news_refresh = refresh_news_if_stale(reason="api_realtime_status_stale_check")
    account_payload = PaperActivityEngine().state(catch_up=True)
    account_summary = account_payload.get("summary", {})
    news_state = load_news_state()
    news_summary = (news_state.get("news") or {}).get("summary", {}) if isinstance(news_state.get("news"), dict) else {}
    tick_age = account_summary.get("last_tick_age_seconds")
    news_age = _age(news_state.get("last_refresh_at"))
    specialized_news = network_status(run_due=True)
    news_bridge = bridge_status()
    warnings: list[str] = []

    if tick_age is None:
        warnings.append("Virtual Account ещё не сделал execution tick.")
    elif int(tick_age) > 180:
        warnings.append(f"Virtual Account stale: последний tick {tick_age} сек. назад.")
    if news_age is None:
        warnings.append("News Monitor ещё не сделал real RSS refresh.")
    elif int(news_age) > 300:
        warnings.append(f"News Monitor stale: последний refresh {news_age} сек. назад.")
    if specialized_news.get("status") != "ok":
        warnings.append(
            "Specialized News AI degraded: "
            f"healthy={specialized_news.get('healthy_count', 0)}/{specialized_news.get('agent_count', 0)}, "
            f"attention={specialized_news.get('attention_count', 0)}."
        )
    if not specialized_news.get("thread_alive"):
        warnings.append("Specialized News AI background thread is not alive.")
    if not news_bridge.get("thread_alive"):
        warnings.append("News AI → system bots bridge thread is not alive.")
    if news_bridge.get("last_failures"):
        warnings.append(f"News bridge has {len(news_bridge.get('last_failures', []))} delivery failures.")

    telegram = telegram_health()
    if telegram.get("verdict") != "working":
        warnings.append(f"Telegram не полностью working: {telegram.get('verdict')}")
    agents = build_agent_health_snapshot()
    if agents.get("status") != "ok":
        summary = agents.get("summary", {})
        warnings.append(
            "AI agents not fully proven: "
            f"working={summary.get('working', 0)}, degraded={summary.get('degraded', 0)}, unknown={summary.get('unknown', 0)}."
        )

    return {
        "status": "ok" if not warnings else "warning",
        "generated_at": now_iso(),
        "uptime_seconds": int(time.time()) - STARTED_AT,
        "constitution": constitution_snapshot(),
        "warnings": warnings,
        "agents": agents,
        "virtual_account": {
            "autorun": paper_activity_autorun_status(),
            "summary": account_summary,
            "trade_count": account_summary.get("trade_count", 0),
            "open_positions": account_summary.get("open_positions", 0),
            "closed_positions": account_summary.get("closed_positions", 0),
            "net_pnl": account_summary.get("net_pnl", 0),
            "total_fees": account_summary.get("total_fees", 0),
            "last_tick_age_seconds": tick_age,
            "mode": account_payload.get("mode"),
            "execution_mode": account_payload.get("execution_mode", account_summary.get("execution_mode")),
            "real_orders_blocked": True,
        },
        "paper_activity": {"deprecated": True, "use": "virtual_account", "summary": account_summary},
        "news": {
            "autorun": news_autorun_status(),
            "refresh_status": news_refresh,
            "source_mode": news_state.get("source_mode"),
            "last_refresh_at": news_state.get("last_refresh_at"),
            "last_refresh_age_seconds": news_age,
            "item_count": news_summary.get("total", news_state.get("last_refresh_item_count", 0)),
            "high_urgency": news_summary.get("high_urgency", 0),
            "needs_confirmation": news_summary.get("needs_confirmation", 0),
            "average_credibility_percent": news_summary.get("average_credibility_percent", 0),
            "errors": news_state.get("last_refresh_errors", []),
            "specialized_agents": specialized_news,
            "bridge": news_bridge,
        },
        "telegram": telegram,
        "truth": {
            "fake_static_activity_allowed": False,
            "decorative_agent_scores_allowed": False,
            "missing_evidence_status": "unknown",
            "virtual_account_only": True,
            "live_orders_allowed": False,
            "known_architecture_debt": ["GET realtime status still performs bounded refresh/catch-up until worker migration"],
            "real_system_organs": ["News", "Risk", "Portfolio", "Learning", "Evidence", "Audit", "Telegram", "Mini App"],
            "visible_surfaces": ["Mini App", "website", "Telegram"],
        },
    }


def _age(timestamp: object) -> int | None:
    try:
        ts = int(timestamp or 0)
    except (TypeError, ValueError):
        return None
    if ts <= 0:
        return None
    return max(0, int(time.time()) - ts)


def _render(status: dict[str, Any]) -> str:
    account = status.get("virtual_account", {})
    news = status.get("news", {})
    specialized = news.get("specialized_agents", {})
    bridge = news.get("bridge", {})
    agent_summary = (status.get("agents") or {}).get("summary", {})
    warnings = "".join(f"<li>{warning}</li>" for warning in status.get("warnings", [])) or "<li>Критичных предупреждений нет.</li>"
    return f"""<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>SharipovAI · Realtime Status</title><style>body{{margin:0;background:#07111f;color:#eef4ff;font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif}}main{{padding:18px;max-width:980px;margin:auto}}.card{{background:#111827;border:1px solid #263245;border-radius:20px;padding:18px;margin:14px 0}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px}}.stat{{background:#0b1220;border:1px solid #1f2a3d;border-radius:14px;padding:12px}}small{{display:block;color:#9db0cc}}b{{font-size:20px}}.ok{{display:inline-block;background:#10b981;color:#03130d;border-radius:999px;padding:7px 12px;font-weight:900}}.warn{{display:inline-block;background:#f59e0b;color:#120a02;border-radius:999px;padding:7px 12px;font-weight:900}}a{{color:#60a5fa;font-weight:800}}</style></head><body><main><section class="card"><span class="{'ok' if status.get('status') == 'ok' else 'warn'}">{status.get('status')}</span><h1>Realtime Status</h1><p>Единая правда для сайта, Mini App и Telegram.</p><p><a href="/api/realtime/status">JSON</a> · <a href="/api/agent-health">Agent health</a> · <a href="/news-agents">News agents</a> · <a href="/virtual-account">Virtual Account</a></p></section><section class="card"><h2>AI agents</h2><div class="grid"><div class="stat"><small>Total</small><b>{agent_summary.get('total_bots')}</b></div><div class="stat"><small>Working</small><b>{agent_summary.get('working')}</b></div><div class="stat"><small>Degraded</small><b>{agent_summary.get('degraded')}</b></div><div class="stat"><small>Unknown</small><b>{agent_summary.get('unknown')}</b></div></div></section><section class="card"><h2>Specialized News AI</h2><div class="grid"><div class="stat"><small>Agents</small><b>{specialized.get('agent_count')}</b></div><div class="stat"><small>Healthy</small><b>{specialized.get('healthy_count')}</b></div><div class="stat"><small>Attention</small><b>{specialized.get('attention_count')}</b></div><div class="stat"><small>Network thread</small><b>{specialized.get('thread_alive')}</b></div><div class="stat"><small>Bridge thread</small><b>{bridge.get('thread_alive')}</b></div><div class="stat"><small>Last sent</small><b>{bridge.get('last_sent_count', 0)}</b></div></div></section><section class="card"><h2>Virtual Account Execution</h2><div class="grid"><div class="stat"><small>Trades</small><b>{account.get('trade_count')}</b></div><div class="stat"><small>Open</small><b>{account.get('open_positions')}</b></div><div class="stat"><small>Closed</small><b>{account.get('closed_positions')}</b></div><div class="stat"><small>Net PnL</small><b>{account.get('net_pnl')}</b></div><div class="stat"><small>Fees</small><b>{account.get('total_fees')}</b></div><div class="stat"><small>Last tick age</small><b>{account.get('last_tick_age_seconds')}</b></div></div></section><section class="card"><h2>News Monitor</h2><div class="grid"><div class="stat"><small>Items</small><b>{news.get('item_count')}</b></div><div class="stat"><small>Credibility</small><b>{news.get('average_credibility_percent')}%</b></div><div class="stat"><small>Needs confirmation</small><b>{news.get('needs_confirmation')}</b></div><div class="stat"><small>Last refresh age</small><b>{news.get('last_refresh_age_seconds')}</b></div><div class="stat"><small>Source mode</small><b>{news.get('source_mode')}</b></div><div class="stat"><small>Autorun</small><b>{(news.get('autorun') or {}).get('status')}</b></div></div></section><section class="card"><h2>Warnings</h2><ul>{warnings}</ul></section></main></body></html>"""
