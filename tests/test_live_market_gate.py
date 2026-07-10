from __future__ import annotations

from exchange_connector.market_data import MarketQuote, MarketDataUnavailable
import trading_intelligence


def _quote() -> MarketQuote:
    return MarketQuote(
        symbol="BTCUSDT",
        price=60000.0,
        change_24h_percent=2.0,
        volume_24h=1000000.0,
        source="bybit",
        source_url="https://api.bybit.com/v5/market/tickers",
        received_at="2026-07-10T00:00:00+00:00",
        received_at_unix_ms=1,
    )


def test_trade_gate_uses_verified_live_quote(monkeypatch) -> None:
    monkeypatch.setattr(trading_intelligence._MARKET_DATA, "quote", lambda symbol: _quote())
    result = trading_intelligence.trade_gate()
    assert result["market_data_verified"] is True
    assert result["market_quote"]["price"] == 60000.0
    assert result["market_quote"]["source"] == "bybit"


def test_trade_gate_blocks_when_live_quote_is_unavailable(monkeypatch) -> None:
    def fail(_symbol: str):
        raise MarketDataUnavailable("providers unavailable")

    monkeypatch.setattr(trading_intelligence._MARKET_DATA, "quote", fail)
    result = trading_intelligence.trade_gate()
    assert result["decision"] == "BLOCK"
    assert result["can_trade_virtual"] is False
    assert result["market_data_verified"] is False
    assert any("котировка" in item for item in result["blockers"])


def test_explicit_unverified_payload_is_blocked_without_network(monkeypatch) -> None:
    monkeypatch.setattr(
        trading_intelligence._MARKET_DATA,
        "quote",
        lambda _symbol: (_ for _ in ()).throw(AssertionError("network must not be called")),
    )
    result = trading_intelligence.trade_gate({"exchange_ok": False, "market_data_verified": False})
    assert result["decision"] == "BLOCK"
