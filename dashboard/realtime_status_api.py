"""Unified realtime status API for SharipovAI.

Every live surface reads the same market-backed virtual-account truth.
"""
from __future__ import annotations

import time
from typing import Any

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from agent_health import build_agent_health_snapshot
from market_paper_engine import PaperActivityEngine
from news_monitor.agent_bridge import bridge_status
from news_monitor.agent_network import network_status
from news_monitor.news_autorun import news_autorun_status, refresh_news_if_stale
from news_monitor.storage import load_news_state
from paper_activity_autorun import paper_activity_autorun_status
from sharipovai_constitution import constitution_snapshot, now_iso
from telegram_health import telegram_health

STARTED_AT = int(time.time())


def install_realtime_status_api(app: FastAPI) -> None:
    if getattr(app.state, "realtime_status_api_installed", False):
        return
    app.state.realtime_status_api_installed = True
    try:
        from .news_agent_network_api import install_news_agent_network_api

        install_news_agent_network_api(app)
        app.state.news_agent_network_install_error = None
    except Exception as exc:
        app.state.news_agent_network_install_error = f"{type(exc).__name__}: {exc}"

    @app.get("/api/realtime/status")
    def realtime_status() -> dict[str, Any]:
        return build_realtime_status(app)

    @app.get("/api/agent-health")
    def agent_health() -> dict[str, Any]:
        return build_agent_health_snapshot()

    @app.get("/realtime-status", response_class=HTMLResponse)
    def realtime_status_page() -> HTMLResponse:
        return HTMLResponse(_render(build_realtime_status(app)))


def build_realtime_status(app: FastAPI | None = None) -> dict[str, Any]:
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

    install_error = getattr(app.state, "news_agent_network_install_error", None) if app is not None else None
    if install_error:
        warnings.append(f"Specialized News AI API startup error: {install_error}")
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
        "startup": {
            "news_agent_network_api_installed": not bool(install_error),
            "news_agent_network_install_error": install_error,
        },
        "agents": agents,
        "virtual_account": {
            "autorun": paper_activity_autorun_status(),
            "summary": account_summary,
            "trade_count": account_summary.get("trade_count", 0),
            "buy_count": account_summary.get("buy_count", 0),
            "sell_count": account_summary.get("sell_count", 0),
            "open_positions": account_summary.get("open_positions", 0),
            "closed_positions": account_summary.get("closed_positions", 0),
            "win_rate_percent": account_summary.get("win_rate_percent", 0),
            "cash": account_summary.get("cash", 0),
            "equity": account_summary.get("equity", 0),
            "net_pnl": account_summary.get("net_pnl", 0),
            "total_fees": account_summary.get("total_fees", 0),
            "last_tick_age_seconds": tick_age,
            "mode": account_payload.get("mode"),
            "execution_mode": account_payload.get("execution_mode", account_summary.get("execution_mode")),
            "market_price_accounting": account_summary.get("market_price_accounting", False),
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
            "market_price_accounting": True,
            "historical_trade_fabrication_allowed": False,
            "known_architecture_debt": ["GET realtime status still performs bounded refresh/catch-up until worker migration"],
            "real_system_organs": [
                "General Controller",
                "Market Intelligence",
                "News Intelligence",
                "Risk Engine",
                "Portfolio & Reports",
                "Virtual Account Execution",
                "Decision Quality",
                "Learning Engine",
                "Security Guard",
            ],
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
    warnings = "".join(f"<li>{warning}</li>" for warning in status.get("warnings", [])) or "<li>Критичных предупреждений нет.</li>"
    badge = "ok" if status.get("status") == "ok" else "warn"
    return f"""<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>SharipovAI · Realtime Status</title><style>body{{margin:0;background:#07111f;color:#eef4ff;font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif}}main{{padding:18px;max-width:980px;margin:auto}}.card{{background:#111827;border:1px solid #263245;border-radius:20px;padding:18px;margin:14px 0}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px}}.stat{{background:#0b1220;border:1px solid #1f2a3d;border-radius:14px;padding:12px}}small{{display:block;color:#9db0cc}}b{{font-size:20px}}.ok,.warn{{display:inline-block;border-radius:999px;padding:7px 12px;font-weight:900}}.ok{{background:#10b981;color:#03130d}}.warn{{background:#f59e0b;color:#120a02}}a{{color:#60a5fa;font-weight:800}}</style></head><body><main><section class="card"><span class="{badge}">{status.get('status')}</span><h1>Realtime Status</h1><p><a href="/api/realtime/status">JSON</a> · <a href="/virtual-account">Virtual Account</a></p></section><section class="card"><h2>Virtual Account</h2><div class="grid"><div class="stat"><small>Trades</small><b>{account.get('trade_count')}</b></div><div class="stat"><small>Buy / Sell</small><b>{account.get('buy_count')} / {account.get('sell_count')}</b></div><div class="stat"><small>Open / Closed</small><b>{account.get('open_positions')} / {account.get('closed_positions')}</b></div><div class="stat"><small>Win rate</small><b>{account.get('win_rate_percent')}%</b></div><div class="stat"><small>Equity</small><b>{account.get('equity')}</b></div><div class="stat"><small>Net PnL</small><b>{account.get('net_pnl')}</b></div><div class="stat"><small>Fees</small><b>{account.get('total_fees')}</b></div><div class="stat"><small>Market prices</small><b>{account.get('market_price_accounting')}</b></div></div></section><section class="card"><h2>Warnings</h2><ul>{warnings}</ul></section></main></body></html>"""
