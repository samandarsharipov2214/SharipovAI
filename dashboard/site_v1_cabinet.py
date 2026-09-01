"""Authenticated Site V1 cabinet: canonical autonomous paper, never demo."""
from __future__ import annotations

import math
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from telegram_runtime_state import canonical_state_from_app


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
    return {
        "status": "ok" if available else "unavailable",
        "data_available": available,
        "source_of_truth": "autonomous_paper",
        "mode": str(state.get("mode") or "UNAVAILABLE") if available else "UNAVAILABLE",
        "equity": state.get("equity") if available else None,
        "cash": state.get("cash") if available else None,
        "net_pnl": state.get("net_pnl") if available else None,
        "total_fees": state.get("total_fees") if available else None,
        "open_positions": state.get("open_positions") if available else None,
        "positions": state.get("positions") if available else None,
        "last_action": last_action,
        "last_reason": last_reason,
        "worker_running": state.get("worker_running") if available else None,
        "wait": wait,
        "drawdown_percent": _optional_drawdown(app) if available else None,
        "error": None if available else str(state.get("error") or "autonomous_paper_loop_missing"),
    }


def _optional_drawdown(app: Any) -> float | None:
    """Report drawdown only when peak equity is present. Never invent a zero."""
    loop = getattr(getattr(app, "state", None), "autonomous_paper_loop", None)
    if loop is None:
        return None
    try:
        from telegram_runtime_state import _nonblocking_paper_snapshot

        raw = _nonblocking_paper_snapshot(loop)
    except Exception:
        return None
    if not isinstance(raw, dict) or "peak_equity" not in raw:
        return None
    try:
        equity = float(raw.get("equity"))
        peak = float(raw.get("peak_equity"))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(equity) or not math.isfinite(peak) or peak <= 0:
        return None
    return max(0.0, (peak - equity) / peak * 100.0)


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
