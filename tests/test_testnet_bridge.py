from __future__ import annotations

import json

from autonomous_trading.execution_journal import ExecutionJournal
from autonomous_trading.testnet_bridge import AutonomousTestnetBridge


def test_execution_journal_counts_verified_modes(tmp_path) -> None:
    journal = ExecutionJournal(str(tmp_path / "journal.json"))
    journal.append({"status": "accepted", "mode": "sandbox", "order_id": "t1"})
    journal.append({"status": "accepted", "mode": "live", "order_id": "l1"})
    journal.append({"status": "blocked_or_error", "mode": "sandbox"})
    summary = journal.summary()
    assert summary["verified_testnet_orders"] == 1
    assert summary["verified_live_orders"] == 1
    assert summary["accepted_orders"] == 2


def test_bridge_does_nothing_when_autonomous_testnet_disabled(tmp_path, monkeypatch) -> None:
    paper = tmp_path / "paper.json"
    paper.write_text(json.dumps({"trades": [{"side": "BUY", "symbol": "BTCUSDT", "quantity": 0.001, "price": 50000}]}))
    monkeypatch.setenv("AUTONOMOUS_PAPER_STATE_FILE", str(paper))
    monkeypatch.setenv("TESTNET_BRIDGE_STATE_FILE", str(tmp_path / "bridge.json"))
    monkeypatch.setenv("EXECUTION_JOURNAL_FILE", str(tmp_path / "journal.json"))
    monkeypatch.setenv("AUTONOMOUS_TESTNET_ENABLED", "0")
    bridge = AutonomousTestnetBridge()
    bridge.tick()
    snapshot = bridge.snapshot()
    assert snapshot["last_status"] == "disabled"
    assert snapshot["processed_trade_count"] == 0
    assert snapshot["journal"]["accepted_orders"] == 0


def test_stage_controller_uses_persisted_testnet_evidence(tmp_path, monkeypatch) -> None:
    paper = tmp_path / "paper.json"
    trades = []
    for index in range(30):
        trades.append({"side": "SELL", "net_pnl": 2.0 if index < 20 else -1.0})
    paper.write_text(json.dumps({"trades": trades, "equity": 10030}))
    journal = ExecutionJournal(str(tmp_path / "journal.json"))
    for index in range(50):
        journal.append({"status": "accepted", "mode": "sandbox", "order_id": str(index)})
    monkeypatch.setenv("AUTONOMOUS_PAPER_STATE_FILE", str(paper))
    from autonomous_trading.stage_controller import StageController
    assessment = StageController(str(paper), journal=journal).assess()
    assert assessment.metrics["verified_testnet_orders"] == 50.0
    assert assessment.eligible_stage == 3
    assert any("владельца" in item for item in assessment.blockers)
