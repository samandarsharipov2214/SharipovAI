from __future__ import annotations

from risk_engine import CanonicalRiskService


def test_canonical_risk_service_fails_closed_without_verified_market() -> None:
    result = CanonicalRiskService().evaluate(
        {"market_data_verified": False, "exchange_ok": False},
        profile="health_probe",
    )

    assert result.allowed_virtual is False
    assert result.allowed_live is False
    assert result.decision == "BLOCK"
    assert result.risk_score == 100.0
    assert "market_data_unverified" in result.hard_blocks
    assert "exchange_unavailable" in result.hard_blocks


def test_canonical_risk_service_applies_council_limits() -> None:
    service = CanonicalRiskService()

    safe = service.evaluate(
        {
            "market_data_verified": True,
            "exchange_ok": True,
            "price_change_24h_percent": 1.0,
            "turnover_usdt": 10_000_000.0,
            "portfolio_drawdown_percent": 1.0,
            "ws_consensus_deviation_percent": 0.1,
            "max_abs_change_percent": 12.0,
            "min_turnover_usdt": 5_000_000.0,
            "max_drawdown_percent": 8.0,
        },
        profile="council",
    )
    blocked = service.evaluate(
        {
            "market_data_verified": True,
            "exchange_ok": True,
            "price_change_24h_percent": 13.0,
            "turnover_usdt": 100_000.0,
            "portfolio_drawdown_percent": 9.0,
            "ws_consensus_deviation_percent": 0.9,
            "max_abs_change_percent": 12.0,
            "min_turnover_usdt": 5_000_000.0,
            "max_drawdown_percent": 8.0,
        },
        profile="council",
    )

    assert safe.hard_blocks == ()
    assert safe.allowed_virtual is True
    assert set(blocked.hard_blocks) == {
        "extreme_24h_volatility",
        "insufficient_verified_liquidity",
        "paper_portfolio_drawdown_limit",
        "websocket_consensus_price_divergence",
    }
    assert blocked.allowed_virtual is False


def test_trade_gate_profile_preserves_virtual_only_and_live_lock() -> None:
    service = CanonicalRiskService()

    result = service.evaluate(
        {
            "market_data_verified": True,
            "exchange_ok": True,
            "price_change_24h_percent": 7.0,
            "volatility_percent": 4.0,
            "trend_score": 0.7,
            "liquidity_score": 80.0,
            "news_shock_score": 10.0,
            "news_credibility_percent": 90.0,
            "ai_consensus_score": 90.0,
            "risk_per_trade_percent": 1.0,
            "strategy_approved": False,
            "live_requested": False,
        },
        profile="trade_gate",
    )

    assert result.decision == "VIRTUAL_ONLY"
    assert result.allowed_virtual is True
    assert result.allowed_live is False
    assert result.market_regime["recommended_action"] == "VIRTUAL_ONLY"


def test_trade_gate_requires_explicit_exchange_and_consensus_evidence() -> None:
    result = CanonicalRiskService().evaluate(
        {
            "market_data_verified": True,
            "price_change_24h_percent": 7.0,
            "volatility_percent": 4.0,
            "trend_score": 0.7,
            "liquidity_score": 80.0,
            "news_shock_score": 10.0,
            "news_credibility_percent": 90.0,
            "risk_per_trade_percent": 1.0,
            "strategy_approved": True,
        },
        profile="trade_gate",
    )

    assert result.decision == "BLOCK"
    assert result.allowed_virtual is False
    assert "exchange_unavailable" in result.hard_blocks
    assert "low_ai_consensus" in result.hard_blocks


def test_council_requires_explicit_verified_liquidity() -> None:
    result = CanonicalRiskService().evaluate(
        {
            "market_data_verified": True,
            "exchange_ok": True,
            "price_change_24h_percent": 1.0,
            "portfolio_drawdown_percent": 1.0,
            "ws_consensus_deviation_percent": 0.1,
        },
        profile="council",
    )

    assert result.allowed_virtual is False
    assert "missing_verified_liquidity" in result.hard_blocks


def test_assessment_dict_is_json_canonical_for_idempotent_comparison() -> None:
    result = CanonicalRiskService().evaluate(
        {
            "market_data_verified": False,
            "exchange_ok": False,
        },
        profile="health_probe",
    )

    payload = result.to_dict()
    assert isinstance(payload["hard_blocks"], list)
    assert isinstance(payload["blockers"], list)
    assert isinstance(payload["warnings"], list)
