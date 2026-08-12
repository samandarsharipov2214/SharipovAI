"""Deterministic, fail-closed Alpha validation for pre-registered experiments."""
from __future__ import annotations

import hashlib
import math
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Callable

from historical_data import HistoricalDataLoader

from .alpha_experiment import AlphaExperiment
from .backtest import EventDrivenBacktester, Strategy
from .benchmarks import BenchmarkSuiteResult, compare_strategy_to_benchmarks
from .models import BacktestConfig, BacktestResult, Fill, MarketEvent, Side


class AlphaVerdict(StrEnum):
    ACCEPT_FOR_LONGER_PAPER = "ACCEPT_FOR_LONGER_PAPER"
    REJECT_HYPOTHESIS = "REJECT_HYPOTHESIS"
    INSUFFICIENT_SAMPLE = "INSUFFICIENT_SAMPLE"


@dataclass(frozen=True, slots=True)
class AlphaAcceptanceCriteria:
    """Thresholds that must be frozen before final holdout evaluation."""

    minimum_organic_closed_trades: int = 30
    maximum_drawdown_percent: float = 15.0
    minimum_profitable_validation_window_percent: float = 60.0
    require_positive_final_net_pnl: bool = True
    require_positive_final_expectancy: bool = True
    require_candidate_beat_buy_hold: bool = True

    def __post_init__(self) -> None:
        if (
            isinstance(self.minimum_organic_closed_trades, bool)
            or not isinstance(self.minimum_organic_closed_trades, int)
            or self.minimum_organic_closed_trades <= 0
        ):
            raise ValueError("minimum_organic_closed_trades must be a positive integer")
        for name, value in (
            ("maximum_drawdown_percent", self.maximum_drawdown_percent),
            (
                "minimum_profitable_validation_window_percent",
                self.minimum_profitable_validation_window_percent,
            ),
        ):
            if isinstance(value, bool) or not math.isfinite(float(value)):
                raise ValueError(f"{name} must be finite")
        if not 0 < self.maximum_drawdown_percent <= 100:
            raise ValueError("maximum_drawdown_percent must be within 0..100")
        if not 0 <= self.minimum_profitable_validation_window_percent <= 100:
            raise ValueError(
                "minimum_profitable_validation_window_percent must be within 0..100"
            )


@dataclass(frozen=True, slots=True)
class AlphaRunMetrics:
    net_pnl: float
    return_percent: float
    gross_trading_pnl: float
    total_fees: float
    total_spread_cost: float
    total_slippage_cost_including_impact: float
    total_funding_cost: float
    net_expectancy_per_organic_closed_trade: float
    profit_factor: float
    max_drawdown_percent: float
    fill_count: int
    organic_closed_trade_count: int
    synthetic_finalization_count: int
    winning_organic_closed_trades: int
    losing_organic_closed_trades: int
    exposure_time_percent: float

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class AlphaValidationWindow:
    start_ms: int
    end_ms: int
    event_count: int
    metrics: AlphaRunMetrics

    def to_dict(self) -> dict[str, object]:
        return {
            "start_ms": self.start_ms,
            "end_ms": self.end_ms,
            "event_count": self.event_count,
            "metrics": self.metrics.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class AlphaValidationReport:
    experiment_id: str
    experiment_fingerprint: str
    dataset_manifest_sha256: str
    strategy: str
    validation_windows: tuple[AlphaValidationWindow, ...]
    final_oos_event_count: int
    final_oos_metrics: AlphaRunMetrics
    benchmark_metrics: dict[str, AlphaRunMetrics]
    candidate_rank: int
    candidate_beats_buy_hold: bool
    profitable_validation_window_percent: float
    verdict: AlphaVerdict
    reasons: tuple[str, ...]
    paper_authorized: bool = False
    testnet_authorized: bool = False
    mainnet_authorized: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "experiment_id": self.experiment_id,
            "experiment_fingerprint": self.experiment_fingerprint,
            "dataset_manifest_sha256": self.dataset_manifest_sha256,
            "strategy": self.strategy,
            "validation_windows": [item.to_dict() for item in self.validation_windows],
            "final_oos_event_count": self.final_oos_event_count,
            "final_oos_metrics": self.final_oos_metrics.to_dict(),
            "benchmark_metrics": {
                name: metrics.to_dict() for name, metrics in self.benchmark_metrics.items()
            },
            "candidate_rank": self.candidate_rank,
            "candidate_beats_buy_hold": self.candidate_beats_buy_hold,
            "profitable_validation_window_percent": self.profitable_validation_window_percent,
            "verdict": self.verdict.value,
            "reasons": list(self.reasons),
            "paper_authorized": self.paper_authorized,
            "testnet_authorized": self.testnet_authorized,
            "mainnet_authorized": self.mainnet_authorized,
        }


