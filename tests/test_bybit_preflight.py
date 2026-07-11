from __future__ import annotations

import httpx
import pytest

from exchange_connector.bybit_preflight import BybitPreflightError, run_bybit_preflight


class FakeHTTP:
    def __init__(self, server_time_ms: int) -> None:
        self.server_time_ms = server_time_ms

    def get(self, url: str, headers=None):
        request = httpx.Request("GET", url)
        return httpx.Response(
            200,
            json={
                "retCode": 0,
                "retMsg": "OK",
                "result": {"timeSecond": str(self.server_time_ms // 1000)},
                "time": self.server_time_ms,
            },
            request=request,
        )


class FakeAccountClient:
    def __init__(self, server_time_ms: int, key_info: dict) -> None:
        self.api_key = "key"
        self.api_secret = "secret"
        self.timeout = 1.0
        self._client = FakeHTTP(server_time_ms)
        self.key_info = key_info

    def _candidate_base_urls(self):
        return ["https://api.bybit.eu"]

    def _private_get(self, base_url: str, path: str, params: dict):
        assert path == "/v5/user/query-api"
        return {"retCode": 0, "result": self.key_info}


def _safe_key_info(**overrides):
    data = {
        "readOnly": 1,
        "permissions": {"Wallet": []},
        "uta": 1,
        "isMaster": False,
        "ips": ["203.0.113.10"],
        "deadlineDay": 30,
        "type": 1,
        "kycRegion": "DEU",
    }
    data.update(overrides)
    return data


def test_safe_read_only_key_passes(monkeypatch):
    now_ms = 1_800_000_000_000
    monkeypatch.setattr("exchange_connector.bybit_preflight.time.time", lambda: now_ms / 1000)
    result = run_bybit_preflight(FakeAccountClient(now_ms - 250, _safe_key_info()))

    assert result["status"] == "ok"
    assert result["read_only"] is True
    assert result["clock_skew_ms"] == 250
    assert result["is_master"] is False


def test_write_capable_key_is_rejected(monkeypatch):
    now_ms = 1_800_000_000_000
    monkeypatch.setattr("exchange_connector.bybit_preflight.time.time", lambda: now_ms / 1000)

    with pytest.raises(BybitPreflightError, match="read-only"):
        run_bybit_preflight(FakeAccountClient(now_ms, _safe_key_info(readOnly=0)))


def test_withdraw_permission_is_rejected(monkeypatch):
    now_ms = 1_800_000_000_000
    monkeypatch.setattr("exchange_connector.bybit_preflight.time.time", lambda: now_ms / 1000)
    key = _safe_key_info(permissions={"Wallet": ["Withdraw"]})

    with pytest.raises(BybitPreflightError, match="withdrawal"):
        run_bybit_preflight(FakeAccountClient(now_ms, key))


def test_excessive_clock_skew_is_rejected(monkeypatch):
    now_ms = 1_800_000_000_000
    monkeypatch.setattr("exchange_connector.bybit_preflight.time.time", lambda: now_ms / 1000)
    monkeypatch.setenv("BYBIT_MAX_CLOCK_SKEW_MS", "1000")

    with pytest.raises(BybitPreflightError, match="clock skew"):
        run_bybit_preflight(FakeAccountClient(now_ms - 5000, _safe_key_info()))


def test_subaccount_requirement_is_fail_closed(monkeypatch):
    now_ms = 1_800_000_000_000
    monkeypatch.setattr("exchange_connector.bybit_preflight.time.time", lambda: now_ms / 1000)
    monkeypatch.setenv("BYBIT_REQUIRE_SUBACCOUNT", "1")

    with pytest.raises(BybitPreflightError, match="subaccount"):
        run_bybit_preflight(FakeAccountClient(now_ms, _safe_key_info(isMaster=True)))
