from __future__ import annotations

import json

import httpx
import pytest

from autonomous_trading.stage_controller import StageController
from exchange_connector.bybit_execution import BybitExecutionClient


def _testnet_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BYBIT_TESTNET_API_KEY", "key")
    monkeypatch.setenv("BYBIT_TESTNET_API_SECRET", "secret")
    monkeypatch.setenv("BYBIT_ALLOW_LEGACY_EXCHANGE_CREDENTIALS", "0")
    monkeypatch.delenv("EXCHANGE_API_KEY", raising=False)
    monkeypatch.delenv("EXCHANGE_API_SECRET", raising=False)


def test_testnet_order_requires_explicit_unlock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXCHANGE_MODE", "sandbox")
    _testnet_credentials(monkeypatch)
    monkeypatch.delenv("TESTNET_EXECUTION_ENABLED", raising=False)
    monkeypatch.setenv("EXECUTION_KILL_SWITCH", "0")
    client = BybitExecutionClient()
    with pytest.raises(RuntimeError, match="Testnet execution is locked"):
        client.place_market_order(symbol="BTCUSDT", side="BUY", quantity=0.001, reference_price=50000)


def test_live_requires_all_independent_gates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXCHANGE_MODE", "live")
    monkeypatch.setenv("BYBIT_MAINNET_API_KEY", "key")
    monkeypatch.setenv("BYBIT_MAINNET_API_SECRET", "secret")
    monkeypatch.setenv("BYBIT_ALLOW_LEGACY_EXCHANGE_CREDENTIALS", "0")
    monkeypatch.setenv("EXCHANGE_LIVE_TRADING_ENABLED", "1")
    monkeypatch.setenv("LIVE_EXECUTION_MANUAL_UNLOCK", "1")
    monkeypatch.setenv("LIVE_EXECUTION_CONFIRMATION", "wrong")
    monkeypatch.setenv("EXECUTION_KILL_SWITCH", "0")
    client = BybitExecutionClient()
    assert client.status()["live_execution_enabled"] is False


def test_notional_cap_blocks_large_order(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXCHANGE_MODE", "sandbox")
    _testnet_credentials(monkeypatch)
    monkeypatch.setenv("TESTNET_EXECUTION_ENABLED", "1")
    monkeypatch.setenv("EXECUTION_KILL_SWITCH", "0")
    monkeypatch.setenv("EXECUTION_MAX_NOTIONAL_USDT", "25")
    client = BybitExecutionClient()
    with pytest.raises(RuntimeError, match="exceeds safety cap"):
        client.place_market_order(symbol="BTCUSDT", side="BUY", quantity=0.01, reference_price=50000)


def test_stage_controller_requires_evidence(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    state = {"equity": 10020, "trades": [{"side": "SELL", "net_pnl": 1.0}]}
    path = tmp_path / "state.json"
    path.write_text(json.dumps(state), encoding="utf-8")
    monkeypatch.setenv("AUTONOMOUS_TRADING_STAGE", "2")
    assessment = StageController(str(path)).assess()
    assert assessment.eligible_stage == 2
    assert assessment.blockers


def test_signed_testnet_order_returns_order_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXCHANGE_MODE", "sandbox")
    _testnet_credentials(monkeypatch)
    monkeypatch.setenv("TESTNET_EXECUTION_ENABLED", "1")
    monkeypatch.setenv("EXECUTION_KILL_SWITCH", "0")
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"retCode": 0, "result": {"orderId": "abc"}}))
    with httpx.Client(transport=transport) as http_client:
        result = BybitExecutionClient(client=http_client).place_market_order(
            symbol="BTCUSDT", side="BUY", quantity=0.0001, reference_price=50000
        )
    assert result.order_id == "abc"
    assert result.mode == "sandbox"
