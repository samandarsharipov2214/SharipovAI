from __future__ import annotations

import math

import pytest

from exchange_connector.bybit_account import BybitAccountClient, _number
from exchange_connector.bybit_execution import BybitExecutionClient, _positive


def test_execution_client_uses_testnet_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXCHANGE_MODE", "sandbox")
    monkeypatch.setenv("EXCHANGE_BASE_URL", "https://api-testnet.bybit.com")
    monkeypatch.setenv("BYBIT_TESTNET_API_KEY", "test-key")
    monkeypatch.setenv("BYBIT_TESTNET_API_SECRET", "test-secret")
    monkeypatch.setenv("EXECUTION_KILL_SWITCH", "1")
    client = BybitExecutionClient()
    assert client.status()["credential_profile"] == "testnet_execution"
    assert client.status()["live_execution_enabled"] is False


def test_account_client_does_not_reuse_testnet_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BYBIT_TESTNET_API_KEY", "test-key")
    monkeypatch.setenv("BYBIT_TESTNET_API_SECRET", "test-secret")
    monkeypatch.delenv("BYBIT_READONLY_API_KEY", raising=False)
    monkeypatch.delenv("BYBIT_READONLY_API_SECRET", raising=False)
    client = BybitAccountClient()
    assert client.status()["credentials_configured"] is False
    assert client.status()["credential_profile"] == "live_read_only"


def test_non_finite_numbers_are_blocked() -> None:
    with pytest.raises(ValueError):
        _positive(float("nan"), "quantity")
    with pytest.raises(ValueError):
        _positive(float("inf"), "quantity")
    assert _number(float("nan")) == 0.0
    assert _number(float("inf")) == 0.0
