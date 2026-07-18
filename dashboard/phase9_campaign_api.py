"""Admin-only Phase 9 results, scaling and monitoring API."""
from __future__ import annotations

from typing import Any, Mapping

from fastapi import FastAPI, HTTPException, Query, Request
from pydantic import BaseModel, Field

from campaigns.phase9_results import CampaignResultsService
from .admin_guard import install_sensitive_api_guard, require_admin


class ScalingRequest(BaseModel):
    model_config = {"extra": "forbid", "allow_inf_nan": False}

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
        raise RuntimeError(
            "Phase 7 and Phase 8 services must be installed before Phase 9 API"
        )
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
        source_timestamp = source.get("generated_at_ms")
        if source_timestamp is None:
            raise HTTPException(
                status_code=409,
                detail="Phase 8 analysis timestamp is required for immutable evidence",
            )
        try:
            report = service.build_report(
                source,
                monitor.actual_fills(campaign_id),
                generated_at_ms=int(source_timestamp),
            )
        except (TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "status": "phase9_report_blocked",
                    "error_type": type(exc).__name__,
                    "campaign_id": campaign_id,
                },
            ) from exc
        response = dict(report)
        performance = getattr(app.state, "phase10_scaling_service", None)
        if performance is None:
            response["performance_tracking_status"] = "phase10_not_installed"
            return response
        try:
            snapshot = performance.record_snapshot(
                _performance_metrics(report, source),
                captured_at_ms=int(source_timestamp),
            )
        except (TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "status": "performance_tracking_blocked",
                    "error_type": type(exc).__name__,
                    "campaign_id": campaign_id,
                },
            ) from exc
        response["performance_tracking_status"] = "recorded"
        response["performance_snapshot_id"] = snapshot["snapshot_id"]
        response["performance_evidence_sha256"] = snapshot["evidence_sha256"]
        return response

    @app.get("/api/campaigns/phase9/report/{campaign_id}")
    def get_report(request: Request, campaign_id: str) -> dict[str, Any]:
        require_admin(request)
        row = service.get_report(campaign_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Phase 9 report not found")
        return row

    @app.get("/api/campaigns/phase9/reports")
    def list_reports(
        request: Request,
        limit: int = Query(default=100, ge=1, le=500),
    ) -> dict[str, Any]:
        require_admin(request)
        rows = service.list_reports(limit)
        return {
            "status": "ok",
            "count": len(rows),
            "reports": rows,
            "mainnet_enabled": False,
        }

    @app.post("/api/campaigns/phase9/scaling-plan")
    def create_scaling_plan(
        request: Request,
        body: ScalingRequest,
    ) -> dict[str, Any]:
        require_admin(request)
        reports = []
        for campaign_id in body.campaign_ids:
            report = service.get_report(campaign_id)
            if report is None:
                raise HTTPException(
                    status_code=409,
                    detail=f"missing Phase 9 report: {campaign_id}",
                )
            reports.append(report)
        return service.prepare_scaling(
            reports,
            actor=body.actor,
            reason=body.reason,
        )

    @app.get("/api/campaigns/phase9/scaling-plans")
    def list_scaling_plans(
        request: Request,
        limit: int = Query(default=100, ge=1, le=500),
    ) -> dict[str, Any]:
        require_admin(request)
        rows = service.list_scaling_plans(limit)
        return {
            "status": "ok",
            "count": len(rows),
            "plans": rows,
            "mainnet_enabled": False,
        }


def _performance_metrics(
    report: Mapping[str, Any],
    analysis: Mapping[str, Any],
) -> dict[str, Any]:
    pnl = report.get("pnl") if isinstance(report.get("pnl"), Mapping) else {}
    risk = (
        report.get("risk_metrics")
        if isinstance(report.get("risk_metrics"), Mapping)
        else {}
    )
    return {
        "campaign_id": str(report.get("campaign_id") or ""),
        "analysis_id": str(
            report.get("analysis_id") or analysis.get("analysis_id") or ""
        ),
        "phase9_report_id": str(report.get("report_id") or ""),
        "phase9_evidence_sha256": str(report.get("evidence_sha256") or ""),
        "net_pnl_usdt": pnl.get("net_realized_pnl_usdt", 0.0),
        "fees_usdt": pnl.get("fees_usdt", analysis.get("fees_usdt", 0.0)),
        "matched_fill_count": report.get("matched_fill_count", 0),
        "maximum_drawdown_bps": risk.get("maximum_drawdown_bps", 0.0),
    }


__all__ = ["install_phase9_campaign_api"]
