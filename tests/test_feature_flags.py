from __future__ import annotations

from config.feature_flags import FEATURES, feature_snapshot, is_feature_enabled


def test_all_trading_features_are_disabled_by_default(monkeypatch):
    for feature in FEATURES.values():
        monkeypatch.delenv(feature.name, raising=False)

    snapshot = feature_snapshot()

    assert snapshot
    assert all(enabled is False for enabled in snapshot.values())
    assert snapshot["bybit_live_execution"] is False
    assert snapshot["bybit_testnet_execution"] is False


def test_known_feature_requires_explicit_truthy_value(monkeypatch):
    flag = FEATURES["bybit_preview_engine"]
    monkeypatch.setenv(flag.name, "true")
    assert is_feature_enabled("bybit_preview_engine") is True

    monkeypatch.setenv(flag.name, "false")
    assert is_feature_enabled("bybit_preview_engine") is False


def test_unknown_feature_fails_closed():
    assert is_feature_enabled("does_not_exist") is False
