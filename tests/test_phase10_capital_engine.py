from __future__ import annotations

import math

import pytest

from risk.phase10_capital_engine import CapitalPolicy, CorrelationAwareCapitalEngine


def test_position_size_respects_scaling_position_and_cluster_caps():
    result = CorrelationAwareCapitalEngine().size(
        equity_usdt=1000,
        stop_distance_fraction=0.02,
        realized_volatility=0.01,
        proposed_symbol="BTCUSDT",
        open_positions=[
            {"symbol": "ETHUSDT", "notional_usdt": 40},
            {"symbol": "BTCUSDT", "notional_usdt": 45},
        ],
        correlations={"BTCUSDT": {"ETHUSDT": 0.85}},
        scaling_ceiling_usdt=37.5,
    )
    assert result["allowed"] is True
    assert result["notional_usdt"] == 5
    assert result["position_exposure_before_usdt"] == 45
    assert result["position_remaining_usdt"] == 5
    assert result["cluster_exposure_before_usdt"] == 85
    assert result["cluster_remaining_usdt"] == 15


def test_normal_cluster_capacity_returns_smallest_safe_notional():
    result = CorrelationAwareCapitalEngine().size(
        equity_usdt=1000,
        stop_distance_fraction=0.02,
        realized_volatility=0.01,
        proposed_symbol="BTCUSDT",
        open_positions=[{"symbol": "ETHUSDT", "notional_usdt": 80}],
        correlations={"BTCUSDT": {"ETHUSDT": 0.85}},
        scaling_ceiling_usdt=37.5,
    )
    assert result["allowed"] is True
    assert result["notional_usdt"] == 20
    assert "ETHUSDT" in result["correlated_symbols"]
    assert result["mainnet_enabled"] is False


def test_missing_correlation_data_fails_closed():
    result = CorrelationAwareCapitalEngine().size(
        equity_usdt=1000,
        stop_distance_fraction=0.02,
        realized_volatility=0.01,
        proposed_symbol="BTCUSDT",
        open_positions=[{"symbol": "ETHUSDT", "notional_usdt": 10}],
        correlations={},
        scaling_ceiling_usdt=25,
    )
    assert result["allowed"] is False
    assert result["reason"] == "missing_correlation_data"
    assert result["missing_correlations"] == ["ETHUSDT"]


def test_invalid_correlation_and_position_data_fail_closed():
    engine = CorrelationAwareCapitalEngine()
    invalid_correlation = engine.size(
        equity_usdt=1000,
        stop_distance_fraction=0.02,
        realized_volatility=0.01,
        proposed_symbol="BTCUSDT",
        open_positions=[{"symbol": "ETHUSDT", "notional_usdt": 10}],
        correlations={"BTCUSDT": {"ETHUSDT": 1.5}},
        scaling_ceiling_usdt=25,
    )
    assert invalid_correlation["allowed"] is False
    assert invalid_correlation["reason"] == "invalid_correlation_data"

    invalid_position = engine.size(
        equity_usdt=1000,
        stop_distance_fraction=0.02,
        realized_volatility=0.01,
        proposed_symbol="BTCUSDT",
        open_positions=[{"symbol": "", "notional_usdt": 10}],
        correlations={},
        scaling_ceiling_usdt=25,
    )
    assert invalid_position["allowed"] is False
    assert invalid_position["reason"] == "invalid_positions"


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("equity_usdt", float("nan"), "invalid_equity_or_stop"),
        ("stop_distance_fraction", float("inf"), "invalid_equity_or_stop"),
        ("realized_volatility", float("nan"), "invalid_volatility"),
        ("scaling_ceiling_usdt", float("inf"), "invalid_scaling_authority"),
    ],
)
def test_non_finite_inputs_fail_closed(field, value, reason):
    payload = {
        "equity_usdt": 1000,
        "stop_distance_fraction": 0.02,
        "realized_volatility": 0.01,
        "proposed_symbol": "BTCUSDT",
        "open_positions": [],
        "correlations": {},
        "scaling_ceiling_usdt": 25,
    }
    payload[field] = value
    result = CorrelationAwareCapitalEngine().size(**payload)
    assert result["allowed"] is False
    assert result["reason"] == reason
    assert result["notional_usdt"] == 0


def test_invalid_policy_is_rejected_before_sizing():
    with pytest.raises(ValueError):
        CapitalPolicy(maximum_notional_usdt=math.nan)
    with pytest.raises(ValueError):
        CapitalPolicy(maximum_notional_usdt=51)
    with pytest.raises(ValueError):
        CapitalPolicy(correlation_threshold=1.1)
