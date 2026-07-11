from __future__ import annotations

import pytest

from exchange_connector.bybit_websocket_state import BybitWebSocketState, ReconnectPolicy


def _ticker(*, ts: int, price: str = "60000", sequence: int = 1) -> dict:
    return {
        "topic": "tickers.BTCUSDT",
        "ts": ts,
        "cs": sequence,
        "data": {"lastPrice": price},
    }


def test_fresh_connected_quote_is_available(monkeypatch):
    monkeypatch.setenv("BYBIT_WS_MAX_QUOTE_AGE_SECONDS", "1.0")
    state = BybitWebSocketState()
    state.mark_connected()
    state.ingest_ticker(_ticker(ts=10_000), received_at_ms=10_100)

    quote = state.current_quote("BTC/USDT", now_ms=10_500)

    assert quote.price == 60000
    assert state.status(now_ms=10_500)["verified"] is True


def test_disconnected_stream_fails_closed():
    state = BybitWebSocketState()
    state.ingest_ticker(_ticker(ts=10_000), received_at_ms=10_100)

    with pytest.raises(RuntimeError, match="disconnected"):
        state.current_quote("BTCUSDT", now_ms=10_200)


def test_stale_quote_is_rejected(monkeypatch):
    monkeypatch.setenv("BYBIT_WS_MAX_QUOTE_AGE_SECONDS", "0.5")
    state = BybitWebSocketState()
    state.mark_connected()
    state.ingest_ticker(_ticker(ts=10_000), received_at_ms=10_100)

    with pytest.raises(RuntimeError, match="stale"):
        state.current_quote("BTCUSDT", now_ms=10_700)


def test_late_or_future_events_are_rejected(monkeypatch):
    monkeypatch.setenv("BYBIT_WS_MAX_EXCHANGE_LAG_MS", "1000")
    monkeypatch.setenv("BYBIT_WS_MAX_FUTURE_SKEW_MS", "250")
    state = BybitWebSocketState()

    with pytest.raises(ValueError, match="too late"):
        state.ingest_ticker(_ticker(ts=8_000), received_at_ms=10_000)

    with pytest.raises(ValueError, match="future"):
        state.ingest_ticker(_ticker(ts=10_500), received_at_ms=10_000)


def test_sequence_must_advance():
    state = BybitWebSocketState()
    state.ingest_ticker(_ticker(ts=10_000, sequence=5), received_at_ms=10_100)

    with pytest.raises(ValueError, match="sequence"):
        state.ingest_ticker(_ticker(ts=10_050, sequence=5), received_at_ms=10_150)


def test_reconnect_delay_is_bounded_and_resets(monkeypatch):
    monkeypatch.setenv("BYBIT_WS_RECONNECT_BASE_SECONDS", "0.5")
    monkeypatch.setenv("BYBIT_WS_RECONNECT_MAX_SECONDS", "2")
    policy = ReconnectPolicy()

    delays = [policy.next_delay(random_value=0) for _ in range(5)]
    assert delays == [0.5, 1.0, 2.0, 2.0, 2.0]

    policy.reset()
    assert policy.next_delay(random_value=0) == 0.5
