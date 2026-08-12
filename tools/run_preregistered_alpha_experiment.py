#!/usr/bin/env python3
"""Run one immutable preregistered Alpha experiment and write its verdict.

This is research-only. Even an ACCEPT_FOR_LONGER_PAPER verdict does not start a
Paper campaign and cannot enable Testnet or Mainnet. Final OOS is claimed once
per content-addressed dataset holdout range.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

from historical_data import HistoricalDataLoader
from trading_core.alpha_consumption import claim_final_oos, complete_final_oos
from trading_core.alpha_dataset_contract import require_regime_breakout_dataset
from trading_core.alpha_experiment import AlphaExperiment
from trading_core.alpha_final_oos import (
    prepare_preregistered_final_oos as run_preregistered_pre_final_validation,
    run_prepared_final_oos_validation,
)
from trading_core.alpha_strategies import (
    RegimeFilteredBreakoutConfig,
    RegimeFilteredBreakoutStrategy,
)
from trading_core.alpha_validation import (
    AlphaAcceptanceCriteria,
    canonical_falsification_rule,
    sha256_file,
)
from trading_core.models import BacktestConfig

_BENCHMARKS = ("buy_and_hold", "trend_following", "breakout", "mean_reversion")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--experiment", required=True)
    parser.add_argument("--report", required=True, help="New immutable result JSON path")
    args = parser.parse_args()

    _require_clean_git_worktree()
    manifest_path = Path(args.manifest).resolve()
    experiment_path = Path(args.experiment).resolve()
    report_path = Path(args.report).resolve()
    if report_path.exists():
        raise FileExistsError("alpha result is immutable; choose a new report path")

    experiment = AlphaExperiment.load(experiment_path)
    if experiment.strategy != "regime_filtered_breakout_v1":
        raise ValueError("this runner only supports the preregistered first Alpha candidate")
    strategy_config = RegimeFilteredBreakoutConfig(**experiment.parameters)
    strategy_probe = RegimeFilteredBreakoutStrategy(strategy_config)
    backtest_config = BacktestConfig(
        **experiment.cost_config,
        **experiment.risk_config,
        execution_timing=experiment.execution_timing,
    )
    criteria = AlphaAcceptanceCriteria()
    current_git_sha = _current_git_sha()
    if current_git_sha != experiment.git_sha:
        raise ValueError("current git SHA differs from preregistered git SHA")
    if sha256_file(manifest_path) != experiment.dataset_manifest_sha256:
        raise ValueError("experiment dataset manifest SHA256 does not match loaded manifest")
    if strategy_probe.hypothesis != experiment.hypothesis:
        raise ValueError("strategy hypothesis differs from preregistration")
    if tuple(experiment.acceptance_metrics) != criteria.canonical_metrics():
        raise ValueError("acceptance criteria differ from preregistration")
    if experiment.falsification_rule != canonical_falsification_rule(criteria):
        raise ValueError("falsification rule differs from preregistered acceptance contract")
    if tuple(experiment.benchmarks) != _BENCHMARKS:
        raise ValueError("experiment benchmarks differ from canonical benchmark suite")

    experiment_artifact_sha256 = _sha256(experiment_path)
    with HistoricalDataLoader(manifest_path) as loader:
        require_regime_breakout_dataset(loader)
        _validate_ranges_within_manifest(experiment, loader)
        # Keep the established callable name so the source-level ordering
        # contract continues to prove pre-final completion before claim.  The
        # implementation now returns an immutable evidence snapshot instead of
        # being replayed later.
        prepared = run_preregistered_pre_final_validation(
            loader,
            experiment,
            lambda: RegimeFilteredBreakoutStrategy(strategy_config),
            candidate_name="regime_filtered_breakout_v1",
            current_git_sha=current_git_sha,
            backtest_config=backtest_config,
            criteria=criteria,
        )
        receipt_path = claim_final_oos(
            manifest_path=manifest_path,
            experiment=experiment,
            experiment_artifact_sha256=experiment_artifact_sha256,
        )
        # Do not repeat pre-final validation after the receipt exists.  Only the
        # untouched holdout and benchmarks are evaluated from the frozen snapshot.
        report = run_prepared_final_oos_validation(
            loader,
            experiment,
            lambda: RegimeFilteredBreakoutStrategy(strategy_config),
            prepared,
            candidate_name="regime_filtered_breakout_v1",
            current_git_sha=current_git_sha,
            backtest_config=backtest_config,
            criteria=criteria,
        )

    artifact = {
        "schema_version": 1,
        "research_only": True,
        "experiment_artifact_sha256": experiment_artifact_sha256,
        "final_oos_consumption_receipt": str(receipt_path),
        "result": report.to_dict(),
    }
    encoded = json.dumps(artifact, indent=2, sort_keys=True).encode("utf-8")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with report_path.open("xb") as handle:
            handle.write(encoded)
    except FileExistsError as exc:
        raise FileExistsError("alpha result path became occupied during execution") from exc
    report_sha256 = hashlib.sha256(encoded).hexdigest()
    complete_final_oos(
        receipt_path,
        verdict=report.verdict.value,
        report_path=report_path,
        report_sha256=report_sha256,
    )

    print(
        json.dumps(
            {
                "status": "completed",
                "verdict": report.verdict.value,
                "reasons": list(report.reasons),
                "report": str(report_path),
                "report_sha256": report_sha256,
                "final_oos_consumption_receipt": str(receipt_path),
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


def _validate_ranges_within_manifest(
    experiment: AlphaExperiment,
    loader: HistoricalDataLoader,
) -> None:
    manifest = loader.manifest
    for start_ms, end_ms in (
        experiment.train_range,
        *experiment.validation_ranges,
        experiment.final_oos_range,
    ):
        if start_ms < manifest.start_timestamp_ms or end_ms > manifest.end_timestamp_ms:
            raise ValueError("experiment range falls outside dataset manifest bounds")


def _require_clean_git_worktree() -> None:
    completed = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=normal"],
        check=True,
        capture_output=True,
        text=True,
    )
    if completed.stdout.strip():
        raise RuntimeError("alpha research requires a clean git worktree")


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
