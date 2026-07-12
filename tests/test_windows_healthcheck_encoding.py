from pathlib import Path


def test_pc_node_healthcheck_is_windows_powershell_51_safe() -> None:
    path = Path("scripts/windows/check_pc_node.ps1")
    payload = path.read_bytes()

    # Windows PowerShell 5.1 treats UTF-8 without BOM as the active ANSI code page.
    # Keep this entrypoint ASCII-only so parsing is deterministic on every locale.
    assert payload.isascii()

    text = payload.decode("ascii")
    assert "All PC node checks passed." in text
    assert "-RequireManagedProcesses" not in text
    assert "Test-ManagedProcess" in text
