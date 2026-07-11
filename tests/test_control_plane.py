from pathlib import Path

import pytest

from control_plane import ControlPlane, component_registry


def test_registry_has_unique_ids() -> None:
    components = component_registry()
    ids = [item["id"] for item in components]
    assert len(ids) == len(set(ids))
    assert "pc_agent" in ids
    assert "general_ai" in ids


def test_snapshot_disables_arbitrary_shell(tmp_path: Path) -> None:
    plane = ControlPlane(tmp_path)
    snapshot = plane.snapshot()
    assert snapshot["control"]["arbitrary_shell_enabled"] is False
    assert snapshot["control"]["real_trading_enabled"] is False


def test_enqueue_accepts_only_allow_list(tmp_path: Path) -> None:
    plane = ControlPlane(tmp_path)
    command = plane.enqueue("run_health_check", requested_by="test")
    assert command["status"] == "pending"
    assert list((tmp_path / "runtime" / "commands").glob("*.json"))
    with pytest.raises(ValueError):
        plane.enqueue("powershell arbitrary-command")
