from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8-sig")


def test_bootstrap_is_passive_by_default() -> None:
    script = read("scripts/windows/bootstrap_pc_node.ps1")
    assert "[switch]$Activate" in script
    assert "if ($Activate)" in script
    assert 'mode = $(if ($Activate) { "active" } else { "standby" })' in script
    assert "disabled_until_failover" in script


def test_active_autostart_requires_explicit_switch() -> None:
    script = read("scripts/windows/install_autostart.ps1")
    assert "[switch]$EnableActiveNode" in script
    assert "if (-not $EnableActiveNode)" in script
    assert "PC node remains passive" in script


def test_windows_sync_is_scheduled_without_parallel_runs() -> None:
    script = read("scripts/windows/install_vps_backup_sync.ps1")
    assert '"SharipovAI VPS Backup Sync"' in script
    assert "-MultipleInstances IgnoreNew" in script
    assert "Initial VPS backup synchronization failed" in script
    assert "remote_backups\\current\\manifest.json" in script


def test_vps_backup_timer_is_persistent_and_hourly() -> None:
    script = read("deploy/vps/install_backup_timer.sh")
    assert "OnUnitActiveSec=1h" in script
    assert "Persistent=true" in script
    assert "systemctl start sharipovai-backup.service" in script
    assert 'test -s "$latest"' in script


def test_failover_refuses_healthy_vps_without_force() -> None:
    script = read("scripts/windows/activate_pc_failover.ps1")
    assert "VPS is healthy. Refusing PC failover" in script
    assert "-not $Force" in script
    assert "restore_verified_backup.py" in script
    assert "check_pc_node.ps1" in script


def test_failover_requires_ready_standby_even_with_force() -> None:
    script = read("scripts/windows/activate_pc_failover.ps1")
    assert "standby_health_report.py" in script
    assert "PC failover blocked because standby is not READY" in script
    assert "Force may bypass only the live VPS check" in script
    assert "maximum_backup_age_seconds" in script


def test_sync_persists_success_and_failure_status() -> None:
    script = read("scripts/windows/sync_vps_backup.ps1")
    assert "vps_backup_sync_status.json" in script
    assert 'Save-SyncStatus "ok"' in script
    assert 'Save-SyncStatus "error"' in script


def test_readiness_command_writes_a_visible_report() -> None:
    script = read("scripts/windows/check_standby_readiness.ps1")
    assert "standby_health_report.py" in script
    assert "runtime\\standby_health.json" in script
    assert "SharipovAI standby status" in script
