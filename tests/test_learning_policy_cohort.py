from __future__ import annotations

import copy

import pytest

from learning_engine.paper_economic_shadow import assess_opportunity, digest, read_sources
from storage import ProjectDatabase
from test_paper_economic_shadow import START, opportunity, sources


def linked_sources():
    data = sources()
    first = data["epochs"][0]["value"]
    first.update(decision_policy_version="decision-1", risk_version="risk-1", cost_model_version="cost-1")
    data["epochs"].append({"stored_at_ms": START + 3500, "value": {
        **first, "epoch_id": "epoch-2", "sha": "b" * 40, "epoch_start_ms": START + 3500}})
    data["policy_links"] = [{"stored_at_ms": START + 4000, "value": {
        "schema_version": 1, "scope": "scope-a", "status": "verified",
        "observation_epoch_id": "epoch-2", "policy_evaluation_id": "epoch-1",
        "epoch_ids": ["epoch-1", "epoch-2"], "verification_sha256": "a" * 64,
        "policy_changed": False, "risk_budget_changed": False,
        "configuration_unchanged": True, "entry_exit_policy_unchanged": True}}]
    return data


def assess(data):
    return assess_opportunity(opportunity(paper_build_sha="b" * 40), data)


def test_verified_policy_history_is_separate_from_build_and_forecast_support():
    data = linked_sources()
    before = digest(data)
    result = assess(data)
    context = result["learning_context"]
    assert context["cohort"]["sample_size"] == result["edge"]["sample_size"] == 0
    policy = context["policy_cohort"]
    assert policy["cohort"]["sample_size"] == 1
    assert policy["cohort"]["historical_net_expectancy_usdt"] == pytest.approx(-1.199)
    assert policy["evidence_outcome_ids"] == ["paper:b1"]
    assert policy["execution_authority"] is False
    assert policy["policy_influence"] == "SHADOW_ONLY"
    assert context["confidence_adjustment"] is result["edge"]["expected_net_edge_percent"] is None
    assert result["live_policy_changed"] is False
    assert digest(data) == before
    no_link = copy.deepcopy(data)
    no_link["policy_links"] = []
    expected = assess(no_link)
    context.pop("policy_cohort")
    assert result == expected


@pytest.mark.parametrize("boundary", ["equivalence", "epoch", "outcome"])
def test_physical_registration_and_outcome_availability_are_strict(boundary):
    data = linked_sources()
    if boundary == "equivalence":
        data["policy_links"][0]["stored_at_ms"] = START + 5000
        assert "policy_cohort" not in assess(data)["learning_context"]
    elif boundary == "epoch":
        data["epochs"][0]["stored_at_ms"] = START + 5000
        assert assess(data)["learning_context"]["policy_cohort"]["cohort"] is None
    else:
        data["outcomes"]["paper:b1"]["stored_at_ms"] = START + 5000
        assert assess(data)["learning_context"]["policy_cohort"]["cohort"]["sample_size"] == 0


def test_epoch_registered_or_changed_after_verification_requires_new_evidence():
    data = linked_sources()
    # Epoch is available at the decision, but was unavailable to the verifier.
    data["epochs"][0]["stored_at_ms"] = START + 4500
    assert assess(data)["learning_context"]["policy_cohort"]["status"] == "INVALID_EQUIVALENCE"


@pytest.mark.parametrize("field,value", [
    ("status", "planned"), ("verification_sha256", ""), ("policy_changed", True),
    ("risk_budget_changed", True), ("configuration_unchanged", False),
    ("entry_exit_policy_unchanged", False), ("epoch_ids", ["epoch-2", "unknown"]),
    ("epoch_ids", ["epoch-1", "epoch-1", "epoch-2"]), ("policy_evaluation_id", "unregistered"),
    ("schema_version", True),
])
def test_incomplete_or_unverified_equivalence_cannot_merge_cohorts(field, value):
    data = linked_sources()
    data["policy_links"][0]["value"][field] = value
    descriptor = assess(data)["learning_context"]["policy_cohort"]
    assert descriptor["status"] == "INVALID_EQUIVALENCE"
    assert descriptor["cohort"] is None


@pytest.mark.parametrize("field", ["strategy_version", "decision_policy_version", "risk_version", "cost_model_version"])
def test_changed_or_missing_core_versions_override_equivalence_assertion(field):
    data = linked_sources()
    data["epochs"][0]["value"][field] = "different"
    assert assess(data)["learning_context"]["policy_cohort"]["cohort"] is None
    data["epochs"][0]["value"].pop(field)
    assert assess(data)["learning_context"]["policy_cohort"]["cohort"] is None


def test_ambiguous_links_fail_and_other_scopes_or_targets_do_not_interfere():
    data = linked_sources()
    baseline = assess(data)
    extra = copy.deepcopy(data["policy_links"][0])
    data["policy_links"].append(extra)
    assert assess(data)["learning_context"]["policy_cohort"]["status"] == "AMBIGUOUS_EQUIVALENCE"
    extra["value"]["scope"] = "other-account"
    assert assess(data) == baseline
    extra["value"].update(scope="scope-a", observation_epoch_id="future-observation")
    assert assess(data) == baseline


