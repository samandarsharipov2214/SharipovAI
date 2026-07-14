from __future__ import annotations

from trading_core import (
    BacktestConfig,
    MarketEvent,
    TrendFollowingStrategy,
    compare_strategy_to_benchmarks,
    run_benchmark_suite,
)


def _trend_events() -> tuple[MarketEvent, ...]:
    return tuple(
        MarketEvent(
            timestamp_ms=index,
            symbol="BTCUSDT",
            bid=100.0 + index * 0.5,
            ask=100.1 + index * 0.5,
            volume=1_000_000.0,
        )
        for index in range(1, 121)
    )


def _config() -> BacktestConfig:
    return BacktestConfig(
        fee_rate=0.0005,
        maker_fee_rate=0.0002,
        slippage_bps=1.0,
        market_impact_bps=5.0,
    )


def test_mandatory_benchmark_suite_runs_four_baselines() -> None:
    suite = run_benchmark_suite(_trend_events(), config=_config())

    assert {entry.name for entry in suite.entries} == {
        "buy_and_hold",
        "trend_following",
        "breakout",
        "mean_reversion",
    }
    assert len(suite.ranking) == 4
    assert suite.metadata["comparison_required"] is True
    assert suite.metadata["costs_included"] is True
    assert suite.metadata["funding_included"] is True


def test_candidate_is_ranked_against_all_benchmarks() -> None:
    suite = compare_strategy_to_benchmarks(
        _trend_events(),
        lambda: TrendFollowingStrategy(short_window=10, long_window=30),
        candidate_name="candidate_trend",
        config=_config(),
    )

    assert len(suite.entries) == 5
    assert "candidate_trend" in suite.ranking
    assert suite.metadata["candidate_rank"] >= 1
    assert isinstance(suite.metadata["candidate_beats_buy_hold"], bool)
