from __future__ import annotations

import pytest

from autonomous_trading.general_controller_v2 import (
    DecisionQualitySignal,
    GateSignal,
    GateVerdict,
    GeneralControllerV2,
    SpecialistRecommendation,
    TradingIntent,
)


def _recommendation(
    agent_id: str,
    intent: TradingIntent,
    *,
    confidence: float = 85.0,
    evidence_score: float = 90.0,
    risk_score: float = 20.0,
    verified: bool = True,
) -> SpecialistRecommendation:
    return SpecialistRecommendation(
        agent_id=agent_id,
        intent=intent,
        confidence=confidence,
        evidence_score=evidence_score,
        risk_score=risk_score,
        verified=verified,
        rationale="test evidence",
        evidence_ids=(f"evidence-{agent_id}",),
    )


def _quality(*, blocked: bool = False, quality: float = 80.0, agreement: float = 80.0) -> DecisionQualitySignal:
    return DecisionQualitySignal(
        blocked=blocked,
        quality_score=quality,
        agreement=agreement,
        reason="quality evidence",
    )


def _gates(
    *,
    risk: GateVerdict = GateVerdict.PASS,
    portfolio: GateVerdict = GateVerdict.PASS,
    security: GateVerdict = GateVerdict.PASS,
) -> tuple[GateSignal, ...]:
    return (
        GateSignal("risk_engine", risk, ("risk verdict",)),
        GateSignal("portfolio_engine", portfolio, ("portfolio verdict",), max_notional_usdt=100.0),
        GateSignal("security_guard", security, ("security verdict",)),
    )


def _strong_buy() -> tuple[SpecialistRecommendation, ...]:
    return (
        _recommendation("market_intelligence", TradingIntent.BUY),
        _recommendation("news_intelligence", TradingIntent.BUY),
        _recommendation("cross_exchange_validation", TradingIntent.BUY),
    )


def test_general_controller_owns_final_buy_but_shadow_cannot_execute() -> None:
    decision = GeneralControllerV2().decide(_strong_buy(), decision_quality=_quality(), gates=_gates())

    assert decision.preliminary_intent is TradingIntent.BUY
    assert decision.final_intent is TradingIntent.BUY
    assert decision.blocked is False
    assert decision.shadow is True
    assert decision.execution_authority is False


def test_risk_wait_forces_final_wait_even_after_preliminary_buy() -> None:
    decision = GeneralControllerV2().decide(
        _strong_buy(),
        decision_quality=_quality(),
        gates=_gates(risk=GateVerdict.WAIT),
    )

    assert decision.preliminary_intent is TradingIntent.BUY
    assert decision.final_intent is TradingIntent.WAIT
    assert decision.blocked is False
    assert "risk_engine" in decision.reason


def test_risk_block_is_hard_veto() -> None:
    decision = GeneralControllerV2().decide(
        _strong_buy(),
        decision_quality=_quality(),
        gates=_gates(risk=GateVerdict.BLOCK),
    )

    assert decision.preliminary_intent is TradingIntent.BUY
    assert decision.final_intent is TradingIntent.WAIT
    assert decision.blocked is True


def test_security_block_is_hard_veto() -> None:
    decision = GeneralControllerV2().decide(
        _strong_buy(),
        decision_quality=_quality(),
        gates=_gates(security=GateVerdict.BLOCK),
    )

    assert decision.final_intent is TradingIntent.WAIT
    assert decision.blocked is True
    assert "security_guard" in decision.reason


def test_portfolio_wait_prevents_trade() -> None:
    decision = GeneralControllerV2().decide(
        _strong_buy(),
        decision_quality=_quality(),
        gates=_gates(portfolio=GateVerdict.WAIT),
    )

    assert decision.final_intent is TradingIntent.WAIT
    assert decision.blocked is False


def test_gate_and_advisory_agents_cannot_create_direction() -> None:
    recommendations = (
        _recommendation("risk_engine", TradingIntent.BUY, confidence=100.0, evidence_score=100.0, risk_score=0.0),
        _recommendation("portfolio_engine", TradingIntent.BUY, confidence=100.0, evidence_score=100.0, risk_score=0.0),
        _recommendation("security_guard", TradingIntent.BUY, confidence=100.0, evidence_score=100.0, risk_score=0.0),
        _recommendation("decision_quality", TradingIntent.BUY, confidence=100.0, evidence_score=100.0, risk_score=0.0),
    )

    decision = GeneralControllerV2().decide(recommendations, decision_quality=_quality(), gates=_gates())

    assert decision.preliminary_intent is TradingIntent.WAIT
    assert decision.final_intent is TradingIntent.WAIT
    assert set(decision.ignored_agents) == {
        "decision_quality",
        "portfolio_engine",
        "risk_engine",
        "security_guard",
    }


def test_contradictory_directional_evidence_downgrades_to_wait() -> None:
    recommendations = (
        _recommendation("market_intelligence", TradingIntent.BUY),
        _recommendation("news_intelligence", TradingIntent.SELL),
    )

    decision = GeneralControllerV2().decide(recommendations, decision_quality=_quality(), gates=_gates())

    assert decision.preliminary_intent is TradingIntent.WAIT
    assert decision.final_intent is TradingIntent.WAIT
    assert "contradictory" in decision.reason


def test_decision_quality_block_prevents_directional_trade() -> None:
    decision = GeneralControllerV2().decide(
        _strong_buy(),
        decision_quality=_quality(blocked=True),
        gates=_gates(),
    )

    assert decision.preliminary_intent is TradingIntent.WAIT
    assert decision.final_intent is TradingIntent.WAIT


def test_missing_mandatory_gate_fails_closed() -> None:
    decision = GeneralControllerV2().decide(
        _strong_buy(),
        decision_quality=_quality(),
        gates=(
            GateSignal("risk_engine", GateVerdict.PASS),
            GateSignal("portfolio_engine", GateVerdict.PASS, max_notional_usdt=100.0),
        ),
    )

    assert decision.final_intent is TradingIntent.WAIT
    assert decision.blocked is True
    assert "security_guard" in decision.reason


def test_zero_portfolio_notional_forces_wait() -> None:
    decision = GeneralControllerV2().decide(
        _strong_buy(),
        decision_quality=_quality(),
        gates=(
            GateSignal("risk_engine", GateVerdict.PASS),
            GateSignal("portfolio_engine", GateVerdict.PASS, max_notional_usdt=0.0),
            GateSignal("security_guard", GateVerdict.PASS),
        ),
    )

    assert decision.final_intent is TradingIntent.WAIT
    assert decision.blocked is False


def test_duplicate_gate_is_rejected() -> None:
    with pytest.raises(ValueError, match="duplicate gate"):
        GeneralControllerV2().decide(
            _strong_buy(),
            decision_quality=_quality(),
            gates=(
                GateSignal("risk_engine", GateVerdict.PASS),
                GateSignal("risk_engine", GateVerdict.PASS),
                GateSignal("portfolio_engine", GateVerdict.PASS),
                GateSignal("security_guard", GateVerdict.PASS),
            ),
        )
