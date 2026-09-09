from __future__ import annotations

import copy

import pytest

from learning_engine import OutcomeAttributionService, OutcomeEvidence, SelfLearningSupervisor
from learning_engine.research_challengers import ResearchChallengerService
from meta_ai_persistence import EVENT_NAMESPACE
from storage import ProjectDatabase

START = 1_700_000_000_000


def _database(tmp_path):
    database = ProjectDatabase(f"sqlite:///{tmp_path / 'learning.db'}")
    database.initialize()
    return database


def _settlement(database, monkeypatch, decision, *, pnl=-0.16100462, confidence=0.7425, offset=1000, regime="trend"):
    assessed, recorded = START, START + offset
    monkeypatch.setattr("storage.project_database._now_ms", lambda: recorded)
    database.append_event(EVENT_NAMESPACE, "decision_assessment", decision, {
        "assessment": {"action": "BUY", "regime": regime},
        "opinions": [{"agent_id": "market_intelligence", "action": "BUY", "confidence": confidence,
                      "evidence_score": 1.0}],
    }, created_at_ms=assessed)
    settlement = {"decision_id": decision, "selected_action": "BUY", "net_pnl": pnl,
                  "realized_outcome": "PROFIT" if pnl > 1e-9 else "LOSS" if pnl < -1e-9 else "FLAT",
                  "drawdown_contribution": max(0, -pnl), "evidence_class": "verified_market",
                  "verified_market_data": True, "execution_authority": False}
    database.put_json("paper_decision_settlements", decision, settlement, expected_version=0)
    return settlement, recorded


@pytest.mark.parametrize("pnl", [-0.16100462, 0, 0.23])
def test_v2_economics_never_fabricate_hold_or_direction_calibration(tmp_path, monkeypatch, pnl):
    database = _database(tmp_path)
    settlement, recorded = _settlement(database, monkeypatch, "bnb", pnl=pnl)
    source_before = database.get_json("paper_decision_settlements", "bnb")
    supervisor = SelfLearningSupervisor(database)
    evidence = supervisor._evidence_from_settlement("bnb", settlement, recorded)
    assert evidence["agents"][0]["confidence"] == pytest.approx(74.25)
    assert evidence["occurred_at_ms"] == recorded > START
    assert evidence["evidence_available_at_ms"] == recorded
    result = supervisor.attribution.record(evidence)
    assert result["realized_action"] is None
    assert result["net_pnl"] == pnl
    assert result["attributions"][0]["direction_correct"] is None
    assert result["attributions"][0]["confidence_error"] is None
    metric = supervisor.attribution.agent_metrics()[0]
    assert metric["direction_labeled_count"] == 0
    assert metric["direction_accuracy"] is None
    assert metric["mean_confidence_error"] is None
    assert metric["learning_score"] is None
    assert metric["attributed_pnl"] == pnl
    assert database.get_json("paper_decision_settlements", "bnb") == source_before
    assert supervisor.attribution.record(evidence)["idempotent"] is True
    assert supervisor.attribution.summary()["economic_only_outcome_count"] == 1


def test_versioned_projection_preserves_all_old_learning_evidence(tmp_path, monkeypatch):
    database = _database(tmp_path)
    legacy = {"outcome_id": "paper:bnb", "realized_action": "HOLD", "confidence": 0.7425,
              "net_pnl": -0.16100462, "occurred_at_ms": START}
    database.put_json("self_learning_outcomes", "paper:bnb", legacy, expected_version=0)
    database.put_json("self_learning_agent_metrics", "market_intelligence", {"outcome_count": 99}, expected_version=0)
    old = database.get_json("self_learning_outcomes", "paper:bnb")
    old_metric = database.get_json("self_learning_agent_metrics", "market_intelligence")
    _settlement(database, monkeypatch, "bnb")
    supervisor = SelfLearningSupervisor(database)
    assert supervisor.run_once(now_ms=START + 1001)["processed_count"] == 1
    assert database.get_json("self_learning_outcomes", "paper:bnb") == old
    assert database.get_json("self_learning_agent_metrics", "market_intelligence") == old_metric
    assert supervisor.attribution.agent_metrics()[0]["outcome_count"] == 1
    assert supervisor.run_once(now_ms=START + 2000)["skipped_count"] == 1


