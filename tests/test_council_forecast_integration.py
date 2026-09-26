from dataclasses import replace
import json

import pytest

from autonomous_trading import forecast_contract as fc
from test_prospective_forecast import NOW, passing_artifact
from test_paper_anti_churn_fee_driven import Clock, MID, SYMBOL, _build_loop, _plan_buy, _quote


def configured(tmp_path, monkeypatch, *, promoted=True, expected=.02):
    monkeypatch.setattr(fc.time, "time", lambda: NOW / 1000)
    loop, stream, plan, runtime, clock = _build_loop(tmp_path, monkeypatch, clock=Clock(NOW))
    artifact = passing_artifact(expected)
    path = tmp_path / "artifact.json"
    path.write_text(json.dumps(artifact))
    monkeypatch.setattr(fc, "REVIEWED_MODELS", frozenset({fc.digest(artifact)}) if promoted else frozenset())
    loop.forecast_service = fc.ProspectiveForecastService(loop.database, artifact_path=path)
    stream.current = replace(stream.current, feature_received_at_ms=NOW)
    _plan_buy(plan, "typed-first-entry", now_ms=NOW)
    plan["proposal"] = replace(plan["proposal"], evidence_packet=replace(plan["proposal"].evidence_packet,
        received_timestamp_ms=NOW))
    return loop, stream, plan, runtime, clock


@pytest.mark.parametrize("promoted,expected", [(False, .5), (True, .005), (True, -.01)])
def test_unpromoted_or_cost_insufficient_typed_forecast_waits(tmp_path, monkeypatch, promoted, expected):
    loop, stream, plan, runtime, clock = configured(tmp_path, monkeypatch, promoted=promoted, expected=expected)
    before = loop._state["cash"]
    loop.tick()
    assert loop._state["cash"] == before and loop._state["positions"] == {}
    assert not runtime.consumed
    assert loop._state["last_action"] == "WAIT"


def test_qualified_edge_opens_once_then_horizon_exit_reconciles_costs(tmp_path, monkeypatch):
    loop, stream, plan, runtime, clock = configured(tmp_path, monkeypatch)
    before = loop._state["cash"]
    loop.tick()
    assert runtime.consumed == ["typed-first-entry"]
    position = loop._state["positions"][SYMBOL]
    evidence = position["forecast_evidence"]
    assert evidence["status"] == "ELIGIBLE"
    assert evidence["conservative_edge_usdt"] > evidence["required_cost_usdt"]
    assert position["forecast_exit_at_ms"] == NOW + 300_000
    # Repeated calls cannot add exposure or consume the same authorization.
    loop.tick()
    assert runtime.consumed == ["typed-first-entry"]
    clock.advance(300_000)
    monkeypatch.setattr(fc.time, "time", lambda: clock.now_ms() / 1000)
    stream.current = _quote(MID + 10, now_ms=clock.now_ms())
    loop.tick()
    assert loop._state["positions"] == {}
    buy, sell = loop._state["trades"][-2:]
    assert sell["reason"] == "protective_forecast_horizon"
    assert sell["forecast_evidence"]["forecast_id"] == buy["forecast_evidence"]["forecast_id"]
    net = (sell["price"] - buy["price"]) * buy["quantity"] - buy["fee"] - sell["fee"]
    assert sell["net_pnl"] == pytest.approx(net)
    assert loop._state["cash"] == pytest.approx(before + net)
    assert sell["decision_settlement"]["net_pnl"] == pytest.approx(net)
    assert buy["impact_cost"] > 0 and sell["impact_cost"] > 0


def test_generation_storage_failure_remains_observable_without_buy(tmp_path, monkeypatch):
    loop, stream, plan, runtime, clock = configured(tmp_path, monkeypatch)
    original = loop.database.put_json
    def fail(namespace, *args, **kwargs):
        if namespace == "paper_prospective_forecasts":
            raise RuntimeError("database busy")
        return original(namespace, *args, **kwargs)
    monkeypatch.setattr(loop.database, "put_json", fail)
    loop.tick()
    assert not runtime.consumed
    assert loop.forecast_service.status()["error"] == "forecast_generation_error:RuntimeError"


@pytest.mark.parametrize("corrupt", [["invalid"], "invalid", 5.])
def test_malformed_persisted_forecast_cannot_crash_loop_or_buy(tmp_path, monkeypatch, corrupt):
    loop, stream, plan, runtime, clock = configured(tmp_path, monkeypatch)
    original = loop.database.get_json
    def read(namespace, key):
        row = original(namespace, key)
        if namespace == "paper_prospective_forecasts" and row:
            return {**row, "value": corrupt}
        return row
    monkeypatch.setattr(loop.database, "get_json", read)
    loop.tick()
    assert not runtime.consumed
    assert loop._state["last_action"] == "WAIT"
    assert "forecast_malformed" in loop._state["forecast_gate_assessments"][SYMBOL]["reason"]


