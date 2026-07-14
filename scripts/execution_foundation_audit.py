"""Fail-closed audit for the canonical execution, risk and research foundation."""
from __future__ import annotations

import inspect
import json
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class Check:
    name: str
    passed: bool
    detail: str


def run_audit() -> dict[str, Any]:
    checks: list[Check] = []

    def record(name: str, passed: bool, detail: str) -> None:
        checks.append(Check(name, bool(passed), str(detail)))

    try:
        from autonomous_trading import StartupExecutionReconciler
        from exchange_connector import (
            ApprovedExecutionRequest,
            ExecutionIdempotencyRepository,
        )
        from exchange_connector.bybit_execution import BybitExecutionClient
        from exchange_connector.execution_contract import MAINNET_EXECUTION_COMPILED

        status = BybitExecutionClient().status()
        record(
            "mainnet_compiled_out",
            MAINNET_EXECUTION_COMPILED is False
            and status.get("live_execution_enabled") is False
            and status.get("mainnet_hard_blocked") is True,
            json.dumps(
                {
                    "compiled": MAINNET_EXECUTION_COMPILED,
                    "live_enabled": status.get("live_execution_enabled"),
                    "hard_blocked": status.get("mainnet_hard_blocked"),
                },
                sort_keys=True,
            ),
        )
        record(
            "canonical_execution_imports",
            all(
                (
                    ApprovedExecutionRequest,
                    ExecutionIdempotencyRepository,
                    StartupExecutionReconciler,
                )
            ),
            "approved request, durable idempotency and reconciliation import",
        )
        legacy_source = inspect.getsource(BybitExecutionClient.place_market_order)
        record(
            "legacy_executor_removed",
            "legacy place_market_order path is removed" in legacy_source
            and "_send_market_order(" not in legacy_source,
            "legacy method contains no submission path",
        )
    except Exception as exc:
        record("canonical_execution_imports", False, f"{type(exc).__name__}: {exc}")

    try:
        from dashboard import execution_stages_api

        dashboard_source = inspect.getsource(execution_stages_api)
        record(
            "raw_dashboard_executor_removed",
            "status_code=410" in dashboard_source
            and "ApprovedExecutionRequest" in dashboard_source
            and "client.place_market_order(" not in dashboard_source,
            "manual endpoint is an authenticated tombstone",
        )
    except Exception as exc:
        record("raw_dashboard_executor_removed", False, f"{type(exc).__name__}: {exc}")

    try:
        from risk_engine import RiskLimits

        limits = RiskLimits()
        record(
            "hard_risk_defaults",
            limits.max_portfolio_exposure_percent <= 80
            and limits.max_correlated_exposure_percent <= 35
            and limits.max_daily_loss_percent <= 2
            and limits.max_portfolio_drawdown_percent <= 10,
            json.dumps(asdict(limits), sort_keys=True),
        )
    except Exception as exc:
        record("hard_risk_defaults", False, f"{type(exc).__name__}: {exc}")

    try:
        from trading_core import EventDrivenBacktester, ExecutionCostModel

        model = ExecutionCostModel()
        record(
            "event_driven_research_core",
            EventDrivenBacktester is not None
            and model.fee_rate > 0
            and model.slippage_bps > 0,
            f"fee_rate={model.fee_rate}, slippage_bps={model.slippage_bps}",
        )
    except Exception as exc:
        record("event_driven_research_core", False, f"{type(exc).__name__}: {exc}")

    errors = [item for item in checks if not item.passed]
    return {
        "status": "ok" if not errors else "blocked",
        "checks": [asdict(item) for item in checks],
        "errors": [f"{item.name}: {item.detail}" for item in errors],
    }


def main() -> int:
    report = run_audit()
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
