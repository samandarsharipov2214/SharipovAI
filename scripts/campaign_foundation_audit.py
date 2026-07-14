"""Fail-closed audit for automatic experiments and scheduled Testnet campaigns."""
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
class Check:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True, slots=True)
class Report:
    status: str
    checks: tuple[Check, ...]

    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status, "checks": [asdict(item) for item in self.checks]}


def audit(root: Path) -> Report:
    root = root.resolve()
    checks: list[Check] = []

    def record(name: str, passed: bool, detail: str) -> None:
        checks.append(Check(name, bool(passed), detail))

    try:
        from experiments import (
            AutomaticExperimentRunner,
            ChampionChallengerRegistry,
            ImmutableExperimentResultStore,
        )

        record(
            "automatic_experiment_runner",
            all(
                item is not None
                for item in (
                    AutomaticExperimentRunner,
                    ImmutableExperimentResultStore,
                    ChampionChallengerRegistry,
                )
            ),
            "automatic runner, write-once results and leadership registry import",
        )
    except Exception as exc:
        record("automatic_experiment_runner", False, f"{type(exc).__name__}: {exc}")

    try:
        from autonomous_trading import ShadowModePlanner, ShadowModeTestnetBridge
        from campaigns import (
            FinalPromotionReportEngine,
            ScheduledCampaignOrchestrator,
            ShadowCampaignPolicy,
            TestnetShadowCampaign,
        )
        from exchange_connector import (
            BybitExecutionStateStore,
            BybitTradingReferenceClient,
            InstrumentRules,
        )
        from validation import RuntimeFillHarvester

        record(
            "scheduled_campaign_runtime",
            all(
                item is not None
                for item in (
                    BybitExecutionStateStore,
                    BybitTradingReferenceClient,
                    InstrumentRules,
                    ShadowModePlanner,
                    ShadowModeTestnetBridge,
                    RuntimeFillHarvester,
                    ScheduledCampaignOrchestrator,
                    ShadowCampaignPolicy,
                    TestnetShadowCampaign,
                    FinalPromotionReportEngine,
                )
            ),
            "execution evidence, bounded campaigns, scheduler and final report import",
        )
    except Exception as exc:
        record("scheduled_campaign_runtime", False, f"{type(exc).__name__}: {exc}")

    reference_source = _read(root / "exchange_connector" / "bybit_reference_data.py")
    execution_source = _read(root / "exchange_connector" / "bybit_execution_state.py")
    websocket_source = _read(root / "exchange_connector" / "bybit_private_order_ws.py")
    shadow_source = _read(root / "autonomous_trading" / "shadow_mode.py")
    campaign_source = _read(root / "campaigns" / "core.py")
    record(
        "actual_bybit_execution_contract",
        "/v5/account/fee-rate" in reference_source
        and "/v5/market/instruments-info" in reference_source
        and "ROUND_DOWN" in reference_source
        and "execFee" in execution_source
        and "feeCurrency" in execution_source
        and '"order", "execution"' in websocket_source
        and "maximum_testnet_notional_usdt" in shadow_source
        and "25.0" in shadow_source,
        "actual fee/instrument endpoints, execution topic, downward normalization and hard cap exist",
    )

    record(
        "bounded_campaign_policy",
        "minimum_testnet_notional_usdt: float = 10.0" in campaign_source
        and "maximum_testnet_notional_usdt: float = 25.0" in campaign_source
        and "minimum_matched_fills: int = 20" in campaign_source
        and "maximum_orphan_orders: int = 0" in campaign_source
        and "maximum_duplicate_orders: int = 0" in campaign_source
        and "maximum_unresolved_orders: int = 0" in campaign_source
        and "scheduled campaign requires manual Testnet approval" in campaign_source,
        "campaign requires approved experiment, 10-25 USDT, 20 fills and zero identity failures",
    )

    leadership_source = _read(root / "experiments" / "champion_challenger.py")
    leadership_router = _read(root / "dashboard" / "routers" / "leadership.py")
    record(
        "leadership_evidence_gate",
        "automated_gate_passed" in leadership_source
        and "manual_decision" in leadership_source
        and "runtime_deployment_changed" in leadership_source
        and "PROMOTE:" in leadership_source
        and "/champion-challenger" in leadership_router
        and "/api/strategy-leadership/{scope}/promote" in leadership_router,
        "champion promotion is evidence-bound, versioned and exposed without deploy side effects",
    )

    dashboard_entry = _read(root / "dashboard" / "__init__.py")
    campaign_api = _read(root / "dashboard" / "campaign_api.py")
    record(
        "campaign_runtime_wired",
        "install_fill_harvester_api" in dashboard_entry
        and "install_campaign_api" in dashboard_entry
        and "/api/campaigns/orchestrator/status" in campaign_api
        and "/api/campaigns/schedules" in campaign_api
        and "/api/campaigns/{campaign_id}/promotion-report" in campaign_api,
        "harvester, scheduler lifecycle, schedules and final report APIs are installed",
    )

    workflow = _read(root / ".github" / "workflows" / "tests.yml")
    required_tests = (
        "test_automatic_experiment_runner.py",
        "test_bybit_reference_data.py",
        "test_bybit_execution_state.py",
        "test_private_execution_ws.py",
        "test_shadow_mode.py",
        "test_runtime_fill_harvester.py",
        "test_scheduled_campaign_orchestrator.py",
        "test_final_promotion_report.py",
        "test_champion_challenger_registry.py",
        "test_leadership_dashboard.py",
    )
    missing = [name for name in required_tests if name not in workflow]
    record(
        "ci_campaign_regressions",
        not missing,
        "all scheduled campaign regression tests are in CI" if not missing else f"missing: {missing}",
    )

    constitution = _read(root / "CONSTITUTION.md").lower()
    readme = _read(root / "README.md").lower()
    policy_tokens = (
        "scheduled campaign orchestrator",
        "private execution topic",
        "10–25",
        "20 matched",
        "zero orphan",
        "final promotion report",
        "champion / challenger",
    )
    absent_constitution = [token for token in policy_tokens if token not in constitution]
    absent_readme = [token for token in policy_tokens if token not in readme]
    record(
        "binding_campaign_policy",
        not absent_constitution and not absent_readme,
        "Constitution and README bind scheduled execution-evidence campaigns"
        if not absent_constitution and not absent_readme
        else f"Constitution missing {absent_constitution}; README missing {absent_readme}",
    )

    passed = all(item.passed for item in checks)
    return Report("ok" if passed else "blocked", tuple(checks))


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Audit SharipovAI scheduled shadow campaign foundation"
    )
    parser.add_argument("--root", default=".")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    report = audit(Path(args.root))
    if args.json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
    else:
        for item in report.checks:
            print(f"[{'PASS' if item.passed else 'FAIL'}] {item.name}: {item.detail}")
        print(f"RESULT: {report.status}")
    return 0 if report.status == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
