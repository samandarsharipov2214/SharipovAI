from __future__ import annotations

import json

from autonomous_trading.testnet_bridge import AutonomousTestnetBridge

TRADE = {
    "time": "2026-07-11T00:00:00+00:00",
    "symbol": "BTCUSDT",
    "side": "BUY",
    "quantity": 0.01,
    "price": 100.0,
    "reason": "momentum",
    "source": "bybit_websocket",
}


class Client:
    mode = "sandbox"
    max_notional = 25

    def __init__(self):
        self.calls = []

    def status(self):
        return {}

    def place_market_order(self, **kwargs):
        self.calls.append(kwargs)
        raise AssertionError("corrupt state must block execution")


def test_corrupt_bridge_state_blocks_without_replaying(tmp_path, monkeypatch):
    paper = tmp_path / "paper.json"
    state = tmp_path / "bridge.json"
    journal = tmp_path / "journal.json"
    paper.write_text(json.dumps({"trades": [TRADE]}), encoding="utf-8")
    state.write_text("broken", encoding="utf-8")
    monkeypatch.setenv("AUTONOMOUS_PAPER_STATE_FILE", str(paper))
    monkeypatch.setenv("TESTNET_BRIDGE_STATE_FILE", str(state))
    monkeypatch.setenv("EXECUTION_JOURNAL_FILE", str(journal))
    monkeypatch.setenv("AUTONOMOUS_TESTNET_ENABLED", "1")

    client = Client()
    bridge = AutonomousTestnetBridge(client)
    bridge.tick()
    assert client.calls == []
    assert bridge._state["last_status"] == "blocked_corrupt_state"
    assert state.read_text(encoding="utf-8") == "broken"
