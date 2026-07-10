from __future__ import annotations

from dataclasses import replace

from exchange_connector.market_data import MarketDataUnavailable, MarketQuote
from news_monitor import market_impact_tracker as module
from news_monitor.market_impact_tracker import NewsMarketImpactTracker, infer_symbols


def quote(price: float) -> MarketQuote:
    return MarketQuote(
        symbol="BTCUSDT",
        price=price,
        change_24h_percent=1.0,
        volume_24h=1_000_000.0,
        source="bybit",
        source_url="https://api.bybit.com/v5/market/tickers",
        received_at="2026-07-10T00:00:00+00:00",
        received_at_unix_ms=1,
    )


class FakeMarketData:
    def __init__(self, prices: list[float]) -> None:
        self.prices = prices
        self.calls = 0

    def quote(self, symbol: str) -> MarketQuote:
        assert symbol == "BTCUSDT"
        price = self.prices[min(self.calls, len(self.prices) - 1)]
        self.calls += 1
        return replace(quote(price), symbol=symbol)


def news_state(title: str = "Bitcoin ETF approval boosts institutional demand") -> dict:
    return {
        "news": {
            "items": [
                {
                    "source_id": "reuters",
                    "title": title,
                    "content": "Bitcoin demand rises after ETF approval.",
                    "published_at": 1_700_000_000,
                    "tags": ["bitcoin", "etf", "approval"],
                }
            ]
        }
    }


def test_capture_and_finalize_uses_verified_before_and_after_quotes(tmp_path, monkeypatch) -> None:
    now = [1_700_000_000]
    monkeypatch.setattr(module, "load_news_state", lambda: news_state())
    tracker = NewsMarketImpactTracker(
        market_data=FakeMarketData([100.0, 103.0]),  # type: ignore[arg-type]
        state_path=tmp_path / "impact.json",
        clock=lambda: now[0],
    )
    tracker.horizon_minutes = 1

    captured = tracker.scan_new_news()
    assert captured["captured"] == 1
    assert tracker.status()["pending"] == 1

    now[0] += 61
    finalized = tracker.finalize_due()
    assert finalized["completed"] == 1
    assert tracker.status()["history"] == 1

    pattern = tracker.pattern_for(
        title="Bitcoin ETF approval increases demand",
        symbol="BTCUSDT",
        tags=["bitcoin", "etf", "approval"],
    )
    assert pattern["match_count"] == 1
    assert pattern["usable_for_decision"] is False


def test_unavailable_after_quote_keeps_pending_and_never_fakes_price(tmp_path, monkeypatch) -> None:
    now = [1_700_000_000]
    monkeypatch.setattr(module, "load_news_state", lambda: news_state())

    class FailingAfter(FakeMarketData):
        def quote(self, symbol: str) -> MarketQuote:
            if self.calls:
                raise MarketDataUnavailable("providers unavailable")
            return super().quote(symbol)

    tracker = NewsMarketImpactTracker(
        market_data=FailingAfter([100.0]),  # type: ignore[arg-type]
        state_path=tmp_path / "impact.json",
        clock=lambda: now[0],
    )
    tracker.horizon_minutes = 1
    tracker.scan_new_news()
    now[0] += 61

    result = tracker.finalize_due()
    assert result["completed"] == 0
    assert result["retries"] == 1
    assert tracker.status()["pending"] == 1
    assert tracker.status()["history"] == 0


def test_two_similar_material_reactions_make_third_pattern_usable(tmp_path, monkeypatch) -> None:
    now = [1_700_000_000]
    current = {"title": "Bitcoin ETF approval boosts institutional demand"}
    monkeypatch.setattr(module, "load_news_state", lambda: news_state(current["title"]))
    tracker = NewsMarketImpactTracker(
        market_data=FakeMarketData([100.0, 103.0, 110.0, 114.0]),  # type: ignore[arg-type]
        state_path=tmp_path / "impact.json",
        clock=lambda: now[0],
    )
    tracker.horizon_minutes = 1

    tracker.scan_new_news()
    now[0] += 61
    tracker.finalize_due()

    current["title"] = "New Bitcoin ETF approved for institutions"
    now[0] += 10
    tracker.scan_new_news()
    now[0] += 61
    tracker.finalize_due()

    pattern = tracker.pattern_for(
        title="Another Bitcoin ETF receives approval",
        symbol="BTCUSDT",
        tags=["bitcoin", "etf", "approval"],
    )
    assert pattern["match_count"] == 2
    assert pattern["expected_direction"] == "up"
    assert pattern["usable_for_decision"] is True


def test_symbol_inference_requires_explicit_asset() -> None:
    assert infer_symbols({"title": "Bitcoin ETF approved"}) == ["BTCUSDT"]
    assert infer_symbols({"title": "Central bank policy update"}) == []
    assert infer_symbols({"title": "Market update", "metadata": {"symbol": "ETHUSDT"}}) == ["ETHUSDT"]
