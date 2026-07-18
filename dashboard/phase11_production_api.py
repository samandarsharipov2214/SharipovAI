"""Admin-only Phase 11 production audit and readiness API."""
from __future__ import annotations

from typing import Any
from fastapi import FastAPI, Request

from audit.phase11_production_audit import ProductionAudit
from .admin_guard import install_sensitive_api_guard, require_admin


def install_phase11_production_api(app: FastAPI) -> None:
    if getattr(app.state, "phase11_production_api_installed", False):
        return
    install_sensitive_api_guard(app)
    audit = ProductionAudit()
    app.state.phase11_production_audit = audit
    app.state.phase11_production_api_installed = True

    @app.get("/api/production/phase11/audit")
    def production_audit(request: Request) -> dict[str, Any]:
        require_admin(request)
        return audit.run()

    @app.get("/api/production/phase11/overview")
    def production_overview(request: Request) -> dict[str, Any]:
        require_admin(request)
        report = audit.run()
        phase10 = getattr(app.state, "phase10_scaling_service", None)
        activations = phase10.list_activations(limit=20) if phase10 and hasattr(phase10, "list_activations") else []
        active = [row for row in activations if row.get("status") == "active"]
        return {
            "status": "ok",
            "readiness": report["status"],
            "blockers": report["blockers"],
            "warnings": report["warnings"],
            "active_scaling_authorities": len(active),
            "mainnet_enabled": False,
            "automatic_campaign_launch": False,
            "audit_sha256": report["audit_sha256"],
        }


__all__ = ["install_phase11_production_api"]
