"""Admin-only Phase 10 scaling, performance and capital APIs."""
from __future__ import annotations

from typing import Any
from fastapi import FastAPI, HTTPException, Request

from campaigns.phase10_scaling import ControlledScalingService
from risk.phase10_capital_engine import CorrelationAwareCapitalEngine
from .admin_guard import install_sensitive_api_guard, require_admin


def install_phase10_scaling_api(app: FastAPI) -> None:
    if getattr(app.state, "phase10_scaling_api_installed", False):
        return
    database = getattr(app.state, "project_database", None)
    phase9 = getattr(app.state, "phase9_campaign_results", None)
    if database is None or phase9 is None:
        raise RuntimeError("Phase 9 services must be installed before Phase 10 API")
    install_sensitive_api_guard(app)
    scaling = ControlledScalingService(database)
    capital = CorrelationAwareCapitalEngine()
    app.state.phase10_controlled_scaling = scaling
    app.state.phase10_capital_engine = capital
    app.state.phase10_scaling_api_installed = True

    @app.post("/api/campaigns/phase10/activate/{plan_id}")
    async def activate(request: Request, plan_id: str) -> dict[str, Any]:
        require_admin(request)
        body = await request.json()
        plans = phase9.list_scaling_plans(limit=500)
        plan = next((item for item in plans if item.get("plan_id") == plan_id), None)
        if plan is None:
            raise HTTPException(status_code=404, detail="scaling plan not found")
        try:
            return scaling.activate(plan, actor=str(body.get("actor") or ""), confirmation=str(body.get("confirmation") or ""), scope=str(body.get("scope") or "BTCUSDT"))
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/campaigns/phase10/revoke/{activation_id}")
    async def revoke(request: Request, activation_id: str) -> dict[str, Any]:
        require_admin(request)
        body = await request.json()
        try:
            return scaling.revoke(activation_id, actor=str(body.get("actor") or ""), reason=str(body.get("reason") or ""))
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/campaigns/phase10/activations")
    def activations(request: Request, limit: int = 100) -> dict[str, Any]:
        require_admin(request)
        rows = scaling.list_activations(min(max(limit, 1), 500))
        return {"status": "ok", "count": len(rows), "activations": rows, "mainnet_enabled": False}

    @app.get("/api/performance/phase10/overview")
    def performance(request: Request) -> dict[str, Any]:
        require_admin(request)
        snapshots = scaling.list_snapshots(500)
        reports = scaling.list_monthly_reports(36)
        return {"status": "ok", "snapshots": snapshots, "monthly_reports": reports, "mainnet_enabled": False}

    @app.post("/api/risk/phase10/size")
    async def size(request: Request) -> dict[str, Any]:
        require_admin(request)
        body = await request.json()
        return capital.size(
            equity_usdt=float(body.get("equity_usdt") or 0),
            stop_distance_fraction=float(body.get("stop_distance_fraction") or 0),
            realized_volatility=float(body.get("realized_volatility") or 0),
            proposed_symbol=str(body.get("proposed_symbol") or ""),
            open_positions=list(body.get("open_positions") or []),
            correlations=dict(body.get("correlations") or {}),
            scaling_ceiling_usdt=float(body.get("scaling_ceiling_usdt") or 0),
        )

    from .phase11_production_api import install_phase11_production_api
    install_phase11_production_api(app)


__all__ = ["install_phase10_scaling_api"]
