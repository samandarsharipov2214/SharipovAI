"""Fail-closed audit for experiments, Testnet campaigns and operator controls."""
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
            CampaignOperationsService,
            CampaignPromotionDecisionEngine,
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
                    CampaignOperationsService,
                    FinalPromotionReportEngine,
                    CampaignPromotionDecisionEngine,
                )
            ),
            "execution evidence, bounded campaign, operations, report and decision imports",
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
        "actual fees, filters, private execution topic and downward normalization exist",
    )

    record(
        "bounded_campaign_policy",
        "minimum_testnet_notional_usdt: float = 10.0" in campaign_source
        and "maximum_testnet_notional_usdt: float = 25.0" in campaign_source
        and "minimum_matched_fills: int = 20" in campaign_source
        and "maximum_orphan_orders: int = 0" in campaign_source
        and "maximum_duplicate_orders: int = 0" in campaign_source
        and "maximum_unresolved_orders: int = 0" in campaign_source
        and "actual_execution_fees" in campaign_source
        and "scheduled campaign requires manual Testnet approval" in campaign_source,
        "campaign requires approved experiment, 10-25 USDT, 20 fills and zero identity failures",
    )

    orchestrator_source = _read(root / "campaigns" / "orchestrator.py")
    operations_source = _read(root / "campaigns" / "operations.py")
    decision_source = _read(root / "campaigns" / "decisions.py")
    record(
        "single_campaign_and_manual_decision",
        "multiple non-terminal campaigns detected" in orchestrator_source
        and "global_campaign_authorization_busy" in orchestrator_source
        and "I_APPROVE_BOUNDED_TESTNET_SHADOW_CAMPAIGN" in operations_source
        and "approved_promoted_experiment" in operations_source
        and "campaign decision token does not match" in decision_source
        and "immutable manual decision" in decision_source,
        "single authorization, exact start confirmation and immutable report-bound decision exist",
    )

    dashboard_entry = _read(root / "dashboard" / "__init__.py")
    campaign_api = _read(root / "dashboard" / "campaign_api.py")
    campaign_ui = _read(root / "dashboard" / "static" / "web2" / "campaign_operations_v36.js")
    decision_ui = _read(root / "dashboard" / "static" / "web2" / "campaign_decision_v37.js")
    record(
        "campaign_runtime_and_dashboard_wired",
        "install_fill_harvester_api" in dashboard_entry
        and "install_campaign_api" in dashboard_entry
        and "/api/campaigns/operations" in campaign_api
        and "/api/campaigns/first-testnet/start" in campaign_api
        and "/api/campaigns/{campaign_id}/promotion-report" in campaign_api
        and "/api/campaigns/{campaign_id}/decision" in campaign_api
        and "matched_fills" in campaign_ui
        and "remaining_fills" in campaign_ui
        and "approval_token" in decision_ui,
        "Campaign Operations and manual report decision UI/API are installed",
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
        "leadership is evidence-bound and cannot deploy or enable execution",
    )

    cleanroom_source = _read(root / "scripts" / "ci_runtime_state.py")
    conftest_source = _read(root / "conftest.py")
    record(
        "ci_runtime_cleanroom",
        "execution_safety_violations" in cleanroom_source
        and "unsafe reset target rejected" in cleanroom_source
        and "production Bybit base URL is forbidden in CI" in cleanroom_source
        and "GITHUB_ACTIONS=true" in cleanroom_source
        and "pytest_sessionstart" in conftest_source
        and "SHARIPOVAI_CI_CLEANROOM_REPORT=" in conftest_source
        and "runtime-state-" in conftest_source,
        "every Actions pytest process fails closed and emits reset evidence",
    )

    operator_source = _read(root / "scripts" / "testnet_campaignctl.py")
    runbook = _read(root / "docs" / "first-real-testnet-campaign.md")
    operator_tokens = (
        "I_APPROVE_BOUNDED_TESTNET_SHADOW_CAMPAIGN",
        "I_APPROVE_BOUNDED_TESTNET_CAMPAIGN_CYCLE",
        "I_APPROVE_IMMUTABLE_CAMPAIGN_REPORT",
        "I_APPROVE_MANUAL_CAMPAIGN_DECISION",
        "CampaignOperationsService",
        "CampaignPromotionDecisionEngine",
    )
    record(
        "operator_control_plane",
        all(token in operator_source for token in operator_tokens)
        and "20+" in runbook
        and "actual private execution ids and fees" in runbook.lower()
        and "Synthetic fills are not evidence" in runbook,
        "operator CLI uses canonical services and runbook forbids synthetic evidence",
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
        "test_campaign_operations.py",
        "test_campaign_operations_ui.py",
    )
    missing = [name for name in required_tests if name not in workflow]
    record(
        "ci_campaign_regressions",
        not missing,
        "all campaign regression suites are in CI" if not missing else f"missing: {missing}",
    )

    new_tests = (
        root / "tests" / "test_ci_runtime_state.py",
        root / "tests" / "test_testnet_campaignctl.py",
    )
    record(
        "phase7_semantic_contracts",
        all(path.exists() for path in new_tests),
        "cleanroom and operator CLI semantic tests exist",
    )

    constitution = _read(root / "CONSTITUTION.md").lower()
    readme = _read(root / "README.md").lower()
    policy_concepts = {
        "bounded_notional": ("10–25 usdt", "10–25 usdt"),
        "matched_fills": ("20+ actual matched", "20+ matched"),
        "zero_identity_failures": ("zero orphan", "zero orphan"),
        "private_evidence": ("private order and execution evidence", "private execution evidence"),
        "final_report": ("final report", "final promotion report"),
        "manual_decision": ("manual decision", "manual decision"),
        "ci_cleanroom": ("ci cleanroom", "ci cleanroom"),
        "operator_cli": ("operator control plane", "operator cli"),
        "mainnet_lock": ("mainnet execution is compiled out", "mainnet execution is compiled out"),
    }
    missing_constitution = [
        name for name, (constitution_token, _) in policy_concepts.items()
        if constitution_token not in constitution
    ]
    missing_readme = [
        name for name, (_, readme_token) in policy_concepts.items()
        if readme_token not in readme
    ]
    record(
        "binding_campaign_policy",
        not missing_constitution and not missing_readme,
        "Constitution and README bind campaign, cleanroom and manual-decision contracts"
        if not missing_constitution and not missing_readme
        else (
            f"Constitution missing {missing_constitution}; "
            f"README missing {missing_readme}"
        ),
    )

    passed = all(item.passed for item in checks)
    return Report("ok" if passed else "blocked", tuple(checks))


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Audit SharipovAI scheduled Testnet campaign foundation"
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
