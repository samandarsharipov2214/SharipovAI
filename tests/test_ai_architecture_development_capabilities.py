from __future__ import annotations

from ai_architecture_registry import CANONICAL_AI_ORGANS, responsibility_owner


def _organ(identifier: str):
    return next(item for item in CANONICAL_AI_ORGANS if item.id == identifier)


def test_development_capabilities_are_owned_by_existing_ai_organs() -> None:
    general = _organ("general_controller")
    security = _organ("security_guard")
    learning = _organ("learning_engine")

    assert "development_change_orchestration" in general.owns
    assert {"patch_policy", "protected_path_guard"} <= set(security.owns)
    assert {"repair_memory", "few_shot_curation"} <= set(learning.owns)


def test_new_capabilities_resolve_to_one_canonical_owner() -> None:
    expected = {
        "development_change_orchestration": "general_controller",
        "patch_policy": "security_guard",
        "protected_path_guard": "security_guard",
        "repair_memory": "learning_engine",
        "few_shot_curation": "learning_engine",
    }

    for capability, owner in expected.items():
        result = responsibility_owner(capability)
        assert result["status"] == "ok"
        assert result["owners"] == [
            {
                "id": owner,
                "name": _organ(owner).name,
            }
        ]
        assert result["recommendation"] == "extend_existing"
