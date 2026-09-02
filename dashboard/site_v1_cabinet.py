"""Authenticated Site V1 cabinet: canonical autonomous paper, never demo."""
from __future__ import annotations

import math
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from telegram_runtime_state import canonical_state_from_app

_NEWS_WINDOW = 8


def cabinet_payload(app: Any) -> dict[str, Any]:
    """Project the telegram/paper contract into the Site V1 cabinet JSON.

    Missing runtime is UNAVAILABLE with null money fields. Never fabricate 0.
    """
    state = canonical_state_from_app(app)
    available = bool(state.get("data_available"))
    last_action = state.get("last_action") if available else None
    last_reason = state.get("last_reason") if available else None
    wait = None
    if isinstance(last_action, str) and last_action.strip().upper() == "WAIT":
        wait = "WAIT"
    payload = {
        "status": "ok" if available else "unavailable",
        "data_available": available,
        "source_of_truth": "autonomous_paper",
        "mode": str(state.get("mode") or "UNAVAILABLE") if available else "UNAVAILABLE",
        "equity": state.get("equity") if available else None,
        "cash": state.get("cash") if available else None,
        "net_pnl": state.get("net_pnl") if available else None,
        "realized_pnl": state.get("realized_pnl") if available else None,
        "unrealized_pnl": state.get("unrealized_pnl") if available else None,
        "peak_equity": state.get("peak_equity") if available else None,
        "total_fees": state.get("total_fees") if available else None,
        "open_positions": state.get("open_positions") if available else None,
        "positions": state.get("positions") if available else None,
        "trades": list(state.get("trades") or []) if available else [],
        "trade_count": state.get("trade_count") if available else None,
        "last_action": last_action,
        "last_reason": last_reason,
        "worker_running": state.get("worker_running") if available else None,
        "database_backed": state.get("database_backed") if available else None,
        "market_verified": state.get("market_verified") if available else None,
        "market_age_seconds": state.get("market_age_seconds") if available else None,
        "wait": wait,
        "drawdown_percent": _drawdown_percent(state.get("equity"), state.get("peak_equity")) if available else None,
        "error": None if available else str(state.get("error") or "autonomous_paper_loop_missing"),
    }
    payload.update(_cabinet_news())
    return payload


def _cabinet_news() -> dict[str, Any]:
    """Project a short saved news list. Never scrape and never inject demo items."""
    try:
        from news_monitor.storage import load_news_state

        state = load_news_state()
    except Exception as exc:
        return {
            "news_available": False,
            "news": [],
            "news_error": f"{type(exc).__name__}: {exc}"[:240],
        }
    news = state.get("news") if isinstance(state, dict) else None
    raw_items = news.get("items") if isinstance(news, dict) else None
    if not isinstance(raw_items, list):
        raw_items = []
    items: list[dict[str, str]] = []
    for raw in raw_items[:_NEWS_WINDOW]:
        if not isinstance(raw, dict):
            continue
        title = str(raw.get("title") or "").strip()
        if not title:
            continue
        items.append(
            {
                "title": title[:240],
                "source": str(raw.get("source_name") or raw.get("source_id") or "").strip()[:120],
                "published_at": str(raw.get("published_at") or "").strip()[:64],
            }
        )
    return {"news_available": True, "news": items, "news_error": None}


def _drawdown_percent(equity: Any, peak: Any) -> float | None:
    """Report drawdown only when peak equity is present. Never invent a zero."""
    try:
        equity_f = float(equity)
        peak_f = float(peak)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(equity_f) or not math.isfinite(peak_f) or peak_f <= 0:
        return None
    return max(0.0, (peak_f - equity_f) / peak_f * 100.0)


def install_site_v1_cabinet(app: FastAPI) -> None:
    if getattr(app.state, "site_v1_cabinet_installed", False):
        return
    app.state.site_v1_cabinet_installed = True

    @app.get("/api/site-v1/cabinet")
    def site_v1_cabinet(request: Request) -> JSONResponse:
        del request
        return JSONResponse(
            cabinet_payload(app),
            headers={"Cache-Control": "no-store"},
        )


__all__ = ["cabinet_payload", "install_site_v1_cabinet"]
