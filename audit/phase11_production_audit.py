"""Deterministic fail-closed production readiness audit.

The audit never changes execution flags, credentials, campaign state, scaling
authority, or order state. Database health may initialize the canonical schema.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class AuditCheck:
    name: str
    severity: str
    passed: bool
    evidence: dict[str, Any]
    remediation: str = ""


class ProductionAudit:
    """Run secret-free checks and emit deterministic evidence."""

    def __init__(
        self,
        root: str | Path = ".",
        *,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self.root = Path(root).resolve()
        self.environ = dict(os.environ if environ is None else environ)

    def run(self) -> dict[str, Any]:
        checks = [
            self._execution_lock(),
            self._runtime_configuration(),
            self._database_health(),
            self._secret_hygiene(),
            self._required_assets(),
            self._deployment_contracts(),
            self._dashboard_contracts(),
            self._ci_crash_contracts(),
            self._runtime_limits(),
        ]
        blockers = sorted(
            item.name
            for item in checks
            if not item.passed and item.severity == "critical"
        )
        warnings = sorted(
            item.name
            for item in checks
            if not item.passed and item.severity != "critical"
        )
        deterministic = {
            "schema_version": 4,
            "status": (
                "ready_for_bounded_testnet_preflight"
                if not blockers
                else "blocked"
            ),
            "blockers": blockers,
            "warnings": warnings,
            "checks": [asdict(item) for item in checks],
            "mainnet_enabled": False,
            "automatic_campaign_launch": False,
        }
        return {
            **deterministic,
            "created_at_ms": int(time.time() * 1000),
            "host": {
                "python": platform.python_version(),
                "platform": platform.system(),
            },
            "audit_sha256": hashlib.sha256(
                _canonical_json(deterministic)
            ).hexdigest(),
        }

    def _execution_lock(self) -> AuditCheck:
        try:
            from exchange_connector.bybit_execution import BybitExecutionClient
            from exchange_connector.execution_contract import (
                MAINNET_EXECUTION_COMPILED,
            )

            status = BybitExecutionClient().status()
            evidence = {
                "compiled": bool(MAINNET_EXECUTION_COMPILED),
                "live_execution_enabled": bool(
                    status.get("live_execution_enabled")
                ),
                "mainnet_hard_blocked": bool(
                    status.get("mainnet_hard_blocked")
                ),
                "testnet_execution_enabled": bool(
                    status.get("testnet_execution_enabled")
                ),
                "kill_switch": bool(status.get("kill_switch")),
            }
            passed = (
                MAINNET_EXECUTION_COMPILED is False
                and evidence["live_execution_enabled"] is False
                and evidence["mainnet_hard_blocked"] is True
                and evidence["testnet_execution_enabled"] is False
                and evidence["kill_switch"] is True
            )
        except Exception as exc:
            evidence = {"error_type": type(exc).__name__}
            passed = False
        return AuditCheck(
            "compile_and_runtime_execution_lock",
            "critical",
            passed,
            evidence,
            "Restore the compile lock, kill switch and disabled execution state.",
        )

    def _runtime_configuration(self) -> AuditCheck:
        disabled = (
            "EXCHANGE_LIVE_TRADING_ENABLED",
            "FEATURE_BYBIT_LIVE_EXECUTION",
            "FEATURE_BYBIT_TESTNET_EXECUTION",
            "TESTNET_EXECUTION_ENABLED",
            "AUTONOMOUS_TESTNET_ENABLED",
            "AUTONOMOUS_TESTNET_BRIDGE_ENABLED",
            "FEATURE_BYBIT_PRIVATE_ORDER_WS",
            "BYBIT_ALLOW_LEGACY_EXCHANGE_CREDENTIALS",
        )
        unsafe = sorted(
            name for name in disabled if _truthy(self.environ.get(name, "0"))
        )
        auth_names = ("AUTH_SECRET", "ADMIN_USERNAME", "ADMIN_PASSWORD")
        evidence = {
            "unsafe_enabled_flags": unsafe,
            "kill_switch_engaged": _truthy(
                self.environ.get("EXECUTION_KILL_SWITCH", "1")
            ),
            "authentication_enabled": not _truthy(
                self.environ.get("SHARIPOVAI_DISABLE_AUTH", "0")
            ),
            "authentication_material_configured": all(
                bool(str(self.environ.get(name, "")).strip())
                for name in auth_names
            ),
            "database_required": _truthy(
                self.environ.get("SHARIPOVAI_DATABASE_REQUIRED", "1")
            ),
            "database_url_configured": bool(
                str(self.environ.get("DATABASE_URL", "")).strip()
            ),
            "exchange_mode_is_sandbox": str(
                self.environ.get("EXCHANGE_MODE", "sandbox")
            ).strip().lower()
            == "sandbox",
        }
        passed = not unsafe and all(
            value is True
            for key, value in evidence.items()
            if key != "unsafe_enabled_flags"
        )
        return AuditCheck(
            "safe_runtime_configuration",
            "critical",
            passed,
            evidence,
            "Disable execution flags, configure auth/database and keep sandbox mode.",
        )

    def _database_health(self) -> AuditCheck:
        try:
            from storage import ProjectDatabase

            health = ProjectDatabase(
                self.environ.get("DATABASE_URL") or None
            ).health()
            passed = health.get("status") == "ok" and int(
                health.get("schema_version") or 0
            ) >= 1
            evidence = {
                "status": health.get("status"),
                "backend": health.get("backend"),
                "required": health.get("required"),
                "schema_version": health.get("schema_version"),
                "error_type": str(health.get("error") or "").split(":", 1)[0]
                or None,
            }
        except Exception as exc:
            passed = False
            evidence = {
                "status": "error",
                "error_type": type(exc).__name__,
            }
        return AuditCheck(
            "canonical_database_health",
            "critical",
            passed,
            evidence,
            "Restore the canonical database and verify schema migrations.",
        )

    def _secret_hygiene(self) -> AuditCheck:
        forbidden = {
            ".env",
            ".env.testnet-campaign",
            "secrets.json",
            "credentials.json",
            "id_rsa",
            "id_ed25519",
        }
        present = sorted(
            name for name in forbidden if (self.root / name).exists()
        )
        tracked: list[str] = []
        git_verified = False
        try:
            result = subprocess.run(
                ["git", "ls-files", "-z"],
                cwd=self.root,
                check=True,
                capture_output=True,
                timeout=5,
            )
            git_verified = True
            paths = [
                item.decode("utf-8", errors="replace")
                for item in result.stdout.split(b"\0")
                if item
            ]
            tracked = sorted(
                path
                for path in paths
                if Path(path).name in forbidden
                or Path(path).suffix.lower()
                in {".pem", ".key", ".p12", ".pfx"}
            )
        except (OSError, subprocess.SubprocessError):
            git_verified = False
        return AuditCheck(
            "secret_file_hygiene",
            "critical",
            not present and not tracked and git_verified,
            {
                "forbidden_root_files": present,
                "forbidden_tracked_files": tracked,
                "git_inventory_verified": git_verified,
            },
            "Remove tracked secret material, rotate credentials and verify Git inventory.",
        )

    def _required_assets(self) -> AuditCheck:
        required = (
            "CONSTITUTION.md",
            "README.md",
            ".github/workflows/phase11-hardening.yml",
            "campaigns/phase9_results.py",
            "campaigns/phase10_scaling.py",
            "risk/phase10_capital_engine.py",
            "dashboard/static/web2/index.html",
            "dashboard/phase9_campaign_api.py",
            "dashboard/phase10_scaling_api.py",
            "dashboard/phase11_production_api.py",
            "deploy/vps/phase11_release_preflight.sh",
            "deploy/vps/phase11_post_deploy_verify.sh",
            "deploy/vps/install_phase10_monthly_monitor.sh",
            "deploy/vps/systemd/sharipovai-monthly-performance.service",
            "deploy/vps/systemd/sharipovai-monthly-performance.timer",
            "tests/test_phase9_results_and_scaling.py",
            "tests/test_phase11_crash_resilience.py",
        )
        missing: list[str] = []
        escaped: list[str] = []
        for relative in required:
            path = self.root / relative
            if not path.exists():
                missing.append(relative)
                continue
            try:
                path.resolve().relative_to(self.root)
            except ValueError:
                escaped.append(relative)
        return AuditCheck(
            "required_production_assets",
            "critical",
            not missing and not escaped,
            {"missing": missing, "escaped_root": escaped},
            "Restore required assets and remove symlinks escaping the repository root.",
        )

    def _deployment_contracts(self) -> AuditCheck:
        sources = {
            "preflight": self._read(
                "deploy/vps/phase11_release_preflight.sh"
            ),
            "post_deploy": self._read(
                "deploy/vps/phase11_post_deploy_verify.sh"
            ),
            "installer": self._read(
                "deploy/vps/install_phase10_monthly_monitor.sh"
            ),
            "service": self._read(
                "deploy/vps/systemd/sharipovai-monthly-performance.service"
            ),
            "timer": self._read(
                "deploy/vps/systemd/sharipovai-monthly-performance.timer"
            ),
            "monthly_cli": self._read("scripts/phase10_monthly_report.py"),
        }
        expected = {
            "preflight": (
                "#!/usr/bin/env bash",
                "git diff --quiet",
                "SHARIPOVAI_EXPECTED_SHA",
                "AUTH_SECRET",
                "ADMIN_USERNAME",
                "ADMIN_PASSWORD",
                "SHARIPOVAI_DATABASE_REQUIRED",
                "tests/test_phase9_results_and_scaling.py",
                "tests/test_phase11_crash_resilience.py",
                "ProductionAudit",
            ),
            "post_deploy": (
                "#!/usr/bin/env bash",
                "/api/health",
                "mktemp",
                "ProjectDatabase",
                "os.replace",
                "audit_sha256",
                "http_health",
            ),
            "installer": (
                "#!/usr/bin/env bash",
                "systemd-analyze verify",
                "systemctl enable --now",
            ),
            "service": (
                "NoNewPrivileges=true",
                "ProtectSystem=strict",
                "SuccessExitStatus=3",
                "ReadWritePaths=/var/lib/sharipovai",
                "ReadWritePaths=-/opt/sharipovai/data",
            ),
            "timer": (
                "OnCalendar=monthly",
                "Persistent=true",
                "RandomizedDelaySec=900",
            ),
            "monthly_cli": (
                "#!/usr/bin/env python3",
                "os.replace",
                "os.fsync",
            ),
        }
        missing = [
            f"{name}:{token}"
            for name, tokens in expected.items()
            for token in tokens
            if token not in sources[name]
        ]
        return AuditCheck(
            "deployment_preflight_and_verification",
            "critical",
            not missing,
            {"missing_contracts": missing},
            "Restore SHA, auth, database, atomic output, systemd and crash contracts.",
        )

    def _dashboard_contracts(self) -> AuditCheck:
        sources = {
            "index": self._read("dashboard/static/web2/index.html"),
            "phase10": self._read(
                "dashboard/static/web2/phase10_scaling_performance_v42.js"
            ),
            "phase11": self._read(
                "dashboard/static/web2/phase11_production_v43.js"
            ),
            "stylesheet": self._read(
                "dashboard/static/web2/phase11_production_v43.css"
            ),
            "guard": self._read("dashboard/admin_guard.py"),
        }
        expected = {
            "index": (
                "viewport",
                "theme-color",
                "data-phase10-scaling-performance",
                "data-phase11-production",
            ),
            "phase10": (
                "AbortController",
                "visibilitychange",
                "replaceChildren",
                "lastSuccessfulAt",
            ),
            "phase11": (
                "AbortController",
                "aria-live",
                "visibilitychange",
                "localStorage",
                "lastSuccessfulAt",
                "replaceChildren",
            ),
            "stylesheet": (
                "prefers-reduced-motion",
                "prefers-color-scheme",
                "@media",
                ":focus-visible",
            ),
            "guard": (
                "/api/campaigns/phase9/",
                "/api/campaigns/phase10/",
                "/api/production/phase11/",
            ),
        }
        missing = [
            f"{name}:{token}"
            for name, tokens in expected.items()
            for token in tokens
            if token not in sources[name]
        ]
        unsafe = [
            f"{name}:{token}"
            for name in ("phase10", "phase11")
            for token in ("innerHTML", "insertAdjacentHTML", "eval(")
            if token in sources[name]
        ]
        return AuditCheck(
            "dashboard_responsive_realtime_contract",
            "warning",
            not missing and not unsafe,
            {"missing": missing, "unsafe_dom_patterns": unsafe},
            "Restore accessible, authorized and injection-safe rendering.",
        )

    def _ci_crash_contracts(self) -> AuditCheck:
        workflows = self._read(".github/workflows/tests.yml") + "\n" + self._read(
            ".github/workflows/phase11-hardening.yml"
        )
        required = (
            "tests/test_phase9_results_and_scaling.py",
            "tests/test_phase10_controlled_scaling.py",
            "tests/test_phase10_capital_engine.py",
            "tests/test_phase11_production_audit.py",
            "tests/test_phase11_dashboard_contract.py",
            "tests/test_phase11_crash_resilience.py",
            "pip_audit",
            "compileall",
        )
        missing = [token for token in required if token not in workflows]
        return AuditCheck(
            "ci_phase9_phase11_crash_contracts",
            "critical",
            not missing,
            {"missing": missing},
            "Add immutable evidence, hardening and crash tests to mandatory CI.",
        )

    def _runtime_limits(self) -> AuditCheck:
        raw = self.environ.get("PHASE11_MAX_TESTNET_NOTIONAL_USDT", "50")
        maximum = _finite(raw)
        return AuditCheck(
            "bounded_testnet_notional",
            "critical",
            maximum is not None and 0 < maximum <= 50,
            {"configured": raw, "maximum_usdt": maximum},
            "Keep the hard Testnet ceiling finite and at or below 50 USDT.",
        )

    def _read(self, relative: str) -> str:
        path = self.root / relative
        try:
            path.resolve().relative_to(self.root)
            return path.read_text(encoding="utf-8")
        except (ValueError, OSError):
            return ""


def _truthy(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _finite(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


__all__ = ["AuditCheck", "ProductionAudit"]
