"""End-to-end research-integrity contracts for the preregistered Alpha runner."""
from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path

import duckdb
import pytest

from historical_data import DataManifest, HistoricalDataLoader
from trading_core.alpha_experiment import AlphaExperiment
from trading_core.alpha_strategies import (
    RegimeFilteredBreakoutConfig,
    RegimeFilteredBreakoutStrategy,
)
from trading_core.alpha_validation import (
    AlphaAcceptanceCriteria,
    AlphaVerdict,
    alpha_metrics,
    backtest_cost_config,
    backtest_risk_config,
    run_preregistered_alpha_validation,
    sha256_file,
)
from trading_core.models import BacktestConfig, BacktestResult, Fill, Side

_GIT_SHA = "a" * 40
_BENCHMARKS = ("buy_and_hold", "trend_following", "breakout", "mean_reversion")


def _dataset(tmp_path: Path) -> Path:
    parquet = tmp_path / "bars.parquet"
    connection = duckdb.connect(database=":memory:")
    try:
        connection.execute(
            "CREATE TABLE bars(timestamp_ms BIGINT, symbol VARCHAR, close DOUBLE, volume DOUBLE)"
        )
        rows = [
            (index * 60_000, "BTCUSDT", 100.0 + index * 0.05, 1_000.0 + index)
            for index in range(1, 31)
        ]
        connection.executemany("INSERT INTO bars VALUES (?, ?, ?, ?)", rows)
        escaped = str(parquet).replace("'", "''")
        connection.execute(f"COPY bars TO '{escaped}' (FORMAT PARQUET)")
    finally:
        connection.close()

    manifest = DataManifest(
        schema_version=1,
        dataset_id="alpha-validation-fixture",
        dataset_version="v1",
        venue="bybit",
        market_type="spot",
        source="test-fixture",
        symbols=("BTCUSDT",),
        interval_ms=60_000,
        timezone="UTC",
        start_timestamp_ms=60_000,
        end_timestamp_ms=1_800_000,
        row_count=30,
        parquet_files=(parquet.name,),
        sha256={parquet.name: hashlib.sha256(parquet.read_bytes()).hexdigest()},
        created_at="2026-08-12T12:00:00+00:00",
        commit_sha=_GIT_SHA,
        timestamp_semantics="bar_close",
    )
    manifest_path = tmp_path / "manifest.json"
    manifest.save(manifest_path)
    return manifest_path


def _strategy_config() -> RegimeFilteredBreakoutConfig:
    return RegimeFilteredBreakoutConfig(
        breakout_window=5,
        exit_window=3,
        volatility_window=5,
        trend_window=3,
        volume_window=5,
        breakout_buffer_percent=0.05,
        minimum_volatility_percent=0.01,
        maximum_volatility_percent=10.0,
        minimum_trend_percent=0.10,
        volume_multiplier=1.05,
        maximum_hold_bars=8,
        cooldown_bars=2,
        requested_risk_percent=1.0,
        stop_loss_percent=2.0,
    )


def _backtest_config() -> BacktestConfig:
    return BacktestConfig(execution_timing="auto")


def _experiment(
    manifest_path: Path,
    *,
    strategy_config: RegimeFilteredBreakoutConfig | None = None,
    backtest_config: BacktestConfig | None = None,
    criteria: AlphaAcceptanceCriteria | None = None,
) -> AlphaExperiment:
    strategy = strategy_config or _strategy_config()
    backtest = backtest_config or _backtest_config()
    acceptance = criteria or AlphaAcceptanceCriteria()
    return AlphaExperiment(
        experiment_id="alpha-regime-breakout-fixture-v1",
        git_sha=_GIT_SHA,
        dataset_manifest_sha256=sha256_file(manifest_path),
        strategy="regime_filtered_breakout_v1",
        parameters=strategy.to_dict(),
        cost_config=backtest_cost_config(backtest),
        risk_config=backtest_risk_config(backtest),
        execution_timing="auto",
        train_range=(60_000, 600_000),
        validation_ranges=((660_000, 900_000), (960_000, 1_200_000)),
        final_oos_range=(1_260_000, 1_800_000),
        benchmarks=_BENCHMARKS,
        acceptance_metrics=acceptance.canonical_metrics(),
    )


def test_preregistered_runner_returns_truthful_insufficient_sample_and_never_promotes(
    tmp_path: Path,
) -> None:
    manifest_path = _dataset(tmp_path)
    strategy_config = _strategy_config()
    backtest = _backtest_config()
    criteria = AlphaAcceptanceCriteria()
    experiment = _experiment(
        manifest_path,
        strategy_config=strategy_config,
        backtest_config=backtest,
        criteria=criteria,
    )

    with HistoricalDataLoader(manifest_path) as loader:
        report = run_preregistered_alpha_validation(
            loader,
            experiment,
            lambda: RegimeFilteredBreakoutStrategy(strategy_config),
            candidate_name="regime_filtered_breakout_v1",
            current_git_sha=_GIT_SHA,
            backtest_config=backtest,
            criteria=criteria,
        )

    assert report.verdict is AlphaVerdict.INSUFFICIENT_SAMPLE
    assert report.train_event_count == 10
    assert len(report.validation_windows) == 2
    assert report.final_oos_event_count == 10
    assert report.final_oos_metrics.organic_closed_trade_count == 0
    assert tuple(report.benchmark_metrics) == _BENCHMARKS
    assert report.paper_authorized is False
    assert report.testnet_authorized is False
    assert report.mainnet_authorized is False


