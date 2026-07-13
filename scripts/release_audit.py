"""Fail-closed release audit for the VPS-based SharipovAI deployment."""
from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

EXPECTED_ORGANS = (
    "general_controller",
    "market_intelligence",
    "news_intelligence",
    "risk_engine",
    "portfolio_engine",
    "virtual_execution",
    "decision_quality",
    "learning_engine",
    "security_guard",
)
REQUIRED_ROUTES = {
    "/health",
    "/api/system/database/status",
    "/api/project-memory/messages",
    "/api/exchange/private-order-ws/status",
    "/api/exchange/private-order-ws/snapshot",
    "/api/exchange/private-order-ws/reconcile",
}


@dataclass(frozen=True, slots=True)
class AuditCheck:
    name: str
    status: str
    detail: str


@dataclass(frozen=True, slots=True)
class AuditReport:
    status: str
    checks: tuple[AuditCheck, ...]
    errors: tuple[str, ...]
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "checks": [asdict(item) for item in self.checks],
            "errors": list(self.errors),
            "warnings": list(self.warnings),
        }


def audit_repository(root: Path, *, runtime: bool = False) -> AuditReport:
    root = root.resolve()
    checks: list[AuditCheck] = []
    errors: list[str] = []
    warnings: list[str] = []

    def record(name: str, passed: bool, detail: str, *, warning: bool = False) -> None:
        status = "pass" if passed else "warning" if warning else "fail"
        checks.append(AuditCheck(name, status, detail))
        if not passed:
            (warnings if warning else errors).append(f"{name}: {detail}")

    _audit_architecture(record)
    _audit_blueprint(root, record)
    _audit_workflows(root, record)
    _audit_runtime_code(record)
    _audit_database_and_journal(record)
    if runtime:
        _audit_runtime_environment(record)

    return AuditReport(
        status="ok" if not errors else "blocked",
        checks=tuple(checks),
        errors=tuple(errors),
        warnings=tuple(warnings),
    )


def _audit_architecture(record: Callable[..., None]) -> None:
    try:
        from ai_architecture_registry import CANONICAL_AI_ORGANS

        ids = tuple(item.id for item in CANONICAL_AI_ORGANS)
        record(
            "canonical_ai_organs",
            ids == EXPECTED_ORGANS and len(ids) == len(set(ids)),
            f"found={ids}",
        )
        record(
            "ai_organ_responsibilities",
            all(organ.responsibility.strip() and organ.owns for organ in CANONICAL_AI_ORGANS),
            "all organs have responsibilities and owned capabilities",
        )
    except Exception as exc:
        record("canonical_ai_organs", False, f"{type(exc).__name__}: {exc}")


def _audit_blueprint(root: Path, record: Callable[..., None]) -> None:
    """Audit the current VPS deployment contract.

    The historical function name remains because older tooling imports it, but
    Render is not part of the active deployment.
    """
    compose_path = root / "deploy/vps/docker-compose.yml"
    caddy_path = root / "deploy/vps/Caddyfile"
    update_path = root / "deploy/vps/update_from_main.sh"
    dockerfile_path = root / "Dockerfile"
    required = (compose_path, caddy_path, update_path, dockerfile_path)
    missing = [str(path.relative_to(root)) for path in required if not path.exists()]
    record("vps_deployment_files", not missing, f"missing={missing}")
    if missing:
        return

    compose = compose_path.read_text(encoding="utf-8")
    caddy = caddy_path.read_text(encoding="utf-8")
    update = update_path.read_text(encoding="utf-8")
    contracts = {
        "vps_app_service": "sharipovai:" in compose and "uvicorn dashboard:app" in compose,
        "vps_reverse_proxy_service": "caddy:" in compose and "reverse_proxy sharipovai:8000" in caddy,
        "vps_loopback_application_port": "127.0.0.1:8000:8000" in compose,
        "vps_restart_policy": compose.count("restart: unless-stopped") >= 2,
        "vps_healthcheck": "healthcheck:" in compose and "/health" in compose,
        "vps_environment_file": ".env.vps" in compose,
        "vps_auth_enabled": _compose_env_value(compose, "SHARIPOVAI_DISABLE_AUTH") == "0",
        "vps_database_required": _compose_env_value(compose, "SHARIPOVAI_DATABASE_REQUIRED") == "1",
        "vps_testnet_locked": all(
            _compose_env_value(compose, name) == "0"
            for name in (
                "TESTNET_EXECUTION_ENABLED",
                "AUTONOMOUS_TESTNET_ENABLED",
                "AUTONOMOUS_TESTNET_BRIDGE_ENABLED",
            )
        ),
        "vps_live_locked": _compose_env_value(compose, "EXCHANGE_LIVE_TRADING_ENABLED") == "0",
        "vps_kill_switch": _compose_env_value(compose, "EXECUTION_KILL_SWITCH") == "1",
        "vps_exchange_sandbox": _compose_env_value(compose, "EXCHANGE_MODE") == "sandbox",
        "vps_stage_safe": _compose_env_value(compose, "AUTONOMOUS_TRADING_STAGE") in {"0", "1", "2"},
        "vps_private_ws_default_off": _compose_env_value(compose, "FEATURE_BYBIT_PRIVATE_ORDER_WS") == "0",
        "vps_legacy_keys_locked": _compose_env_value(compose, "BYBIT_ALLOW_LEGACY_EXCHANGE_CREDENTIALS") == "0",
        "vps_https_security_headers": all(
            token in caddy
            for token in ("Strict-Transport-Security", "X-Content-Type-Options", "X-Frame-Options")
        ),
        "vps_bounded_update": all(token in update for token in ("git", "main", "health")),
    }
    for name, passed in contracts.items():
        record(name, passed, "contract satisfied" if passed else "required VPS contract is missing or unsafe")


