from __future__ import annotations

import os

import pytest

from exchange_connector.bybit_execution import BybitExecutionClient
from exchange_connector.execution_contract import (
    MAINNET_EXECUTION_COMPILED,
    build_execution_request,
    validate_execution_request,
)
from trading_candidate import (
    CandidateValidation,
    MarketRegime,
    TradingCandidate,
    TradingCategory,
    TradingDecision,
    TradingEnvironment,
    TradingSide,
)


def _candidate(environment: TradingEnvironment = TradingEnvironment.TESTNET) -> TradingCandidate:
    return TradingCandidate(
        candidate_id="candidate-001",
        symbol="BTCUSDT",
        category=TradingCategory.SPOT,
        side=TradingSide.BUY,
        environment=environment,
        market_timestamp_ms=9_999_000,
        received_timestamp_ms=9_999_100,
        reference_price=50_000.0,
        data_sources=("bybit-ticker", "bybit-orderbook", "binance-cross-check"),
        market_regime=MarketRegime.TREND,
        signal_evidence=("signal-1",),
        news_evidence=(),
        news_assessment_id="news-1",
        portfolio_snapshot_id="portfolio-1",
        cost_snapshot_id="cost-1",
        estimated_fees=0.1,
        estimated_slippage=0.1,
        risk_score=20.0,
        risk_blocks=(),
        confidence=80.0,
        consensus=85.0,
        decision=TradingDecision.ALLOW,
        expires_at_ms=10_005_000,
    )


def _validation() -> CandidateValidation:
    return CandidateValidation(
        valid=True,
        decision=TradingDecision.ALLOW,
        errors=(),
        effective_min_confidence=70.0,
        effective_min_consensus=70.0,
    )


def test_builds_short_lived_testnet_execution_request() -> None:
    request = build_execution_request(
        _candidate(),
        _validation(),
        quantity=0.0002,
        now_ms=10_000_000,
    )

    assert request.environment is TradingEnvironment.TESTNET
    assert request.notional == 10.0
    assert request.order_link_id.startswith("SAI-")
    assert len(request.order_link_id) <= 36
    assert len(request.candidate_hash) == 64
    validate_execution_request(request, now_ms=10_000_001)


def test_mainnet_request_is_compiled_out() -> None:
    assert MAINNET_EXECUTION_COMPILED is False
    with pytest.raises(RuntimeError, match="mainnet execution is compiled out"):
        build_execution_request(
            _candidate(TradingEnvironment.MAINNET),
            _validation(),
            quantity=0.0002,
            now_ms=10_000_000,
        )


def test_invalid_or_non_allow_validation_cannot_execute() -> None:
    rejected = CandidateValidation(
        valid=False,
        decision=TradingDecision.BLOCK,
        errors=("risk block",),
        effective_min_confidence=70.0,
        effective_min_consensus=70.0,
    )
    with pytest.raises(RuntimeError, match="does not permit execution"):
        build_execution_request(
            _candidate(),
            rejected,
            quantity=0.0002,
            now_ms=10_000_000,
        )


def test_live_client_remains_locked_even_when_environment_flags_are_set(monkeypatch) -> None:
    monkeypatch.setenv("EXCHANGE_MODE", "live")
    monkeypatch.setenv("EXCHANGE_BASE_URL", "https://api.bybit.com")
    monkeypatch.setenv("EXCHANGE_LIVE_TRADING_ENABLED", "1")
    monkeypatch.setenv("LIVE_EXECUTION_MANUAL_UNLOCK", "1")
    monkeypatch.setenv("LIVE_EXECUTION_CONFIRMATION", "I_ACCEPT_REAL_FINANCIAL_RISK")
    monkeypatch.setenv("EXECUTION_KILL_SWITCH", "0")

    client = BybitExecutionClient()
    status = client.status()

    assert status["live_execution_enabled"] is False
    assert status["mainnet_execution_compiled"] is False
    assert status["mainnet_hard_blocked"] is True
    with pytest.raises(RuntimeError, match="Mainnet execution is compiled out"):
        client.place_market_order(
            symbol="BTCUSDT",
            side="Buy",
            quantity=0.0002,
            reference_price=50_000.0,
        )
