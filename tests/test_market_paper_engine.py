from __future__ import annotations

from typing import Any

from market_paper_engine import MarketPaperActivityEngine


def _payload(symbol: str, *, price: float = 100.0, change: float = 3.0, shock: float = 20.0) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "market_data_verified": True,
        "exchange_ok": True,
        "price": price,
        "price_change_24h_percent": change,
        "volatility_percent": abs(change),
        "trend_score": max(-1.0, min(1.0, change / 10.0)),
        "liquidity_score": 80.0,
        "news_shock_score": shock,
        "news_credibility_percent": 80.0,
        "ai_consensus_score": 80.0,
        "strategy_approved": True,
        "live_requested": False,
        "market_quote": {
            "symbol": symbol,
            "price": price,
            "source": "test-exchange",
            "received_at": "2026-07-13T00:00:00+00:00",
            "verified": True,
        },
    }


def test_market_engine_opens_and_persists_real_price_trade(tmp_path) -> None:
    path = tmp_path / "virtual_account.json"
    factory = lambda symbol: _payload(symbol)
    engine = MarketPaperActivityEngine(path=path, market_payload_factory=factory)

    result = engine.tick(force=True, now=1_000)

    assert result["status"] == "ok"
    trade = result["trade"]
    assert trade["entry_price"] == 100.0
    assert trade["quantity"] == 1.0
    assert trade["quote_source"] == "test-exchange"
    assert trade["real_order_placed"] is False

    reloaded = MarketPaperActivityEngine(path=path, market_payload_factory=factory).state()
    assert reloaded["summary"]["trade_count"] == 1
    assert reloaded["summary"]["open_positions"] == 1
    assert reloaded["summary"]["market_price_accounting"] is True


def test_news_wait_does_not_prevent_virtual_evidence_collection(tmp_path) -> None:
    path = tmp_path / "virtual_account.json"
    factory = lambda symbol: _payload(symbol, shock=100.0)
    engine = MarketPaperActivityEngine(path=path, market_payload_factory=factory)

    result = engine.tick(force=True, now=1_000)

    assert result["status"] == "ok"
    assert result["gate"]["market_regime"]["recommended_action"] == "WAIT"
    assert result["gate"]["can_trade_real"] is False
    assert result["trade"]["real_order_placed"] is False


def test_unverified_market_data_blocks_virtual_entry(tmp_path) -> None:
    def unavailable(symbol: str) -> dict[str, Any]:
        raise RuntimeError("exchange offline")

    engine = MarketPaperActivityEngine(
        path=tmp_path / "virtual_account.json",
        market_payload_factory=unavailable,
    )

    result = engine.tick(force=True, now=1_000)

    assert result["status"] == "blocked"
    assert result["state"]["summary"]["trade_count"] == 0
    assert result["state"]["summary"]["real_orders_blocked"] is True


def test_catch_up_never_fabricates_historical_trades(tmp_path) -> None:
    path = tmp_path / "virtual_account.json"
    factory = lambda symbol: _payload(symbol)
    engine = MarketPaperActivityEngine(path=path, market_payload_factory=factory)

    result = engine.catch_up(now=10_000, max_ticks=24)

    assert result["catch_up_ticks"] == 1
    assert result["historical_prices_fabricated"] is False
    assert engine.state()["summary"]["trade_count"] == 1
