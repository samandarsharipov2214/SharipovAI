from risk.phase10_capital_engine import CorrelationAwareCapitalEngine


def test_position_size_respects_scaling_and_cluster_caps():
    engine = CorrelationAwareCapitalEngine()
    result = engine.size(
        equity_usdt=1000,
        stop_distance_fraction=0.02,
        realized_volatility=0.01,
        proposed_symbol="BTCUSDT",
        open_positions=[{"symbol": "ETHUSDT", "notional_usdt": 80}],
        correlations={"BTCUSDT": {"ETHUSDT": 0.85}},
        scaling_ceiling_usdt=37.5,
    )
    assert result["allowed"] is True
    assert result["notional_usdt"] <= 20
    assert result["notional_usdt"] <= 37.5
    assert "ETHUSDT" in result["correlated_symbols"]
    assert result["mainnet_enabled"] is False


def test_invalid_inputs_fail_closed():
    result = CorrelationAwareCapitalEngine().size(
        equity_usdt=0,
        stop_distance_fraction=0,
        realized_volatility=0,
        proposed_symbol="BTCUSDT",
        open_positions=[],
        correlations={},
        scaling_ceiling_usdt=50,
    )
    assert result == {"allowed": False, "reason": "invalid_equity_or_stop", "notional_usdt": 0.0}
