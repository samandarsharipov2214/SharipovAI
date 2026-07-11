from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WINDOWS = ROOT / "scripts" / "windows"


def _read(name: str) -> str:
    path = WINDOWS / name
    assert path.exists(), f"missing Windows runtime script: {path}"
    return path.read_text(encoding="utf-8-sig")


def test_pc_node_startup_is_managed_and_health_gated() -> None:
    script = _read("start_pc_node.ps1")

    assert "pc_node.pid" in script
    assert "pc_node.stdout.log" in script
    assert "pc_node.stderr.log" in script
    assert "Start-Process" in script
    assert "/health" in script
    assert "did not become healthy" in script


def test_backup_startup_is_single_instance_and_manifest_gated() -> None:
    script = _read("start_backup.ps1")

    assert "backup.pid" in script
    assert "current\\manifest.json" in script
    assert "Test-FreshManifest" in script
    assert "pc_node_backup.py" in script
    assert "did not become healthy" in script


def test_bootstrap_installs_starts_and_verifies_everything() -> None:
    script = _read("bootstrap_pc_node.ps1")

    for required in (
        "setup_pc.ps1",
        "install_autostart.ps1",
        "start_backup.ps1",
        "start_pc_node.ps1",
        "check_pc_node.ps1",
        "RequireManagedProcesses",
        "pc_node_installation.json",
    ):
        assert required in script


def test_health_check_can_require_managed_processes() -> None:
    script = _read("check_pc_node.ps1")

    assert "RequireManagedProcesses" in script
    assert "pc_node.pid" in script
    assert "backup.pid" in script
    assert "Get-Process" in script


def test_autostart_uses_hardened_entrypoints() -> None:
    script = _read("install_autostart.ps1")

    assert "start_pc_node.ps1" in script
    assert "start_backup.ps1" in script
    assert "-WindowStyle Hidden" in script
