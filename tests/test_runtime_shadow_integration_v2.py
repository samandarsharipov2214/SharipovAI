from types import SimpleNamespace

from decision_quality import CandidateEvidencePacket
from trading_candidate import (
    MarketRegime,
    TradingCategory,
    TradingDecision,
    TradingEnvironment,
    TradingSide,
)

from autonomous_trading.general_controller_v2 import GateSignal, GateVerdict
from autonomous_trading.runtime_shadow_integration_v2 import RuntimeShadowV2, immutable_shadow_input
from autonomous_trading.shadow_dual_run_v2 import Decision


def _packet(*, cost_snapshot_id: str = "cost-1") -> CandidateEvidencePacket:
    return CandidateEvidencePacket(
        candidate_id="decision-1",
        symbol="BTCUSDT",
        category=TradingCategory.SPOT,
        side=TradingSide.BUY,
        environment=TradingEnvironment.PAPER,
        market_timestamp_ms=1_000_000,
        received_timestamp_ms=1_000_100,
        reference_price=50_000.0,
        data_sources=("bybit", "bitget", "mexc"),
        market_regime=MarketRegime.TREND,
        signal_evidence=("signal-1",),
        news_evidence=("news-1",),
        news_assessment_id="news-assessment-1",
        portfolio_snapshot_id="portfolio-1",
        cost_snapshot_id=cost_snapshot_id,
        estimated_fees=1.0,
        estimated_slippage=2.0,
        risk_score=20.0,
        risk_blocks=(),
        expires_at_ms=1_005_000,
    )


def _authorization():
    candidate = SimpleNamespace(
        candidate_id="decision-1",
        side=TradingSide.BUY,
        market_timestamp_ms=1_000_000,
    )
    return SimpleNamespace(
        decision_id="decision-1",
        authorized=True,
        decision=TradingDecision.ALLOW,
        reason="canonical paper authorization",
        candidate_result=SimpleNamespace(candidate=candidate),
        assessment=SimpleNamespace(
            blocked=False,
            quality_score=90.0,
            agreement=0.90,
            reason="verified evidence",
        ),
    )


def _payloads():
    return (
        {
            "agent_id": "technical_analyst",
            "action": "BUY",
            "confidence": 90,
            "evidence_score": 90,
            "risk_score": 20,
            "verified_market_data": True,
            "evidence_ids": ("signal-1",),
        },
        {
            "agent_id": "news_analyst",
            "action": "BUY",
            "confidence": 85,
            "evidence_score": 80,
            "risk_score": 20,
            "verified_market_data": True,
            "evidence_ids": ("news-1",),
        },
    )


def _pass_gates():
    return (
        GateSignal("risk_engine", GateVerdict.PASS),
        GateSignal("portfolio_engine", GateVerdict.PASS, max_notional_usdt=100.0),
        GateSignal("security_guard", GateVerdict.PASS),
    )


def test_immutable_shadow_input_fingerprints_exact_canonical_packet():
    first = immutable_shadow_input(_packet())
    same = immutable_shadow_input(_packet())
    changed = immutable_shadow_input(_packet(cost_snapshot_id="cost-2"))

    assert first.snapshot_id == "decision-1:1000000"
    assert first.evidence_hash == same.evidence_hash
    assert first.evidence_hash != changed.evidence_hash


def test_runtime_shadow_compares_current_paper_with_non_executing_gc_v2():
    result = RuntimeShadowV2().evaluate(
        authorization=_authorization(),
        evidence_packet=_packet(),
        agent_payloads=_payloads(),
        gates=_pass_gates(),
    )

    assert result.comparison.same_evidence is True
    assert result.comparison.authoritative.decision is Decision.BUY
    assert result.comparison.challenger.decision is Decision.BUY
    assert result.comparison.decision_match is True
    assert result.comparison.authoritative.execution_authority is True
    assert result.comparison.challenger.execution_authority is False
    assert result.execution_authority is False
    assert result.controller.execution_authority is False


def test_runtime_shadow_missing_mandatory_gate_fails_closed_to_wait():
    gates = tuple(gate for gate in _pass_gates() if gate.gate != "security_guard")

    result = RuntimeShadowV2().evaluate(
        authorization=_authorization(),
        evidence_packet=_packet(),
        agent_payloads=_payloads(),
        gates=gates,
    )

    assert result.comparison.authoritative.decision is Decision.BUY
    assert result.comparison.challenger.decision is Decision.WAIT
    assert result.comparison.decision_match is False
    assert result.controller.blocked is True
    assert "missing mandatory gate" in result.controller.reason
