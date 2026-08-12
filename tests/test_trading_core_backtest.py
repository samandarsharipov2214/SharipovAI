from __future__ import annotations

import hashlib
from pathlib import Path

import duckdb
import pytest

from historical_data import DataManifest, HistoricalDataLoader
from trading_core import (
    BacktestConfig,
    EventDrivenBacktester,
    MarketEvent,
    Side,
    Signal,
)
from trading_core.alpha_consumption import (
    FinalOOSAlreadyConsumed,
    claim_final_oos,
    complete_final_oos,
)
from trading_core.alpha_experiment import AlphaExperiment
from trading_core.alpha_statistics import circular_block_bootstrap_mean_ci
from trading_core.alpha_strategies import (
    RegimeFilteredBreakoutConfig,
    RegimeFilteredBreakoutStrategy,
)
from trading_core.alpha_validation import (
    AlphaAcceptanceCriteria,
    AlphaVerdict,
    backtest_cost_config,
    backtest_risk_config,
    canonical_falsification_rule,
    run_preregistered_alpha_validation,
    sha256_file,
)


class BuyThenSell:
    def __init__(self) -> None:
        self.count = 0

    def on_market(self, event, portfolio):
        del portfolio
        self.count += 1
        if self.count == 1:
            return Signal(Side.BUY, reason="entry")
        if self.count == 3:
            return Signal(Side.SELL, reason="exit")
        return None


class BuyEveryNewSymbol:
    def on_market(self, event, portfolio):
        if event.symbol not in portfolio.positions:
            return Signal(Side.BUY, reason="portfolio-entry")
        return None


class FirstBuyThenSell:
    def __init__(self) -> None:
        self.entered = False

    def on_market(self, event, portfolio):
        if event.symbol == "BTCUSDT" and not self.entered:
            self.entered = True
            return Signal(Side.BUY, reason="close_signal")
        if event.symbol == "BTCUSDT" and event.symbol in portfolio.positions:
            return Signal(Side.SELL, reason="close_exit")
        return None


def test_event_driven_backtest_uses_bid_ask_fees_and_slippage() -> None:
    events = [
        MarketEvent(1, "BTCUSDT", bid=99.0, ask=100.0),
        MarketEvent(2, "BTCUSDT", bid=100.0, ask=101.0),
        MarketEvent(3, "BTCUSDT", bid=109.0, ask=110.0),
    ]

    result = EventDrivenBacktester().run(events, BuyThenSell())

    assert result.ending_equity > result.initial_cash
    assert result.net_pnl > 0
    assert result.total_fees > 0
    assert result.total_slippage_cost > 0
    assert result.trade_count == 2
    assert result.winning_closed_trades == 1
    assert result.metadata["lookahead_allowed"] is False
    assert result.metadata["bid_ask_mode"] is True


def test_flat_market_loses_spread_fees_and_slippage() -> None:
    events = [
        MarketEvent(1, "BTCUSDT", bid=99.0, ask=100.0),
        MarketEvent(2, "BTCUSDT", bid=99.0, ask=100.0),
        MarketEvent(3, "BTCUSDT", bid=99.0, ask=100.0),
    ]

    result = EventDrivenBacktester().run(events, BuyThenSell())

    assert result.net_pnl < 0
    assert result.losing_closed_trades == 1
    assert abs(result.net_pnl) >= result.total_fees


def test_backtester_rejects_out_of_order_and_duplicate_timestamps() -> None:
    events = [
        MarketEvent(2, "BTCUSDT", bid=99.0, ask=100.0),
        MarketEvent(1, "BTCUSDT", bid=100.0, ask=101.0),
    ]

    with pytest.raises(ValueError, match="strictly increasing"):
        EventDrivenBacktester().run(events, BuyThenSell())


def test_close_derived_signal_fills_only_on_next_event_of_same_symbol() -> None:
    close = {"price_source": "synthetic_from_close", "timestamp_semantics": "bar_close", "interval_ms": 60_000}
    events = [
        MarketEvent(1, "BTCUSDT", 99.0, 101.0, metadata=close),
        MarketEvent(2, "ETHUSDT", 49.0, 51.0, metadata=close),
        MarketEvent(3, "BTCUSDT", 109.0, 111.0, metadata=close),
        MarketEvent(4, "BTCUSDT", 119.0, 121.0, metadata=close),
    ]

    result = EventDrivenBacktester().run(events, FirstBuyThenSell())

    assert [(fill.side, fill.timestamp_ms, fill.symbol, fill.execution_timing) for fill in result.fills] == [
        (Side.BUY, 3, "BTCUSDT", "next_event"),
        (Side.SELL, 4, "BTCUSDT", "next_event"),
    ]


