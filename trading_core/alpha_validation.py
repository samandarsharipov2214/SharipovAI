"""Deterministic, fail-closed Alpha validation for pre-registered experiments."""
from __future__ import annotations

import hashlib
import math
import re
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Callable

from historical_data import HistoricalDataLoader

from .alpha_experiment import AlphaExperiment
from .alpha_statistics import circular_block_bootstrap_mean_ci
from .backtest import EventDrivenBacktester, Strategy
from .benchmarks import BenchmarkEntry, BenchmarkSuiteResult, compare_strategy_to_benchmarks
from .models import BacktestConfig, BacktestResult, Side

_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_CANONICAL_BENCHMARKS = (
    "buy_and_hold",
    "trend_following",
    "breakout",
    "mean_reversion",
)


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
    require_positive_expectancy_ci_lower: bool = True
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

    def canonical_metrics(self) -> tuple[str, ...]:
        return (
            f"minimum_organic_closed_trades={self.minimum_organic_closed_trades}",
            f"maximum_drawdown_percent={float(self.maximum_drawdown_percent):g}",
            "minimum_profitable_validation_window_percent="
            f"{float(self.minimum_profitable_validation_window_percent):g}",
            f"require_positive_final_net_pnl={str(self.require_positive_final_net_pnl).lower()}",
            "require_positive_final_expectancy="
            f"{str(self.require_positive_final_expectancy).lower()}",
            "require_positive_expectancy_ci_lower="
            f"{str(self.require_positive_expectancy_ci_lower).lower()}",
            "require_candidate_beat_buy_hold="
            f"{str(self.require_candidate_beat_buy_hold).lower()}",
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
    expectancy_ci_95_lower: float | None
    expectancy_ci_95_upper: float | None
    expectancy_ci_block_length: int | None
    expectancy_ci_bootstrap_samples: int | None
    expectancy_ci_method: str
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
    git_sha: str
    dataset_manifest_sha256: str
    dataset_id: str
    dataset_version: str
    dataset_venue: str
    dataset_market_type: str
    dataset_source: str
    dataset_symbols: tuple[str, ...]
    dataset_interval_ms: int
    dataset_timestamp_semantics: str
    strategy: str
    hypothesis: str
    falsification_rule: str
    train_event_count: int
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
            "git_sha": self.git_sha,
            "dataset_manifest_sha256": self.dataset_manifest_sha256,
            "dataset": {
                "dataset_id": self.dataset_id,
                "dataset_version": self.dataset_version,
                "venue": self.dataset_venue,
                "market_type": self.dataset_market_type,
                "source": self.dataset_source,
                "symbols": list(self.dataset_symbols),
                "interval_ms": self.dataset_interval_ms,
                "timestamp_semantics": self.dataset_timestamp_semantics,
            },
            "strategy": self.strategy,
            "hypothesis": self.hypothesis,
            "falsification_rule": self.falsification_rule,
            "train_event_count": self.train_event_count,
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
    current_git_sha: str,
    backtest_config: BacktestConfig,
    criteria: AlphaAcceptanceCriteria,
) -> AlphaValidationReport:
    """Run frozen sequential validation then one untouched final holdout."""

    train_event_count, validation_windows = run_preregistered_pre_final_validation(
        loader,
        experiment,
        strategy_factory,
        candidate_name=candidate_name,
        current_git_sha=current_git_sha,
        backtest_config=backtest_config,
        criteria=criteria,
    )

    # Final OOS is materialized only after all immutable bindings and sequential
    # validation windows have succeeded.  The one-shot runner claims the
    # holdout only after calling this same pre-final validation function.
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
        sum(window.metrics.net_pnl > 0 for window in validation_windows)
        / len(validation_windows)
        * 100.0
    )
    verdict, reasons = _verdict(
        candidate_metrics,
        profitable_validation_window_percent=profitable_percent,
        candidate_beats_buy_hold=candidate_beats_buy_hold,
        criteria=criteria,
    )
    manifest = loader.manifest
    return AlphaValidationReport(
        experiment_id=experiment.experiment_id,
        experiment_fingerprint=experiment.fingerprint(),
        git_sha=str(current_git_sha).strip().lower(),
        dataset_manifest_sha256=sha256_file(loader.manifest_path),
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
        train_event_count=train_event_count,
        validation_windows=validation_windows,
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


def run_preregistered_pre_final_validation(
    loader: HistoricalDataLoader,
    experiment: AlphaExperiment,
    strategy_factory: Callable[[], Strategy],
    *,
    candidate_name: str,
    current_git_sha: str,
    backtest_config: BacktestConfig,
    criteria: AlphaAcceptanceCriteria,
) -> tuple[int, tuple[AlphaValidationWindow, ...]]:
    """Validate immutable bindings and sequential windows without reading Final OOS.

    A one-shot holdout receipt must never be claimed until this function has
    completed successfully.  It intentionally does not materialize events in
    ``experiment.final_oos_range``.
    """

    dataset_report = loader.require_final_oos_eligible()
    if not dataset_report.final_oos_eligible:
        raise ValueError("historical dataset is not final-OOS eligible")

    clean_git_sha = str(current_git_sha).strip().lower()
    if not _GIT_SHA.fullmatch(clean_git_sha):
        raise ValueError("current_git_sha must be 40 lowercase hex characters")
    if clean_git_sha != experiment.git_sha:
        raise ValueError("current git SHA differs from preregistered git SHA")

    actual_manifest_sha = sha256_file(loader.manifest_path)
    if actual_manifest_sha != experiment.dataset_manifest_sha256:
        raise ValueError("experiment dataset manifest SHA256 does not match loaded manifest")
    if experiment.strategy != candidate_name:
        raise ValueError("experiment strategy identity does not match candidate_name")

    _validate_experiment_ranges(experiment, loader)
    _validate_strategy_binding(experiment, strategy_factory, candidate_name)
    _validate_backtest_binding(experiment, backtest_config)
    _validate_acceptance_binding(experiment, criteria)
    if experiment.falsification_rule != canonical_falsification_rule(criteria):
        raise ValueError("falsification rule differs from preregistered acceptance contract")
    if tuple(experiment.benchmarks) != _CANONICAL_BENCHMARKS:
        raise ValueError("experiment benchmarks differ from canonical benchmark suite")

    train_events = tuple(
        loader.iter_events(
            start_timestamp_ms=experiment.train_range[0],
            end_timestamp_ms=experiment.train_range[1],
        )
    )
    if not train_events:
        raise ValueError("training range contains no market events")

    validation_windows: list[AlphaValidationWindow] = []
    for start_ms, end_ms in experiment.validation_ranges:
        events = tuple(
            loader.iter_events(start_timestamp_ms=start_ms, end_timestamp_ms=end_ms)
        )
        if not events:
            raise ValueError("validation range contains no market events")
        result = EventDrivenBacktester(backtest_config).run(events, strategy_factory())
        validation_windows.append(
            AlphaValidationWindow(
                start_ms=start_ms,
                end_ms=end_ms,
                event_count=len(events),
                metrics=alpha_metrics(result),
            )
        )

    return len(train_events), tuple(validation_windows)


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
    expectancy = sum(organic_pnls) / len(organic_pnls) if organic_pnls else 0.0
    interval = circular_block_bootstrap_mean_ci(organic_pnls)
    return AlphaRunMetrics(
        net_pnl=round(result.net_pnl, 8),
        return_percent=round(result.return_percent, 8),
        gross_trading_pnl=round(result.gross_trading_pnl, 8),
        total_fees=round(result.total_fees, 8),
        total_spread_cost=round(sum(float(fill.spread_cost) for fill in result.fills), 8),
        total_slippage_cost_including_impact=round(result.total_slippage_cost, 8),
        total_funding_cost=round(result.total_funding_cost, 8),
        net_expectancy_per_organic_closed_trade=round(expectancy, 8),
        expectancy_ci_95_lower=None if interval is None else round(interval.lower, 8),
        expectancy_ci_95_upper=None if interval is None else round(interval.upper, 8),
        expectancy_ci_block_length=None if interval is None else interval.block_length,
        expectancy_ci_bootstrap_samples=None if interval is None else interval.bootstrap_samples,
        expectancy_ci_method="circular_block_bootstrap_95_seed0",
        profit_factor=round(_profit_factor(organic_pnls), 8),
        max_drawdown_percent=round(result.max_drawdown_percent, 8),
        fill_count=len(result.fills),
        organic_closed_trade_count=len(organic_sells),
        synthetic_finalization_count=int(synthetic_count),
        winning_organic_closed_trades=sum(value > 0 for value in organic_pnls),
        losing_organic_closed_trades=sum(value < 0 for value in organic_pnls),
        exposure_time_percent=round(result.exposure_time_percent, 8),
    )


def backtest_cost_config(config: BacktestConfig) -> dict[str, object]:
    return {
        "fee_rate": config.fee_rate,
        "maker_fee_rate": config.maker_fee_rate,
        "slippage_bps": config.slippage_bps,
        "market_impact_bps": config.market_impact_bps,
        "max_participation_rate": config.max_participation_rate,
    }


def backtest_risk_config(config: BacktestConfig) -> dict[str, object]:
    return {
        "initial_cash": config.initial_cash,
        "reserve_percent": config.reserve_percent,
        "max_total_exposure_percent": config.max_total_exposure_percent,
        "max_position_percent": config.max_position_percent,
        "max_correlated_exposure_percent": config.max_correlated_exposure_percent,
        "max_risk_per_trade_percent": config.max_risk_per_trade_percent,
        "max_open_positions": config.max_open_positions,
        "minimum_notional": config.minimum_notional,
        "force_close_at_end": config.force_close_at_end,
    }


def canonical_falsification_rule(criteria: AlphaAcceptanceCriteria) -> str:
    gates: list[str] = []
    if criteria.require_positive_final_net_pnl:
        gates.append("final-OOS net PnL is non-positive")
    if criteria.require_positive_final_expectancy:
        gates.append("organic final-OOS net expectancy is non-positive")
    if criteria.require_positive_expectancy_ci_lower:
        gates.append("the 95% circular block-bootstrap expectancy lower bound is not positive")
    gates.append(
        f"max drawdown exceeds {float(criteria.maximum_drawdown_percent):g}%"
    )
    gates.append(
        "profitable sequential validation windows are below "
        f"{float(criteria.minimum_profitable_validation_window_percent):g}%"
    )
    if criteria.require_candidate_beat_buy_hold:
        gates.append("the candidate fails the risk-adjusted Buy&Hold comparison")
    return (
        "INSUFFICIENT_SAMPLE if organic final-OOS closed trades < "
        f"{criteria.minimum_organic_closed_trades}; otherwise REJECT_HYPOTHESIS if "
        + "; or if ".join(gates)
        + "."
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


def _validate_strategy_binding(
    experiment: AlphaExperiment,
    strategy_factory: Callable[[], Strategy],
    candidate_name: str,
) -> None:
    probe = strategy_factory()
    if getattr(probe, "candidate_name", None) != candidate_name:
        raise ValueError("strategy factory candidate identity differs from preregistration")
    if getattr(probe, "benchmark", True) is not False:
        raise ValueError("alpha candidate must be explicitly marked non-benchmark")
    if str(getattr(probe, "hypothesis", "")).strip() != experiment.hypothesis:
        raise ValueError("strategy hypothesis differs from preregistration")
    strategy_config = getattr(probe, "config", None)
    to_dict = getattr(strategy_config, "to_dict", None)
    if not callable(to_dict):
        raise ValueError("alpha candidate must expose serializable frozen config")
    actual_parameters = dict(to_dict())
    if actual_parameters != dict(experiment.parameters):
        raise ValueError("strategy parameters differ from preregistration")


def _validate_backtest_binding(
    experiment: AlphaExperiment,
    config: BacktestConfig,
) -> None:
    if config.execution_timing != experiment.execution_timing:
        raise ValueError("backtest execution timing differs from preregistration")
    if backtest_cost_config(config) != dict(experiment.cost_config):
        raise ValueError("backtest cost config differs from preregistration")
    if backtest_risk_config(config) != dict(experiment.risk_config):
        raise ValueError("backtest risk config differs from preregistration")


def _validate_acceptance_binding(
    experiment: AlphaExperiment,
    criteria: AlphaAcceptanceCriteria,
) -> None:
    if tuple(experiment.acceptance_metrics) != criteria.canonical_metrics():
        raise ValueError("acceptance criteria differ from preregistration")


def _entry(comparison: BenchmarkSuiteResult, name: str) -> BenchmarkEntry:
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
    if criteria.require_positive_expectancy_ci_lower and (
        metrics.expectancy_ci_95_lower is None or metrics.expectancy_ci_95_lower <= 0
    ):
        failures.append("final_oos_expectancy_ci_lower_not_positive")
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
    "backtest_cost_config",
    "backtest_risk_config",
    "canonical_falsification_rule",
    "run_preregistered_alpha_validation",
    "run_preregistered_pre_final_validation",
    "sha256_file",
]
