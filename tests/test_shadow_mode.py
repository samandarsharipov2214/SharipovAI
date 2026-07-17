from __future__ import annotations

import pytest

from autonomous_trading import ShadowModePlanner, ShadowModePolicy
from exchange_connector.bybit_reference_data import (
    FeeSchedule,
    InstrumentRules,
    TradingReferenceSnapshot,
)
from trading_candidate import (
    MarketRegime,
    TradingCandidate,
    TradingCategory,
    TradingDecision,
    TradingEnvironment,
    TradingSide,
)


class _ReferenceClient:
    def __init__(self, snapshot: TradingReferenceSnapshot) -> None:
        self.snapshot = snapshot

    def get(self, symbol, *, category, allow_network, now_ms):
        assert symbol == "BTCUSDT"
        assert category == "spot"
        assert allow_network is True
        assert now_ms == 1_000_000
        return self.snapshot


def _candidate() -> TradingCandidate:
    return TradingCandidate(
        candidate_id="testnet-shadow-candidate",
        symbol="BTCUSDT",
        category=TradingCategory.SPOT,
        side=TradingSide.BUY,
        environment=TradingEnvironment.TESTNET,
        market_timestamp_ms=999_500,
        received_timestamp_ms=999_600,
        reference_price=50_000.0,
        data_sources=("bybit-ticker", "bybit-orderbook", "cross-check"),
        market_regime=MarketRegime.TREND,
        signal_evidence=("signal-1",),
        news_evidence=(),
        news_assessment_id="news-1",
        portfolio_snapshot_id="portfolio-1",
        cost_snapshot_id="cost-1",
        estimated_fees=0.1,
        estimated_slippage=0.1,
        risk_score=10.0,
        risk_blocks=(),
        confidence=80.0,
        consensus=80.0,
        decision=TradingDecision.ALLOW,
        expires_at_ms=1_004_000,
    )


def test_shadow_plan_preserves_source_identity_and_caps_notional() -> None:
    snapshot = TradingReferenceSnapshot(
        environment="sandbox",
        category="spot",
        symbol="BTCUSDT",
        received_at_ms=999_900,
        expires_at_ms=1_010_000,
        fee=FeeSchedule("spot", "BTCUSDT", 0.0001, 0.0006, "test"),
        instrument=InstrumentRules(
            category="spot",
            symbol="BTCUSDT",
            status="Trading",
            base_coin="BTC",
            quote_coin="USDT",
            tick_size=0.01,
            quantity_step=0.0001,
            minimum_quantity=0.0001,
            minimum_notional=5.0,
            maximum_market_quantity=10.0,
            funding_interval_minutes=0,
            source="test",
        ),
    )
    planner = ShadowModePlanner(
        _ReferenceClient(snapshot),
        policy=ShadowModePolicy(maximum_testnet_notional_usdt=25.0),
    )
    plan = planner.plan(
        paper_trade={
            "trade_id": "paper-1",
            "candidate_id": "paper-candidate-1",
            "execution_candidate": {"candidate_id": "paper-candidate-1"},
            "created_at_ms": 999_500,
            "symbol": "BTCUSDT",
            "side": "BUY",
            "price": 50_000.0,
            "quantity": 1.0,
        },
        testnet_candidate=_candidate(),
        execution_max_notional=100.0,
        now_ms=1_000_000,
    )

    assert plan.source_candidate_id == "paper-candidate-1"
    assert plan.testnet_candidate_id == "testnet-shadow-candidate"
    assert plan.testnet_quantity == pytest.approx(0.0005)
    assert plan.testnet_notional == pytest.approx(25.0)
    assert plan.paper_quantity == 1.0
    assert plan.shadow_pair_id.startswith("shadow_")
