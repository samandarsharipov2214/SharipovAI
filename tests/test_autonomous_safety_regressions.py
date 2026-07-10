from __future__ import annotations

import json
from dataclasses import dataclass

from autonomous_trading.loop import AutonomousPaperLoop
from autonomous_trading.testnet_bridge import AutonomousTestnetBridge


@dataclass
class _Quote:
    symbol: str = "BTCUSDT"
    price: float = 110.0
    change_24h_percent: float | None = 1.0


class _Stream:
    symbols = ["BTCUSDT"]

    def snapshot(self):
        return {
            "verified": True,
            "status": "live",
            "connected": True,
            "age_seconds": 0.1,
            "last_error": "",
            "quotes": {"BTCUSDT": {"price": 110.0}},
        }

    def quote(self, symbol: str):
        return _Quote(symbol=symbol)


class _NeverExecuteClient:
    mode = "sandbox"
    max_notional = 25.0

    def status(self):
        return {"testnet_execution_enabled": False}

    def place_market_order(self, **kwargs):  # pragma: no cover - must never be called
        raise AssertionError("historical trades must not be replayed")


def test_paper_tick_persists_mark_to_market_equity(tmp_path, monkeypatch):
    state_file = tmp_path / "paper.json"
    monkeypatch.setenv("AUTONOMOUS_PAPER_STATE_FILE", str(state_file))
    loop = AutonomousPaperLoop(_Stream())
    loop._state["cash"] = 900.0
    loop._state["positions"] = {
        "BTCUSDT": {
            "quantity": 1.0,
            "entry_price": 100.0,
            "opened_at": loop._now(),
            "entry_fee": 0.1,
            "reason": "test",
        }
    }

    loop.tick()

    persisted = json.loads(state_file.read_text(encoding="utf-8"))
    assert persisted["equity"] == 1010.0
    assert persisted["unrealized_pnl"] == 10.0


def test_disabled_bridge_baselines_existing_history(tmp_path, monkeypatch):
    paper_file = tmp_path / "paper.json"
    bridge_file = tmp_path / "bridge.json"
    journal_file = tmp_path / "journal.json"
    paper_file.write_text(
        json.dumps({"trades": [{"symbol": "BTCUSDT", "side": "BUY", "quantity": 0.01, "price": 100.0}]}),
        encoding="utf-8",
    )
    monkeypatch.setenv("AUTONOMOUS_PAPER_STATE_FILE", str(paper_file))
    monkeypatch.setenv("TESTNET_BRIDGE_STATE_FILE", str(bridge_file))
    monkeypatch.setenv("EXECUTION_JOURNAL_FILE", str(journal_file))
    monkeypatch.setenv("AUTONOMOUS_TESTNET_ENABLED", "0")
    monkeypatch.delenv("TESTNET_REPLAY_HISTORICAL_TRADES", raising=False)

    bridge = AutonomousTestnetBridge(_NeverExecuteClient())
    bridge.tick()

    assert bridge.snapshot()["processed_trade_count"] == 1
    assert bridge.snapshot()["last_status"] == "disabled"
