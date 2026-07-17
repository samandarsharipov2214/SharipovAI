from __future__ import annotations

import pytest

from autonomous_trading.testnet_bridge import _candidate_from_trade
from storage import ProjectDatabase
from trading_candidate import (
    MarketRegime,
    TradingCandidate,
    TradingCategory,
    TradingDecision,
    TradingEnvironment,
    TradingSide,
)


def _database(tmp_path) -> ProjectDatabase:
    database = ProjectDatabase(f"sqlite:///{tmp_path / 'project.db'}")
    database.initialize()
    return database


def _paper_candidate(now_ms: int) -> TradingCandidate:
    return TradingCandidate(
        candidate_id="paper-candidate-1",
        symbol="BTCUSDT",
        category=TradingCategory.SPOT,
        side=TradingSide.BUY,
        environment=TradingEnvironment.PAPER,
        market_timestamp_ms=now_ms - 1_000,
        received_timestamp_ms=now_ms - 900,
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
        confidence=85.0,
        consensus=85.0,
        decision=TradingDecision.ALLOW,
        expires_at_ms=now_ms + 5_000,
    )


def _trade(now_ms: int) -> dict[str, object]:
    return {
        "trade_id": "paper-trade-1",
        "candidate_id": "paper-candidate-1",
        "created_at_ms": now_ms - 1_000,
        "symbol": "BTCUSDT",
        "side": "BUY",
        "price": 50_000.0,
        "quantity": 0.0002,
    }


def test_bridge_reissues_fresh_testnet_candidate_from_stored_paper_evidence(tmp_path) -> None:
    now_ms = 10_000_000
    database = _database(tmp_path)
    source = _paper_candidate(now_ms)
    database.put_json(
        "trading_candidates",
        source.candidate_id,
        source.to_dict(),
        expected_version=0,
    )

    mirrored = _candidate_from_trade(
        _trade(now_ms),
        database=database,
        now_ms=now_ms,
    )

    assert mirrored.environment is TradingEnvironment.TESTNET
    assert mirrored.decision is TradingDecision.ALLOW
    assert mirrored.candidate_id.startswith("testnet_")
    assert mirrored.symbol == source.symbol
    assert mirrored.side is source.side
    assert mirrored.reference_price == 50_000.0
    assert mirrored.expires_at_ms == now_ms + 4_000


def test_bridge_blocks_trade_without_canonical_candidate_evidence(tmp_path) -> None:
    database = _database(tmp_path)

    with pytest.raises(ValueError, match="no canonical candidate evidence"):
        _candidate_from_trade(
            _trade(10_000_000),
            database=database,
            now_ms=10_000_000,
        )


def test_bridge_blocks_stale_paper_trade_even_when_candidate_exists(tmp_path) -> None:
    now_ms = 10_000_000
    database = _database(tmp_path)
    source = _paper_candidate(now_ms)
    database.put_json(
        "trading_candidates",
        source.candidate_id,
        source.to_dict(),
        expected_version=0,
    )
    trade = _trade(now_ms)
    trade["created_at_ms"] = now_ms - 5_001

    with pytest.raises(ValueError, match="too old"):
        _candidate_from_trade(
            trade,
            database=database,
            now_ms=now_ms,
        )