def _audit_workflows(root: Path, record: Callable[..., None]) -> None:
    guardrails = _read(root / ".github/workflows/project-guardrails.yml")
    full = _read(root / ".github/workflows/full-stabilization.yml")
    windows = _read(root / ".github/workflows/windows-agent-package.yml")
    recovery = _read(root / ".github/workflows/vps-recovery.yml")
    tests = _read(root / ".github/workflows/tests.yml")

    record(
        "ci_project_guardrails",
        all(
            token in guardrails
            for token in (
                "python scripts/migrate_project_db.py",
                "python -m compileall",
                "Import application safely",
                "Verify execution remains locked",
                "Run fail-closed release audit",
            )
        ),
        "migration, compile, import, execution lock and release audit gates",
    )
    record(
        "ci_full_suite",
        "Run full pytest suite" in full and "python -m pytest" in full,
        "scheduled/manual full pytest gate",
    )
    record(
        "ci_tests_isolated",
        "Prepare isolated runtime state" in tests and "EXECUTION_KILL_SWITCH: '1'" in tests,
        "primary pytest workflow isolates state and locks execution",
    )
    record(
        "ci_windows_agent",
        "runs-on: [self-hosted, Windows, X64, sharipovai-windows-ci]" in windows
        and "Run PC node tests" in windows
        and "python -m pytest" in windows,
        "self-hosted Windows agent verification gate",
    )
    record(
        "ci_vps_recovery",
        all(token in recovery for token in ("self-hosted", "127.0.0.1:8000/health", "read-only")),
        "read-only VPS diagnosis workflow",
    )


def _audit_runtime_code(record: Callable[..., None]) -> None:
    try:
        import dashboard

        # Mounted routers are not guaranteed to appear as flat APIRoute objects in
        # ``app.routes``. OpenAPI is the canonical resolved HTTP contract.
        routes = set(dashboard.app.openapi().get("paths", {}))
        missing = sorted(REQUIRED_ROUTES - routes)
        record(
            "dashboard_required_routes",
            not missing,
            f"missing={missing}" if missing else "all required routes registered",
        )
    except Exception as exc:
        record("dashboard_required_routes", False, f"dashboard import failed: {type(exc).__name__}: {exc}")

    try:
        from exchange_connector.bybit_private_order_ws import BybitPrivateOrderWebSocket

        forbidden = {
            name
            for name in dir(BybitPrivateOrderWebSocket)
            if name.lower() in {
                "create_order",
                "place_order",
                "place_market_order",
                "amend_order",
                "cancel_order",
            }
        }
        record("private_ws_read_only", not forbidden, f"forbidden_methods={sorted(forbidden)}")
    except Exception as exc:
        record("private_ws_read_only", False, f"{type(exc).__name__}: {exc}")


def _audit_database_and_journal(record: Callable[..., None]) -> None:
    try:
        from storage import ProjectDatabase

        health = ProjectDatabase().health()
        record(
            "canonical_database",
            health.get("status") == "ok",
            json.dumps(health, ensure_ascii=False, sort_keys=True),
        )
    except Exception as exc:
        record("canonical_database", False, f"{type(exc).__name__}: {exc}")

    try:
        from autonomous_trading import ExecutionJournal

        summary = ExecutionJournal().summary()
        passed = summary.get("database_backed") is True and summary.get("retention_truncated") is False
        record(
            "execution_journal_database",
            passed,
            f"database_backed={summary.get('database_backed')}, retention_truncated={summary.get('retention_truncated')}",
        )
    except Exception as exc:
        record("execution_journal_database", False, f"{type(exc).__name__}: {exc}")


