"""Admin-only Phase 10 scaling, performance and capital APIs."""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from pydantic import BaseModel, Field

from campaigns.phase10_scaling import ControlledScalingService
from risk.phase10_capital_engine import CorrelationAwareCapitalEngine
from .admin_guard import install_sensitive_api_guard, require_admin


class _StrictModel(BaseModel):
    model_config = {"extra": "forbid", "allow_inf_nan": False}


class ActivationRequest(_StrictModel):
    actor: str = Field(min_length=1, max_length=128)
    confirmation: str = Field(min_length=1, max_length=128)
    scope: str = Field(default="BTCUSDT", min_length=3, max_length=32, pattern=r"^[A-Za-z0-9]+$")


class RevokeRequest(_StrictModel):
    actor: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=1, max_length=1000)


class PositionInput(_StrictModel):
    symbol: str = Field(min_length=3, max_length=32, pattern=r"^[A-Za-z0-9]+$")
    notional_usdt: float = Field(ge=0)


class CapitalSizeRequest(_StrictModel):
    equity_usdt: float = Field(gt=0)
    stop_distance_fraction: float = Field(gt=0, le=1)
    realized_volatility: float = Field(ge=0, le=10)
    proposed_symbol: str = Field(min_length=3, max_length=32, pattern=r"^[A-Za-z0-9]+$")
    open_positions: list[PositionInput] = Field(default_factory=list, max_length=500)
    correlations: dict[str, dict[str, float]] = Field(default_factory=dict)
    scaling_ceiling_usdt: float = Field(gt=0, le=50)


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
    app.state.phase10_scaling_service = scaling
    app.state.phase10_capital_engine = capital
    app.state.phase10_scaling_api_installed = True

    @app.post("/api/campaigns/phase10/activate/{plan_id}")
    def activate(request: Request, plan_id: str, body: ActivationRequest) -> dict[str, Any]:
        require_admin(request)
        plans = phase9.list_scaling_plans(limit=500)
        plan = next((item for item in plans if item.get("plan_id") == plan_id), None)
        if plan is None:
            raise HTTPException(status_code=404, detail="scaling plan not found")
        try:
            return scaling.activate(
                plan,
                actor=body.actor,
                confirmation=body.confirmation,
                scope=body.scope,
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/campaigns/phase10/revoke/{activation_id}")
    def revoke(request: Request, activation_id: str, body: RevokeRequest) -> dict[str, Any]:
        require_admin(request)
        try:
            return scaling.revoke(
                activation_id,
                actor=body.actor,
                reason=body.reason,
            )
        except ValueError as exc:
            status = 404 if "not found" in str(exc) else 409
            raise HTTPException(status_code=status, detail=str(exc)) from exc

    @app.get("/api/campaigns/phase10/activations")
    def activations(
        request: Request,
        limit: int = Query(default=100, ge=1, le=500),
    ) -> dict[str, Any]:
        require_admin(request)
        rows = scaling.list_activations(limit)
        active_ids = {item["activation_id"] for item in scaling.active_activations(limit=limit)}
        return {
            "status": "ok",
            "count": len(rows),
            "active_count": len(active_ids),
            "activations": [
                {**row, "currently_valid": row.get("activation_id") in active_ids}
                for row in rows
            ],
            "mainnet_enabled": False,
        }

    @app.get("/api/performance/phase10/overview")
    def performance(
        request: Request,
        snapshot_limit: int = Query(default=100, ge=1, le=500),
        report_limit: int = Query(default=24, ge=1, le=120),
    ) -> dict[str, Any]:
        require_admin(request)
        snapshots = scaling.list_snapshots(snapshot_limit)
        reports = scaling.list_monthly_reports(report_limit)
        latest = reports[0] if reports else None
        return {
            "status": "ok",
            "snapshot_count": len(snapshots),
            "monthly_report_count": len(reports),
            "snapshots": snapshots,
            "monthly_reports": reports,
            "latest_monthly_report": latest,
            "mainnet_enabled": False,
        }

    @app.post("/api/risk/phase10/size")
    def size(request: Request, body: CapitalSizeRequest) -> dict[str, Any]:
        require_admin(request)
        return capital.size(
            equity_usdt=body.equity_usdt,
            stop_distance_fraction=body.stop_distance_fraction,
            realized_volatility=body.realized_volatility,
            proposed_symbol=body.proposed_symbol,
            open_positions=[item.model_dump() for item in body.open_positions],
            correlations=body.correlations,
            scaling_ceiling_usdt=body.scaling_ceiling_usdt,
        )

    from .phase11_production_api import install_phase11_production_api

    install_phase11_production_api(app)


__all__ = ["install_phase10_scaling_api"]
