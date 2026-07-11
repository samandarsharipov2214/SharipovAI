from __future__ import annotations

import json

import httpx

from exchange_connector.bybit_account import BybitAccountClient


def _response(payload: dict) -> httpx.Response:
    return httpx.Response(200, json=payload, request=httpx.Request("GET", "https://api.bybit.eu/test"))


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def get(self, url: str, params=None, headers=None):
        self.calls.append(url)
        if "wallet-balance" in url:
            return _response({"retCode": 0, "result": {"list": [{"totalEquity": "100", "totalWalletBalance": "95", "totalAvailableBalance": "80", "totalPerpUPL": "5", "coin": [{"coin": "USDT", "equity": "100", "walletBalance": "95", "availableToWithdraw": "80", "unrealisedPnl": "5", "usdValue": "100"}]}]}})
        if "position/list" in url:
            return _response({"retCode": 0, "result": {"list": [{"symbol": "BTCUSDT", "side": "Buy", "size": "0.01", "avgPrice": "60000", "markPrice": "61000", "unrealisedPnl": "10", "leverage": "2", "liqPrice": "30000"}]}})
        return _response({"retCode": 0, "result": {"list": []}})


def test_fetch_snapshot_is_read_only_and_normalized(monkeypatch, tmp_path):
    monkeypatch.setenv("EXCHANGE_API_KEY", "key")
    monkeypatch.setenv("EXCHANGE_API_SECRET", "secret")
    monkeypatch.setenv("BYBIT_ACCOUNT_BASE_URL", "https://api.bybit.eu")
    monkeypatch.setenv("BYBIT_ACCOUNT_STATE_FILE", str(tmp_path / "account.json"))
    fake = FakeClient()
    client = BybitAccountClient(client=fake)

    snapshot = client.fetch_snapshot()
    path = client.save_snapshot(snapshot)

    assert snapshot.status == "connected"
    assert snapshot.total_equity == 100
    assert snapshot.coins[0]["coin"] == "USDT"
    assert snapshot.positions[0]["symbol"] == "BTCUSDT"
    assert all("/v5/order/create" not in call for call in fake.calls)
    assert json.loads(path.read_text())["source"] == "bybit_private_api_v5"


def test_missing_credentials_are_blocked(monkeypatch):
    monkeypatch.delenv("EXCHANGE_API_KEY", raising=False)
    monkeypatch.delenv("EXCHANGE_API_SECRET", raising=False)
    client = BybitAccountClient(client=FakeClient())
    try:
        client.fetch_snapshot()
    except RuntimeError as exc:
        assert "credentials" in str(exc).lower()
    else:
        raise AssertionError("missing credentials must be blocked")
