"""Unified realtime status API for SharipovAI.

This endpoint exists because every live surface must show the same truth:
Mini App, website, and Telegram should not display fake/static demo state.
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from news_monitor.news_autorun import news_autorun_status, refresh_news_if_stale
from news_monitor.storage import load_news_state
from paper_activity_autorun import paper_activity_autorun_status
from paper_activity_engine import PaperActivityEngine
from sharipovai_constitution import constitution_snapshot, now_iso
from telegram_health import telegram_health

STARTED_AT = int(time.time())


def install_realtime_status_api(app: FastAPI) -> None:
    """Install realtime truth/status endpoints."""

    if getattr(app.state, "realtime_status_api_installed", False):
        return
    app.state.realtime_status_api_installed = True

    @app.get("/api/realtime/status")
    def realtime_status() -> dict[str, Any]:
        return build_realtime_status()

    @app.get("/realtime-status", response_class=HTMLResponse)
    def realtime_status_page() -> HTMLResponse:
        status = build_realtime_status()
        return HTMLResponse(_render(status))


def build_realtime_status() -> dict[str, Any]:
    """Collect current background status for app/site/Telegram."""

    news_refresh = refresh_news_if_stale(reason="api_realtime_status_stale_check")
    paper_payload = PaperActivityEngine().state(catch_up=True)
    paper_summary = paper_payload.get("summary", {})
    news_state = load_news_state()
    news_summary = (news_state.get("news") or {}).get("summary", {}) if isinstance(news_state.get("news"), dict) else {}
    paper_age = paper_summary.get("last_tick_age_seconds")
    news_age = _age(news_state.get("last_refresh_at"))
    warnings: list[str] = []
    if paper_age is None:
        warnings.append("Paper Activity ещё не сделал tick.")
    elif int(paper_age) > 180:
        warnings.append(f"Paper Activity stale: последний tick {paper_age} сек. назад.")
    if news_age is None:
        warnings.append("News Monitor ещё не сделал real RSS refresh.")
    elif int(news_age) > 300:
        warnings.append(f"News Monitor stale: последний refresh {news_age} сек. назад.")
    telegram = telegram_health()
    if telegram.get("verdict") != "working":
        warnings.append(f"Telegram не полностью working: {telegram.get('verdict')}")
    return {
        "status": "ok" if not warnings else "warning",
        "generated_at": now_iso(),
        "uptime_seconds": int(time.time()) - STARTED_AT,
        "constitution": constitution_snapshot(),
        "warnings": warnings,
        "paper_activity": {
            "autorun": paper_activity_autorun_status(),
            "summary": paper_summary,
            "trade_count": paper_summary.get("trade_count", 0),
            "open_positions": paper_summary.get("open_positions", 0),
            "closed_positions": paper_summary.get("closed_positions", 0),
            "net_pnl": paper_summary.get("net_pnl", 0),
            "last_tick_age_seconds": paper_age,
            "mode": paper_payload.get("mode"),
        },
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
        },
        "telegram": telegram,
        "truth": {
            "fake_static_demo_allowed": False,
            "paper_only": True,
            "live_orders_allowed": False,
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
    paper = status.get("paper_activity", {})
    news = status.get("news", {})
    warnings = "".join(f"<li>{warning}</li>" for warning in status.get("warnings", [])) or "<li>Критичных предупреждений нет.</li>"
    return f"""<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>SharipovAI · Realtime Status</title><style>body{{margin:0;background:#07111f;color:#eef4ff;font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif}}main{{padding:18px;max-width:980px;margin:auto}}.card{{background:#111827;border:1px solid #263245;border-radius:20px;padding:18px;margin:14px 0}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px}}.stat{{background:#0b1220;border:1px solid #1f2a3d;border-radius:14px;padding:12px}}small{{display:block;color:#9db0cc}}b{{font-size:20px}}.ok{{display:inline-block;background:#10b981;color:#03130d;border-radius:999px;padding:7px 12px;font-weight:900}}.warn{{display:inline-block;background:#f59e0b;color:#120a02;border-radius:999px;padding:7px 12px;font-weight:900}}a{{color:#60a5fa;font-weight:800}}</style></head><body><main><section class="card"><span class="{'ok' if status.get('status') == 'ok' else 'warn'}">{status.get('status')}</span><h1>Realtime Status</h1><p>Единая правда для сайта, Mini App и Telegram. Фейковая статичная demo-активность запрещена.</p><p><a href="/api/realtime/status">JSON</a> · <a href="/paper-activity">Paper Activity</a> · <a href="/api/social-news/rss/refresh">Refresh News</a></p></section><section class="card"><h2>Paper Activity</h2><div class="grid"><div class="stat"><small>Trades</small><b>{paper.get('trade_count')}</b></div><div class="stat"><small>Open</small><b>{paper.get('open_positions')}</b></div><div class="stat"><small>Closed</small><b>{paper.get('closed_positions')}</b></div><div class="stat"><small>Net PnL</small><b>{paper.get('net_pnl')}</b></div><div class="stat"><small>Last tick age</small><b>{paper.get('last_tick_age_seconds')}</b></div><div class="stat"><small>Autorun</small><b>{(paper.get('autorun') or {}).get('status')}</b></div></div></section><section class="card"><h2>News Monitor</h2><div class="grid"><div class="stat"><small>Items</small><b>{news.get('item_count')}</b></div><div class="stat"><small>Credibility</small><b>{news.get('average_credibility_percent')}%</b></div><div class="stat"><small>Needs confirmation</small><b>{news.get('needs_confirmation')}</b></div><div class="stat"><small>Last refresh age</small><b>{news.get('last_refresh_age_seconds')}</b></div><div class="stat"><small>Source mode</small><b>{news.get('source_mode')}</b></div><div class="stat"><small>Autorun</small><b>{(news.get('autorun') or {}).get('status')}</b></div></div></section><section class="card"><h2>Warnings</h2><ul>{warnings}</ul></section></main></body></html>"""
