"""Admin-only lifecycle and API for scheduled Testnet shadow campaigns."""
from __future__ import annotations

from typing import Any, Callable

from fastapi import FastAPI, HTTPException, Request

from autonomous_trading import ShadowModeTestnetBridge
from campaigns import (
    CampaignOperationsService,
    FIRST_TESTNET_CONFIRMATION,
    FinalPromotionReportEngine,
    ScheduledCampaignOrchestrator,
    TestnetShadowCampaign,
)
from storage import ProjectDatabase
from validation import RuntimeFillHarvester

from .admin_guard import install_sensitive_api_guard, require_admin


def install_campaign_api(app: FastAPI) -> None:
    if getattr(app.state, "campaign_api_installed", False):
        return
    database = getattr(app.state, "project_database", None)
    if not isinstance(database, ProjectDatabase):
        raise RuntimeError("ProjectDatabase must be installed before campaign API")
    app.state.campaign_api_installed = True
    install_sensitive_api_guard(app)
    shared_bridge = getattr(app.state, "autonomous_testnet_bridge", None)
    shared_harvester = getattr(app.state, "runtime_fill_harvester", None)
    campaign = TestnetShadowCampaign(
        database,
        bridge=(shared_bridge if isinstance(shared_bridge, ShadowModeTestnetBridge) else None),
        harvester=(shared_harvester if isinstance(shared_harvester, RuntimeFillHarvester) else None),
    )
    orchestrator = ScheduledCampaignOrchestrator(database, campaign=campaign)
    reports = FinalPromotionReportEngine(database)
    operations = CampaignOperationsService(
        database,
        orchestrator=orchestrator,
        campaign=campaign,
        reports=reports,
    )
    app.state.scheduled_campaign_orchestrator = orchestrator
    app.state.testnet_shadow_campaign = campaign
    app.state.final_promotion_report_engine = reports
    app.state.campaign_operations_service = operations
    _register_event(app, "startup", orchestrator.start)
    _register_event(app, "shutdown", orchestrator.stop)

    @app.get("/api/campaigns/orchestrator/status")
    def orchestrator_status(request: Request) -> dict[str, Any]:
        require_admin(request)
        return orchestrator.status()

    @app.post("/api/campaigns/orchestrator/tick")
    def orchestrator_tick(request: Request) -> dict[str, Any]:
        require_admin(request)
        try:
            return orchestrator.tick()
        except Exception as exc:
            raise _service_error(exc) from exc

    @app.get("/api/campaigns/operations")
    def campaign_operations(request: Request) -> dict[str, Any]:
        require_admin(request)
        return operations.snapshot()

    @app.get("/api/campaigns/first-testnet/plan")
    def first_testnet_plan(request: Request, experiment_id: str = "") -> dict[str, Any]:
        require_admin(request)
        return operations.first_testnet_plan(experiment_id=experiment_id)

    @app.post("/api/campaigns/first-testnet/start")
    async def start_first_testnet(request: Request) -> dict[str, Any]:
        principal = require_admin(request)
        payload = await _json_body(request)
        confirmation = str(payload.get("confirmation", ""))
        if confirmation != FIRST_TESTNET_CONFIRMATION:
            raise HTTPException(
                status_code=409,
                detail={
                    "status": "blocked",
                    "message": "exact bounded Testnet confirmation is required",
                    "required_confirmation": FIRST_TESTNET_CONFIRMATION,
                },
            )
        try:
            return operations.start_first_testnet_campaign(
                experiment_id=str(payload.get("experiment_id", "")),
                scope=str(payload.get("scope", "BTCUSDT")),
                actor=str(getattr(principal, "username", "admin")),
                confirmation=confirmation,
            )
        except (ValueError, KeyError, TypeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(
                status_code=409,
                detail={"status": "blocked", "message": str(exc)},
            ) from exc

    @app.get("/api/campaigns/schedules")
    def schedules(request: Request) -> dict[str, Any]:
        require_admin(request)
        rows = orchestrator.list_schedules(limit=500)
        return {"status": "ok", "count": len(rows), "schedules": rows}

    @app.post("/api/campaigns/schedules")
    async def create_schedule(request: Request) -> dict[str, Any]:
        principal = require_admin(request)
        payload = await _json_body(request)
        try:
            schedule = orchestrator.create_schedule(
                experiment_id=str(payload.get("experiment_id", "")),
                scope=str(payload.get("scope", "")),
                interval_seconds=int(payload.get("interval_seconds", 300)),
                actor=str(getattr(principal, "username", "admin")),
                start_at_ms=(
                    int(payload["start_at_ms"])
                    if payload.get("start_at_ms") not in (None, "")
                    else None
                ),
                enabled=bool(payload.get("enabled", True)),
            )
        except (ValueError, KeyError, TypeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"status": "created", "schedule": schedule, "runtime_flags_changed": False}

    @app.get("/api/campaigns")
    def campaigns(request: Request) -> dict[str, Any]:
        require_admin(request)
        rows = orchestrator.campaign.list(limit=500)
        return {"status": "ok", "count": len(rows), "campaigns": rows}

    # Static paths must be registered before /api/campaigns/{campaign_id}.
    @app.get("/api/campaigns/promotion-reports")
    def promotion_reports(request: Request) -> dict[str, Any]:
        require_admin(request)
        rows = reports.list(limit=500)
        return {"status": "ok", "count": len(rows), "reports": rows}

    @app.get("/api/campaigns/{campaign_id}")
    def campaign_detail(request: Request, campaign_id: str) -> dict[str, Any]:
        require_admin(request)
        campaign_row = orchestrator.campaign.get(campaign_id)
        if campaign_row is None:
            raise HTTPException(status_code=404, detail="campaign not found")
        report = (
            reports.get(str(campaign_row.get("final_report_id") or ""))
            if campaign_row.get("final_report_id")
            else None
        )
        return {
            "status": "ok",
            "campaign": campaign_row,
            "final_promotion_report": report or {},
        }

    @app.post("/api/campaigns/{campaign_id}/run")
    def run_campaign(request: Request, campaign_id: str) -> dict[str, Any]:
        principal = require_admin(request)
        try:
            campaign_row = orchestrator.campaign.run_cycle(
                campaign_id,
                actor=str(getattr(principal, "username", "admin")),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="campaign not found") from exc
        except Exception as exc:
            raise _service_error(exc) from exc
        return {
            "status": "ok",
            "campaign": campaign_row,
            "runtime_flags_changed": False,
        }

    @app.post("/api/campaigns/{campaign_id}/promotion-report")
    def generate_final_report(request: Request, campaign_id: str) -> dict[str, Any]:
        principal = require_admin(request)
        campaign_row = orchestrator.campaign.get(campaign_id)
        if campaign_row is None:
            raise HTTPException(status_code=404, detail="campaign not found")
        existing_id = str(campaign_row.get("final_report_id") or "")
        if existing_id:
            existing = reports.get(existing_id)
            if existing is None:
                raise HTTPException(status_code=503, detail="campaign final report reference is missing")
            report = existing
        else:
            try:
                report = reports.generate(
                    campaign_id,
                    actor=str(getattr(principal, "username", "admin")),
                )
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "status": "ok",
            "report": report,
            "manual_decision_required": True,
            "runtime_flags_changed": False,
        }


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


async def _json_body(request: Request) -> dict[str, Any]:
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="request body must be JSON") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="request body must be an object")
    return payload


def _service_error(exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=503,
        detail={"status": "unavailable", "message": f"{type(exc).__name__}: {exc}"},
    )


__all__ = ["install_campaign_api"]
