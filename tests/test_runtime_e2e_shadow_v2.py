from __future__ import annotations

import time
from threading import RLock
from types import SimpleNamespace

import pytest

from decision_quality import CandidateEvidencePacket
from trading_candidate import (
    MarketRegime,
    TradingCategory,
    TradingDecision,
    TradingEnvironment,
    TradingSide,
)

from autonomous_trading.council_loop import CouncilAuthorizedPaperLoop, CouncilEntryProposal
from autonomous_trading.general_controller_v2 import GateSignal, GateVerdict
from autonomous_trading.runtime_e2e_shadow_v2 import (
    attach_paper_settlement,
    build_runtime_shadow_record,
    idempotent_upsert_record,
)
from autonomous_trading.runtime_gate_provider_v2 import CanonicalShadowGateProvider
from autonomous_trading.runtime_shadow_integration_v2 import RuntimeShadowV2
from autonomous_trading.shadow_dual_run_v2 import Decision


def _packet(*, received_timestamp_ms: int = 1_000_100) -> CandidateEvidencePacket:
    return CandidateEvidencePacket(
        candidate_id="decision-1",
        symbol="BTCUSDT",
        category=TradingCategory.SPOT,
        side=TradingSide.BUY,
        environment=TradingEnvironment.PAPER,
        market_timestamp_ms=1_000_000,
        received_timestamp_ms=received_timestamp_ms,
        reference_price=50_000.0,
        data_sources=("bybit", "bitget", "mexc"),
        market_regime=MarketRegime.TREND,
        signal_evidence=("signal-1",),
        news_evidence=("news-1",),
        news_assessment_id="news-assessment-1",
        portfolio_snapshot_id="portfolio-1",
        cost_snapshot_id="cost-1",
        estimated_fees=1.0,
        estimated_slippage=2.0,
        risk_score=20.0,
        risk_blocks=(),
        expires_at_ms=1_005_000,
    )


def _candidate():
    return SimpleNamespace(
        candidate_id="decision-1",
        symbol="BTCUSDT",
        side=TradingSide.BUY,
        market_timestamp_ms=1_000_000,
    )


def _authorization(
    *,
    authorized: bool = True,
    validation_valid: bool | None = None,
    validation_errors: tuple[str, ...] = (),
):
    if validation_valid is None:
        validation_valid = authorized
    return SimpleNamespace(
        decision_id="decision-1",
        authorized=authorized,
        decision=TradingDecision.ALLOW if authorized else TradingDecision.WAIT,
        reason="canonical paper authorization" if authorized else "canonical wait",
        candidate_result=SimpleNamespace(
            candidate=_candidate(),
            validation=SimpleNamespace(valid=validation_valid, errors=validation_errors),
            general_controller_decision=TradingDecision.ALLOW if authorized else TradingDecision.WAIT,
        ),
        assessment=SimpleNamespace(
            blocked=False,
            quality_score=90.0,
            agreement=90.0,
            confidence=90.0,
            action="ALLOW" if authorized else "WAIT",
            reason="verified evidence",
            regime="trend",
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
            "agent_id": "news_intelligence",
            "action": "BUY",
            "confidence": 85,
            "evidence_score": 80,
            "risk_score": 20,
            "verified_market_data": True,
            "evidence_ids": ("news-1",),
        },
    )


def _gates(*, risk=GateVerdict.PASS, security=GateVerdict.PASS):
    return (
        GateSignal("risk_engine", risk, reasons=("risk evidence",)),
        GateSignal("portfolio_engine", GateVerdict.PASS, max_notional_usdt=100.0),
        GateSignal("security_guard", security, reasons=("security evidence",)),
    )


def _record(*, gates=None):
    packet = _packet()
    authorization = _authorization()
    selected_gates = tuple(gates or _gates())
    result = RuntimeShadowV2().evaluate(
        authorization=authorization,
        evidence_packet=packet,
        agent_payloads=_payloads(),
        gates=selected_gates,
    )
    return build_runtime_shadow_record(
        decision_id="decision-1",
        symbol="BTCUSDT",
        decision_ts_ms=1_000_200,
        evidence_packet=packet,
        gates=selected_gates,
        result=result,
    )


def test_record_preserves_identical_evidence_lineage_and_no_execution_authority():
    record = _record()

    assert record["snapshot_id"] == "decision-1:1000000"
    assert record["same_evidence"] is True
    assert record["champion_action"] == Decision.BUY.value
    assert record["challenger_action"] == Decision.BUY.value
    assert record["execution_authority"] is False
    assert record["paper_authority_switched"] is False
    assert record["controller"]["execution_authority"] is False


