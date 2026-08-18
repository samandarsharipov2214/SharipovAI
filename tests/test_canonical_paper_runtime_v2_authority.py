import time
from pathlib import Path

from autonomous_trading.canonical_runtime import CanonicalPaperDecisionRuntime
from decision_quality import CandidateEvidencePacket
from storage import ProjectDatabase
from trading_candidate import (
    MarketRegime,
    TradingCategory,
    TradingDecision,
    TradingEnvironment,
    TradingSide,
)


def _database(tmp_path: Path) -> ProjectDatabase:
    database = ProjectDatabase(f"sqlite:///{tmp_path / 'paper-v2.db'}")
    database.initialize()
    return database


def _payload(agent_id: str, action: str, *, confidence: float = 90.0):
    return {
        "agent_id": agent_id,
        "action": action,
        "confidence": confidence,
        "evidence_score": 90.0,
        "risk_score": 20.0,
        "rationale": f"{agent_id}:{action}",
        "verified_market_data": True,
        "evidence_class": "verified_market",
        "learning_eligible": True,
        "evidence_eligible": True,
        "reputation_eligible": True,
    }


def _prepare_evidence(database: ProjectDatabase, decision_id: str) -> CandidateEvidencePacket:
    now_ms = int(time.time() * 1000)
    risk_id = f"risk-{decision_id}"
    portfolio_id = f"portfolio-{decision_id}"
    database.put_json(
        "risk_assessments",
        risk_id,
        {
            "decision_id": decision_id,
            "risk_score": 20.0,
            "blocks": [],
            "assessment": {
                "allowed_virtual": True,
                "blockers": [],
                "hard_blocks": [],
            },
        },
    )
    database.put_json(
        "portfolio_snapshots",
        portfolio_id,
        {
            "decision_id": decision_id,
            "cash": 10_000.0,
            "equity": 10_000.0,
            "open_symbols": [],
            "environment": "paper",
        },
    )
    return CandidateEvidencePacket(
        candidate_id=decision_id,
        symbol="BTCUSDT",
        category=TradingCategory.SPOT,
        side=TradingSide.SELL,  # legacy/provider side must not own V2 direction
        environment=TradingEnvironment.PAPER,
        market_timestamp_ms=now_ms - 200,
        received_timestamp_ms=now_ms - 100,
        reference_price=50_000.0,
        data_sources=("bybit", "bitget", "mexc"),
        market_regime=MarketRegime.TREND,
        signal_evidence=("market-evidence", risk_id, portfolio_id, "cost-1"),
        news_evidence=("news-1",),
        news_assessment_id="news-assessment-1",
        portfolio_snapshot_id=portfolio_id,
        cost_snapshot_id="cost-1",
        estimated_fees=0.1,
        estimated_slippage=0.05,
        risk_score=20.0,
        risk_blocks=(),
        expires_at_ms=now_ms + 8_000,
    )


def _assessment_time(packet: CandidateEvidencePacket) -> int:
    return packet.received_timestamp_ms + 100


def test_gc_v2_overrides_legacy_wait_and_provider_side_for_paper(tmp_path):
    database = _database(tmp_path)
    runtime = CanonicalPaperDecisionRuntime(database)
    decision_id = "paper-v2-buy-1"
    packet = _prepare_evidence(database, decision_id)
    payloads = (
        _payload("market_intelligence", "BUY"),
        _payload("news_intelligence", "BUY", confidence=85.0),
        _payload("portfolio_engine", "WAIT", confidence=100.0),
        _payload("risk_engine", "WAIT", confidence=100.0),
    )

    authorization = runtime.assess_entry(
        decision_id,
        payloads,
        packet,
        general_controller_decision=TradingDecision.WAIT,
        now_ms=_assessment_time(packet),
        regime="bull",
    )

    assert authorization.authorized is True
    assert authorization.decision is TradingDecision.ALLOW
    assert authorization.assessment.action == "BUY"
    assert authorization.candidate_result.candidate.side is TradingSide.BUY

    stored = database.get_json(runtime.v2_decision_namespace, decision_id)
    assert stored is not None
    value = stored["value"]
    assert value["paper_decision_owner"] == "general_controller_v2"
    assert value["legacy_provider_directive"] == "WAIT"
    assert value["legacy_provider_directive_authority"] is False
    assert value["source_packet_side"] == "Sell"
    assert value["candidate_side"] == "Buy"
    assert value["controller"]["final_intent"] == "BUY"
    assert value["paper_authority"] is True
    assert value["execution_authority"] is False


def test_v2_loss_does_not_become_realized_sell_or_reward_opposite_agents(tmp_path):
    database = _database(tmp_path)
    runtime = CanonicalPaperDecisionRuntime(database)
    decision_id = "paper-v2-loss-1"
    packet = _prepare_evidence(database, decision_id)
    payloads = (
        _payload("market_intelligence", "BUY"),
        _payload("news_intelligence", "BUY"),
        _payload("portfolio_engine", "WAIT"),
        _payload("risk_engine", "WAIT"),
    )
    authorization = runtime.assess_entry(
        decision_id,
        payloads,
        packet,
        general_controller_decision=TradingDecision.WAIT,
        now_ms=_assessment_time(packet),
        regime="bull",
    )
    assert authorization.authorized is True

    settlement = runtime.settle_exit(
        decision_id,
        net_pnl=-12.5,
        drawdown_contribution=12.5,
    )

    assert settlement["selected_action"] == "BUY"
    assert settlement["realized_outcome"] == "LOSS"
    assert settlement["reputation_recorded"] is False
    assert settlement["legacy_direction_labeling_disabled"] is True
    assert "realized_action" not in settlement
    assert settlement["learning_mode"] == "v2_role_aware_pending_replay"
