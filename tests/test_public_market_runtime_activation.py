from __future__ import annotations

from dashboard.market_data_api import _configure_public_stream_feature
from exchange_connector.bybit_websocket_worker import BybitWebSocketWorker


def test_market_stream_switch_activates_only_guarded_public_feature(monkeypatch) -> None:
    monkeypatch.delenv("FEATURE_BYBIT_WEBSOCKET", raising=False)
    monkeypatch.setenv("MARKET_STREAM_ENABLED", "1")
    _configure_public_stream_feature()
    assert __import__("os").environ["FEATURE_BYBIT_WEBSOCKET"] == "1"


def test_explicit_public_feature_off_is_never_overridden(monkeypatch) -> None:
    monkeypatch.setenv("FEATURE_BYBIT_WEBSOCKET", "0")
    monkeypatch.setenv("MARKET_STREAM_ENABLED", "1")
    _configure_public_stream_feature()
    assert __import__("os").environ["FEATURE_BYBIT_WEBSOCKET"] == "0"


def test_absent_market_switch_keeps_public_feature_off(monkeypatch) -> None:
    monkeypatch.delenv("FEATURE_BYBIT_WEBSOCKET", raising=False)
    monkeypatch.delenv("MARKET_STREAM_ENABLED", raising=False)
    _configure_public_stream_feature()
    assert "FEATURE_BYBIT_WEBSOCKET" not in __import__("os").environ


def test_worker_uses_existing_market_stream_symbols(monkeypatch) -> None:
    monkeypatch.delenv("BYBIT_WS_SYMBOLS", raising=False)
    monkeypatch.setenv("MARKET_STREAM_SYMBOLS", "BTCUSDT,ETHUSDT,SOLUSDT")

    worker = BybitWebSocketWorker(state=object())

    assert worker.symbols == ("BTCUSDT", "ETHUSDT", "SOLUSDT")


def test_explicit_worker_symbols_override_legacy_setting(monkeypatch) -> None:
    monkeypatch.setenv("BYBIT_WS_SYMBOLS", "BTCUSDT,XRPUSDT")
    monkeypatch.setenv("MARKET_STREAM_SYMBOLS", "BTCUSDT,ETHUSDT,SOLUSDT")

    worker = BybitWebSocketWorker(state=object())

    assert worker.symbols == ("BTCUSDT", "XRPUSDT")