def test_risk_and_security_veto_force_challenger_wait_without_changing_champion():
    for gates in (
        _gates(risk=GateVerdict.BLOCK),
        _gates(security=GateVerdict.BLOCK),
    ):
        record = _record(gates=gates)
        assert record["champion_action"] == "BUY"
        assert record["challenger_action"] == "WAIT"
        assert record["controller"]["blocked"] is True
        assert record["execution_authority"] is False


def test_missing_mandatory_gate_fails_closed_to_wait():
    gates = tuple(gate for gate in _gates() if gate.gate != "security_guard")
    record = _record(gates=gates)

    assert record["champion_action"] == "BUY"
    assert record["challenger_action"] == "WAIT"
    assert "missing mandatory gate" in record["controller"]["reason"]


def test_stale_canonical_candidate_forces_challenger_wait_even_if_directional_agents_buy():
    authorization = _authorization(
        authorized=True,
        validation_valid=False,
        validation_errors=("candidate is expired", "market data is stale"),
    )
    result = RuntimeShadowV2().evaluate(
        authorization=authorization,
        evidence_packet=_packet(),
        agent_payloads=_payloads(),
        gates=_gates(),
    )

    assert result.comparison.authoritative.decision is Decision.BUY
    assert result.comparison.challenger.decision is Decision.WAIT
    assert result.controller.execution_authority is False
    assert "freshness validation failed" in result.controller.reason


def test_canonical_gate_provider_uses_persisted_risk_portfolio_and_paper_validation():
    records = {
        ("risk_assessments", "risk-decision-1"): {
            "value": {
                "decision_id": "decision-1",
                "risk_score": 20.0,
                "blocks": [],
                "assessment": {
                    "allowed_virtual": True,
                    "blockers": [],
                    "hard_blocks": [],
                },
            }
        },
        ("portfolio_snapshots", "portfolio-1"): {
            "value": {
                "decision_id": "decision-1",
                "cash": 10_000.0,
                "equity": 9_800.0,
                "environment": "paper",
            }
        },
    }

    class FakeDatabase:
        def get_json(self, namespace, key):
            return records.get((namespace, key))

    provider = CanonicalShadowGateProvider(FakeDatabase())
    gates = provider(_authorization(), _packet(), {"cash": 10_000.0})
    by_name = {gate.gate: gate for gate in gates}

    assert by_name["risk_engine"].verdict is GateVerdict.PASS
    assert by_name["portfolio_engine"].verdict is GateVerdict.PASS
    assert by_name["portfolio_engine"].max_notional_usdt == pytest.approx(9_800.0)
    assert by_name["security_guard"].verdict is GateVerdict.PASS
    assert all("BUY" not in " ".join(gate.reasons) for gate in gates)


def test_canonical_gate_provider_never_fabricates_missing_or_conflicting_evidence():
    class MissingDatabase:
        def get_json(self, namespace, key):
            if namespace == "portfolio_snapshots":
                return {"value": {"decision_id": "other", "cash": 1_000.0, "equity": 1_000.0, "environment": "paper"}}
            return None

    gates = CanonicalShadowGateProvider(MissingDatabase())(_authorization(), _packet(), {})
    by_name = {gate.gate: gate for gate in gates}

    assert by_name["risk_engine"].verdict is GateVerdict.WAIT
    assert by_name["portfolio_engine"].verdict is GateVerdict.WAIT
    assert by_name["security_guard"].verdict is GateVerdict.PASS

    stale_security = CanonicalShadowGateProvider(MissingDatabase())(
        _authorization(validation_valid=False, validation_errors=("candidate is expired",)),
        _packet(),
        {},
    )
    assert {gate.gate: gate for gate in stale_security}["security_guard"].verdict is GateVerdict.BLOCK


def test_idempotent_retry_does_not_duplicate_shadow_record_and_conflict_fails_closed():
    record = _record()
    records, inserted = idempotent_upsert_record({}, record)
    retried, inserted_again = idempotent_upsert_record(records, record)

    assert inserted is True
    assert inserted_again is False
    assert retried == records
    assert list(retried) == ["decision-1"]

    conflict = dict(record)
    conflict["evidence_hash"] = "different"
    with pytest.raises(ValueError, match="different immutable lineage"):
        idempotent_upsert_record(records, conflict)


def test_settlement_links_actual_costs_replay_chronology_and_candidate_only_learning():
    record = _record()
    settled = attach_paper_settlement(
        record,
        settled_at_ms=1_100_000,
        side="SELL",
        quantity=0.01,
        entry_price=50_000.0,
        exit_price=51_000.0,
        entry_fee=0.5,
        exit_fee=0.51,
        net_pnl=8.99,
        slippage_cost=0.0,
    )

    settlement = settled["settlement"]
    replay = settlement["replay_champion"]
    assert settlement["fees"] == pytest.approx(1.01)
    assert settlement["gross_pnl"] == pytest.approx(10.0)
    assert replay["snapshot_id"] == record["snapshot_id"]
    assert replay["evidence_hash"] == record["evidence_hash"]
    assert replay["evidence_max_ts_ms"] <= replay["decision_ts_ms"]
    assert replay["execution_authority"] is False
    assert settlement["counterfactual_outcome_pending_replay"] is True

    lesson = settled["learning_candidate"]
    assert lesson["stage"] == "candidate"
    assert lesson["promotion_path"] == [
        "candidate",
        "replay_validated",
        "shadow_validated",
        "active",
    ]
    assert lesson["direct_activation_allowed"] is False
    assert lesson["execution_authority"] is False


