from ai_architecture_registry import architecture_snapshot, canonical_id, responsibility_owner


def test_canonical_ai_count_and_unique_ids() -> None:
    snapshot = architecture_snapshot()
    ids = [item["id"] for item in snapshot["organs"]]
    assert snapshot["canonical_ai_count"] == 9
    assert len(ids) == len(set(ids))


def test_supervisor_is_general_controller_capability() -> None:
    assert canonical_id("supervisor_ai") == "general_controller"
    assert responsibility_owner("supervision")["owners"] == [
        {"id": "general_controller", "name": "General Controller AI"}
    ]


def test_stress_lab_belongs_to_risk_engine() -> None:
    assert canonical_id("stress_lab_ai") == "risk_engine"
    assert responsibility_owner("stress_lab")["recommendation"] == "extend_existing"


def test_reports_belong_to_portfolio_engine() -> None:
    assert canonical_id("portfolio_report_ai") == "portfolio_engine"
    assert responsibility_owner("reports")["owners"] == [
        {"id": "portfolio_engine", "name": "Portfolio & Reports AI"}
    ]


def test_confidence_and_consensus_share_decision_quality_owner() -> None:
    assert canonical_id("confidence_engine") == "decision_quality"
    assert canonical_id("consensus_engine") == "decision_quality"


def test_interfaces_are_not_ai_organs() -> None:
    snapshot = architecture_snapshot()
    assert "telegram_bot" in snapshot["non_ai_components"]
    assert "mini_app_ui" in snapshot["non_ai_components"]
    assert "evidence_vault" in snapshot["non_ai_components"]