def test_source_cache_invalidated_by_new_evidence(tmp_path, monkeypatch):
    from autonomous_trading.economic_observer import EconomicOpportunityObserver
    from storage import ProjectDatabase
    from test_paper_economic_shadow import sources, opportunity, START
    db = ProjectDatabase(f"sqlite:///{tmp_path / 'shared.db'}")
    db.initialize()
    calls = []
    def read(*args, **kwargs):
        calls.append(1)
        return sources()
    monkeypatch.setattr("autonomous_trading.economic_observer.read_sources", read)
    observer = EconomicOpportunityObserver(db)
    observer.record_batch([opportunity(opportunity_id="one")])
    observer.record_batch([opportunity(opportunity_id="two")])
    assert len(calls) == 1 and observer.source_cache_hits == 1
    # A new epoch/revocation/outcome must invalidate the historical source cache.
    monkeypatch.setattr(fc.time, "time", lambda: (START + 1) / 1000)
    db.put_json("paper_strategy_epochs", "new-epoch", {"epoch_id": "new"})
    observer.record_batch([opportunity(opportunity_id="three")])
    assert len(calls) == 2


@pytest.mark.parametrize("veto", [None, "risk", "security", "portfolio"])
def test_promoted_forecast_still_uses_real_controller_and_all_vetoes(tmp_path, monkeypatch, veto):
    from autonomous_trading.canonical_runtime import CanonicalPaperDecisionRuntime
    from autonomous_trading.council_loop import CouncilEntryProposal
    from trading_candidate import TradingDecision
    from test_canonical_paper_runtime_v2_authority import _payload, _prepare_evidence
    loop, stream, plan, _, clock = configured(tmp_path, monkeypatch)
    runtime = loop.decision_runtime = CanonicalPaperDecisionRuntime(loop.database)
    decision = "actual-canonical-forecast"
    packet = replace(_prepare_evidence(loop.database, decision), symbol=SYMBOL,
        reference_price=MID, received_timestamp_ms=NOW, market_timestamp_ms=NOW)
    if veto == "risk":
        packet = replace(packet, risk_blocks=("review_test_risk_veto",))
    elif veto == "security":
        packet = replace(packet, security_approval_id="must-not-authorize-paper")
    elif veto == "portfolio":
        state = loop.database.get_json("portfolio_snapshots", packet.portfolio_snapshot_id)["value"]
        loop.database.put_json("portfolio_snapshots", packet.portfolio_snapshot_id, {**state, "cash": 0.})
    plan["proposal"] = CouncilEntryProposal(decision, (
        _payload("market_intelligence", "BUY"), _payload("news_intelligence", "BUY"),
        _payload("portfolio_engine", "WAIT"), _payload("risk_engine", "WAIT")), packet,
        TradingDecision.WAIT, "bull")
    before = loop._state["cash"]
    loop.tick()
    if veto:
        assert not loop._state["positions"]
        assert loop.database.get_json(runtime.consumption_namespace, decision) is None
        assert loop._state["cash"] == before
    else:
        position = loop._state["positions"][SYMBOL]
        assert position["quantity"] * position["entry_price"] < before * .11
        record = loop.database.get_json(runtime.v2_decision_namespace, decision)["value"]
        assert record["controller"]["final_intent"] == "BUY"
        assert loop.database.get_json(runtime.consumption_namespace, decision)
        clock.advance(300_000)
        monkeypatch.setattr(fc.time, "time", lambda: clock.now_ms() / 1000)
        stream.current = replace(_quote(MID - 1, now_ms=clock.now_ms()), feature_received_at_ms=clock.now_ms())
        loop.tick()
        settlement = loop.database.get_json(runtime.settlement_namespace, decision)["value"]
        assert settlement["net_pnl"] < 0  # Negative outcomes survive costs and Learning.
        from learning_engine.self_learning_supervisor import SelfLearningSupervisor
        supervisor = SelfLearningSupervisor(loop.database)
        supervisor.run_once()
        outcome = loop.database.get_json("self_learning_outcomes_v2", "paper:" + decision)["value"]
        assert outcome["net_pnl"] == settlement["net_pnl"]
        assert outcome["execution_authority"] is False
