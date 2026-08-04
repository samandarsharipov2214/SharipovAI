"""Unified read-only realtime status API for SharipovAI.

Every live surface reads the canonical Market -> Council -> Decision Quality ->
Autonomous Paper -> Learning runtime. GET requests never execute catch-up cycles,
refresh news, or mutate either the canonical or deprecated virtual account.
"""
from __future__ import annotations

import os
import time
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from sharipovai_constitution import constitution_snapshot, now_iso
from telegram_health import telegram_health

from .news_agent_network_api import bridge_status, network_status

STARTED_AT = int(time.time())
_TRUTH_POLICY = (
    "No decorative score is allowed; only /api/system/ai-organs runtime "
    "evidence determines agent health."
)
_TRUTH_POLICY_UNAVAILABLE = (
    "No decorative score is allowed; canonical runtime evidence is unavailable."
)


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
        return canonical_agent_health(app)

    @app.get("/realtime-status", response_class=HTMLResponse)
    def realtime_status_page() -> HTMLResponse:
        return HTMLResponse(_render(build_realtime_status(app)))


def canonical_agent_health(app: FastAPI) -> dict[str, Any]:
    """Compatibility projection sourced only from the canonical organ monitor."""
    monitor = getattr(app.state, "ai_organ_runtime_monitor", None)
    if monitor is None:
        return {
            "status": "warning",
            "generated_at": int(time.time()),
            "summary": {
                "total_bots": 0,
                "canonical_ai_count": 0,
                "active": 0,
                "warnings": 1,
                "working": 0,
                "degraded": 0,
                "unknown": 1,
            },
            "agents": [],
            "bots": [],
            "truth_policy": _TRUTH_POLICY_UNAVAILABLE,
        }
    snapshot = monitor.snapshot()
    agents: list[dict[str, Any]] = []
    for organ in snapshot.get("organs", []):
        raw_status = str(organ.get("status", "blocked"))
        compatibility_status = {
            "healthy": "working",
            "degraded": "degraded",
            "blocked": "degraded",
        }.get(raw_status, "unknown")
        score = {"healthy": 100, "degraded": 50, "blocked": 0}.get(raw_status)
        checked_at_ms = int(organ.get("checked_at_ms") or 0)
        checked_at = checked_at_ms // 1000 if checked_at_ms > 0 else int(time.time())
        blockers = [str(item) for item in organ.get("blockers", [])]
        evidence = [str(item) for item in organ.get("evidence", [])]
        agents.append(
            {
                "id": str(organ.get("organ_id", "")),
                "name": str(organ.get("organ_id", "")).replace("_", " ").title(),
                "responsibility": str(organ.get("responsibility", "")),
                "status": compatibility_status,
                "runtime_status": raw_status,
                "quality_score": score,
                "health_score": score,
                "checked_at": checked_at,
                "changed_at": checked_at,
                "last_seen": checked_at,
                "last_action": evidence[-1] if evidence else None,
                "last_error": "; ".join(blockers) or None,
                "evidence": evidence,
                "evidence_count": len(evidence),
                "stale": any("stale" in item.lower() for item in blockers),
                "details": {"blockers": blockers},
            }
        )
    working = sum(item["status"] == "working" for item in agents)
    degraded = sum(item["status"] == "degraded" for item in agents)
    unknown = sum(item["status"] == "unknown" for item in agents)
    result = {
        "status": "ok" if snapshot.get("status") == "healthy" else "warning",
        "generated_at": int(time.time()),
        "summary": {
            "total_bots": len(agents),
            "canonical_ai_count": len(agents),
            "active": working,
            "warnings": degraded + unknown,
            "working": working,
            "degraded": degraded,
            "unknown": unknown,
        },
        "agents": agents,
        "bots": agents,
        "canonical_status": snapshot.get("status"),
        "truth_policy": _TRUTH_POLICY,
    }
    return result


