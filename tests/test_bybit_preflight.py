from __future__ import annotations

import time

import pytest

from exchange_connector.bybit_preflight import (
    BybitPreflightError,
    run_bybit_preflight,
    validate_official_bybit_base_url,
)


class _Response:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {
            "retCode": 0,
            "retMsg": "OK",
            "time": int(time.time() * 1000),
            "result": {"timeSecond": str(int(time.time()))},
        }


class _HttpClient:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def get(self, url: str):
        self.calls.append(url)
        return _Response()


class _Client:
    def __init__(self, candidates: list[str], key_info: dict | None = None) -> None:
        self.api_key = "configured"
        self.api_secret = "configured"
        self.timeout = 1.0
        self._client = _HttpClient()
        self._candidates = candidates
        self.key_info = key_info or {
            "readOnly": 1,
            "permissions": {"Wallet": ["AccountTransfer"]},
            "uta": 1,
            "isMaster": False,
            "ips": ["203.0.113.10"],
            "deadlineDay": 30,
            "type": 1,
            "kycRegion": "NLD",
        }

    def _candidate_base_urls(self) -> list[str]:
        return list(self._candidates)

    def _private_get(self, base_url: str, path: str, params: dict) -> dict:
        assert path == "/v5/user/query-api"
        return {"retCode": 0, "result": dict(self.key_info)}


def test_official_regional_hosts_are_allowed() -> None:
    assert validate_official_bybit_base_url("https://api.bybit.eu/") == "https://api.bybit.eu"
    assert validate_official_bybit_base_url("https://api.bybit.nl") == "https://api.bybit.nl"


@pytest.mark.parametrize(
    "url",
    [
        "http://api.bybit.com",
        "https://user@api.bybit.com",
        "https://api.bybit.com:8443",
        "https://api.bybit.com/private",
        "https://api.bybit.com?next=evil",
        "https://127.0.0.1",
        "https://localhost",
        "https://api-testnet.bybit.com",
        "https://evil.example",
    ],
)
def test_unsafe_or_non_mainnet_hosts_are_blocked(url: str) -> None:
    with pytest.raises(BybitPreflightError):
        validate_official_bybit_base_url(url)


def test_invalid_configured_host_blocks_before_network() -> None:
    client = _Client(["https://evil.example", "https://api.bybit.eu"])
    with pytest.raises(BybitPreflightError):
        run_bybit_preflight(client)
    assert client._client.calls == []


def test_read_only_key_passes_preflight(monkeypatch) -> None:
    monkeypatch.setenv("BYBIT_REQUIRE_SUBACCOUNT", "1")
    client = _Client(["https://api.bybit.eu"])
    result = run_bybit_preflight(client)
    assert result["status"] == "ok"
    assert result["base_url"] == "https://api.bybit.eu"
    assert result["read_only"] is True
    assert result["uta"] is True
    assert len(client._client.calls) == 1


def test_write_or_withdraw_key_is_blocked() -> None:
    write_client = _Client(["https://api.bybit.eu"], key_info={"readOnly": 0, "permissions": {}, "uta": 1})
    with pytest.raises(BybitPreflightError):
        run_bybit_preflight(write_client)

    withdraw_client = _Client(
        ["https://api.bybit.eu"],
        key_info={"readOnly": 1, "permissions": {"Wallet": ["Withdraw"]}, "uta": 1},
    )
    with pytest.raises(BybitPreflightError):
        run_bybit_preflight(withdraw_client)


def test_master_key_is_blocked_when_subaccount_is_required(monkeypatch) -> None:
    monkeypatch.setenv("BYBIT_REQUIRE_SUBACCOUNT", "1")
    client = _Client(
        ["https://api.bybit.eu"],
        key_info={"readOnly": 1, "permissions": {"Wallet": []}, "uta": 1, "isMaster": True},
    )
    with pytest.raises(BybitPreflightError):
        run_bybit_preflight(client)
