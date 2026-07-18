"""Fail-closed production audit for SharipovAI Phase 11."""
from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class AuditCheck:
    name: str
    severity: str
    passed: bool
    evidence: dict[str, Any]
    remediation: str = ""


class ProductionAudit:
    """Runs deterministic, secret-free readiness checks and emits immutable evidence."""

    def __init__(self, root: str | Path = ".") -> None:
        self.root = Path(root).resolve()

    def run(self) -> dict[str, Any]:
        checks = [
            self._check_mainnet_lock(),
            self._check_kill_switch(),
            self._check_secret_hygiene(),
            self._check_required_assets(),
            self._check_deployment_contracts(),
            self._check_dashboard_contracts(),
            self._check_runtime_limits(),
        ]
        blockers = [c.name for c in checks if not c.passed and c.severity == "critical"]
        warnings = [c.name for c in checks if not c.passed and c.severity != "critical"]
        payload = {
            "schema_version": 1,
            "created_at_ms": int(time.time() * 1000),
            "host": {"python": platform.python_version(), "platform": platform.system()},
            "status": "ready_for_bounded_testnet_preflight" if not blockers else "blocked",
            "blockers": blockers,
            "warnings": warnings,
            "checks": [asdict(c) for c in checks],
            "mainnet_enabled": False,
            "automatic_campaign_launch": False,
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        payload["audit_sha256"] = hashlib.sha256(canonical).hexdigest()
        return payload

    def _check_mainnet_lock(self) -> AuditCheck:
        bad = {k: os.getenv(k, "") for k in ("EXCHANGE_LIVE_TRADING_ENABLED", "FEATURE_BYBIT_LIVE_EXECUTION") if os.getenv(k, "").lower() in {"1", "true", "yes", "on"}}
        return AuditCheck("mainnet_compiled_and_configured_off", "critical", not bad, {"unsafe_flags": sorted(bad)}, "Disable every Mainnet/live execution flag.")

    def _check_kill_switch(self) -> AuditCheck:
        value = os.getenv("EXECUTION_KILL_SWITCH", "1").lower()
        passed = value in {"1", "true", "yes", "on"}
        return AuditCheck("production_kill_switch_engaged", "critical", passed, {"configured": passed}, "Set EXECUTION_KILL_SWITCH=1.")

    def _check_secret_hygiene(self) -> AuditCheck:
        tracked = [".env", ".env.testnet-campaign", "secrets.json", "credentials.json"]
        present = [name for name in tracked if (self.root / name).exists()]
        return AuditCheck("secret_files_not_present_in_root", "critical", not present, {"present": present}, "Remove secret files from the repository and rotate exposed credentials.")

    def _check_required_assets(self) -> AuditCheck:
        required = ["CONSTITUTION.md", "README.md", "dashboard/static/web2/index.html", "deploy/vps", "tests"]
        missing = [p for p in required if not (self.root / p).exists()]
        return AuditCheck("required_production_assets", "critical", not missing, {"missing": missing}, "Restore missing production assets.")

    def _check_deployment_contracts(self) -> AuditCheck:
        required = ["deploy/vps/phase11_release_preflight.sh", "deploy/vps/phase11_post_deploy_verify.sh"]
        missing = [p for p in required if not (self.root / p).exists()]
        return AuditCheck("deployment_preflight_and_verification", "critical", not missing, {"missing": missing})

    def _check_dashboard_contracts(self) -> AuditCheck:
        index = self.root / "dashboard/static/web2/index.html"
        text = index.read_text(encoding="utf-8") if index.exists() else ""
        tokens = ["viewport", "data-phase11-production", "phase11_production_v43.js", "theme-color"]
        missing = [token for token in tokens if token not in text]
        return AuditCheck("dashboard_responsive_realtime_contract", "warning", not missing, {"missing": missing})

    def _check_runtime_limits(self) -> AuditCheck:
        raw = os.getenv("PHASE11_MAX_TESTNET_NOTIONAL_USDT", "50")
        try:
            maximum = float(raw)
        except (TypeError, ValueError):
            maximum = math.nan
        passed = math.isfinite(maximum) and 0 < maximum <= 50
        return AuditCheck("bounded_testnet_notional", "critical", passed, {"configured": raw, "maximum_usdt": maximum if math.isfinite(maximum) else None}, "Keep the hard ceiling at or below 50 USDT.")


__all__ = ["AuditCheck", "ProductionAudit"]
