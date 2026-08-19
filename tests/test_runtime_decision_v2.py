from autonomous_trading.general_controller_v2 import GateSignal, GateVerdict, TradingIntent
from autonomous_trading.runtime_decision_v2 import (
    directional_quality_signal,
    evaluate_controller_v2,
)


def _payload(agent_id, action, confidence=90, evidence=90, risk=20, verified=True):
    return {
        "agent_id": agent_id,
        "action": action,
        "confidence": confidence,
        "evidence_score": evidence,
        "risk_score": risk,
        "verified_market_data": verified,
        "evidence_class": "verified_market",
    }


def _gates():
    return (
        GateSignal("risk_engine", GateVerdict.PASS),
        GateSignal("portfolio_engine", GateVerdict.PASS, max_notional_usdt=100.0),
        GateSignal("security_guard", GateVerdict.PASS),
    )


def test_wait_and_gate_votes_do_not_dilute_directional_agreement():
    payloads = (
        _payload("market_intelligence", "BUY"),
        _payload("news_intelligence", "BUY", confidence=85, evidence=85),
        _payload("portfolio_engine", "WAIT", confidence=100, evidence=100, risk=0),
        _payload("risk_engine", "WAIT", confidence=100, evidence=100, risk=0),
        _payload("security_guard", "WAIT", confidence=100, evidence=100, risk=0),
    )

    quality = directional_quality_signal(payloads)
    result = evaluate_controller_v2(payloads, gates=_gates())

    assert quality.agreement == 100.0
    assert quality.quality_score >= 80.0
    assert result.controller.final_intent is TradingIntent.BUY
    assert result.controller.execution_authority is False


def test_portfolio_cannot_create_direction_even_with_strong_buy_vote():
    payloads = (
        _payload("market_intelligence", "SELL"),
        _payload("news_intelligence", "SELL"),
        _payload("portfolio_engine", "BUY", confidence=100, evidence=100, risk=0),
    )

    result = evaluate_controller_v2(payloads, gates=_gates())

    assert result.controller.final_intent is TradingIntent.SELL
    assert "portfolio_engine" in result.controller.ignored_agents


def test_missing_security_gate_fails_closed_to_wait():
    gates = tuple(gate for gate in _gates() if gate.gate != "security_guard")
    result = evaluate_controller_v2(
        (
            _payload("market_intelligence", "BUY"),
            _payload("news_intelligence", "BUY"),
        ),
        gates=gates,
    )

    assert result.controller.final_intent is TradingIntent.WAIT
    assert result.controller.blocked is True
    assert "missing mandatory gate" in result.controller.reason


def test_stale_evidence_blocks_direction_before_controller_can_buy():
    result = evaluate_controller_v2(
        (
            _payload("market_intelligence", "BUY"),
            _payload("news_intelligence", "BUY"),
        ),
        gates=_gates(),
        freshness_errors=("market data is stale",),
    )

    assert result.quality.blocked is True
    assert result.controller.final_intent is TradingIntent.WAIT
    assert "freshness" in result.quality.reason
