from __future__ import annotations

import pytest

from trading_core.models import BacktestResult, Fill, Side
from trading_core.performance_statistics import summarize_performance


def _result(*, pnls: tuple[float, ...], notionals: tuple[float, ...]) -> BacktestResult:
    fills: list[Fill] = []
    timestamp = 1
    for index, pnl in enumerate(pnls):
        buy_notional = notionals[index * 2]
        sell_notional = notionals[index * 2 + 1]
        fills.append(
            Fill(
                timestamp_ms=timestamp,
                symbol="BTCUSDT",
                side=Side.BUY,
                quantity=1.0,
                reference_price=buy_notional,
                execution_price=buy_notional,
                notional=buy_notional,
                fee=0.0,
                slippage_cost=0.0,
                realized_pnl=0.0,
                reason="entry",
            )
        )
        timestamp += 1
        fills.append(
            Fill(
                timestamp_ms=timestamp,
                symbol="BTCUSDT",
                side=Side.SELL,
                quantity=1.0,
                reference_price=sell_notional,
                execution_price=sell_notional,
                notional=sell_notional,
                fee=0.0,
                slippage_cost=0.0,
                realized_pnl=pnl,
                reason="exit",
            )
        )
        timestamp += 1
    return BacktestResult(
        initial_cash=1_000.0,
        ending_equity=1_000.0 + sum(pnls),
        net_pnl=sum(pnls),
        return_percent=sum(pnls) / 10.0,
        max_drawdown_percent=7.5,
        total_fees=0.0,
        total_slippage_cost=0.0,
        trade_count=len(fills),
        winning_closed_trades=sum(pnl > 0 for pnl in pnls),
        losing_closed_trades=sum(pnl < 0 for pnl in pnls),
        fills=tuple(fills),
        profit_factor=2.5,
    )


def test_summarize_performance_reports_expectancy_turnover_and_existing_risk_metrics() -> None:
    result = _result(
        pnls=(10.0, -5.0, 20.0, 5.0),
        notionals=(100.0, 110.0, 100.0, 95.0, 100.0, 120.0, 100.0, 105.0),
    )

    stats = summarize_performance(result, bootstrap_samples=500, seed=7)

    assert stats.closed_trade_count == 4
    assert stats.expectancy == 7.5
    assert stats.profit_factor == 2.5
    assert stats.max_drawdown_percent == 7.5
    assert stats.turnover_ratio == 0.83
    assert stats.turnover_percent == 83.0
    assert stats.execution_authority is False


def test_bootstrap_interval_is_deterministic_for_same_seed() -> None:
    result = _result(
        pnls=(4.0, 6.0, 8.0, 10.0, 12.0),
        notionals=(100.0, 101.0) * 5,
    )

    first = summarize_performance(result, bootstrap_samples=1_000, seed=42)
    second = summarize_performance(result, bootstrap_samples=1_000, seed=42)

    assert first.bootstrap_mean_lower == second.bootstrap_mean_lower
    assert first.bootstrap_mean_upper == second.bootstrap_mean_upper
    assert first.positive_expectancy_supported is True


def test_multiple_testing_adjustment_never_narrows_interval() -> None:
    result = _result(
        pnls=(-4.0, 2.0, 5.0, 7.0, 11.0, 13.0),
        notionals=(100.0, 101.0) * 6,
    )

    single = summarize_performance(
        result,
        bootstrap_samples=2_000,
        tested_variants=1,
        seed=9,
    )
    family = summarize_performance(
        result,
        bootstrap_samples=2_000,
        tested_variants=10,
        seed=9,
    )

    assert family.familywise_confidence_level > single.familywise_confidence_level
    assert family.bootstrap_mean_lower <= single.bootstrap_mean_lower
    assert family.bootstrap_mean_upper >= single.bootstrap_mean_upper


def test_synthetic_finalization_is_not_counted_as_observed_closed_trade() -> None:
    result = _result(pnls=(5.0,), notionals=(100.0, 105.0))
    synthetic = Fill(
        timestamp_ms=99,
        symbol="ETHUSDT",
        side=Side.SELL,
        quantity=1.0,
        reference_price=100.0,
        execution_price=100.0,
        notional=100.0,
        fee=0.0,
        slippage_cost=0.0,
        realized_pnl=1_000.0,
        reason="forced_end_of_backtest",
        synthetic_finalization=True,
    )
    result = BacktestResult(
        initial_cash=result.initial_cash,
        ending_equity=result.ending_equity,
        net_pnl=result.net_pnl,
        return_percent=result.return_percent,
        max_drawdown_percent=result.max_drawdown_percent,
        total_fees=result.total_fees,
        total_slippage_cost=result.total_slippage_cost,
        trade_count=result.trade_count + 1,
        winning_closed_trades=result.winning_closed_trades,
        losing_closed_trades=result.losing_closed_trades,
        fills=result.fills + (synthetic,),
        profit_factor=result.profit_factor,
    )

    stats = summarize_performance(result, bootstrap_samples=100)

    assert stats.closed_trade_count == 1
    assert stats.expectancy == 5.0


def test_empty_closed_trade_sample_is_explicitly_insufficient() -> None:
    result = BacktestResult(
        initial_cash=1_000.0,
        ending_equity=1_000.0,
        net_pnl=0.0,
        return_percent=0.0,
        max_drawdown_percent=0.0,
        total_fees=0.0,
        total_slippage_cost=0.0,
        trade_count=0,
        winning_closed_trades=0,
        losing_closed_trades=0,
    )

    stats = summarize_performance(result, bootstrap_samples=100)

    assert stats.sufficient_evidence is False
    assert stats.positive_expectancy_supported is False
    assert stats.bootstrap_mean_lower == 0.0
    assert stats.bootstrap_mean_upper == 0.0


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"bootstrap_samples": 0}, "bootstrap_samples must be positive"),
        ({"confidence_level": 1.0}, "confidence_level must be between 0 and 1"),
        ({"tested_variants": 0}, "tested_variants must be positive"),
    ],
)
def test_invalid_statistics_configuration_fails_closed(kwargs: dict[str, object], message: str) -> None:
    result = _result(pnls=(1.0,), notionals=(100.0, 101.0))

    with pytest.raises(ValueError, match=message):
        summarize_performance(result, **kwargs)
