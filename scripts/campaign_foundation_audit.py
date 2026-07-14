"""Fail-closed audit for automatic experiments and Testnet shadow campaigns."""
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
        from exchange_connector import BybitTradingReferenceClient, InstrumentRules
        from autonomous_trading import ShadowModePlanner, ShadowModeTestnetBridge

        record(
            "shadow_reference_execution",
            all(
                item is not None
                for item in (
                    BybitTradingReferenceClient,
                    InstrumentRules,
                    ShadowModePlanner,
                    ShadowModeTestnetBridge,
                )
            ),
            "dynamic fee/instrument data and shadow-only bridge import",
        )
    except Exception as exc:
        record("shadow_reference_execution", False, f"{type(exc).__name__}: {exc}")

    try:
        from validation import RuntimeFillHarvester

        record(
            "runtime_fill_harvester",
            RuntimeFillHarvester is not None,
            "runtime Paper/Testnet fill harvester imports",
        )
    except Exception as exc:
        record("runtime_fill_harvester", False, f"{type(exc).__name__}: {exc}")

    reference_source = _read(root / "exchange_connector" / "bybit_reference_data.py")
    shadow_source = _read(root / "autonomous_trading" / "shadow_mode.py")
    record(
        "actual_bybit_reference_contract",
        "/v5/account/fee-rate" in reference_source
        and "/v5/market/instruments-info" in reference_source
        and "ROUND_DOWN" in reference_source
        and "maximum_testnet_notional_usdt" in shadow_source
        and "25.0" in shadow_source,
        "actual fee/instrument endpoints, downward normalization and hard shadow cap exist",
    )

    leadership_source = _read(root / "experiments" / "champion_challenger.py")
    record(
        "leadership_evidence_gate",
        "automated_gate_passed" in leadership_source
        and "manual_decision" in leadership_source
        and "runtime_deployment_changed" in leadership_source
        and "PROMOTE:" in leadership_source,
        "champion promotion requires automated plus manual evidence and has no deploy side effect",
    )

    dashboard_entry = _read(root / "dashboard" / "__init__.py")
    record(
        "runtime_harvester_wired",
        "install_fill_harvester_api" in dashboard_entry,
        "fill harvester is installed into the application lifecycle",
    )

    workflow = _read(root / ".github" / "workflows" / "tests.yml")
    required_tests = (
        "test_automatic_experiment_runner.py",
        "test_bybit_reference_data.py",
        "test_shadow_mode.py",
        "test_runtime_fill_harvester.py",
        "test_champion_challenger_registry.py",
    )
    missing = [name for name in required_tests if name not in workflow]
    record(
        "ci_campaign_regressions",
        not missing,
        "all campaign regression tests are in CI" if not missing else f"missing: {missing}",
    )

    constitution = _read(root / "CONSTITUTION.md").lower()
    policy_tokens = (
        "automatic experiment",
        "shadow mode",
        "champion",
        "challenger",
        "actual bybit",
        "runtime fill harvester",
    )
    absent = [token for token in policy_tokens if token not in constitution]
    record(
        "binding_campaign_policy",
        not absent,
        "Constitution binds automatic research and shadow campaigns"
        if not absent
        else f"missing policy tokens: {absent}",
    )

    passed = all(item.passed for item in checks)
    return Report("ok" if passed else "blocked", tuple(checks))


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit SharipovAI shadow campaign foundation")
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