def test_incomplete_source_and_not_yet_started_epoch_cannot_claim_full_support():
    data = linked_sources()
    data["coverage"] = "SOURCE_LIMIT_EXCEEDED"
    assert assess(data)["learning_context"]["policy_cohort"]["status"] == "INCOMPLETE_SOURCE"
    data["coverage"] = "COMPLETE_SNAPSHOT"
    data["epochs"][0]["value"]["epoch_start_ms"] = START + 10_000
    assert assess(data)["learning_context"]["policy_cohort"]["cohort"] is None


@pytest.mark.parametrize("change", ["regime", "pnl", "unverified"])
def test_policy_cohort_reuses_original_economic_and_regime_exclusions(change):
    data = linked_sources()
    if change == "regime":
        data["outcomes"]["paper:b1"]["value"]["regime"] = "bear"
    elif change == "pnl":
        data["outcomes"]["paper:b1"]["value"]["net_pnl"] = 100
    else:
        data["trades"][0]["value"]["verified_market_data"] = False
    assert assess(data)["learning_context"]["policy_cohort"]["cohort"]["sample_size"] == 0


@pytest.mark.parametrize("exit_build", ["unknown", "c" * 40])
def test_unverified_exit_policy_cannot_enter_equivalent_entry_cohort(exit_build):
    data = linked_sources()
    data["epochs"].append({"stored_at_ms": START + 1500, "value": {
        **data["epochs"][0]["value"], "epoch_id": "unlinked-exit-policy",
        "sha": "c" * 40, "epoch_start_ms": START + 1500}})
    data["trades"][1]["value"]["paper_build_sha"] = exit_build
    context = assess(data)["learning_context"]
    # The entry belongs to the linked policy, but its exit does not.
    assert context["same_symbol_prior_reconciled_closes"] == 1
    assert context["policy_cohort"]["cohort"]["sample_size"] == 0
    assert context["policy_cohort"]["excluded_exit_policy_count"] == 1


def test_linked_exit_observation_preserves_separate_entry_and_exit_lineage():
    data = linked_sources()
    data["epochs"][1]["value"]["epoch_start_ms"] = START + 1500
    data["epochs"][1]["stored_at_ms"] = START + 1500
    data["trades"][1]["value"]["paper_build_sha"] = "b" * 40
    cohort = assess(data)["learning_context"]["policy_cohort"]
    assert cohort["cohort"]["sample_size"] == 1
    assert cohort["excluded_exit_policy_count"] == 0
    assert cohort["trade_epoch_lineage"] == [{
        "outcome_id": "paper:b1", "entry_epoch_id": "epoch-1",
        "exit_policy_epoch_id": "epoch-2"}]


def test_database_reads_equivalence_asof_and_keeps_source_limits(tmp_path, monkeypatch):
    db = ProjectDatabase(f"sqlite:///{tmp_path / 'policy.db'}")
    db.initialize()
    db.put_json("paper_policy_equivalence", "link", linked_sources()["policy_links"][0]["value"])
    stored = db.get_json("paper_policy_equivalence", "link")["updated_at_ms"]
    assert read_sources(db, "scope-a", asof_ms=stored)["policy_links"] == []
    assert len(read_sources(db, "scope-a", asof_ms=stored+1)["policy_links"]) == 1
    assert read_sources(db, "scope-a", asof_ms=stored+1)["epochs"] == []
    monkeypatch.setattr("learning_engine.paper_economic_shadow.SOURCE_LIMIT", 0)
    assert read_sources(db, "scope-a", asof_ms=stored+1)["coverage"] == "SOURCE_LIMIT_EXCEEDED"


def test_observer_keeps_captured_history_and_default_support_after_new_link(tmp_path, monkeypatch):
    from autonomous_trading.economic_observer import EconomicOpportunityObserver

    db = ProjectDatabase(f"sqlite:///{tmp_path / 'observer.db'}")
    db.initialize()
    data = linked_sources()
    link = data.pop("policy_links")
    monkeypatch.setattr("autonomous_trading.economic_observer.read_sources", lambda *a, **k: data)
    observer = EconomicOpportunityObserver(db)
    early = opportunity(opportunity_id="before-link", paper_build_sha="b" * 40,
                        decision_time_ms=START + 3800)
    observer.record_batch([early])
    original = db.list_events("paper_economic_opportunities:scope-a", limit=10)[0]["payload"]
    data["policy_links"] = link
    late = opportunity(opportunity_id="after-link", paper_build_sha="b" * 40)
    observer.record_batch([early, late])
    rows = {r["entity_id"]: r["payload"]
            for r in db.list_events("paper_economic_opportunities:scope-a", limit=10)}
    assert len(rows) == 2 and rows["before-link"] == original
    before = db.get_json("paper_learning_shadow_contexts", original["learning_context_id"])["value"]
    after = db.get_json("paper_learning_shadow_contexts", rows["after-link"]["learning_context_id"])["value"]
    assert "policy_cohort" not in before
    assert after["policy_cohort"]["cohort"]["sample_size"] == 1
    assert all(r["learning_sample_size"] == 0 and r["execution_authority"] is False
               and r["edge"]["expected_net_edge_percent"] is None for r in rows.values())
