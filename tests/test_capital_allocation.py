from __future__ import annotations

from capital_allocation import (
    CapitalAllocationPolicy,
    build_capital_allocation,
    capital_snapshot,
    correlation_group_for_symbol,
)


def _policy() -> CapitalAllocationPolicy:
    return CapitalAllocationPolicy(
        reserve_percent=20.0,
        max_total_exposure_percent=80.0,
        max_position_percent=20.0,
        max_symbol_exposure_percent=20.0,
        max_correlated_exposure_percent=35.0,
        max_risk_per_trade_percent=1.0,
        max_daily_loss_percent=2.0,
        minimum_notional=25.0,
        leverage=1.0,
    )


def test_first_position_scales_to_equity_and_position_cap() -> None:
    allocation = build_capital_allocation(
        equity=10_000.0,
        open_trades=[],
        max_open_positions=8,
        stop_loss_percent=0.8,
        fee_rate=0.001,
        requested_risk_percent=1.0,
        policy=_policy(),
        symbol="BTCUSDT",
        correlation_group="crypto_beta",
    )

    assert allocation["allowed"] is True
    assert allocation["notional"] == 2000.0
    assert allocation["reserve_amount"] == 2000.0
    assert allocation["deployable_capital"] == 8000.0
    assert allocation["projected_utilization_percent"] == 20.0
    assert allocation["leverage"] == 1.0


def test_allocator_can_deploy_eighty_percent_across_four_uncorrelated_positions() -> None:
    open_trades = [
        {"status": "OPEN", "notional": 2000.0, "symbol": "ASSET1", "correlation_group": "g1"},
        {"status": "OPEN", "notional": 2000.0, "symbol": "ASSET2", "correlation_group": "g2"},
        {"status": "OPEN", "notional": 2000.0, "symbol": "ASSET3", "correlation_group": "g3"},
    ]
    allocation = build_capital_allocation(
        equity=10_000.0,
        open_trades=open_trades,
        max_open_positions=8,
        stop_loss_percent=0.8,
        fee_rate=0.001,
        requested_risk_percent=1.0,
        policy=_policy(),
        symbol="ASSET4",
        correlation_group="g4",
    )

    assert allocation["allowed"] is True
    assert allocation["notional"] == 2000.0
    assert allocation["projected_utilization_percent"] == 80.0

    snapshot = capital_snapshot(
        equity=10_000.0,
        open_trades=[
            *open_trades,
            {
                "status": "OPEN",
                "notional": allocation["notional"],
                "symbol": "ASSET4",
                "correlation_group": "g4",
            },
        ],
        policy=_policy(),
    )
    assert snapshot["deployed_notional"] == 8000.0
    assert snapshot["available_to_allocate"] == 0.0
    assert snapshot["capital_utilization_percent"] == 80.0
    assert snapshot["deployable_utilization_percent"] == 100.0


def test_allocator_preserves_reserve_instead_of_using_one_hundred_percent() -> None:
    allocation = build_capital_allocation(
        equity=10_000.0,
        open_trades=[{"status": "OPEN", "notional": 8000.0}],
        max_open_positions=8,
        stop_loss_percent=0.8,
        fee_rate=0.001,
        requested_risk_percent=1.0,
        policy=_policy(),
    )

    assert allocation["allowed"] is False
    assert allocation["reason"] == "reserve_or_total_exposure_protected"
    assert allocation["notional"] == 0.0
    assert allocation["reserve_amount"] == 2000.0


def test_risk_budget_can_reduce_position_below_position_cap() -> None:
    allocation = build_capital_allocation(
        equity=10_000.0,
        open_trades=[],
        max_open_positions=2,
        stop_loss_percent=10.0,
        fee_rate=0.001,
        requested_risk_percent=1.0,
        policy=_policy(),
    )

    assert allocation["allowed"] is True
    assert allocation["position_notional_cap"] == 2000.0
    assert allocation["risk_notional_cap"] < allocation["position_notional_cap"]
    assert allocation["notional"] == 980.39


def test_requested_risk_is_capped_and_scaled_by_risk_engine() -> None:
    allocation = build_capital_allocation(
        equity=10_000.0,
        open_trades=[],
        max_open_positions=8,
        stop_loss_percent=0.8,
        fee_rate=0.001,
        requested_risk_percent=25.0,
        risk_size_multiplier=0.25,
        policy=_policy(),
    )

    assert allocation["requested_risk_percent"] == 25.0
    assert allocation["effective_risk_percent"] == 1.0
    assert allocation["risk_size_multiplier"] == 0.25
    assert allocation["notional"] == 250.0


def test_correlation_cap_blocks_another_major_crypto_position() -> None:
    allocation = build_capital_allocation(
        equity=10_000.0,
        open_trades=[
            {
                "status": "OPEN",
                "notional": 2000.0,
                "symbol": "BTCUSDT",
                "correlation_group": "crypto_beta",
            },
            {
                "status": "OPEN",
                "notional": 1500.0,
                "symbol": "ETHUSDT",
                "correlation_group": "crypto_beta",
            },
        ],
        max_open_positions=8,
        stop_loss_percent=0.8,
        fee_rate=0.001,
        requested_risk_percent=1.0,
        policy=_policy(),
        symbol="SOLUSDT",
        correlation_group="crypto_beta",
    )

    assert allocation["allowed"] is False
    assert allocation["reason"] == "correlated_exposure_limit"
    assert allocation["correlated_notional"] == 3500.0
    assert correlation_group_for_symbol("SOL/USDT") == "crypto_beta"


def test_daily_loss_and_hard_risk_blocks_override_free_cash() -> None:
    daily = build_capital_allocation(
        equity=10_000.0,
        open_trades=[],
        max_open_positions=8,
        stop_loss_percent=0.8,
        fee_rate=0.001,
        requested_risk_percent=1.0,
        current_daily_loss_percent=2.0,
        policy=_policy(),
    )
    hard = build_capital_allocation(
        equity=10_000.0,
        open_trades=[],
        max_open_positions=8,
        stop_loss_percent=0.8,
        fee_rate=0.001,
        requested_risk_percent=1.0,
        hard_blocks=("stale_market_data",),
        policy=_policy(),
    )

    assert daily["allowed"] is False
    assert daily["reason"] == "daily_loss_limit"
    assert hard["allowed"] is False
    assert hard["reason"] == "risk_hard_block:stale_market_data"