def test_chronological_availability_never_leaks_future_settlements(tmp_path, monkeypatch):
    database = _database(tmp_path)
    # These are accounting fixtures, not a strategy performance backtest.
    for decision, pnl, offset, regime in [("bnb", -0.16, 1000, "trend"),
        ("sol", 0.23, 2000, "range"), ("eth", -0.08, 3000, "trend")]:
        _settlement(database, monkeypatch, decision, pnl=pnl, offset=offset, regime=regime)
    supervisor = SelfLearningSupervisor(database)
    first = supervisor.run_once(now_ms=START + 1500)
    assert first["processed_count"] == 1
    assert first["learning_summary"]["net_pnl"] == -0.16
    second = supervisor.run_once(now_ms=START + 2500)
    assert second["processed_count"] == 1
    assert second["learning_summary"]["net_pnl"] == pytest.approx(0.07)
    final = supervisor.run_once(now_ms=START + 3500)
    assert final["processed_count"] == 1
    assert final["learning_summary"]["net_pnl"] == pytest.approx(-0.01)
    assert final["learning_summary"]["direction_labeled_outcome_count"] == 0
    assert not ResearchChallengerService(database).evaluate_learning_summary(final["learning_summary"]).eligible


@pytest.mark.parametrize("confidence", [True, float("nan"), -0.01, 74.25])
def test_canonical_probability_boundary_rejects_ambiguous_or_invalid_units(tmp_path, monkeypatch, confidence):
    database = _database(tmp_path)
    # Persistence already rejects non-finite values; build the event directly
    # through the adapter's read boundary to exercise its validation too.
    settlement, recorded = _settlement(database, monkeypatch, "bnb")
    event = database.list_events(EVENT_NAMESPACE, entity_type="decision_assessment", entity_id="bnb", limit=1)[0]
    event = copy.deepcopy(event)
    event["payload"]["opinions"][0]["confidence"] = confidence
    monkeypatch.setattr(database, "list_events", lambda *a, **k: [event])
    with pytest.raises(ValueError, match="probability"):
        SelfLearningSupervisor(database)._evidence_from_settlement("bnb", settlement, recorded)


def test_explicit_direction_uses_correct_probability_and_separate_label_count(tmp_path, monkeypatch):
    database = _database(tmp_path)
    settlement, recorded = _settlement(database, monkeypatch, "bnb", pnl=0.2)
    supervisor = SelfLearningSupervisor(database)
    evidence = supervisor._evidence_from_settlement("bnb", {**settlement, "realized_action": "BUY"}, recorded)
    result = supervisor.attribution.record(evidence)
    assert result["attributions"][0]["confidence_error"] == pytest.approx(0.2575)
    metric = supervisor.attribution.agent_metrics()[0]
    assert metric["direction_labeled_count"] == 1
    assert metric["direction_accuracy"] == 1


def test_missing_or_contradictory_economic_outcome_fails_closed(tmp_path, monkeypatch):
    database = _database(tmp_path)
    settlement, recorded = _settlement(database, monkeypatch, "bnb")
    evidence = SelfLearningSupervisor(database)._evidence_from_settlement("bnb", settlement, recorded)
    for patch in [{"realized_outcome": None}, {"realized_outcome": "PROFIT"},
                  {"evidence_available_at_ms": START - 1}]:
        with pytest.raises(ValueError):
            OutcomeEvidence.from_mapping({**evidence, **patch})
    with pytest.raises(ValueError, match="settlement time"):
        SelfLearningSupervisor(database)._evidence_from_settlement("bnb", {**settlement, "settled_at_ms": START - 1}, recorded)
