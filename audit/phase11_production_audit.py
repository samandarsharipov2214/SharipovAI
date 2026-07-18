"""Deterministic fail-closed production readiness audit.

The audit is read-only. It never changes flags, credentials, database state,
campaign state, scaling authority, or execution state.
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
    """Runs secret-free checks and emits deterministic evidence."""

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
            self._check_compile_and_runtime_execution_lock(),
            self._check_safe_runtime_configuration(),
            self._check_database_health(),
            self._check_secret_hygiene(),
            self._check_required_assets(),
            self._check_deployment_contracts(),
            self._check_dashboard_contracts(),
            self._check_ci_crash_contracts(),
            self._check_runtime_limits(),
        ]
        blockers = sorted(
            check.name for check in checks if not check.passed and check.severity == "critical"
        )
        warnings = sorted(
            check.name for check in checks if not check.passed and check.severity != "critical"
        )
        deterministic = {
            "schema_version": 2,
            "status": "ready_for_bounded_testnet_preflight" if not blockers else "blocked",
            "blockers": blockers,
            "warnings": warnings,
            "checks": [asdict(check) for check in checks],
            "mainnet_enabled": False,
            "automatic_campaign_launch": False,
        }
        evidence_hash = hashlib.sha256(_canonical_json(deterministic)).hexdigest()
        return {
            **deterministic,
            "created_at_ms": int(time.time() * 1000),
            "host": {
                "python": platform.python_version(),
                "platform": platform.system(),
            },
            "audit_sha256": evidence_hash,
        }

    def _check_compile_and_runtime_execution_lock(self) -> AuditCheck:
        evidence: dict[str, Any] = {}
        passed = False
        try:
            from exchange_connector.bybit_execution import BybitExecutionClient
            from exchange_connector.execution_contract import MAINNET_EXECUTION_COMPILED

            status = BybitExecutionClient().status()
            evidence = {
                "compiled": bool(MAINNET_EXECUTION_COMPILED),
                "live_execution_enabled": bool(status.get("live_execution_enabled")),
                "mainnet_hard_blocked": bool(status.get("mainnet_hard_blocked")),
                "testnet_execution_enabled": bool(status.get("testnet_execution_enabled")),
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
        return AuditCheck(
            "compile_and_runtime_execution_lock",
            "critical",
            passed,
            evidence,
            "Restore the compile lock, kill switch and disabled execution state.",
        )

    def _check_safe_runtime_configuration(self) -> AuditCheck:
        required_disabled = (
            "EXCHANGE_LIVE_TRADING_ENABLED",
            "FEATURE_BYBIT_LIVE_EXECUTION",
            "FEATURE_BYBIT_TESTNET_EXECUTION",
            "TESTNET_EXECUTION_ENABLED",
            "AUTONOMOUS_TESTNET_ENABLED",
            "AUTONOMOUS_TESTNET_BRIDGE_ENABLED",
            "FEATURE_BYBIT_PRIVATE_ORDER_WS",
            "BYBIT_ALLOW_LEGACY_EXCHANGE_CREDENTIALS",
        )
        unsafe = sorted(name for name in required_disabled if _truthy(self.environ.get(name, "0")))
        kill_switch = _truthy(self.environ.get("EXECUTION_KILL_SWITCH", "1"))
        auth_enabled = not _truthy(self.environ.get("SHARIPOVAI_DISABLE_AUTH", "0"))
        database_required = _truthy(self.environ.get("SHARIPOVAI_DATABASE_REQUIRED", "1"))
        exchange_mode = str(self.environ.get("EXCHANGE_MODE", "sandbox")).strip().lower()
        passed = not unsafe and kill_switch and auth_enabled and database_required and exchange_mode == "sandbox"
        return AuditCheck(
            "safe_runtime_configuration",
            "critical",
            passed,
            {
                "unsafe_enabled_flags": unsafe,
                "kill_switch_engaged": kill_switch,
                "authentication_enabled": auth_enabled,
                "database_required": database_required,
                "exchange_mode_is_sandbox": exchange_mode == "sandbox",
            },
            "Disable execution flags, enable auth/database requirements and keep sandbox mode.",
        )

    def _check_database_health(self) -> AuditCheck:
        try:
            from storage import ProjectDatabase

            health = ProjectDatabase(self.environ.get("DATABASE_URL") or None).health()
            passed = health.get("status") == "ok" and int(health.get("schema_version") or 0) >= 1
            evidence = {
                "status": health.get("status"),
                "backend": health.get("backend"),
                "required": health.get("required"),
                "schema_version": health.get("schema_version"),
                "error_type": str(health.get("error") or "").split(":", 1)[0] or None,
            }
        except Exception as exc:
            passed = False
            evidence = {"status": "error", "error_type": type(exc).__name__}
        return AuditCheck(
            "canonical_database_health",
            "critical",
            passed,
            evidence,
            "Restore the canonical database and verify schema migrations.",
        )

    def _check_secret_hygiene(self) -> AuditCheck:
        forbidden_names = {
            ".env",
            ".env.testnet-campaign",
            "secrets.json",
            "credentials.json",
            "id_rsa",
            "id_ed25519",
        }
        present = sorted(name for name in forbidden_names if (self.root / name).exists())
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
            paths = [item.decode("utf-8", errors="replace") for item in result.stdout.split(b"\0") if item]
            for path in paths:
                candidate = Path(path)
                if candidate.name in forbidden_names or candidate.suffix.lower() in {".pem", ".key", ".p12", ".pfx"}:
                    tracked.append(path)
        except (OSError, subprocess.SubprocessError):
            git_verified = False
        passed = not present and not tracked and git_verified
        return AuditCheck(
            "secret_file_hygiene",
            "critical",
            passed,
            {
                "forbidden_root_files": present,
                "forbidden_tracked_files": sorted(tracked),
                "git_inventory_verified": git_verified,
            },
            "Remove tracked secret material, rotate credentials and restore Git inventory verification.",
        )

    def _check_required_assets(self) -> AuditCheck:
        required = (
            "CONSTITUTION.md",
            "README.md",
            "dashboard/static/web2/index.html",
            "dashboard/phase10_scaling_api.py",
            "dashboard/phase11_production_api.py",
            "campaigns/phase10_scaling.py",
            "risk/phase10_capital_engine.py",
            "deploy/vps/phase11_release_preflight.sh",
            "deploy/vps/phase11_post_deploy_verify.sh",
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

    def _check_deployment_contracts(self) -> AuditCheck:
        preflight = self._read("deploy/vps/phase11_release_preflight.sh")
        verifier = self._read("deploy/vps/phase11_post_deploy_verify.sh")
        required_preflight = (
            "git diff --quiet",
            "SHARIPOVAI_EXPECTED_SHA",
            "SHARIPOVAI_DATABASE_REQUIRED",
            "tests/test_phase11_crash_resilience.py",
            "ProductionAudit",
        )
        required_verifier = (
            "mktemp",
            "ProjectDatabase",
            "os.replace",
            "audit_sha256",
            "http_health",
        )
        missing = [f"preflight:{token}" for token in required_preflight if token not in preflight]
        missing.extend(f"post_deploy:{token}" for token in required_verifier if token not in verifier)
        executable = all(
            os.access(self.root / path, os.X_OK)
            for path in (
                "deploy/vps/phase11_release_preflight.sh",
                "deploy/vps/phase11_post_deploy_verify.sh",
            )
            if (self.root / path).exists()
        )
        if not executable:
            missing.append("deployment_scripts_not_executable")
        return AuditCheck(
            "deployment_preflight_and_verification",
            "critical",
            not missing,
            {"missing_contracts": missing},
            "Restore immutable-SHA, clean-tree, database, atomic-output and crash-test checks.",
        )

    def _check_dashboard_contracts(self) -> AuditCheck:
        index = self._read("dashboard/static/web2/index.html")
        script = self._read("dashboard/static/web2/phase11_production_v43.js")
        stylesheet = self._read("dashboard/static/web2/phase11_production_v43.css")
        tokens = {
            "index": (
                "viewport",
                "theme-color",
                "data-phase11-production",
                "phase11_production_v43.js",
            ),
            "script": (
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
        }
        sources = {"index": index, "script": script, "stylesheet": stylesheet}
        missing = [f"{source}:{token}" for source, expected in tokens.items() for token in expected if token not in sources[source]]
        unsafe = [token for token in ("innerHTML", "insertAdjacentHTML", "eval(") if token in script]
        return AuditCheck(
            "dashboard_responsive_realtime_contract",
            "warning",
            not missing and not unsafe,
            {"missing": missing, "unsafe_dom_patterns": unsafe},
            "Restore accessible, abortable, visibility-aware and injection-safe rendering.",
        )

    def _check_ci_crash_contracts(self) -> AuditCheck:
        workflow = self._read(".github/workflows/tests.yml")
        required = (
            "tests/test_phase10_controlled_scaling.py",
            "tests/test_phase10_capital_engine.py",
            "tests/test_phase11_production_audit.py",
            "tests/test_phase11_crash_resilience.py",
        )
        missing = [token for token in required if token not in workflow]
        return AuditCheck(
            "ci_phase10_phase11_crash_contracts",
            "critical",
            not missing,
            {"missing": missing},
            "Add Phase 10/11 hardening and crash tests to mandatory CI.",
        )

    def _check_runtime_limits(self) -> AuditCheck:
        raw = self.environ.get("PHASE11_MAX_TESTNET_NOTIONAL_USDT", "50")
        maximum = _finite(raw)
        passed = maximum is not None and 0 < maximum <= 50
        return AuditCheck(
            "bounded_testnet_notional",
            "critical",
            passed,
            {"configured": raw, "maximum_usdt": maximum},
            "Keep the hard Testnet ceiling finite and at or below 50 USDT.",
        )

    def _read(self, relative: str) -> str:
        path = self.root / relative
        try:
            path.resolve().relative_to(self.root)
        except ValueError:
            return ""
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
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
