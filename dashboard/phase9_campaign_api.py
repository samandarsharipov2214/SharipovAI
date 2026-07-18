"""Admin-only Phase 9 results, scaling and monitoring API."""
from __future__ import annotations

from typing import Any
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from campaigns.phase9_results import CampaignResultsService
from .admin_guard import install_sensitive_api_guard, require_admin


class ScalingRequest(BaseModel):
    campaign_ids: list[str] = Field(min_length=1, max_length=20)
    actor: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=1, max_length=1000)


def install_phase9_campaign_api(app: FastAPI) -> None:
    if getattr(app.state, "phase9_campaign_api_installed", False):
        return
    analysis = getattr(app.state, "phase8_post_campaign_analysis", None)
    monitor = getattr(app.state, "phase7_campaign_monitor", None)
    database = getattr(app.state, "project_database", None)
    if analysis is None or monitor is None or database is None:
        raise RuntimeError("Phase 7 and Phase 8 services must be installed before Phase 9 API")
    install_sensitive_api_guard(app)
    service = CampaignResultsService(database)
    app.state.phase9_campaign_results = service
    app.state.phase9_campaign_api_installed = True

    @app.post("/api/campaigns/phase9/report/{campaign_id}")
    def build_report(request: Request, campaign_id: str) -> dict[str, Any]:
        require_admin(request)
        source = analysis.get(campaign_id)
        if source is None:
            raise HTTPException(status_code=409, detail="Phase 8 analysis is required")
        return service.build_report(source, monitor.actual_fills(campaign_id))

    @app.get("/api/campaigns/phase9/report/{campaign_id}")
    def get_report(request: Request, campaign_id: str) -> dict[str, Any]:
        require_admin(request)
        row = service.get_report(campaign_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Phase 9 report not found")
        return row

    @app.get("/api/campaigns/phase9/reports")
    def list_reports(request: Request, limit: int = 100) -> dict[str, Any]:
        require_admin(request)
        rows = service.list_reports(min(max(limit, 1), 500))
        return {"status": "ok", "count": len(rows), "reports": rows, "mainnet_enabled": False}

    @app.post("/api/campaigns/phase9/scaling-plan")
    def create_scaling_plan(request: Request, body: ScalingRequest) -> dict[str, Any]:
        require_admin(request)
        reports = []
        for campaign_id in body.campaign_ids:
            report = service.get_report(campaign_id)
            if report is None:
                raise HTTPException(status_code=409, detail=f"missing Phase 9 report: {campaign_id}")
            reports.append(report)
        return service.prepare_scaling(reports, actor=body.actor, reason=body.reason)

    @app.get("/api/campaigns/phase9/scaling-plans")
    def list_scaling_plans(request: Request, limit: int = 100) -> dict[str, Any]:
        require_admin(request)
        rows = service.list_scaling_plans(min(max(limit, 1), 500))
        return {"status": "ok", "count": len(rows), "plans": rows, "mainnet_enabled": False}


__all__ = ["install_phase9_campaign_api"]