def test_manifest_or_git_identity_drift_fails_before_final_oos(tmp_path: Path) -> None:
    manifest_path = _dataset(tmp_path)
    strategy_config = _strategy_config()
    backtest = _backtest_config()
    criteria = AlphaAcceptanceCriteria()
    experiment = _experiment(manifest_path)

    with HistoricalDataLoader(manifest_path) as loader:
        with pytest.raises(ValueError, match="current git SHA differs"):
            run_preregistered_alpha_validation(
                loader,
                experiment,
                lambda: RegimeFilteredBreakoutStrategy(strategy_config),
                candidate_name="regime_filtered_breakout_v1",
                current_git_sha="b" * 40,
                backtest_config=backtest,
                criteria=criteria,
            )

    drifted = replace(experiment, dataset_manifest_sha256="0" * 64)
    with HistoricalDataLoader(manifest_path) as loader:
        with pytest.raises(ValueError, match="manifest SHA256"):
            run_preregistered_alpha_validation(
                loader,
                drifted,
                lambda: RegimeFilteredBreakoutStrategy(strategy_config),
                candidate_name="regime_filtered_breakout_v1",
                current_git_sha=_GIT_SHA,
                backtest_config=backtest,
                criteria=criteria,
            )


def test_strategy_cost_risk_and_acceptance_drift_all_fail_closed(tmp_path: Path) -> None:
    manifest_path = _dataset(tmp_path)
    strategy_config = _strategy_config()
    backtest = _backtest_config()
    criteria = AlphaAcceptanceCriteria()
    base = _experiment(manifest_path)

    cases = (
        (
            replace(base, parameters={**base.parameters, "volume_multiplier": 9.0}),
            backtest,
            criteria,
            "strategy parameters",
        ),
        (
            replace(base, cost_config={**base.cost_config, "fee_rate": 0.0}),
            backtest,
            criteria,
            "cost config",
        ),
        (
            replace(base, risk_config={**base.risk_config, "max_position_percent": 99.0}),
            backtest,
            criteria,
            "risk config",
        ),
        (
            replace(base, acceptance_metrics=("minimum_organic_closed_trades=1",)),
            backtest,
            criteria,
            "acceptance criteria",
        ),
    )
    for experiment, active_backtest, active_criteria, message in cases:
        with HistoricalDataLoader(manifest_path) as loader:
            with pytest.raises(ValueError, match=message):
                run_preregistered_alpha_validation(
                    loader,
                    experiment,
                    lambda: RegimeFilteredBreakoutStrategy(strategy_config),
                    candidate_name="regime_filtered_breakout_v1",
                    current_git_sha=_GIT_SHA,
                    backtest_config=active_backtest,
                    criteria=active_criteria,
                )


def test_synthetic_finalization_cannot_inflate_closed_trade_sample() -> None:
    organic = Fill(
        timestamp_ms=1,
        symbol="BTCUSDT",
        side=Side.SELL,
        quantity=1.0,
        reference_price=105.0,
        execution_price=105.0,
        notional=105.0,
        fee=0.1,
        slippage_cost=0.0,
        realized_pnl=4.9,
        reason="organic_exit",
        synthetic_finalization=False,
    )
    synthetic = replace(
        organic,
        timestamp_ms=2,
        realized_pnl=999.0,
        reason="backtest_end",
        synthetic_finalization=True,
    )
    result = BacktestResult(
        initial_cash=10_000.0,
        ending_equity=10_004.9,
        net_pnl=4.9,
        return_percent=0.049,
        max_drawdown_percent=1.0,
        total_fees=0.2,
        total_slippage_cost=0.0,
        trade_count=2,
        winning_closed_trades=2,
        losing_closed_trades=0,
        fills=(organic, synthetic),
        gross_trading_pnl=4.9,
    )

    metrics = alpha_metrics(result)

    assert metrics.organic_closed_trade_count == 1
    assert metrics.synthetic_finalization_count == 1
    assert metrics.net_expectancy_per_organic_closed_trade == 4.9


def test_manifest_hash_helper_is_content_addressed(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    path.write_text("first", encoding="utf-8")
    first = sha256_file(path)
    path.write_text("second", encoding="utf-8")
    second = sha256_file(path)

    assert first != second
    assert len(first) == len(second) == 64