def build_realtime_status(app: FastAPI | None = None) -> dict[str, Any]:
    warnings: list[str] = []
    install_error = getattr(app.state, "news_agent_network_install_error", None) if app is not None else "FastAPI app is unavailable"
    if install_error:
        warnings.append(f"Canonical News Intelligence startup error: {install_error}")

    paper = _canonical_paper_snapshot(app)
    paper_summary = _paper_summary(paper)
    tick_age = _iso_age(paper.get("updated_at"))
    if paper.get("status") == "unavailable":
        warnings.append("Canonical autonomous paper runtime is unavailable.")
    elif paper.get("worker_running") is False and _truthy("AUTONOMOUS_PAPER_ENABLED", True):
        warnings.append("Canonical autonomous paper worker is not running.")
    if tick_age is not None and tick_age > 180:
        warnings.append(f"Canonical autonomous paper state is stale: {tick_age} sec.")

    try:
        specialized_news = network_status(run_due=False, app=app)
        news_bridge = bridge_status(app=app)
    except Exception as exc:
        specialized_news = {"status": "warning", "error": f"{type(exc).__name__}: {exc}", "agents": []}
        news_bridge = {"status": "warning", "delivery_mode": "shared_database", "consumer_active": False}
    if specialized_news.get("status") != "ok":
        warnings.append(
            "Canonical News Intelligence degraded: "
            + str(specialized_news.get("last_error") or specialized_news.get("error") or "runtime evidence unavailable")
        )
    if news_bridge.get("consumer_active") is not True:
        warnings.append("News shared-database consumer contract is not active.")

    telegram = telegram_health()
    if telegram.get("verdict") != "working":
        warnings.append(f"Telegram не полностью working: {telegram.get('verdict')}")

    agents = canonical_agent_health(app) if app is not None else canonical_agent_health_unavailable()
    if agents.get("status") != "ok":
        summary = agents.get("summary", {})
        warnings.append(
            "AI agents not fully proven: "
            f"working={summary.get('working', 0)}, degraded={summary.get('degraded', 0)}, unknown={summary.get('unknown', 0)}."
        )

    hub = specialized_news.get("hub") if isinstance(specialized_news.get("hub"), dict) else {}
    latest_news = hub.get("latest") if isinstance(hub.get("latest"), dict) else {}
    fetched = latest_news.get("fetched") if isinstance(latest_news.get("fetched"), dict) else {}
    last_news_ms = int(fetched.get("received_at_ms") or specialized_news.get("last_cycle_at_ms") or 0)
    news_age = _timestamp_age(last_news_ms)

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
            "autorun": {
                "status": "running" if paper.get("worker_running") else "disabled" if not _truthy("AUTONOMOUS_PAPER_ENABLED", True) else "stopped",
                "enabled": _truthy("AUTONOMOUS_PAPER_ENABLED", True),
                "thread_alive": bool(paper.get("worker_running")),
                "canonical": True,
            },
            "summary": paper_summary,
            **paper_summary,
            "last_tick_age_seconds": tick_age,
            "mode": paper.get("mode"),
            "execution_mode": "virtual_execution_only",
            "market_price_accounting": True,
            "real_orders_blocked": True,
            "decision_mode": paper.get("decision_mode"),
            "entry_without_authorization_allowed": paper.get("entry_without_authorization_allowed"),
            "database_backed": paper.get("database_backed"),
            "source_of_truth": "autonomous_paper",
            "mutation_on_get": False,
        },
        "paper_activity": {
            "deprecated": True,
            "active": False,
            "source_of_truth": "autonomous_paper",
            "excluded_from_health": True,
            "excluded_from_learning": True,
            "autorun_enabled": False,
            "mutation_on_get": False,
        },
        "news": {
            "canonical_owner": "news_intelligence",
            "refresh_status": "background_worker",
            "last_refresh_at_ms": last_news_ms or None,
            "last_refresh_age_seconds": news_age,
            "item_count": hub.get("article_history_count", 0),
            "high_urgency": (hub.get("urgency_counts") or {}).get("high", 0),
            "critical_urgency": (hub.get("urgency_counts") or {}).get("critical", 0),
            "errors": [specialized_news.get("last_error")] if specialized_news.get("last_error") else [],
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
            "get_requests_mutate_runtime": False,
            "known_architecture_debt": ["Legacy PaperActivityEngine remains import-compatible but is not a runtime source of truth."],
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


def canonical_agent_health_unavailable() -> dict[str, Any]:
    return {
        "status": "warning",
        "summary": {
            "total_bots": 0,
            "canonical_ai_count": 0,
            "active": 0,
            "warnings": 1,
            "working": 0,
            "degraded": 0,
            "unknown": 1,
        },
        "agents": [],
        "bots": [],
        "truth_policy": _TRUTH_POLICY_UNAVAILABLE,
    }


def _canonical_paper_snapshot(app: FastAPI | None) -> dict[str, Any]:
    loop = getattr(getattr(app, "state", None), "autonomous_paper_loop", None)
    if loop is None:
        return {"status": "unavailable", "worker_running": False, "positions": {}, "trades": []}
    try:
        snapshot = loop.snapshot()
    except Exception as exc:
        return {
            "status": "unavailable",
            "error": f"{type(exc).__name__}: {exc}",
            "worker_running": False,
            "positions": {},
            "trades": [],
        }
    if not isinstance(snapshot, dict):
        return {"status": "unavailable", "worker_running": False, "positions": {}, "trades": []}
    snapshot.setdefault("status", "ok")
    snapshot.setdefault("worker_running", bool(getattr(loop, "_thread", None) and loop._thread.is_alive()))
    return snapshot


def _paper_summary(paper: dict[str, Any]) -> dict[str, Any]:
    trades = [item for item in paper.get("trades", []) if isinstance(item, dict)]
    buy = [item for item in trades if str(item.get("side", "")).upper() == "BUY"]
    sell = [item for item in trades if str(item.get("side", "")).upper() == "SELL"]
    profitable = [item for item in sell if float(item.get("net_pnl") or 0.0) > 0]
    positions = paper.get("positions") if isinstance(paper.get("positions"), dict) else {}
    return {
        "trade_count": int(paper.get("trade_history_count") or len(trades)),
        "buy_count": len(buy),
        "sell_count": len(sell),
        "open_positions": len(positions),
        "closed_positions": len(sell),
        "win_rate_percent": round(len(profitable) / len(sell) * 100.0, 2) if sell else 0.0,
        "cash": float(paper.get("cash") or 0.0),
        "equity": float(paper.get("equity") or 0.0),
        "net_pnl": float(paper.get("realized_pnl") or 0.0) + float(paper.get("unrealized_pnl") or 0.0),
        "realized_pnl": float(paper.get("realized_pnl") or 0.0),
        "unrealized_pnl": float(paper.get("unrealized_pnl") or 0.0),
        "total_fees": float(paper.get("total_fees") or 0.0),
        "last_action": paper.get("last_action"),
        "last_reason": paper.get("last_reason"),
        "suppressed_wait_events": int(paper.get("suppressed_wait_events") or 0),
    }


def _iso_age(timestamp: object) -> int | None:
    if not timestamp:
        return None
    try:
        parsed = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return max(0, int((datetime.now(UTC) - parsed.astimezone(UTC)).total_seconds()))


def _timestamp_age(timestamp_ms: int) -> int | None:
    if timestamp_ms <= 0:
        return None
    return max(0, int(time.time() - timestamp_ms / 1000.0))


def _truthy(name: str, default: bool = False) -> bool:
    fallback = "1" if default else "0"
    return os.getenv(name, fallback).strip().lower() in {"1", "true", "yes", "on"}


def _render(status: dict[str, Any]) -> str:
    account = status.get("virtual_account", {})
    warnings = "".join(f"<li>{warning}</li>" for warning in status.get("warnings", [])) or "<li>Критичных предупреждений нет.</li>"
    badge = "ok" if status.get("status") == "ok" else "warn"
    return f"""<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>SharipovAI · Realtime Status</title><style>body{{margin:0;background:#07111f;color:#eef4ff;font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif}}main{{padding:18px;max-width:980px;margin:auto}}.card{{background:#111827;border:1px solid #263245;border-radius:20px;padding:18px;margin:14px 0}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px}}.stat{{background:#0b1220;border:1px solid #1f2a3d;border-radius:14px;padding:12px}}small{{display:block;color:#9db0cc}}b{{font-size:20px}}.ok,.warn{{display:inline-block;border-radius:999px;padding:7px 12px;font-weight:900}}.ok{{background:#10b981;color:#03130d}}.warn{{background:#f59e0b;color:#120a02}}a{{color:#60a5fa;font-weight:800}}</style></head><body><main><section class="card"><span class="{badge}">{status.get('status')}</span><h1>Realtime Status</h1><p><a href="/api/realtime/status">JSON</a> · <a href="/virtual-account">Virtual Account</a></p></section><section class="card"><h2>Canonical Virtual Account</h2><div class="grid"><div class="stat"><small>Trades</small><b>{account.get('trade_count')}</b></div><div class="stat"><small>Buy / Sell</small><b>{account.get('buy_count')} / {account.get('sell_count')}</b></div><div class="stat"><small>Open / Closed</small><b>{account.get('open_positions')} / {account.get('closed_positions')}</b></div><div class="stat"><small>Win rate</small><b>{account.get('win_rate_percent')}%</b></div><div class="stat"><small>Equity</small><b>{account.get('equity')}</b></div><div class="stat"><small>Net PnL</small><b>{account.get('net_pnl')}</b></div><div class="stat"><small>Fees</small><b>{account.get('total_fees')}</b></div><div class="stat"><small>Read-only GET</small><b>{not account.get('mutation_on_get', True)}</b></div></div></section><section class="card"><h2>Warnings</h2><ul>{warnings}</ul></section></main></body></html>"""


__all__ = ["build_realtime_status", "canonical_agent_health", "install_realtime_status_api"]