def _audit_runtime_environment(record: Callable[..., None]) -> None:
    required = ("AUTH_SECRET", "ADMIN_USERNAME", "ADMIN_PASSWORD", "DATABASE_URL")
    missing = [name for name in required if not os.getenv(name, "").strip()]
    record(
        "runtime_required_configuration",
        not missing,
        f"missing={missing}" if missing else "required configuration present",
    )
    record("runtime_auth_enabled", not _truthy("SHARIPOVAI_DISABLE_AUTH"), "SHARIPOVAI_DISABLE_AUTH must be 0")
    record("runtime_database_required", _truthy("SHARIPOVAI_DATABASE_REQUIRED"), "SHARIPOVAI_DATABASE_REQUIRED must be 1")
    record("runtime_kill_switch", _truthy("EXECUTION_KILL_SWITCH"), "EXECUTION_KILL_SWITCH must be explicitly 1")
    record(
        "runtime_testnet_locked",
        not any(
            _truthy(name)
            for name in (
                "TESTNET_EXECUTION_ENABLED",
                "AUTONOMOUS_TESTNET_ENABLED",
                "AUTONOMOUS_TESTNET_BRIDGE_ENABLED",
            )
        ),
        "Testnet execution and bridge must remain disabled",
    )
    record("runtime_live_locked", not _truthy("EXCHANGE_LIVE_TRADING_ENABLED"), "Live execution must remain disabled")
    record(
        "runtime_exchange_sandbox",
        os.getenv("EXCHANGE_MODE", "").strip().lower() == "sandbox",
        "EXCHANGE_MODE must be sandbox",
    )
    stage = _integer_env("AUTONOMOUS_TRADING_STAGE")
    record("runtime_stage_safe", stage in {0, 1, 2}, f"AUTONOMOUS_TRADING_STAGE must be 0..2, found {stage}")
    record(
        "runtime_private_ws_default_off",
        not _truthy("FEATURE_BYBIT_PRIVATE_ORDER_WS"),
        "Private stream must remain off until operator activation",
    )
    record(
        "runtime_legacy_keys_locked",
        not _truthy("BYBIT_ALLOW_LEGACY_EXCHANGE_CREDENTIALS"),
        "Legacy exchange credential fallback must remain disabled",
    )
    mainnet_present = bool(
        os.getenv("BYBIT_MAINNET_API_KEY", "").strip()
        or os.getenv("BYBIT_MAINNET_API_SECRET", "").strip()
    )
    record(
        "runtime_mainnet_credentials_absent",
        not mainnet_present or _truthy("RELEASE_AUDIT_ALLOW_MAINNET_CREDENTIALS"),
        "Mainnet credentials must be absent before explicit approval",
    )
    for prefix in ("BYBIT_READONLY", "BYBIT_TESTNET", "BYBIT_MAINNET"):
        key = bool(os.getenv(f"{prefix}_API_KEY", "").strip())
        secret = bool(os.getenv(f"{prefix}_API_SECRET", "").strip())
        record(
            f"runtime_{prefix.lower()}_pair",
            key == secret,
            "credential pair must be both present or both absent",
        )
    telegram_ready = bool(
        os.getenv("BOT_TOKEN", "").strip()
        and os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip()
    )
    record(
        "runtime_telegram_secrets",
        telegram_ready,
        "Telegram secrets are not present in this environment",
        warning=True,
    )


def _compose_env_value(text: str, name: str) -> str | None:
    patterns = (
        rf'(?m)^\s*{re.escape(name)}:\s*["\']?([^"\'\s#]+)',
        rf'(?m)^\s*-\s*{re.escape(name)}=([^\s#]+)',
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1).strip().strip("\"'")
    return None


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _truthy(name: str, *, default: bool = False) -> bool:
    raw = os.getenv(name, "1" if default else "0")
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _integer_env(name: str) -> int | None:
    try:
        return int(os.getenv(name, ""))
    except (TypeError, ValueError):
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit SharipovAI release safety and correctness")
    parser.add_argument("--root", default=".")
    parser.add_argument("--runtime", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    report = audit_repository(Path(args.root), runtime=args.runtime)
    if args.json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
    else:
        for check in report.checks:
            print(f"[{check.status.upper()}] {check.name}: {check.detail}")
        print(f"RESULT: {report.status}; errors={len(report.errors)}; warnings={len(report.warnings)}")
    return 0 if report.status == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
