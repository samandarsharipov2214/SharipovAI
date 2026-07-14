"""Fail-closed audit for research, historical data and observability foundations."""
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


def audit_research_foundation(root: Path) -> AuditReport:
    root = root.resolve()
    checks: list[AuditCheck] = []

    def record(name: str, passed: bool, detail: str) -> None:
        checks.append(AuditCheck(name=name, passed=bool(passed), detail=detail))

    try:
        from trading_core import (
            BreakoutStrategy,
            BuyAndHoldStrategy,
            EventDrivenBacktester,
            MeanReversionStrategy,
            TrendFollowingStrategy,
            WalkForwardBacktester,
            compare_strategy_to_benchmarks,
            run_benchmark_suite,
        )

        record(
            "event_driven_walk_forward",
            EventDrivenBacktester is not None and WalkForwardBacktester is not None,
            "event-driven and walk-forward APIs import",
        )
        benchmark_types = (
            BuyAndHoldStrategy,
            TrendFollowingStrategy,
            BreakoutStrategy,
            MeanReversionStrategy,
        )
        record(
            "mandatory_benchmarks",
            all(item is not None for item in benchmark_types)
            and run_benchmark_suite is not None
            and compare_strategy_to_benchmarks is not None,
            "buy-hold, trend, breakout and mean-reversion are available",
        )
    except Exception as exc:
        record(
            "event_driven_walk_forward",
            False,
            f"{type(exc).__name__}: {exc}",
        )
        record(
            "mandatory_benchmarks",
            False,
            f"{type(exc).__name__}: {exc}",
        )

    try:
        from historical_data import DataManifest, HistoricalDataLoader, validate_dataset

        record(
            "historical_data_layer",
            DataManifest is not None
            and HistoricalDataLoader is not None
            and validate_dataset is not None,
            "manifest, DuckDB loader and validation APIs import",
        )
    except Exception as exc:
        record("historical_data_layer", False, f"{type(exc).__name__}: {exc}")

    try:
        from observability import JsonFormatter, observe_http, record_backtest_result

        record(
            "observability_layer",
            JsonFormatter is not None
            and observe_http is not None
            and record_backtest_result is not None,
            "structured logs and Prometheus metrics APIs import",
        )
    except Exception as exc:
        record("observability_layer", False, f"{type(exc).__name__}: {exc}")

    requirements = _read(root / "requirements.txt").lower()
    record(
        "research_dependencies",
        "duckdb" in requirements and "prometheus-client" in requirements,
        "DuckDB and prometheus-client are declared",
    )

    dashboard_entry = _read(root / "dashboard" / "__init__.py")
    execution_router = _read(root / "dashboard" / "routers" / "execution_status.py")
    record(
        "dashboard_operational_structure",
        "install_operational_routers" in dashboard_entry
        and "install_observability" in dashboard_entry
        and "ApprovedExecutionRequest" in execution_router
        and "raw_order_api" in execution_router,
        "operational routers, observability and read-only execution status are wired",
    )

    tests_workflow = _read(root / ".github" / "workflows" / "tests.yml")
    required_tests = (
        "test_trading_core_funding_walk_forward.py",
        "test_benchmark_strategies.py",
        "test_historical_data_layer.py",
        "test_observability.py",
        "test_execution_status_router.py",
    )
    missing_tests = [name for name in required_tests if name not in tests_workflow]
    record(
        "ci_research_suite",
        not missing_tests,
        "all required research tests are in CI"
        if not missing_tests
        else f"missing tests in CI: {missing_tests}",
    )

    constitution = _read(root / "CONSTITUTION.md").lower()
    promotion_tokens = (
        "promotion gate",
        "walk-forward",
        "out-of-sample",
        "buy-and-hold",
        "funding",
    )
    missing_policy = [token for token in promotion_tokens if token not in constitution]
    record(
        "binding_promotion_gate",
        not missing_policy,
        "Constitution contains explicit research promotion rules"
        if not missing_policy
        else f"missing Constitution tokens: {missing_policy}",
    )

    readme = _read(root / "README.md").lower()
    documentation_tokens = (
        "historical_data",
        "walkforwardbacktester",
        "/execution-status",
        "/metrics",
    )
    missing_docs = [token for token in documentation_tokens if token not in readme]
    record(
        "research_documentation",
        not missing_docs,
        "README documents research, data and operational surfaces"
        if not missing_docs
        else f"missing README tokens: {missing_docs}",
    )

    passed = all(check.passed for check in checks)
    return AuditReport(status="ok" if passed else "blocked", checks=tuple(checks))


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit SharipovAI research foundation")
    parser.add_argument("--root", default=".")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    report = audit_research_foundation(Path(args.root))
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
