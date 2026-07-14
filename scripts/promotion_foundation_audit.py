"""Fail-closed audit for experiment, fill-validation and promotion foundations."""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@dataclass(frozen=True, slots=True)
class AuditCheck:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True, slots=True)
class AuditReport:
    status: str
    checks: tuple[AuditCheck, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "checks": [asdict(check) for check in self.checks],
        }


def audit_promotion_foundation(root: Path) -> AuditReport:
    root = root.resolve()
    checks: list[AuditCheck] = []

    def record(name: str, passed: bool, detail: str) -> None:
        checks.append(AuditCheck(name=name, passed=bool(passed), detail=detail))

    try:
        from experiments import ExperimentRegistry, PromotionGateEngine, PromotionTarget
        from validation import FillDivergenceAnalyzer, FillValidationRepository

        record(
            "experiment_registry",
            ExperimentRegistry is not None,
            "canonical experiment registry imports",
        )
        record(
            "promotion_gate_engine",
            PromotionGateEngine is not None and PromotionTarget is not None,
            "automated report and staged targets import",
        )
        record(
            "fill_divergence_validation",
            FillDivergenceAnalyzer is not None and FillValidationRepository is not None,
            "Paper/Testnet divergence and persistence APIs import",
        )
    except Exception as exc:
        detail = f"{type(exc).__name__}: {exc}"
        record("experiment_registry", False, detail)
        record("promotion_gate_engine", False, detail)
        record("fill_divergence_validation", False, detail)

    try:
        from exchange_connector.execution_contract import MAINNET_EXECUTION_COMPILED
        from exchange_connector.private_ws_gate import PrivateStreamHealthRepository

        record(
            "private_stream_gate",
            PrivateStreamHealthRepository is not None,
            "persistent private WebSocket readiness gate imports",
        )
        record(
            "mainnet_compile_lock",
            MAINNET_EXECUTION_COMPILED is False,
            "Mainnet remains compiled out",
        )
    except Exception as exc:
        detail = f"{type(exc).__name__}: {exc}"
        record("private_stream_gate", False, detail)
        record("mainnet_compile_lock", False, detail)

    registry_source = _read(root / "experiments" / "registry.py")
    record(
        "manual_approval_binding",
        "APPROVE:" in registry_source
        and "blocked promotion cannot be manually approved" in registry_source
        and "runtime" not in registry_source.lower().split("manual_decision", 1)[-1][:800],
        "manual approval is experiment/stage-bound and cannot override blocked gates",
    )

    reconciler = _read(root / "autonomous_trading" / "startup_reconciliation.py")
    private_worker = _read(root / "exchange_connector" / "bybit_private_order_ws.py")
    record(
        "testnet_private_stream_startup_gate",
        "require_private_stream" in reconciler
        and "private_stream_ready" in reconciler
        and "PrivateStreamHealthRepository" in private_worker
        and "last_heartbeat_at_ms" in private_worker,
        "Testnet reconciliation consumes persisted private-stream heartbeat evidence",
    )

    router = _read(root / "dashboard" / "routers" / "experiments.py")
    route_tokens = (
        "/backtest-results",
        "/experiment-comparison",
        "/api/experiments",
        "promotion-report",
        "promotion-decision",
        "runtime_flags_changed",
    )
    missing_routes = [token for token in route_tokens if token not in router]
    record(
        "experiment_dashboard",
        not missing_routes,
        "read-only result/comparison views and admin promotion endpoints are wired"
        if not missing_routes
        else f"missing dashboard tokens: {missing_routes}",
    )

    tests_workflow = _read(root / ".github" / "workflows" / "tests.yml")
    required_tests = (
        "test_experiment_registry_promotion.py",
        "test_fill_divergence_validation.py",
        "test_private_ws_startup_gate.py",
        "test_experiment_dashboard.py",
    )
    missing_tests = [name for name in required_tests if name not in tests_workflow]
    record(
        "ci_promotion_suite",
        not missing_tests,
        "all promotion foundation tests are in critical CI"
        if not missing_tests
        else f"missing tests in CI: {missing_tests}",
    )

    constitution = _read(root / "CONSTITUTION.md").lower()
    policy_tokens = (
        "persistent experiment registry",
        "paper -> testnet",
        "testnet -> controlled_mainnet",
        "private order websocket gate",
        "manual approval rules",
        "mainnet_execution_compiled=false",
    )
    missing_policy = [token for token in policy_tokens if token not in constitution]
    record(
        "binding_staged_promotion_policy",
        not missing_policy,
        "Constitution binds Research/Paper/Testnet/Controlled Mainnet gates"
        if not missing_policy
        else f"missing Constitution tokens: {missing_policy}",
    )

    readme = _read(root / "README.md").lower()
    docs_tokens = (
        "experimentregistry",
        "filldivergenceanalyzer",
        "/backtest-results",
        "/experiment-comparison",
        "feature_bybit_private_order_ws=0",
    )
    missing_docs = [token for token in docs_tokens if token not in readme]
    record(
        "promotion_documentation",
        not missing_docs,
        "README documents experiment, validation, stream and UI surfaces"
        if not missing_docs
        else f"missing README tokens: {missing_docs}",
    )

    passed = all(check.passed for check in checks)
    return AuditReport(status="ok" if passed else "blocked", checks=tuple(checks))


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Audit SharipovAI experiment promotion foundation"
    )
    parser.add_argument("--root", default=".")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    report = audit_promotion_foundation(Path(args.root))
    if args.json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
    else:
        for check in report.checks:
            status = "PASS" if check.passed else "FAIL"
            print(f"[{status}] {check.name}: {check.detail}")
        print(f"RESULT: {report.status}")
    return 0 if report.status == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
