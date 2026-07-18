"""Read-only Phase 8 live campaign API."""
from __future__ import annotations

from typing import Any, Callable

from fastapi import FastAPI, HTTPException, Request

from campaigns import Phase8CampaignLiveView, Phase8PostCampaignAnalyzer
from observability import Phase8RiskAlertMonitor, Phase8RiskAlertService
from storage import ProjectDatabase

from .admin_guard import install_sensitive_api_guard, require_admin


def install_phase8_campaign_api(app: FastAPI) -> None:
    if getattr(app.state, "phase8_campaign_api_installed", False):
        return
    database = getattr(app.state, "project_database", None)
    operations = getattr(app.state, "campaign_operations_service", None)
    monitor = getattr(app.state, "phase7_campaign_monitor", None)
    campaign = getattr(app.state, "testnet_shadow_campaign", None)
    reports = getattr(app.state, "final_promotion_report_engine", None)
    if not isinstance(database, ProjectDatabase):
        raise RuntimeError("ProjectDatabase must be installed before Phase 8 API")
    if operations is None or monitor is None or campaign is None or reports is None:
        raise RuntimeError("Phase 7 campaign services must be installed before Phase 8 API")

    install_sensitive_api_guard(app)
    analyzer = Phase8PostCampaignAnalyzer(database, campaign=campaign, reports=reports, monitor=monitor)
    live = Phase8CampaignLiveView(database, operations=operations, monitor=monitor, analyzer=analyzer)
    risk_alerts = Phase8RiskAlertMonitor(live.snapshot, Phase8RiskAlertService(database))
    app.state.phase8_post_campaign_analyzer = analyzer
    app.state.phase8_campaign_live_view = live
    app.state.phase8_risk_alert_monitor = risk_alerts
    app.state.phase8_campaign_api_installed = True
    _register_event(app, "startup", live.start)
    _register_event(app, "startup", risk_alerts.start)
    _register_event(app, "shutdown", risk_alerts.stop)
    _register_event(app, "shutdown", live.stop)

    @app.get("/api/campaigns/phase8/live")
    def phase8_live(request: Request, since_sequence: int = -1, refresh: bool = False) -> dict[str, Any]:
        require_admin(request)
        try:
            payload = live.refresh() if refresh else live.snapshot(since_sequence=since_sequence)
            critical_monitor = getattr(app.state, "campaign_critical_alert_monitor", None)
            critical = critical_monitor.status() if critical_monitor is not None else {}
            return {
                **payload,
                "critical_alerts": critical,
                "phase8_risk_alerts": risk_alerts.status(),
                "runtime_flags_changed": False,
                "mainnet_enabled": False,
            }
        except Exception as exc:
            raise _service_error(exc) from exc

    @app.get("/api/campaigns/phase8/analysis/{campaign_id}")
    def phase8_analysis(request: Request, campaign_id: str) -> dict[str, Any]:
        require_admin(request)
        try:
            analysis = analyzer.latest_for_campaign(campaign_id) or analyzer.preview(campaign_id)
            return {
                "status": "ready" if analysis.get("analysis_id") else "preview",
                "analysis": analysis,
                "runtime_flags_changed": False,
                "mainnet_enabled": False,
            }
        except Exception as exc:
            raise _service_error(exc) from exc

    @app.get("/api/campaigns/phase8/recommendation/{campaign_id}")
    def phase8_recommendation(request: Request, campaign_id: str) -> dict[str, Any]:
        require_admin(request)
        try:
            analysis = analyzer.latest_for_campaign(campaign_id) or analyzer.preview(campaign_id)
            return {
                "status": "ok",
                "campaign_id": campaign_id,
                "recommendation": dict(analysis.get("recommendation") or {}),
                "gates": dict(analysis.get("gates") or {}),
                "drawdown": dict(analysis.get("drawdown") or {}),
                "manual_decision_required": True,
                "automatic_promotion": False,
                "runtime_flags_changed": False,
                "mainnet_enabled": False,
            }
        except Exception as exc:
            raise _service_error(exc) from exc


def _register_event(app: FastAPI, event: str, handler: Callable[[], None]) -> None:
    add_event_handler = getattr(app, "add_event_handler", None)
    if callable(add_event_handler):
        add_event_handler(event, handler)
        return
    handlers = getattr(getattr(app, "router", None), f"on_{event}", None)
    if isinstance(handlers, list):
        handlers.append(handler)
        return
    raise RuntimeError(f"FastAPI lifecycle handler registration unavailable for {event}")


def _service_error(exc: Exception) -> HTTPException:
    status = 404 if isinstance(exc, KeyError) else 409 if isinstance(exc, ValueError) else 503
    return HTTPException(status_code=status, detail={"status": "unavailable", "message": f"{type(exc).__name__}: {exc}"})


__all__ = ["install_phase8_campaign_api"]
