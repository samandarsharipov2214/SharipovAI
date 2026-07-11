from __future__ import annotations

import pytest

from exchange_connector.bybit_credentials import account_credentials, execution_credentials, private_stream_credentials


def _clear(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "BYBIT_READONLY_API_KEY", "BYBIT_READONLY_API_SECRET",
        "BYBIT_TESTNET_API_KEY", "BYBIT_TESTNET_API_SECRET",
        "BYBIT_MAINNET_API_KEY", "BYBIT_MAINNET_API_SECRET",
        "EXCHANGE_API_KEY", "EXCHANGE_API_SECRET",
        "BYBIT_ALLOW_LEGACY_EXCHANGE_CREDENTIALS",
    ):
        monkeypatch.delenv(name, raising=False)


def test_profiles_are_separate(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("BYBIT_READONLY_API_KEY", "read")
    monkeypatch.setenv("BYBIT_READONLY_API_SECRET", "read-secret")
    monkeypatch.setenv("BYBIT_TESTNET_API_KEY", "test")
    monkeypatch.setenv("BYBIT_TESTNET_API_SECRET", "test-secret")
    monkeypatch.setenv("BYBIT_MAINNET_API_KEY", "live")
    monkeypatch.setenv("BYBIT_MAINNET_API_SECRET", "live-secret")
    assert account_credentials().api_key == "read"
    assert execution_credentials("sandbox").api_key == "test"
    assert execution_credentials("live").api_key == "live"
    assert private_stream_credentials("mainnet").profile == "live_read_only"


def test_legacy_credentials_are_blocked_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("EXCHANGE_API_KEY", "legacy")
    monkeypatch.setenv("EXCHANGE_API_SECRET", "legacy-secret")
    assert account_credentials().configured is False
    assert execution_credentials("sandbox").configured is False


def test_legacy_migration_requires_explicit_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("EXCHANGE_API_KEY", "legacy")
    monkeypatch.setenv("EXCHANGE_API_SECRET", "legacy-secret")
    monkeypatch.setenv("BYBIT_ALLOW_LEGACY_EXCHANGE_CREDENTIALS", "1")
    assert execution_credentials("sandbox").profile.endswith("_legacy")


def test_partial_pair_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("BYBIT_TESTNET_API_KEY", "only-key")
    with pytest.raises(RuntimeError):
        execution_credentials("sandbox")
