from ai_architecture_registry import architecture_snapshot, canonical_id, responsibility_owner
from ai_evidence import REAL_DATA_VIRTUAL_EXECUTION, enrich_ai_status, system_scoreboard


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


def test_scoreboard_contains_exactly_nine_canonical_organs() -> None:
    scoreboard = system_scoreboard()
    ids = [item["id"] for item in scoreboard["agents"]]
    assert scoreboard["total"] == 9
    assert scoreboard["canonical_total"] == 9
    assert len(ids) == len(set(ids))
    assert "telegram_bot_ai" not in ids
    assert "mini_app_ui_ai" not in ids
    assert "stress_lab_ai" not in ids


def test_legacy_execution_alias_does_not_create_extra_ai() -> None:
    enriched = enrich_ai_status({"id": "demo_trader", "verdict": "работает"})
    assert enriched["id"] == "virtual_execution"
    assert enriched["real_data_status"] == REAL_DATA_VIRTUAL_EXECUTION


def test_runtime_rows_override_defaults_without_duplication() -> None:
    scoreboard = system_scoreboard(
        [
            {"id": "supervisor_ai", "name": "Old supervisor", "verdict": "частично работает"},
            {"id": "stress_bot", "name": "Old stress", "verdict": "работает"},
            {"id": "telegram_bot_ai", "name": "Interface", "verdict": "работает"},
        ]
    )
    by_id = {item["id"]: item for item in scoreboard["agents"]}
    assert scoreboard["total"] == 9
    assert by_id["general_controller"]["verdict"] == "частично работает"
    assert by_id["risk_engine"]["verdict"] == "работает"
    assert "telegram_bot_ai" not in by_id
