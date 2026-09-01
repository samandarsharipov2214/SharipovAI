from __future__ import annotations

import pytest

from trading_core import BacktestConfig, BuyAndHoldStrategy, MarketEvent
from trading_core.cost_scenarios import (
    TransactionCostScenario,
    evaluate_transaction_cost_scenarios,
)


def _events() -> tuple[MarketEvent, ...]:
    return (
        MarketEvent(1, "BTCUSDT", 99.9, 100.1, source="fixture", volume=1_000_000.0, funding_rate=0.0001),
        MarketEvent(2, "BTCUSDT", 100.9, 101.1, source="fixture", volume=1_000_000.0, funding_rate=0.0001),
    )


def _scenario(scenario_id: str, *, fee: float, slippage: float) -> TransactionCostScenario:
    return TransactionCostScenario(
        scenario_id=scenario_id,
        fee_rate=fee,
        maker_fee_rate=fee,
        slippage_bps=slippage,
        market_impact_bps=0.0,
        fee_source="exchange-fee-snapshot:test",
        spread_source="historical-bbo:test",
        slippage_source="research-calibration:test",
        funding_source="historical-funding:test",
    )


def test_cost_scenarios_keep_provenance_and_increase_costs_deterministically() -> None:
    low, stressed = evaluate_transaction_cost_scenarios(
        _events(),
        strategy_factory=BuyAndHoldStrategy,
        scenarios=(
            _scenario("low", fee=0.0001, slippage=0.0),
            _scenario("stressed", fee=0.002, slippage=25.0),
        ),
        base_config=BacktestConfig(market_impact_bps=0.0),
    )

    assert low.scenario_id == "low"
    assert stressed.scenario_id == "stressed"
    assert stressed.result.total_fees > low.result.total_fees
    assert stressed.result.total_slippage_cost > low.result.total_slippage_cost
    assert stressed.result.ending_equity < low.result.ending_equity
    assert stressed.provenance["fee_source"] == "exchange-fee-snapshot:test"
    assert stressed.provenance["spread_input"] == "market_event.bid_ask"
    assert stressed.provenance["funding_input"] == "market_event.funding_rate"


def test_cost_scenario_rejects_missing_provenance_and_duplicate_ids() -> None:
    with pytest.raises(ValueError, match="fee_source must not be blank"):
        TransactionCostScenario(
            scenario_id="bad",
            fee_rate=0.001,
            maker_fee_rate=0.001,
            slippage_bps=1.0,
            market_impact_bps=1.0,
            fee_source="",
            spread_source="bbo",
            slippage_source="calibration",
            funding_source="funding",
        )

    scenario = _scenario("same", fee=0.001, slippage=1.0)
    with pytest.raises(ValueError, match="scenario_id values must be unique"):
        evaluate_transaction_cost_scenarios(
            _events(),
            strategy_factory=BuyAndHoldStrategy,
            scenarios=(scenario, scenario),
        )


def test_execution_cost_model_round_trip_includes_fees_spread_and_slippage() -> None:
    from trading_core.costs import ExecutionCostModel

    event = _events()[0]
    model = ExecutionCostModel(fee_rate=0.001, slippage_bps=5.0, market_impact_bps=0.0)
    round_trip = model.estimate_round_trip(event, quantity=2.0)

    assert round_trip.fee > 0
    assert round_trip.spread_cost > 0
    assert round_trip.slippage_cost > 0
    assert round_trip.all_in == round_trip.fee + round_trip.spread_cost + round_trip.slippage_cost
    tight = ExecutionCostModel(fee_rate=0.0, slippage_bps=0.0, market_impact_bps=0.0)
    cheap = tight.estimate_round_trip(event, quantity=2.0)
    assert cheap.fee == 0
    assert cheap.slippage_cost == 0
    assert cheap.all_in == cheap.spread_cost
    assert round_trip.all_in > cheap.all_in
