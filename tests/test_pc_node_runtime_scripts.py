from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WINDOWS = ROOT / "scripts" / "windows"


def _read(name: str) -> str:
    path = WINDOWS / name
    assert path.exists(), f"missing Windows runtime script: {path}"
    return path.read_text(encoding="utf-8-sig")


def test_pc_agent_launcher_is_detached_single_instance_and_health_gated() -> None:
    script = _read("start_pc_agent.ps1")

    assert "pc_agent.pid" in script
    assert "pc_agent_status.json" in script
    assert "pc_agent.stdout.log" in script
    assert "pc_agent.stderr.log" in script
    assert "Start-Process" in script
    assert "Test-AgentHealthy" in script
    assert "did not become healthy" in script


def test_bootstrap_installs_starts_and_verifies_unified_agent() -> None:
    script = _read("bootstrap_pc_node.ps1")

    for required in (
        "setup_pc.ps1",
        "install_autostart.ps1",
        "start_pc_agent.ps1",
        "check_pc_node.ps1",
        "RequireManagedProcesses",
        "pc_node_installation.json",
    ):
        assert required in script

    assert "start_pc_node.ps1" not in script
    assert "start_backup.ps1" not in script


def test_health_check_verifies_agent_pid_status_web_and_backup() -> None:
    script = _read("check_pc_node.ps1")

    assert "RequireManagedProcesses" in script
    assert "pc_agent.pid" in script
    assert "pc_agent_status.json" in script
    assert "web_healthy" in script
    assert "backup_healthy" in script
    assert "Get-Process" in script


def test_autostart_uses_only_unified_pc_agent() -> None:
    script = _read("install_autostart.ps1")

    assert "start_pc_agent.ps1" in script
    assert "SharipovAI PC Agent.lnk" in script
    assert "SharipovAI PC Node.lnk" in script
    assert "Remove-Item" in script


def test_updater_restarts_agent_and_runs_managed_health_check() -> None:
    script = _read("update_pc_node.ps1")

    assert "pc_node_agent.py" in script
    assert "start_pc_agent.ps1" in script
    assert "RequireManagedProcesses" in script
    assert "pc_agent.pid" in script
    assert "start_pc_node.ps1" not in script
    assert "start_backup.ps1" not in script


def test_setup_fails_closed_on_dependency_and_backup_errors() -> None:
    script = _read("setup_pc.ps1")

    assert script.count("$LASTEXITCODE -ne 0") >= 4
    assert "bootstrap_pc_node.ps1 -SkipSetup" in script