def run_preregistered_alpha_validation(
    loader: HistoricalDataLoader,
    experiment: AlphaExperiment,
    strategy_factory: Callable[[], Strategy],
    *,
    candidate_name: str,
    backtest_config: BacktestConfig | None = None,
    criteria: AlphaAcceptanceCriteria | None = None,
) -> AlphaValidationReport:
    """Evaluate frozen validation windows and then one untouched final holdout.

    This function never promotes a strategy and never enables execution. It only
    produces research evidence from a dataset that passed the strict final-OOS
    provenance gate.
    """

    dataset_report = loader.require_final_oos_eligible()
    if not dataset_report.final_oos_eligible:
        raise ValueError("historical dataset is not final-OOS eligible")
    actual_manifest_sha = sha256_file(loader.manifest_path)
    if actual_manifest_sha != experiment.dataset_manifest_sha256:
        raise ValueError("experiment dataset manifest SHA256 does not match loaded manifest")
    if experiment.strategy != candidate_name:
        raise ValueError("experiment strategy identity does not match candidate_name")
    _validate_experiment_ranges(experiment, loader)

    config = backtest_config or BacktestConfig(execution_timing=experiment.execution_timing)
    if config.execution_timing != experiment.execution_timing:
        raise ValueError("backtest execution timing differs from preregistration")
    active_criteria = criteria or AlphaAcceptanceCriteria()

    validation_windows: list[AlphaValidationWindow] = []
    for start_ms, end_ms in experiment.validation_ranges:
        events = tuple(
            loader.iter_events(
                start_timestamp_ms=start_ms,
                end_timestamp_ms=end_ms,
            )
        )
        if not events:
            raise ValueError("validation range contains no market events")
        result = EventDrivenBacktester(config).run(events, strategy_factory())
        validation_windows.append(
            AlphaValidationWindow(
                start_ms=start_ms,
                end_ms=end_ms,
                event_count=len(events),
                metrics=alpha_metrics(result),
            )
        )

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
        config=config,
    )
    candidate_entry = _entry(comparison, candidate_name)
    candidate_metrics = alpha_metrics(candidate_entry.result)
    benchmark_metrics = {
        entry.name: alpha_metrics(entry.result)
        for entry in comparison.entries
        if entry.name != candidate_name
    }
    candidate_rank = comparison.ranking.index(candidate_name) + 1
    candidate_beats_buy_hold = _beats_buy_hold(comparison, candidate_name)
    profitable_percent = (
        sum(window.metrics.net_pnl > 0 for window in validation_windows)
        / len(validation_windows)
        * 100.0
    )
    verdict, reasons = _verdict(
        candidate_metrics,
        profitable_validation_window_percent=profitable_percent,
        candidate_beats_buy_hold=candidate_beats_buy_hold,
        criteria=active_criteria,
    )
    return AlphaValidationReport(
        experiment_id=experiment.experiment_id,
        experiment_fingerprint=experiment.fingerprint(),
        dataset_manifest_sha256=actual_manifest_sha,
        strategy=candidate_name,
        validation_windows=tuple(validation_windows),
        final_oos_event_count=len(final_events),
        final_oos_metrics=candidate_metrics,
        benchmark_metrics=benchmark_metrics,
        candidate_rank=candidate_rank,
        candidate_beats_buy_hold=candidate_beats_buy_hold,
        profitable_validation_window_percent=round(profitable_percent, 8),
        verdict=verdict,
        reasons=reasons,
        # ACCEPT means eligible for human-reviewed longer Paper, never automatic execution.
        paper_authorized=False,
        testnet_authorized=False,
        mainnet_authorized=False,
    )


