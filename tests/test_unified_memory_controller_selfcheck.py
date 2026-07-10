from pathlib import Path

from general_controller import GeneralController
from memory.unified_memory import UnifiedMemory
from system_selfcheck import run_system_selfcheck


def test_unified_memory_is_namespaced_versioned_and_persistent(tmp_path: Path) -> None:
    path = tmp_path / "shared.json"
    memory = UnifiedMemory(path)
    first = memory.put("project", "plan", {"step": 1}, source="telegram")
    second = memory.put("project", "plan", {"step": 2}, source="dashboard")

    assert first.version == 1
    assert second.version == 2
    assert UnifiedMemory(path).get("project", "plan").value == {"step": 2}
    assert memory.list_namespace("project")[0].source == "dashboard"


def test_general_controller_reuses_existing_owner_and_blocks_unknown() -> None:
    controller = GeneralController()
    market = controller.route("market_analysis")
    unknown = controller.route("brand_new_duplicate_ai")

    assert market.allowed is True
    assert market.selected_owner == "market_agent"
    assert unknown.allowed is False


def test_general_controller_blocks_duplicate_architecture_change() -> None:
    result = GeneralController().approve_architecture_change(["market_analysis"])
    assert result["allowed"] is False
    assert result["conflicts"] == {"market_analysis": ["market_agent"]}


def test_full_system_selfcheck_passes() -> None:
    result = run_system_selfcheck()
    assert result["status"] == "ok"
    assert all(check["ok"] for check in result["checks"].values())