def test_future_evidence_is_rejected_before_a_replay_record_can_be_persisted():
    packet = _packet(received_timestamp_ms=1_000_300)
    result = RuntimeShadowV2().evaluate(
        authorization=_authorization(),
        evidence_packet=packet,
        agent_payloads=_payloads(),
        gates=_gates(),
    )

    with pytest.raises(ValueError, match="look-ahead evidence"):
        build_runtime_shadow_record(
            decision_id="decision-1",
            symbol="BTCUSDT",
            decision_ts_ms=1_000_200,
            evidence_packet=packet,
            gates=_gates(),
            result=result,
        )


def test_real_canonical_tick_invokes_shadow_with_the_exact_proposal_packet():
    loop = object.__new__(CouncilAuthorizedPaperLoop)
    packet = _packet()
    proposal = CouncilEntryProposal(
        decision_id="decision-1",
        agent_payloads=_payloads(),
        evidence_packet=packet,
        general_controller_decision=TradingDecision.WAIT,
        regime="trend",
    )
    authorization = _authorization(authorized=False)
    seen = []

    loop.stream = SimpleNamespace(
        symbols=("BTCUSDT",),
        snapshot=lambda: {"verified": True},
        quote=lambda _symbol: SimpleNamespace(price=50_000.0, change_24h_percent=0.0),
    )
    loop._lock = RLock()
    loop._state = {
        "positions": {},
        "cash": 10_000.0,
        "equity": 10_000.0,
        "peak_equity": 10_000.0,
        "realized_pnl": 0.0,
        "unrealized_pnl": 0.0,
        "total_fees": 0.0,
    }
    loop.initial_cash = 10_000.0
    loop.proposal_provider = lambda _symbol, _quote, _state: proposal
    loop.decision_runtime = SimpleNamespace(assess_entry=lambda *args, **kwargs: authorization)
    loop._now_ms = lambda: 1_000_200
    loop._trace = lambda *args, **kwargs: {}
    loop._event = lambda *args, **kwargs: None
    loop._mark_to_market = lambda _market: None
    loop._persist = lambda: None
    loop._evaluate_v2_shadow = lambda **kwargs: seen.append(kwargs)

    loop.tick()

    assert len(seen) == 1
    assert seen[0]["proposal"].evidence_packet is packet
    assert seen[0]["authorization"] is authorization
    assert seen[0]["decision_ts_ms"] == 1_000_200


def test_shadow_exception_and_timeout_are_isolated_from_the_canonical_path():
    loop = object.__new__(CouncilAuthorizedPaperLoop)
    loop._state = {"v2_shadow_records": {}, "v2_shadow_errors": []}
    loop.initial_cash = 10_000.0
    loop.shadow_timeout_seconds = 0.01
    loop._now_ms = lambda: 1_000_200
    loop._trace = lambda *args, **kwargs: {}

    class RaisingShadow:
        def evaluate(self, **kwargs):
            raise RuntimeError("shadow boom")

    loop.shadow_runtime = RaisingShadow()
    loop.shadow_gate_provider = lambda *_args: _gates()
    proposal = CouncilEntryProposal(
        decision_id="decision-1",
        agent_payloads=_payloads(),
        evidence_packet=_packet(),
        general_controller_decision=TradingDecision.ALLOW,
    )
    loop._evaluate_v2_shadow(
        symbol="BTCUSDT",
        proposal=proposal,
        authorization=_authorization(),
        decision_ts_ms=1_000_200,
    )
    assert loop._state["v2_shadow_records"] == {}
    assert "shadow boom" in loop._state["v2_shadow_errors"][-1]["error"]

    loop._state["v2_shadow_errors"] = []
    loop.shadow_runtime = RuntimeShadowV2()

    def slow_gates(*_args):
        time.sleep(0.1)
        return _gates()

    loop.shadow_gate_provider = slow_gates
    started = time.monotonic()
    loop._evaluate_v2_shadow(
        symbol="BTCUSDT",
        proposal=proposal,
        authorization=_authorization(),
        decision_ts_ms=1_000_200,
    )
    elapsed = time.monotonic() - started

    assert elapsed < 0.08
    assert loop._state["v2_shadow_records"] == {}
    assert "TimeoutError" in loop._state["v2_shadow_errors"][-1]["error"]
