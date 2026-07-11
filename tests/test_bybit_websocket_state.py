from __future__ import annotations

import math
import time

import pytest

from exchange_connector.bybit_websocket_state import BybitWebSocketState, ReconnectPolicy


NOW = int(time.time() * 1000)


def _ticker(**changes):
    payload = {
        "topic": "tickers.BTCUSDT",
        "type": "snapshot",
        "ts": NOW - 100,
        "cs": 10,
        "data": {"symbol": "BTCUSDT", "lastPrice": "64000.5"},
    }
    payload.update(changes)
    return payload


def test_valid_quote_requires_confirmed_connection() -> None:
    state = BybitWebSocketState()
    quote = state.ingest_ticker(_ticker(), received_at_ms=NOW)
    assert quote.price == 64000.5
    with pytest.raises(RuntimeError):
        state.current_quote("BTCUSDT", now_ms=NOW)
    state.mark_connected()
    assert state.current_quote("BTCUSDT", now_ms=NOW).symbol == "BTCUSDT"


def test_non_finite_prices_are_blocked() -> None:
    state = BybitWebSocketState()
    for value in ("nan", "inf", "-inf"):
        payload = _ticker(data={"symbol": "BTCUSDT", "lastPrice": value})
        with pytest.raises(ValueError):
            state.ingest_ticker(payload, received_at_ms=NOW)


def test_symbol_mismatch_is_blocked() -> None:
    state = BybitWebSocketState()
    payload = _ticker(data={"symbol": "ETHUSDT", "lastPrice": "64000"})
    with pytest.raises(ValueError, match="does not match"):
        state.ingest_ticker(payload, received_at_ms=NOW)


def test_stale_future_and_invalid_receipt_times_fail_closed(monkeypatch) -> None:
    state = BybitWebSocketState()
    with pytest.raises(ValueError):
        state.ingest_ticker(_ticker(), received_at_ms=0)

    monkeypatch.setattr("exchange_connector.bybit_websocket_state.time.time", lambda: NOW / 1000)
    with pytest.raises(ValueError, match="received_at_ms"):
        state.ingest_ticker(_ticker(), received_at_ms=NOW + state.max_future_skew_ms + 1)

    stale = _ticker(ts=NOW - state.max_exchange_lag_ms - 1)
    with pytest.raises(ValueError, match="too late"):
        state.ingest_ticker(stale, received_at_ms=NOW)

    future = _ticker(ts=NOW + state.max_future_skew_ms + 1)
    with pytest.raises(ValueError, match="future"):
        state.ingest_ticker(future, received_at_ms=NOW)


def test_sequence_must_advance() -> None:
    state = BybitWebSocketState()
    state.ingest_ticker(_ticker(cs=10), received_at_ms=NOW)
    with pytest.raises(ValueError, match="sequence"):
        state.ingest_ticker(_ticker(cs=10, ts=NOW), received_at_ms=NOW + 1)


def test_disconnect_and_staleness_make_cached_quote_unusable() -> None:
    state = BybitWebSocketState()
    state.ingest_ticker(_ticker(), received_at_ms=NOW)
    state.mark_connected()
    assert state.current_quote("BTCUSDT", now_ms=NOW).price > 0

    state.mark_disconnected("network timeout")
    with pytest.raises(RuntimeError, match="disconnected"):
        state.current_quote("BTCUSDT", now_ms=NOW)

    state.mark_connected()
    stale_now = NOW + int(state.max_age_seconds * 1000) + 1
    with pytest.raises(RuntimeError, match="stale"):
        state.current_quote("BTCUSDT", now_ms=stale_now)


def test_status_requires_all_quote_ages_to_be_valid() -> None:
    state = BybitWebSocketState()
    state.ingest_ticker(_ticker(), received_at_ms=NOW)
    state.mark_connected()
    assert state.status(now_ms=NOW)["verified"] is True
    assert state.status(now_ms=NOW + int(state.max_age_seconds * 1000) + 1)["verified"] is False


def test_reconnect_policy_has_hard_cap_and_reset(monkeypatch) -> None:
    monkeypatch.setenv("BYBIT_WS_RECONNECT_BASE_SECONDS", "999")
    monkeypatch.setenv("BYBIT_WS_RECONNECT_MAX_SECONDS", "999")
    policy = ReconnectPolicy()
    delays = [policy.next_delay(random_value=1.0) for _ in range(10)]
    assert all(math.isfinite(value) and 0 < value <= 60 for value in delays)
    policy.reset()
    assert policy.next_delay(random_value=0.0) == policy.base_seconds
