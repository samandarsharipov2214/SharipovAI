from __future__ import annotations

from typing import Any

from capital_allocation import CapitalAllocationPolicy
from dashboard.trade_explanations import enrich_virtual_state, explain_trade
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


def _policy() -> CapitalAllocationPolicy:
    return CapitalAllocationPolicy(
        reserve_percent=20.0,
        max_position_percent=20.0,
        max_risk_per_trade_percent=1.0,
        minimum_notional=25.0,
        leverage=1.0,
    )


def test_market_engine_opens_and_persists_real_price_trade(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("VIRTUAL_ACCOUNT_MAX_OPEN", "8")
    path = tmp_path / "virtual_account.json"
    factory = lambda symbol: _payload(symbol)
    engine = MarketPaperActivityEngine(
        path=path,
        market_payload_factory=factory,
        allocation_policy=_policy(),
    )

    result = engine.tick(force=True, now=1_000)

    assert result["status"] == "ok"
    trade = result["trade"]
    assert trade["entry_price"] == 100.0
    assert trade["notional"] == 2000.0
    assert trade["quantity"] == 20.0
    assert trade["capital_allocation"]["reserve_percent"] == 20.0
    assert trade["leverage"] == 1.0
    assert trade["quote_source"] == "test-exchange"
    assert trade["real_order_placed"] is False

    reloaded = MarketPaperActivityEngine(
        path=path,
        market_payload_factory=factory,
        allocation_policy=_policy(),
    ).state()
    assert reloaded["summary"]["trade_count"] == 1
    assert reloaded["summary"]["open_positions"] == 1
    assert reloaded["summary"]["deployed_notional"] == 2000.0
    assert reloaded["summary"]["reserve_percent"] == 20.0
    assert reloaded["summary"]["market_price_accounting"] is True


def test_news_wait_does_not_prevent_virtual_evidence_collection(tmp_path) -> None:
    path = tmp_path / "virtual_account.json"
    factory = lambda symbol: _payload(symbol, shock=100.0)
    engine = MarketPaperActivityEngine(path=path, market_payload_factory=factory, allocation_policy=_policy())

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
        allocation_policy=_policy(),
    )

    result = engine.tick(force=True, now=1_000)

    assert result["status"] == "blocked"
    assert result["state"]["summary"]["trade_count"] == 0
    assert result["state"]["summary"]["real_orders_blocked"] is True


def test_catch_up_never_fabricates_historical_trades(tmp_path) -> None:
    path = tmp_path / "virtual_account.json"
    factory = lambda symbol: _payload(symbol)
    engine = MarketPaperActivityEngine(path=path, market_payload_factory=factory, allocation_policy=_policy())

    result = engine.catch_up(now=10_000, max_ticks=24)

    assert result["catch_up_ticks"] == 1
    assert result["historical_prices_fabricated"] is False
    assert engine.state()["summary"]["trade_count"] == 1


def test_trade_explanation_backfills_legacy_sell_reason() -> None:
    state = {
        "trades": [
            {
                "symbol": "SOL/USDT",
                "side": "SELL",
                "status": "OPEN",
                "signal_change_24h_percent": -2.125,
                "quote_source": "bybit",
            }
        ]
    }

    enrich_virtual_state(state)

    trade = state["trades"][0]
    assert "Продажа SOL/USDT" in trade["entry_reason_ru"]
    assert "-2.125%" in trade["entry_reason_ru"]
    assert "0.35%" in trade["entry_reason_ru"]
    assert "Позиция ещё открыта" in trade["operation_explanation_ru"]


def test_trade_explanation_maps_close_reason() -> None:
    trade = {
        "symbol": "BTC/USDT",
        "side": "BUY",
        "status": "CLOSED",
        "signal_change_24h_percent": 1.5,
        "close_reason": "take_profit",
    }

    explain_trade(trade)

    assert "Покупка BTC/USDT" in trade["entry_reason_ru"]
    assert trade["close_reason_ru"] == "достигнута цель прибыли"
    assert "Закрытие" in trade["operation_explanation_ru"]
