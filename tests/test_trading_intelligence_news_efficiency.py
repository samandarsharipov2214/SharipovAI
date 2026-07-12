from __future__ import annotations

import trading_intelligence as subject


def _verified_payload() -> dict[str, object]:
    return {
        "symbol": "BTCUSDT",
        "market_data_verified": True,
        "exchange_ok": True,
        "volatility_percent": 1.0,
        "trend_score": 0.1,
        "spread_percent": 0.05,
        "liquidity_score": 80.0,
        "strategy_approved": False,
    }


def test_trade_gate_reads_news_once(monkeypatch) -> None:
    calls = 0

    def fake_news() -> dict[str, object]:
        nonlocal calls
        calls += 1
        return {
            "summary": {
                "urgent_count": 1,
                "needs_confirmation": 2,
                "average_credibility_percent": 72,
            }
        }

    monkeypatch.setattr(subject, "analyzed_news_payload", fake_news)
    result = subject.trade_gate(_verified_payload())

    assert calls == 1
    assert result["inputs"]["news_credibility_percent"] == 72.0
    assert result["market_regime"]["inputs"]["news_shock_score"] == 45.0


def test_trade_gate_does_not_refresh_news_when_metrics_are_supplied(monkeypatch) -> None:
    calls = 0

    def fake_news() -> dict[str, object]:
        nonlocal calls
        calls += 1
        return {"summary": {}}

    monkeypatch.setattr(subject, "analyzed_news_payload", fake_news)
    payload = {
        **_verified_payload(),
        "news_shock_score": 0,
        "news_credibility_percent": 90,
    }
    result = subject.trade_gate(payload)

    assert calls == 0
    assert result["inputs"]["news_credibility_percent"] == 90.0
    assert result["market_regime"]["inputs"]["news_shock_score"] == 0.0
