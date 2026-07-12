from __future__ import annotations

import time

import pytest

from decision_quality import (
    CandidateBridgeError,
    CandidateEvidencePacket,
    DecisionCandidateBridge,
    DecisionQualityAssessment,
)
from storage import ProjectDatabase
from trading_candidate import (
    MarketRegime,
    TradingCategory,
    TradingDecision,
    TradingEnvironment,
    TradingSide,
)


def _database(tmp_path) -> ProjectDatabase:
    database = ProjectDatabase(f"sqlite:///{tmp_path / 'candidate-bridge.db'}")
    database.initialize()
    return database


def _assessment(
    decision_id: str,
    *,
    action: str = "BUY",
    confidence: float = 0.82,
    agreement: float = 0.80,
    blocked: bool = False,
) -> DecisionQualityAssessment:
    return DecisionQualityAssessment(
        decision_id=decision_id,
        action=action,
        confidence=confidence,
        agreement=agreement,
        quality_score=0.81,
        blocked=blocked,
        reason="verified council assessment",
        weighted_scores={"BUY": 1.0},
        dissenting_agents=(),
        rejected_agents=(),
        regime="bull",
        created_at="2026-07-12T00:00:00+00:00",
    )


def _packet(
    decision_id: str,
    *,
    side: TradingSide = TradingSide.BUY,
    environment: TradingEnvironment = TradingEnvironment.PAPER,
    market_regime: MarketRegime = MarketRegime.TREND,
    risk_blocks: tuple[str, ...] = (),
    market_age_ms: int = 100,
) -> tuple[CandidateEvidencePacket, int]:
    now_ms = int(time.time() * 1000)
    return (
        CandidateEvidencePacket(
            candidate_id=decision_id,
            symbol="BTCUSDT",
            category=TradingCategory.SPOT,
            side=side,
            environment=environment,
            market_timestamp_ms=now_ms - market_age_ms,
            received_timestamp_ms=now_ms - 50,
            reference_price=60_000.0,
            data_sources=("bybit_ws", "binance_ws", "coinbase_ws"),
            market_regime=market_regime,
            signal_evidence=("market-signal-1",),
            news_evidence=("news-1",),
            news_assessment_id="news-assessment-1",
            portfolio_snapshot_id="portfolio-1",
            cost_snapshot_id="cost-1",
            estimated_fees=0.1,
            estimated_slippage=0.05,
            risk_score=20.0,
            risk_blocks=risk_blocks,
            expires_at_ms=now_ms + 8_000,
        ),
        now_ms,
    )


def test_verified_assessment_can_create_paper_allow_candidate(tmp_path) -> None:
    database = _database(tmp_path)
    bridge = DecisionCandidateBridge(database)
    packet, now_ms = _packet("candidate-allow")

    result = bridge.build_and_store(
        _assessment("candidate-allow"),
        packet,
        general_controller_decision=TradingDecision.ALLOW,
        now_ms=now_ms,
    )

    assert result.candidate.decision is TradingDecision.ALLOW
    assert result.validation.valid is True
    assert result.downgrade_reasons == ()
    stored = database.get_json("trading_candidates", "candidate-allow")
    assert stored is not None
    assert stored["value"]["decision"] == "ALLOW"
    assert "decision-assessment-candidate-allow" in stored["value"]["signal_evidence"]


def test_general_controller_can_downgrade_but_not_upgrade(tmp_path) -> None:
    bridge = DecisionCandidateBridge(_database(tmp_path))
    packet, now_ms = _packet("candidate-wait")

    result = bridge.build_and_store(
        _assessment("candidate-wait"),
        packet,
        general_controller_decision=TradingDecision.WAIT,
        now_ms=now_ms,
    )

    assert result.candidate.decision is TradingDecision.WAIT
    assert result.validation.valid is True
    assert "general_controller_wait" in result.downgrade_reasons


def test_side_mismatch_is_blocked(tmp_path) -> None:
    bridge = DecisionCandidateBridge(_database(tmp_path))
    packet, now_ms = _packet("candidate-side-mismatch", side=TradingSide.SELL)

    result = bridge.build_and_store(
        _assessment("candidate-side-mismatch", action="BUY"),
        packet,
        general_controller_decision=TradingDecision.ALLOW,
        now_ms=now_ms,
    )

    assert result.candidate.decision is TradingDecision.BLOCK
    assert "decision_side_mismatch" in result.candidate.risk_blocks


def test_low_confidence_cannot_be_upgraded_to_allow(tmp_path) -> None:
    bridge = DecisionCandidateBridge(_database(tmp_path))
    packet, now_ms = _packet("candidate-low-confidence")

    result = bridge.build_and_store(
        _assessment("candidate-low-confidence", confidence=0.60, agreement=0.85),
        packet,
        general_controller_decision=TradingDecision.ALLOW,
        now_ms=now_ms,
    )

    assert result.candidate.decision is TradingDecision.WAIT
    assert "confidence_below_candidate_threshold" in result.downgrade_reasons


def test_mainnet_remains_blocked_until_security_pipeline_is_complete(tmp_path) -> None:
    bridge = DecisionCandidateBridge(_database(tmp_path))
    packet, now_ms = _packet(
        "candidate-mainnet",
        environment=TradingEnvironment.MAINNET,
    )

    result = bridge.build_and_store(
        _assessment("candidate-mainnet"),
        packet,
        general_controller_decision=TradingDecision.ALLOW,
        now_ms=now_ms,
    )

    assert result.candidate.decision is TradingDecision.BLOCK
    assert "mainnet_requires_completed_security_guard_pipeline" in result.candidate.risk_blocks


def test_structurally_stale_candidate_is_rejected_and_audited(tmp_path) -> None:
    database = _database(tmp_path)
    bridge = DecisionCandidateBridge(database)
    packet, now_ms = _packet("candidate-stale", market_age_ms=10_000)

    with pytest.raises(CandidateBridgeError, match="structurally invalid"):
        bridge.build_and_store(
            _assessment("candidate-stale"),
            packet,
            general_controller_decision=TradingDecision.ALLOW,
            now_ms=now_ms,
        )

    events = database.list_events(
        "audit",
        entity_type="candidate_bridge_rejected",
        entity_id="candidate-stale",
        limit=10,
    )
    assert len(events) == 1
    assert "market data is stale" in events[0]["payload"]["errors"]


def test_candidate_id_must_match_assessment_id(tmp_path) -> None:
    bridge = DecisionCandidateBridge(_database(tmp_path))
    packet, now_ms = _packet("candidate-other")

    with pytest.raises(CandidateBridgeError, match="immutable decision_id"):
        bridge.build_and_store(
            _assessment("candidate-original"),
            packet,
            general_controller_decision=TradingDecision.ALLOW,
            now_ms=now_ms,
        )