def test_close_derived_pending_signal_without_next_event_does_not_fill() -> None:
    event = MarketEvent(1, "BTCUSDT", 99.0, 101.0, metadata={"price_source": "synthetic_from_close"})
    result = EventDrivenBacktester(BacktestConfig(force_close_at_end=False)).run([event], FirstBuyThenSell())
    assert result.fills == ()
    assert result.metadata["pending_signals_unfilled"] == 1


def test_crypto_correlation_cap_limits_aggregate_entries() -> None:
    config = BacktestConfig(
        initial_cash=10_000.0,
        reserve_percent=20.0,
        max_total_exposure_percent=80.0,
        max_position_percent=20.0,
        max_correlated_exposure_percent=35.0,
        force_close_at_end=False,
    )
    events = [
        MarketEvent(1, "BTCUSDT", bid=99.0, ask=100.0),
        MarketEvent(2, "ETHUSDT", bid=99.0, ask=100.0),
        MarketEvent(3, "SOLUSDT", bid=99.0, ask=100.0),
    ]

    result = EventDrivenBacktester(config).run(events, BuyEveryNewSymbol())
    buy_fills = [fill for fill in result.fills if fill.side is Side.BUY]

    assert len(buy_fills) == 2
    assert sum(fill.notional for fill in buy_fills) <= 3_511.0
    assert result.ending_equity >= 6_500.0


def _critical_alpha_dataset(tmp_path: Path) -> Path:
    parquet = tmp_path / "alpha-bars.parquet"
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
        dataset_id="critical-alpha-fixture",
        dataset_version="v1",
        venue="bybit",
        market_type="spot",
        source="critical-test-fixture",
        symbols=("BTCUSDT",),
        interval_ms=60_000,
        timezone="UTC",
        start_timestamp_ms=60_000,
        end_timestamp_ms=1_800_000,
        row_count=30,
        parquet_files=(parquet.name,),
        sha256={parquet.name: hashlib.sha256(parquet.read_bytes()).hexdigest()},
        created_at="2026-08-12T12:00:00+00:00",
        commit_sha="a" * 40,
        timestamp_semantics="bar_close",
    )
    manifest_path = tmp_path / "manifest.json"
    manifest.save(manifest_path)
    return manifest_path


def test_critical_suite_executes_preregistered_alpha_path_and_one_shot_receipt(
    tmp_path: Path,
) -> None:
    """Keep the new Alpha path inside the existing critical trading-core coverage gate."""

    manifest_path = _critical_alpha_dataset(tmp_path)
    strategy_config = RegimeFilteredBreakoutConfig(
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
    strategy = RegimeFilteredBreakoutStrategy(strategy_config)
    backtest = BacktestConfig(execution_timing="auto")
    criteria = AlphaAcceptanceCriteria()
    experiment = AlphaExperiment(
        experiment_id="critical-alpha-v1",
        git_sha="a" * 40,
        dataset_manifest_sha256=sha256_file(manifest_path),
        strategy=strategy.candidate_name,
        hypothesis=strategy.hypothesis,
        falsification_rule=canonical_falsification_rule(criteria),
        parameters=strategy_config.to_dict(),
        cost_config=backtest_cost_config(backtest),
        risk_config=backtest_risk_config(backtest),
        execution_timing="auto",
        train_range=(60_000, 600_000),
        validation_ranges=((660_000, 900_000), (960_000, 1_200_000)),
        final_oos_range=(1_260_000, 1_800_000),
        benchmarks=("buy_and_hold", "trend_following", "breakout", "mean_reversion"),
        acceptance_metrics=criteria.canonical_metrics(),
    )

    with HistoricalDataLoader(manifest_path) as loader:
        report = run_preregistered_alpha_validation(
            loader,
            experiment,
            lambda: RegimeFilteredBreakoutStrategy(strategy_config),
            candidate_name=strategy.candidate_name,
            current_git_sha="a" * 40,
            backtest_config=backtest,
            criteria=criteria,
        )

    assert report.verdict is AlphaVerdict.INSUFFICIENT_SAMPLE
    assert report.dataset_id == "critical-alpha-fixture"
    assert report.final_oos_event_count == 10
    assert report.paper_authorized is False
    assert report.testnet_authorized is False
    assert report.mainnet_authorized is False

    receipt = claim_final_oos(
        manifest_path=manifest_path,
        experiment=experiment,
        experiment_artifact_sha256="c" * 64,
    )
    complete_final_oos(
        receipt,
        verdict=report.verdict.value,
        report_path=tmp_path / "alpha-report.json",
        report_sha256="d" * 64,
    )
    with pytest.raises(FinalOOSAlreadyConsumed):
        claim_final_oos(
            manifest_path=manifest_path,
            experiment=experiment,
            experiment_artifact_sha256="e" * 64,
        )

    interval = circular_block_bootstrap_mean_ci(
        [1.0, 2.0, 3.0, 4.0],
        bootstrap_samples=100,
        seed=7,
    )
    assert interval is not None
    assert interval.lower <= interval.upper
    assert interval.sample_count == 4
