"""Final-OOS handoff that never re-runs pre-final validation after claim.

The canonical CLI validates immutable bindings and sequential validation windows
before it creates the one-shot Final OOS receipt.  This module carries those
validated results and the exact manifest digest across the claim boundary, so a
transient failure cannot be introduced by repeating validation after the holdout
has been consumed.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from historical_data import HistoricalDataLoader

from .alpha_experiment import AlphaExperiment
from .alpha_validation import (
    AlphaAcceptanceCriteria,
    AlphaValidationReport,
    AlphaValidationWindow,
    _CANONICAL_BENCHMARKS,
    _beats_buy_hold,
    _entry,
    _verdict,
    alpha_metrics,
    run_preregistered_pre_final_validation,
    sha256_file,
)
from .backtest import Strategy
from .benchmarks import compare_strategy_to_benchmarks
from .models import BacktestConfig


@dataclass(frozen=True, slots=True)
class PreFinalValidationSnapshot:
    """Immutable evidence completed before a one-shot Final OOS claim."""

    train_event_count: int
    validation_windows: tuple[AlphaValidationWindow, ...]
    validated_manifest_sha256: str


def prepare_preregistered_final_oos(
    loader: HistoricalDataLoader,
    experiment: AlphaExperiment,
    strategy_factory: Callable[[], Strategy],
    *,
    candidate_name: str,
    current_git_sha: str,
    backtest_config: BacktestConfig,
    criteria: AlphaAcceptanceCriteria,
) -> PreFinalValidationSnapshot:
    """Complete all pre-final checks and freeze the manifest digest.

    The digest is checked both before and after sequential validation.  A
    concurrent/atomic manifest replacement therefore fails before the holdout is
    claimed instead of allowing the final report to point at a different file.
    """

    digest_before = sha256_file(loader.manifest_path)
    if digest_before != experiment.dataset_manifest_sha256:
        raise ValueError("experiment dataset manifest SHA256 does not match loaded manifest")

    train_event_count, validation_windows = run_preregistered_pre_final_validation(
        loader,
        experiment,
        strategy_factory,
        candidate_name=candidate_name,
        current_git_sha=current_git_sha,
        backtest_config=backtest_config,
        criteria=criteria,
    )

    digest_after = sha256_file(loader.manifest_path)
    if digest_after != digest_before:
        raise RuntimeError("dataset manifest changed during pre-final validation")

    return PreFinalValidationSnapshot(
        train_event_count=train_event_count,
        validation_windows=validation_windows,
        validated_manifest_sha256=digest_before,
    )


def run_prepared_final_oos_validation(
    loader: HistoricalDataLoader,
    experiment: AlphaExperiment,
    strategy_factory: Callable[[], Strategy],
    prepared: PreFinalValidationSnapshot,
    *,
    candidate_name: str,
    current_git_sha: str,
    backtest_config: BacktestConfig,
    criteria: AlphaAcceptanceCriteria,
) -> AlphaValidationReport:
    """Read Final OOS exactly once from already validated pre-final evidence."""

    if prepared.validated_manifest_sha256 != experiment.dataset_manifest_sha256:
        raise ValueError("prepared manifest SHA256 differs from preregistered manifest")
    _require_manifest_unchanged(loader, prepared.validated_manifest_sha256)

    final_events = tuple(
        loader.iter_events(
            start_timestamp_ms=experiment.final_oos_range[0],
            end_timestamp_ms=experiment.final_oos_range[1],
        )
    )
    if not final_events:
        raise ValueError("final OOS range contains no market events")

    comparison = compare_strategy_to_benchmarks(
        final_events,
        strategy_factory,
        candidate_name=candidate_name,
        config=backtest_config,
    )
    candidate_entry = _entry(comparison, candidate_name)
    candidate_metrics = alpha_metrics(candidate_entry.result)
    benchmark_metrics = {
        entry.name: alpha_metrics(entry.result)
        for entry in comparison.entries
        if entry.name != candidate_name
    }
    if tuple(benchmark_metrics) != _CANONICAL_BENCHMARKS:
        raise RuntimeError("benchmark engine returned a non-canonical comparison set")

    candidate_rank = comparison.ranking.index(candidate_name) + 1
    candidate_beats_buy_hold = _beats_buy_hold(comparison, candidate_name)
    profitable_percent = (
        sum(window.metrics.net_pnl > 0 for window in prepared.validation_windows)
        / len(prepared.validation_windows)
        * 100.0
    )
    verdict, reasons = _verdict(
        candidate_metrics,
        profitable_validation_window_percent=profitable_percent,
        candidate_beats_buy_hold=candidate_beats_buy_hold,
        criteria=criteria,
    )

    # The report must identify the exact manifest that was validated before the
    # one-shot claim.  A replacement at any point during Final OOS fails closed.
    _require_manifest_unchanged(loader, prepared.validated_manifest_sha256)
    manifest = loader.manifest
    return AlphaValidationReport(
        experiment_id=experiment.experiment_id,
        experiment_fingerprint=experiment.fingerprint(),
        git_sha=str(current_git_sha).strip().lower(),
        dataset_manifest_sha256=prepared.validated_manifest_sha256,
        dataset_id=manifest.dataset_id,
        dataset_version=manifest.dataset_version,
        dataset_venue=manifest.venue,
        dataset_market_type=manifest.market_type,
        dataset_source=manifest.source,
        dataset_symbols=manifest.symbols,
        dataset_interval_ms=manifest.interval_ms,
        dataset_timestamp_semantics=manifest.timestamp_semantics,
        strategy=candidate_name,
        hypothesis=experiment.hypothesis,
        falsification_rule=experiment.falsification_rule,
        train_event_count=prepared.train_event_count,
        validation_windows=prepared.validation_windows,
        final_oos_event_count=len(final_events),
        final_oos_metrics=candidate_metrics,
        benchmark_metrics=benchmark_metrics,
        candidate_rank=candidate_rank,
        candidate_beats_buy_hold=candidate_beats_buy_hold,
        profitable_validation_window_percent=round(profitable_percent, 8),
        verdict=verdict,
        reasons=reasons,
        paper_authorized=False,
        testnet_authorized=False,
        mainnet_authorized=False,
    )


def _require_manifest_unchanged(
    loader: HistoricalDataLoader,
    expected_sha256: str,
) -> None:
    if sha256_file(loader.manifest_path) != expected_sha256:
        raise RuntimeError("dataset manifest changed after pre-final validation")


__all__ = [
    "PreFinalValidationSnapshot",
    "prepare_preregistered_final_oos",
    "run_prepared_final_oos_validation",
]
