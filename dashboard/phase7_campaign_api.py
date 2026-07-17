"""Admin-only Phase 7 campaign monitoring and critical-alert API."""
from __future__ import annotations

from typing import Any, Callable, Mapping

from fastapi import FastAPI, HTTPException, Request

from campaigns.phase7_monitor import Phase7CampaignMonitor
from observability import CampaignCriticalAlertMonitor, CampaignCriticalAlertService
from storage import ProjectDatabase

from .admin_guard import install_sensitive_api_guard, require_admin


def install_phase7_campaign_api(app: FastAPI) -> None:
    if getattr(app.state, "phase7_campaign_api_installed", False):
        return
    database = getattr(app.state, "project_database", None)
    campaign = getattr(app.state, "testnet_shadow_campaign", None)
    operations = getattr(app.state, "campaign_operations_service", None)
    reports = getattr(app.state, "final_promotion_report_engine", None)
    if not isinstance(database, ProjectDatabase):
        raise RuntimeError("ProjectDatabase must be installed before Phase 7 API")
    if campaign is None or operations is None or reports is None:
        raise RuntimeError("campaign API must be installed before Phase 7 API")

    install_sensitive_api_guard(app)
    monitor = Phase7CampaignMonitor(
        database,
        campaign=campaign,
        operations=operations,
        reports=reports,
    )
    alert_service = CampaignCriticalAlertService(database)

    def critical_snapshot() -> Mapping[str, Any]:
        return {
            **operations.snapshot(),
            "phase7_monitor": monitor.snapshot(),
        }

    alert_monitor = CampaignCriticalAlertMonitor(critical_snapshot, alert_service)
    app.state.phase7_campaign_monitor = monitor
    app.state.campaign_critical_alert_service = alert_service
    app.state.campaign_critical_alert_monitor = alert_monitor
    app.state.phase7_campaign_api_installed = True
    _register_event(app, "startup", monitor.start)
    _register_event(app, "startup", alert_monitor.start)
    _register_event(app, "shutdown", alert_monitor.stop)
    _register_event(app, "shutdown", monitor.stop)

    @app.get("/api/campaigns/phase7/monitor")
    def phase7_monitor(request: Request, refresh: bool = False) -> dict[str, Any]:
        require_admin(request)
        try:
            snapshot = monitor.refresh() if refresh else monitor.snapshot()
            alerts = _alert_tick(alert_monitor) if refresh else alert_monitor.status()
            return {**snapshot, "critical_alerts": alerts}
        except Exception as exc:
            raise _service_error(exc) from exc

    @app.post("/api/campaigns/phase7/refresh")
    def phase7_refresh(request: Request) -> dict[str, Any]:
        require_admin(request)
        try:
            snapshot = monitor.refresh()
            return {**snapshot, "critical_alerts": _alert_tick(alert_monitor)}
        except Exception as exc:
            raise _service_error(exc) from exc

    @app.get("/api/campaigns/phase7/alerts")
    def phase7_alerts(request: Request) -> dict[str, Any]:
        require_admin(request)
        return alert_monitor.status()

    @app.post("/api/campaigns/phase7/alerts/refresh")
    def phase7_alerts_refresh(request: Request) -> dict[str, Any]:
        require_admin(request)
        return _alert_tick(alert_monitor)

    @app.get("/api/campaigns/phase7/fills")
    def phase7_fills(request: Request, campaign_id: str = "") -> dict[str, Any]:
        require_admin(request)
        selected = campaign_id or str(monitor.snapshot().get("campaign_id") or "")
        rows = monitor.actual_fills(selected)
        return {
            "status": "ok",
            "campaign_id": selected,
            "count": len(rows),
            "fills": rows,
            "source": "authenticated private Bybit execution evidence",
            "runtime_flags_changed": False,
            "mainnet_enabled": False,
        }

    @app.get("/api/campaigns/phase7/report")
    def phase7_report(request: Request) -> dict[str, Any]:
        require_admin(request)
        snapshot = monitor.snapshot()
        report_id = str(snapshot.get("final_report_id") or "")
        report = reports.get(report_id) if report_id else None
        return {
            "status": "ready" if report else "pending",
            "campaign_id": str(snapshot.get("campaign_id") or ""),
            "report": report or {},
            "export_path": str(snapshot.get("final_report_path") or ""),
            "actual_fills": monitor.actual_fills(str(snapshot.get("campaign_id") or "")),
            "critical_alerts": alert_monitor.status(),
            "runtime_flags_changed": False,
            "mainnet_enabled": False,
        }


def _alert_tick(monitor: CampaignCriticalAlertMonitor) -> dict[str, Any]:
    try:
        return monitor.tick()
    except Exception as exc:
        return {
            **monitor.status(),
            "status": "error",
            "error": f"{type(exc).__name__}: {exc}",
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


def _service_error(exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=503,
        detail={"status": "unavailable", "message": f"{type(exc).__name__}: {exc}"},
    )


__all__ = ["install_phase7_campaign_api"]
