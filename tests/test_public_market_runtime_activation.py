from __future__ import annotations

from dashboard.market_data_api import _configure_public_stream_feature


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
