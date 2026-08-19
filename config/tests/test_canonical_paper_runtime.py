from __future__ import annotations

import time

import pytest

from autonomous_trading import CanonicalPaperDecisionRuntime, CanonicalPaperRuntimeError
from decision_quality import CandidateEvidencePacket
from storage import ProjectDatabase
from trading_candidate import (
    MarketRegime,
    TradingCategory,
    TradingDecision,
    TradingEnvironment,
    TradingSide,
)


def _database(tmp_path) -> ProjectDatabase:
    database = ProjectDatabase(f"sqlite:///{tmp_path / 'canonical-paper.db'}")
    database.initialize()
    return database


def _payloads(action: str = "BUY") -> list[dict[str, object]]:
    return [
        {
            "agent_id": "market_intelligence",
            "action": action,
            "confidence": 84,
            "evidence_score": 92,
            "risk_score": 18,
            "evidence_class": "verified_market",
            "verified_market_data": True,
            "rationale": "verified multi-source trend",
        },
        {
            "agent_id": "news_intelligence",
            "action": action,
            "confidence": 79,
            "evidence_score": 88,
            "risk_score": 22,
            "evidence_class": "verified_market",
            "verified_market_data": True,
            "rationale": "verified directional news confirmation",
        },
        {
            "agent_id": "portfolio_engine",
            "action": action,
            "confidence": 81,
            "evidence_score": 90,
            "risk_score": 20,
            "evidence_class": "verified_market",
            "verified_market_data": True,
            "rationale": "portfolio exposure remains inside limits",
        },
    ]


def _packet(decision_id: str, *, environment: TradingEnvironment = TradingEnvironment.PAPER):
    now_ms = int(time.time() * 1000)
    packet = CandidateEvidencePacket(
        candidate_id=decision_id,
        symbol="BTCUSDT",
        category=TradingCategory.SPOT,
        side=TradingSide.BUY,
        environment=environment,
        market_timestamp_ms=now_ms - 100,
        received_timestamp_ms=now_ms - 50,
        reference_price=60_000.0,
        data_sources=("bybit_ws", "binance_ws", "coinbase_ws"),
        market_regime=MarketRegime.TREND,
        signal_evidence=("market-signal-1",),
        news_evidence=("news-assessment-1",),
        news_assessment_id="news-assessment-1",
        portfolio_snapshot_id="portfolio-snapshot-1",
        cost_snapshot_id="cost-snapshot-1",
        estimated_fees=0.10,
        estimated_slippage=0.05,
        risk_score=20.0,
        risk_blocks=(),
        expires_at_ms=now_ms + 8_000,
    )
    return packet, now_ms


def _persist_v2_gates(database: ProjectDatabase, decision_id: str, packet: CandidateEvidencePacket) -> None:
    database.put_json(
        "risk_assessments",
        f"risk-{decision_id}",
        {
            "decision_id": decision_id,
            "risk_score": packet.risk_score,
            "blocks": [],
            "assessment": {
                "allowed_virtual": True,
                "blockers": [],
                "hard_blocks": [],
            },
        },
        expected_version=0,
    )
    database.put_json(
        "portfolio_snapshots",
        packet.portfolio_snapshot_id,
        {
            "decision_id": decision_id,
            "cash": 10_000.0,
            "equity": 10_000.0,
            "open_symbols": [],
            "environment": "paper",
        },
        expected_version=0,
    )


def test_verified_council_can_authorize_paper_candidate(tmp_path) -> None:
    database = _database(tmp_path)
    runtime = CanonicalPaperDecisionRuntime(database)
    packet, now_ms = _packet("paper-decision-allow")
    _persist_v2_gates(database, "paper-decision-allow", packet)

    result = runtime.assess_entry(
        "paper-decision-allow",
        _payloads(),
        packet,
        general_controller_decision=TradingDecision.ALLOW,
        now_ms=now_ms,
        regime="bull",
    )

    assert result.authorized is True
    assert result.decision is TradingDecision.ALLOW
    assert result.execution_authority is False
    stored = database.get_json("trading_candidates", "paper-decision-allow")
    assert stored is not None
    assert stored["value"]["decision"] == "ALLOW"


def test_legacy_general_controller_wait_has_no_v2_direction_authority(tmp_path) -> None:
    database = _database(tmp_path)
    runtime = CanonicalPaperDecisionRuntime(database)
    packet, now_ms = _packet("paper-decision-wait")
    _persist_v2_gates(database, "paper-decision-wait", packet)

    result = runtime.assess_entry(
        "paper-decision-wait",
        _payloads(),
        packet,
        general_controller_decision=TradingDecision.WAIT,
        now_ms=now_ms,
        regime="bull",
    )

    assert result.authorized is True
    assert result.decision is TradingDecision.ALLOW
    stored = database.get_json(runtime.v2_decision_namespace, "paper-decision-wait")
    assert stored is not None
    assert stored["value"]["legacy_provider_directive"] == "WAIT"
    assert stored["value"]["legacy_provider_directive_authority"] is False
    assert stored["value"]["paper_decision_owner"] == "general_controller_v2"


def test_runtime_rejects_non_paper_environment(tmp_path) -> None:
    runtime = CanonicalPaperDecisionRuntime(_database(tmp_path))
    packet, now_ms = _packet("paper-decision-mainnet", environment=TradingEnvironment.MAINNET)

    with pytest.raises(CanonicalPaperRuntimeError, match="PAPER candidates only"):
        runtime.assess_entry(
            "paper-decision-mainnet",
            _payloads(),
            packet,
            general_controller_decision=TradingDecision.ALLOW,
            now_ms=now_ms,
            regime="bull",
        )


def test_runtime_fails_closed_without_agent_opinions(tmp_path) -> None:
    runtime = CanonicalPaperDecisionRuntime(_database(tmp_path))
    packet, now_ms = _packet("paper-decision-empty")

    with pytest.raises(CanonicalPaperRuntimeError, match="at least one independent agent"):
        runtime.assess_entry(
            "paper-decision-empty",
            [],
            packet,
            general_controller_decision=TradingDecision.ALLOW,
            now_ms=now_ms,
        )


def test_unverified_agent_payloads_cannot_authorize_paper_candidate(tmp_path) -> None:
    """Missing verification must not be treated as verified market evidence."""

    database = _database(tmp_path)
    runtime = CanonicalPaperDecisionRuntime(database)
    packet, now_ms = _packet("paper-decision-unverified")
    _persist_v2_gates(database, "paper-decision-unverified", packet)
    unverified = [
        {
            key: value
            for key, value in payload.items()
            if key not in {"evidence_class", "verified_market_data"}
        }
        for payload in _payloads()
    ]

    result = runtime.assess_entry(
        "paper-decision-unverified",
        unverified,
        packet,
        general_controller_decision=TradingDecision.ALLOW,
        now_ms=now_ms,
        regime="bull",
    )

    assert result.authorized is False
    assert result.decision is TradingDecision.WAIT
    assert result.assessment.rejected_agents == (
        "market_intelligence",
        "news_intelligence",
        "portfolio_engine",
    )


def test_decision_and_candidate_ids_must_match(tmp_path) -> None:
    runtime = CanonicalPaperDecisionRuntime(_database(tmp_path))
    packet, now_ms = _packet("candidate-other")

    with pytest.raises(CanonicalPaperRuntimeError, match="candidate_id must equal decision_id"):
        runtime.assess_entry(
            "decision-original",
            _payloads(),
            packet,
            general_controller_decision=TradingDecision.ALLOW,
            now_ms=now_ms,
        )
