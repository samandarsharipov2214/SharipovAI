"""Admin-only Phase 8 post-campaign analytics API."""
from __future__ import annotations

from typing import Any
from fastapi import FastAPI, HTTPException, Request

from campaigns.phase8_analysis import PostCampaignAnalysisService
from .admin_guard import install_sensitive_api_guard, require_admin


def install_phase8_campaign_api(app: FastAPI) -> None:
    if getattr(app.state, "phase8_campaign_api_installed", False):
        return
    campaign = getattr(app.state, "testnet_shadow_campaign", None)
    monitor = getattr(app.state, "phase7_campaign_monitor", None)
    database = getattr(app.state, "project_database", None)
    if campaign is None or monitor is None or database is None:
        raise RuntimeError("Phase 7 campaign services must be installed before Phase 8 API")
    install_sensitive_api_guard(app)
    analysis = PostCampaignAnalysisService(database)
    app.state.phase8_post_campaign_analysis = analysis
    app.state.phase8_campaign_api_installed = True

    @app.get("/api/campaigns/phase8/analysis/{campaign_id}")
    def get_analysis(request: Request, campaign_id: str) -> dict[str, Any]:
        require_admin(request)
        row = analysis.get(campaign_id)
        if row is None:
            raise HTTPException(status_code=404, detail="post-campaign analysis not found")
        return row

    @app.get("/api/campaigns/phase8/analyses")
    def list_analyses(request: Request, limit: int = 100) -> dict[str, Any]:
        require_admin(request)
        rows = analysis.list(limit=min(max(limit, 1), 500))
        return {"status": "ok", "count": len(rows), "analyses": rows, "mainnet_enabled": False}

    @app.post("/api/campaigns/phase8/analyze/{campaign_id}")
    def run_analysis(request: Request, campaign_id: str) -> dict[str, Any]:
        require_admin(request)
        row = campaign.get(campaign_id)
        if row is None:
            raise HTTPException(status_code=404, detail="campaign not found")
        if str(row.get("status") or "") != "completed":
            raise HTTPException(status_code=409, detail="campaign must be completed before analysis")
        fills = monitor.actual_fills(campaign_id)
        try:
            result = analysis.analyze(row, fills)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return result


__all__ = ["install_phase8_campaign_api"]
