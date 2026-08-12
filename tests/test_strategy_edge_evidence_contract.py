"""Evidence gates for strategy review during Alpha Validation."""
from __future__ import annotations

from trading_core.models import BacktestResult, Fill, Side
from trading_core.strategy_suite import StrategySuiteConfig, _comparison


def _sell_fill(realized_pnl: float, *, timestamp_ms: int) -> Fill:
    return Fill(
        timestamp_ms=timestamp_ms,
        symbol="BTCUSDT",
        side=Side.SELL,
        quantity=1.0,
        reference_price=100.0,
        execution_price=100.0,
        notional=100.0,
        fee=0.1,
        slippage_cost=0.05,
        realized_pnl=realized_pnl,
        reason="test_close",
    )


def _result(
    *,
    net_pnl: float,
    closed_pnls: tuple[float, ...],
    trade_count: int,
    closed_trade_count: int,
) -> BacktestResult:
    return BacktestResult(
        initial_cash=10_000.0,
        ending_equity=10_000.0 + net_pnl,
        net_pnl=net_pnl,
        return_percent=net_pnl / 100.0,
        max_drawdown_percent=1.0,
        total_fees=1.0,
        total_slippage_cost=0.5,
        trade_count=trade_count,
        winning_closed_trades=sum(value > 0 for value in closed_pnls),
        losing_closed_trades=sum(value < 0 for value in closed_pnls),
        fills=tuple(
            _sell_fill(value, timestamp_ms=index + 1)
            for index, value in enumerate(closed_pnls)
        ),
        metadata={"closed_trade_count": closed_trade_count},
        total_funding_cost=0.0,
        profit_factor=2.0,
    )


def test_strategy_review_counts_closed_round_trips_not_fill_rows() -> None:
    result = _result(
        net_pnl=20.0,
        closed_pnls=(20.0,),
        trade_count=200,
        closed_trade_count=1,
    )

    comparison = _comparison(
        "trend",
        result,
        benchmark_return=-1.0,
        config=StrategySuiteConfig(minimum_trades=2),
    )

    assert comparison.closed_trade_count == 1
    assert "insufficient_closed_trades" in comparison.failed_gates
    assert comparison.review_eligible is False


def test_positive_account_value_cannot_hide_negative_closed_trade_expectancy() -> None:
    result = _result(
        net_pnl=100.0,
        closed_pnls=(-5.0, -7.0),
        trade_count=4,
        closed_trade_count=2,
    )

    comparison = _comparison(
        "breakout",
        result,
        benchmark_return=-10.0,
        config=StrategySuiteConfig(minimum_trades=2),
    )

    assert comparison.net_expectancy_per_closed_trade == -6.0
    assert "non_positive_net_expectancy" in comparison.failed_gates
    assert comparison.review_eligible is False


def test_positive_closed_trade_expectancy_is_exposed_in_report_contract() -> None:
    result = _result(
        net_pnl=20.0,
        closed_pnls=(8.0, 12.0),
        trade_count=4,
        closed_trade_count=2,
    )

    comparison = _comparison(
        "mean_reversion",
        result,
        benchmark_return=-1.0,
        config=StrategySuiteConfig(minimum_trades=2),
    )

    assert comparison.net_expectancy_per_closed_trade == 10.0
    assert comparison.closed_trade_count == 2
    assert "non_positive_net_expectancy" not in comparison.failed_gates
