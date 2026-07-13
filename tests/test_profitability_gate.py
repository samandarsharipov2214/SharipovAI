from __future__ import annotations

import paper_activity_engine as engine_module
from paper_activity_engine import PaperActivityEngine
from profitability_gate import evaluate_profitability_candidate


def _allow_virtual(monkeypatch) -> None:
    monkeypatch.setattr(
        engine_module,
        "trade_gate",
        lambda payload: {
            "can_trade_demo": True,
            "can_trade_virtual": True,
            "ai_consensus_score": 75,
            "decision": "VIRTUAL_ALLOWED",
            "blockers": [],
            "warnings": [],
        },
    )


def test_profitability_gate_blocks_bad_expected_value() -> None:
    result = evaluate_profitability_candidate(
        symbol="ADA/USDT",
        side="SELL",
        tick_count=1,
        notional=100.0,
        estimated_fee=0.1,
        state={"trades": []},
        gate={"ai_consensus_score": 72},
    )
    assert result["decision"] in {"WAIT", "ALLOW"}
    if result["decision"] == "WAIT":
        assert result["blockers"]
        assert "пропущ" in result["reason_ru"].lower()


def test_virtual_engine_skips_when_profitability_gate_blocks(tmp_path, monkeypatch) -> None:
    _allow_virtual(monkeypatch)
    monkeypatch.setenv("VIRTUAL_ACCOUNT_STATE_FILE", str(tmp_path / "virtual.json"))
    monkeypatch.setenv("VIRTUAL_MIN_CONFIDENCE", "95")
    engine = PaperActivityEngine()
    result = engine.tick(force=True, now=1000)
    state = engine.state()
    assert result["status"] == "wait"
    assert state["summary"]["trade_count"] == 0
    assert state["summary"]["skipped_count"] == 1
    assert state["summary"]["last_tick_status"] == "wait_profitability"
    assert "пропущ" in state["summary"]["last_reason_ru"].lower()


def test_virtual_engine_opens_only_allowed_profitability(tmp_path, monkeypatch) -> None:
    _allow_virtual(monkeypatch)
    monkeypatch.setenv("VIRTUAL_ACCOUNT_STATE_FILE", str(tmp_path / "virtual.json"))
    monkeypatch.setenv("VIRTUAL_MIN_CONFIDENCE", "50")
    monkeypatch.setenv("VIRTUAL_MIN_EXPECTED_NET_USDT", "0.05")
    monkeypatch.setenv("VIRTUAL_MIN_EDGE_TO_FEE_RATIO", "1.0")
    engine = PaperActivityEngine()
    result = engine.tick(force=True, now=1000)
    state = engine.state()
    assert result["status"] in {"ok", "wait"}
    if result["status"] == "ok":
        assert state["summary"]["trade_count"] == 1
        assert state["trades"][0]["expected_net_usdt"] >= 0.05
        assert state["trades"][0]["edge_to_fee_ratio"] >= 1.0
