from __future__ import annotations

import json

from autonomous_trading.testnet_bridge import AutonomousTestnetBridge
from autonomous_trading.trade_identity import paper_trade_id

TRADE = {
    "time": "2026-07-11T00:00:00+00:00",
    "symbol": "BTCUSDT",
    "side": "BUY",
    "quantity": 0.01,
    "price": 100.0,
    "fee": 0.001,
    "net_pnl": None,
    "reason": "momentum",
    "source": "bybit_websocket",
    "verified_market_data": True,
}


class Assessment:
    eligible_stage = 3

    def to_dict(self):
        return {"eligible_stage": 3}


class Stages:
    def assess(self):
        return Assessment()


class Result:
    order_id = "oid"

    def __init__(self, candidate_id):
        self.candidate_id = candidate_id

    def to_dict(self):
        return {
            "status": "accepted",
            "mode": "sandbox",
            "category": "spot",
            "symbol": "BTCUSDT",
            "side": "BUY",
            "quantity": 0.01,
            "order_id": "oid",
            "order_link_id": "sai_x",
            "candidate_id": self.candidate_id,
        }


class FakeClient:
    mode = "sandbox"
    max_notional = 25

    def __init__(self):
        self.calls = []

    def status(self):
        return {}

    def place_market_order(self, **kwargs):
        self.calls.append(kwargs)
        return Result(kwargs["candidate_id"])


def bridge(tmp_path, monkeypatch, trades, state=None):
    paper = tmp_path / "paper.json"
    bridge_state = tmp_path / "bridge.json"
    journal = tmp_path / "journal.json"
    paper.write_text(json.dumps({"trades": trades}), encoding="utf-8")
    if state is not None:
        bridge_state.write_text(json.dumps(state), encoding="utf-8")
    monkeypatch.setenv("AUTONOMOUS_PAPER_STATE_FILE", str(paper))
    monkeypatch.setenv("TESTNET_BRIDGE_STATE_FILE", str(bridge_state))
    monkeypatch.setenv("EXECUTION_JOURNAL_FILE", str(journal))
    client = FakeClient()
    instance = AutonomousTestnetBridge(client)
    instance.stages = Stages()
    return instance, client, paper


def test_paper_trade_identity_is_stable_and_existing_id_is_preserved():
    assert paper_trade_id(TRADE) == paper_trade_id(dict(TRADE))
    explicit = dict(TRADE, trade_id="paper_abcdef")
    assert paper_trade_id(explicit) == "paper_abcdef"


def test_bridge_processes_new_trade_after_fixed_length_compaction(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTONOMOUS_TESTNET_ENABLED", "0")
    instance, client, paper = bridge(tmp_path, monkeypatch, [dict(TRADE)])
    instance.tick()
    assert client.calls == []

    new_trade = dict(TRADE, time="2026-07-11T00:01:00+00:00", price=101.0)
    paper.write_text(json.dumps({"trades": [new_trade]}), encoding="utf-8")
    monkeypatch.setenv("AUTONOMOUS_TESTNET_ENABLED", "1")
    instance.tick()
    assert len(client.calls) == 1
    assert client.calls[0]["candidate_id"] == paper_trade_id(new_trade)
    assert instance._state["processed_trade_count"] == 2


def test_old_count_state_migrates_to_trade_ids(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTONOMOUS_TESTNET_ENABLED", "1")
    instance, client, _ = bridge(
        tmp_path,
        monkeypatch,
        [dict(TRADE)],
        {"processed_trade_count": 1, "last_status": "old"},
    )
    instance.tick()
    assert client.calls == []
    assert instance._state["processed_trade_ids"] == [paper_trade_id(TRADE)]
