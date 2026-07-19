"""Admin-only Phase 11 production audit and readiness API."""
from __future__ import annotations

import copy
import math
import os
import threading
import time
from typing import Any

from fastapi import FastAPI, Request

from audit.phase11_production_audit import ProductionAudit
from .admin_guard import install_sensitive_api_guard, require_admin


class _AuditCache:
    def __init__(self, audit: ProductionAudit, ttl_seconds: float) -> None:
        self.audit = audit
        self.ttl_seconds = ttl_seconds
        self._lock = threading.RLock()
        self._report: dict[str, Any] | None = None
        self._loaded_at = 0.0

    def get(self) -> dict[str, Any]:
        now = time.monotonic()
        with self._lock:
            if self._report is None or now - self._loaded_at >= self.ttl_seconds:
                try:
                    self._report = self.audit.run()
                except Exception as exc:
                    self._report = {
                        "schema_version": 2,
                        "created_at_ms": int(time.time() * 1000),
                        "status": "blocked",
                        "blockers": ["audit_internal_error"],
                        "warnings": [],
                        "checks": [],
                        "mainnet_enabled": False,
                        "automatic_campaign_launch": False,
                        "audit_sha256": "",
                        "error_type": type(exc).__name__,
                    }
                self._loaded_at = now
            report = copy.deepcopy(self._report)
            report["cache_age_ms"] = max(0, int((now - self._loaded_at) * 1000))
            report["cache_ttl_seconds"] = self.ttl_seconds
            return report


def install_phase11_production_api(app: FastAPI) -> None:
    if getattr(app.state, "phase11_production_api_installed", False):
        return
    install_sensitive_api_guard(app)
    audit = ProductionAudit()
    cache = _AuditCache(audit, _audit_ttl())
    app.state.phase11_production_audit = audit
    app.state.phase11_production_audit_cache = cache
    app.state.phase11_production_api_installed = True

    @app.get("/api/production/phase11/audit")
    def production_audit(request: Request) -> dict[str, Any]:
        require_admin(request)
        return cache.get()

    @app.get("/api/production/phase11/overview")
    def production_overview(request: Request) -> dict[str, Any]:
        require_admin(request)
        report = cache.get()
        scaling = getattr(app.state, "phase10_scaling_service", None)
        active = scaling.active_activations(limit=500) if scaling else []
        monthly = scaling.list_monthly_reports(limit=1) if scaling else []
        latest_monthly = monthly[0] if monthly else None
        return {
            "status": "ok" if report.get("status") != "blocked" else "blocked",
            "readiness": report.get("status", "blocked"),
            "blockers": list(report.get("blockers") or []),
            "warnings": list(report.get("warnings") or []),
            "active_scaling_authorities": len(active),
            "active_authority_ids": [item.get("activation_id") for item in active],
            "latest_monthly_report": latest_monthly,
            "mainnet_enabled": False,
            "automatic_campaign_launch": False,
            "audit_sha256": str(report.get("audit_sha256") or ""),
            "audit_created_at_ms": report.get("created_at_ms"),
            "cache_age_ms": report.get("cache_age_ms", 0),
        }


def _audit_ttl() -> float:
    raw = os.getenv("PHASE11_AUDIT_CACHE_SECONDS", "15")
    try:
        value = float(raw)
    except ValueError:
        return 15.0
    if not math.isfinite(value):
        return 15.0
    return min(300.0, max(5.0, value))


__all__ = ["install_phase11_production_api"]
