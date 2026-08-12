#!/usr/bin/env python3
"""Create an immutable preregistration for SharipovAI Alpha candidate v1.

This command does not run the final holdout. It only verifies the historical
manifest is final-OOS eligible and freezes code/data/strategy/cost/risk/ranges,
benchmarks and acceptance gates into a content-fingerprinted artifact.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime
from pathlib import Path

from historical_data import HistoricalDataLoader
from trading_core.alpha_experiment import AlphaExperiment
from trading_core.alpha_strategies import RegimeFilteredBreakoutConfig
from trading_core.alpha_validation import (
    AlphaAcceptanceCriteria,
    backtest_cost_config,
    backtest_risk_config,
    sha256_file,
)
from trading_core.models import BacktestConfig

_BENCHMARKS = ("buy_and_hold", "trend_following", "breakout", "mean_reversion")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, help="Canonical historical-data manifest.json")
    parser.add_argument("--output", required=True, help="New immutable preregistration JSON path")
    parser.add_argument("--experiment-id", required=True)
    parser.add_argument("--train", required=True, help="start,end as ISO-8601 or epoch-ms")
    parser.add_argument(
        "--validation",
        action="append",
        required=True,
        help="Validation start,end; repeat for each sequential window",
    )
    parser.add_argument("--final-oos", required=True, help="Untouched final start,end")
    args = parser.parse_args()

    manifest_path = Path(args.manifest).resolve()
    output_path = Path(args.output).resolve()
    current_git_sha = _current_git_sha()

    strategy_config = RegimeFilteredBreakoutConfig()
    backtest_config = BacktestConfig(execution_timing="auto")
    criteria = AlphaAcceptanceCriteria()

    with HistoricalDataLoader(manifest_path) as loader:
        report = loader.require_final_oos_eligible()
        if not report.final_oos_eligible:
            raise ValueError("dataset is not final-OOS eligible")

    experiment = AlphaExperiment(
        experiment_id=str(args.experiment_id).strip(),
        git_sha=current_git_sha,
        dataset_manifest_sha256=sha256_file(manifest_path),
        strategy="regime_filtered_breakout_v1",
        parameters=strategy_config.to_dict(),
        cost_config=backtest_cost_config(backtest_config),
        risk_config=backtest_risk_config(backtest_config),
        execution_timing=backtest_config.execution_timing,
        train_range=_range(args.train),
        validation_ranges=tuple(_range(value) for value in args.validation),
        final_oos_range=_range(args.final_oos),
        benchmarks=_BENCHMARKS,
        acceptance_metrics=criteria.canonical_metrics(),
    )
    experiment.save(output_path)
    print(
        json.dumps(
            {
                "status": "preregistered",
                "experiment_id": experiment.experiment_id,
                "fingerprint": experiment.fingerprint(),
                "git_sha": experiment.git_sha,
                "dataset_manifest_sha256": experiment.dataset_manifest_sha256,
                "strategy": experiment.strategy,
                "train_range": experiment.train_range,
                "validation_ranges": experiment.validation_ranges,
                "final_oos_range": experiment.final_oos_range,
                "output": str(output_path),
                "final_oos_executed": False,
                "paper_authorized": False,
                "testnet_authorized": False,
                "mainnet_authorized": False,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _range(value: str) -> tuple[int, int]:
    parts = [item.strip() for item in str(value).split(",")]
    if len(parts) != 2 or not all(parts):
        raise ValueError("range must be start,end")
    return _timestamp_ms(parts[0]), _timestamp_ms(parts[1])


def _timestamp_ms(value: str) -> int:
    clean = str(value).strip()
    if clean.isdigit():
        parsed = int(clean)
        if parsed <= 0:
            raise ValueError("timestamp must be positive")
        return parsed
    try:
        moment = datetime.fromisoformat(clean.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"invalid ISO-8601 timestamp: {value}") from exc
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError("ISO-8601 timestamps must include a timezone")
    parsed = int(moment.timestamp() * 1000)
    if parsed <= 0:
        raise ValueError("timestamp must be positive")
    return parsed


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
