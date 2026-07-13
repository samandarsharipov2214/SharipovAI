from __future__ import annotations

from capital_allocation import CapitalAllocationPolicy, build_capital_allocation, capital_snapshot


def _policy() -> CapitalAllocationPolicy:
    return CapitalAllocationPolicy(
        reserve_percent=20.0,
        max_position_percent=20.0,
        max_risk_per_trade_percent=1.0,
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
    )

    assert allocation["allowed"] is True
    assert allocation["notional"] == 2000.0
    assert allocation["reserve_amount"] == 2000.0
    assert allocation["deployable_capital"] == 8000.0
    assert allocation["projected_utilization_percent"] == 20.0
    assert allocation["leverage"] == 1.0


def test_allocator_can_deploy_eighty_percent_across_four_positions() -> None:
    open_trades = [
        {"status": "OPEN", "notional": 2000.0},
        {"status": "OPEN", "notional": 2000.0},
        {"status": "OPEN", "notional": 2000.0},
    ]
    allocation = build_capital_allocation(
        equity=10_000.0,
        open_trades=open_trades,
        max_open_positions=8,
        stop_loss_percent=0.8,
        fee_rate=0.001,
        requested_risk_percent=1.0,
        policy=_policy(),
    )

    assert allocation["allowed"] is True
    assert allocation["notional"] == 2000.0
    assert allocation["projected_utilization_percent"] == 80.0

    snapshot = capital_snapshot(
        equity=10_000.0,
        open_trades=[*open_trades, {"status": "OPEN", "notional": allocation["notional"]}],
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
    assert allocation["reason"] == "reserve_protected"
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


def test_requested_risk_is_capped_by_policy() -> None:
    allocation = build_capital_allocation(
        equity=10_000.0,
        open_trades=[],
        max_open_positions=8,
        stop_loss_percent=0.8,
        fee_rate=0.001,
        requested_risk_percent=25.0,
        policy=_policy(),
    )

    assert allocation["requested_risk_percent"] == 25.0
    assert allocation["effective_risk_percent"] == 1.0
    assert allocation["notional"] == 2000.0
