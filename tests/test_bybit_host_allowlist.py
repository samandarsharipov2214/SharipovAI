from __future__ import annotations

import pytest

from exchange_connector.bybit_account import BybitAccountClient
from exchange_connector.bybit_execution import BybitExecutionClient
from exchange_connector.bybit_hosts import validate_bybit_base_url


def test_live_and_testnet_official_hosts_are_accepted() -> None:
    assert validate_bybit_base_url("https://api.bybit.com/", environment="live") == "https://api.bybit.com"
    assert validate_bybit_base_url("https://api.bybit.eu", environment="live_read_only") == "https://api.bybit.eu"
    assert validate_bybit_base_url("https://api-testnet.bybit.com", environment="sandbox") == "https://api-testnet.bybit.com"


@pytest.mark.parametrize(
    "url",
    [
        "http://api.bybit.com",
        "https://api.bybit.com.evil.example",
        "https://user:pass@api.bybit.com",
        "https://api.bybit.com:8443",
        "https://api.bybit.com/v5",
        "https://api.bybit.com?next=evil",
    ],
)
def test_malformed_or_unapproved_hosts_are_blocked(url: str) -> None:
    with pytest.raises(ValueError):
        validate_bybit_base_url(url, environment="live")


def test_environment_mismatch_is_blocked() -> None:
    with pytest.raises(ValueError):
        validate_bybit_base_url("https://api.bybit.com", environment="sandbox")
    with pytest.raises(ValueError):
        validate_bybit_base_url("https://api-testnet.bybit.com", environment="live")


def test_execution_client_fails_before_using_unapproved_host(monkeypatch) -> None:
    monkeypatch.setenv("EXCHANGE_MODE", "sandbox")
    monkeypatch.setenv("EXCHANGE_BASE_URL", "https://attacker.example")
    with pytest.raises(ValueError):
        BybitExecutionClient()


def test_account_client_rejects_explicit_unapproved_host(monkeypatch) -> None:
    monkeypatch.setenv("BYBIT_ACCOUNT_BASE_URL", "https://attacker.example")
    client = BybitAccountClient()
    with pytest.raises(ValueError):
        client.status()
