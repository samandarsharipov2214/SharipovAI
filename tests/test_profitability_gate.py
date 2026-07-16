from __future__ import annotations

from paper_activity_engine import PaperActivityEngine
from profitability_gate import evaluate_profitability_candidate


def verified_gate() -> dict[str, object]:
    return {
        "market_data_verified": True,
        "exchange_ok": True,
        "strategy_approved": True,
        "live_requested": False,
        "ai_consensus_score": 90,
        "news_credibility_percent": 90,
        "news_shock_score": 0,
        "risk_per_trade_percent": 0.5,
        "volatility_percent": 3.0,
        "trend_score": 0.8,
        "spread_percent": 0.03,
        "liquidity_score": 90,
    }


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
    assert result["promotion_eligible"] is False
    assert result["learning_eligible"] is False
    assert result["evidence_class"] == "synthetic_simulation"
    if result["decision"] == "WAIT":
        assert result["blockers"]
        assert result["reason_ru"].strip()


def test_virtual_engine_skips_when_profitability_gate_blocks(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("VIRTUAL_ACCOUNT_STATE_FILE", str(tmp_path / "virtual.json"))
    monkeypatch.setenv("VIRTUAL_MIN_CONFIDENCE", "95")
    engine = PaperActivityEngine()

    result = engine.tick(force=True, now=1000, gate_payload=verified_gate())
    state = engine.state()

    assert result["status"] == "wait"
    assert state["summary"]["trade_count"] == 0
    assert state["summary"]["skipped_count"] == 1
    assert state["summary"]["last_tick_status"] == "wait_profitability"
    assert state["summary"]["last_reason"] == "profitability_gate_wait"
    assert state["summary"]["last_reason_ru"].strip()
    assert result["profitability"]["decision"] == "WAIT"
    assert result["profitability"]["blockers"]


def test_virtual_engine_opens_only_allowed_profitability(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("VIRTUAL_ACCOUNT_STATE_FILE", str(tmp_path / "virtual.json"))
    monkeypatch.setenv("VIRTUAL_MIN_CONFIDENCE", "50")
    monkeypatch.setenv("VIRTUAL_MIN_EXPECTED_NET_USDT", "0.05")
    monkeypatch.setenv("VIRTUAL_MIN_EDGE_TO_FEE_RATIO", "1.0")
    engine = PaperActivityEngine()

    result = engine.tick(force=True, now=1000, gate_payload=verified_gate())
    state = engine.state()

    assert result["status"] in {"ok", "wait"}
    assert result["status"] != "blocked"
    if result["status"] == "ok":
        assert state["summary"]["trade_count"] == 1
        assert state["trades"][0]["expected_net_usdt"] >= 0.05
        assert state["trades"][0]["edge_to_fee_ratio"] >= 1.0
        assert state["trades"][0]["real_order_placed"] is False