def alpha_metrics(result: BacktestResult) -> AlphaRunMetrics:
    organic_sells = tuple(
        fill
        for fill in result.fills
        if fill.side is Side.SELL and not fill.synthetic_finalization
    )
    synthetic_count = sum(
        fill.side is Side.SELL and fill.synthetic_finalization for fill in result.fills
    )
    organic_pnls = tuple(float(fill.realized_pnl) for fill in organic_sells)
    expectancy = (
        sum(organic_pnls) / len(organic_pnls)
        if organic_pnls
        else 0.0
    )
    return AlphaRunMetrics(
        net_pnl=round(result.net_pnl, 8),
        return_percent=round(result.return_percent, 8),
        gross_trading_pnl=round(result.gross_trading_pnl, 8),
        total_fees=round(result.total_fees, 8),
        total_spread_cost=round(sum(float(fill.spread_cost) for fill in result.fills), 8),
        total_slippage_cost_including_impact=round(result.total_slippage_cost, 8),
        total_funding_cost=round(result.total_funding_cost, 8),
        net_expectancy_per_organic_closed_trade=round(expectancy, 8),
        profit_factor=round(_profit_factor(organic_pnls), 8),
        max_drawdown_percent=round(result.max_drawdown_percent, 8),
        fill_count=len(result.fills),
        organic_closed_trade_count=len(organic_sells),
        synthetic_finalization_count=int(synthetic_count),
        winning_organic_closed_trades=sum(value > 0 for value in organic_pnls),
        losing_organic_closed_trades=sum(value < 0 for value in organic_pnls),
        exposure_time_percent=round(result.exposure_time_percent, 8),
    )


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_experiment_ranges(
    experiment: AlphaExperiment,
    loader: HistoricalDataLoader,
) -> None:
    manifest = loader.manifest
    ranges = (experiment.train_range, *experiment.validation_ranges, experiment.final_oos_range)
    for start_ms, end_ms in ranges:
        if start_ms < manifest.start_timestamp_ms or end_ms > manifest.end_timestamp_ms:
            raise ValueError("experiment range falls outside dataset manifest bounds")
    ordered = sorted(ranges, key=lambda item: item[0])
    if tuple(ordered) != ranges:
        raise ValueError("experiment ranges must be chronologically ordered")
    for previous, current in zip(ranges, ranges[1:]):
        if current[0] <= previous[1]:
            raise ValueError("experiment train/validation/final ranges must not overlap")


def _entry(comparison: BenchmarkSuiteResult, name: str):
    for entry in comparison.entries:
        if entry.name == name:
            return entry
    raise RuntimeError(f"comparison did not contain candidate {name}")


def _beats_buy_hold(comparison: BenchmarkSuiteResult, candidate_name: str) -> bool:
    candidate = _entry(comparison, candidate_name)
    buy_hold = _entry(comparison, "buy_and_hold")
    return candidate.risk_adjusted_score > buy_hold.risk_adjusted_score


def _verdict(
    metrics: AlphaRunMetrics,
    *,
    profitable_validation_window_percent: float,
    candidate_beats_buy_hold: bool,
    criteria: AlphaAcceptanceCriteria,
) -> tuple[AlphaVerdict, tuple[str, ...]]:
    if metrics.organic_closed_trade_count < criteria.minimum_organic_closed_trades:
        return (
            AlphaVerdict.INSUFFICIENT_SAMPLE,
            (
                "organic_closed_trade_sample_below_preregistered_minimum",
                f"observed={metrics.organic_closed_trade_count}",
                f"required={criteria.minimum_organic_closed_trades}",
            ),
        )

    failures: list[str] = []
    if criteria.require_positive_final_net_pnl and metrics.net_pnl <= 0:
        failures.append("final_oos_net_pnl_not_positive")
    if (
        criteria.require_positive_final_expectancy
        and metrics.net_expectancy_per_organic_closed_trade <= 0
    ):
        failures.append("final_oos_net_expectancy_not_positive")
    if metrics.max_drawdown_percent > criteria.maximum_drawdown_percent:
        failures.append("final_oos_drawdown_exceeds_preregistered_limit")
    if (
        profitable_validation_window_percent
        < criteria.minimum_profitable_validation_window_percent
    ):
        failures.append("validation_window_stability_below_preregistered_minimum")
    if criteria.require_candidate_beat_buy_hold and not candidate_beats_buy_hold:
        failures.append("candidate_did_not_beat_buy_and_hold_risk_adjusted")
    if failures:
        return AlphaVerdict.REJECT_HYPOTHESIS, tuple(failures)
    return AlphaVerdict.ACCEPT_FOR_LONGER_PAPER, ("all_preregistered_acceptance_gates_passed",)


def _profit_factor(values: tuple[float, ...]) -> float:
    gross_profit = sum(value for value in values if value > 0)
    gross_loss = abs(sum(value for value in values if value < 0))
    if gross_loss == 0:
        return gross_profit if gross_profit > 0 else 0.0
    return gross_profit / gross_loss


__all__ = [
    "AlphaAcceptanceCriteria",
    "AlphaRunMetrics",
    "AlphaValidationReport",
    "AlphaValidationWindow",
    "AlphaVerdict",
    "alpha_metrics",
    "run_preregistered_alpha_validation",
    "sha256_file",
]
