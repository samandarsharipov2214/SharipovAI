#!/usr/bin/env python3
"""Run one immutable preregistered Alpha experiment and write its verdict.

This is research-only. Even an ACCEPT_FOR_LONGER_PAPER verdict does not start a
Paper campaign and cannot enable Testnet or Mainnet.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

from historical_data import HistoricalDataLoader
from trading_core.alpha_experiment import AlphaExperiment
from trading_core.alpha_strategies import (
    RegimeFilteredBreakoutConfig,
    RegimeFilteredBreakoutStrategy,
)
from trading_core.alpha_validation import (
    AlphaAcceptanceCriteria,
    run_preregistered_alpha_validation,
)
from trading_core.models import BacktestConfig


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--experiment", required=True)
    parser.add_argument("--report", required=True, help="New immutable result JSON path")
    args = parser.parse_args()

    manifest_path = Path(args.manifest).resolve()
    experiment_path = Path(args.experiment).resolve()
    report_path = Path(args.report).resolve()
    if report_path.exists():
        raise FileExistsError("alpha result is immutable; choose a new report path")

    experiment = AlphaExperiment.load(experiment_path)
    if experiment.strategy != "regime_filtered_breakout_v1":
        raise ValueError("this runner only supports the preregistered first Alpha candidate")
    strategy_config = RegimeFilteredBreakoutConfig(**experiment.parameters)
    backtest_config = BacktestConfig(
        **experiment.cost_config,
        **experiment.risk_config,
        execution_timing=experiment.execution_timing,
    )
    criteria = AlphaAcceptanceCriteria()
    current_git_sha = _current_git_sha()

    with HistoricalDataLoader(manifest_path) as loader:
        report = run_preregistered_alpha_validation(
            loader,
            experiment,
            lambda: RegimeFilteredBreakoutStrategy(strategy_config),
            candidate_name="regime_filtered_breakout_v1",
            current_git_sha=current_git_sha,
            backtest_config=backtest_config,
            criteria=criteria,
        )

    artifact = {
        "schema_version": 1,
        "research_only": True,
        "experiment_artifact_sha256": _sha256(experiment_path),
        "result": report.to_dict(),
    }
    encoded = json.dumps(artifact, indent=2, sort_keys=True).encode("utf-8")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    temp = report_path.with_suffix(report_path.suffix + ".tmp")
    temp.write_bytes(encoded)
    temp.replace(report_path)
    report_sha256 = hashlib.sha256(encoded).hexdigest()

    print(
        json.dumps(
            {
                "status": "completed",
                "verdict": report.verdict.value,
                "reasons": list(report.reasons),
                "report": str(report_path),
                "report_sha256": report_sha256,
                "paper_started": False,
                "paper_authorized": False,
                "testnet_authorized": False,
                "mainnet_authorized": False,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _current_git_sha() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip().lower()


if __name__ == "__main__":
    raise SystemExit(main())
