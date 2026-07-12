from __future__ import annotations

import paper_activity_engine as engine_module
from paper_activity_engine import PaperActivityEngine
from persistence_paths import durable_data_path


def test_durable_data_path_uses_render_disk(monkeypatch, tmp_path):
    monkeypatch.delenv("VIRTUAL_ACCOUNT_STATE_FILE", raising=False)
    monkeypatch.setenv("RENDER_DISK_PATH", str(tmp_path))
    assert durable_data_path("VIRTUAL_ACCOUNT_STATE_FILE", "data/virtual_account_activity_state.json") == tmp_path / "virtual_account_activity_state.json"


def test_virtual_account_equity_uses_expected_open_edge_not_fee_only_loss(tmp_path, monkeypatch):
    monkeypatch.setenv("VIRTUAL_ACCOUNT_MAX_OPEN", "10")
    monkeypatch.setenv("VIRTUAL_MIN_EXPECTED_NET_USDT", "0")
    monkeypatch.setenv("VIRTUAL_MIN_EDGE_TO_FEE_RATIO", "0")
    monkeypatch.setenv("VIRTUAL_MIN_CONFIDENCE", "0")
    monkeypatch.setattr(
        engine_module,
        "trade_gate",
        lambda payload: {
            "can_trade_demo": True,
            "can_trade_virtual": True,
            "ai_consensus_score": 100,
            "decision": "VIRTUAL_ALLOWED",
            "blockers": [],
            "warnings": [],
        },
    )
    engine = PaperActivityEngine(tmp_path / "state.json")
    opened = []
    now = 1_700_000_000
    for index in range(12):
        result = engine.tick(force=True, now=now + index * 60)
        if result["status"] == "ok":
            opened.append(result["trade"])
    state = engine.state()
    summary = state["summary"]
    assert opened
    assert summary["expected_open_net_pnl"] > 0
    assert summary["equity"] >= summary["cash"]
    assert summary["equity"] > 10_000 - summary["total_fees"]
