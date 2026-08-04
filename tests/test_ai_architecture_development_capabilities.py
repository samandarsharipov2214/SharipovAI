from __future__ import annotations

from ai_architecture_registry import architecture_snapshot, responsibility_owner


def test_development_change_capabilities_have_single_canonical_owner() -> None:
    expected = {
        "development_change_orchestration": "general_controller",
        "patch_policy": "security_guard",
        "protected_path_guard": "security_guard",
        "repair_memory": "learning_engine",
        "few_shot_curation": "learning_engine",
    }
    snapshot = architecture_snapshot()
    names = {organ["id"]: organ["name"] for organ in snapshot["organs"]}
    for capability, owner in expected.items():
        result = responsibility_owner(capability)
        assert result["status"] == "ok"
        assert result["recommendation"] == "extend_existing"
        assert result["owners"] == [{"id": owner, "name": names[owner]}]


def test_architecture_snapshot_exposes_self_healing_ownership() -> None:
    organs = {item["id"]: item for item in architecture_snapshot()["organs"]}
    assert "development_change_orchestration" in organs["general_controller"]["owns"]
    assert {"patch_policy", "protected_path_guard"} <= set(organs["security_guard"]["owns"])
    assert {"repair_memory", "few_shot_curation"} <= set(organs["learning_engine"]["owns"])
