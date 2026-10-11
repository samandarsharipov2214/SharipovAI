from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "deploy" / "vps" / "install_backup_timer.sh"
VERIFIER = ROOT / "deploy" / "vps" / "verify_backup_timer.sh"
RUNNER = ROOT / "deploy" / "vps" / "backup_timer_run.sh"


def test_backup_timer_targets_production_repo_and_runs_at_least_hourly() -> None:
    source = INSTALLER.read_text(encoding="utf-8")

    assert "APP_DIR=${APP_DIR:-/opt/sharipovai-repo}" in source
    assert "OnCalendar=hourly" in source
    assert "OnUnitActiveSec=" not in source
    assert "OnBootSec=" not in source
    assert "Persistent=true" in source
    assert "AccuracySec=30s" in source
    assert "RandomizedDelaySec=0" in source
    assert "systemctl enable --now sharipovai-backup.timer" in source
    assert "systemctl is-active --quiet sharipovai-backup.timer" in source
    assert "verify_backup_timer.sh" in source
    assert "backup_timer_run.sh" in source
    assert "ExecStart=/usr/bin/bash $RUNNER" in source


def test_backup_timer_verifies_first_archive_and_checksum() -> None:
    source = INSTALLER.read_text(encoding="utf-8")

    assert "systemctl start sharipovai-backup.service" in source
    assert "latest.tar.gz" in source
    assert "sha256sum -c" in source
    assert "first backup service run failed" in source
    assert "backup checksum verification failed" in source
    assert "BACKUP_MAX_AGE_SECONDS=3600" in source
    assert "verify_backup_timer.sh" in source


def test_backup_verifier_fails_closed_on_stale_or_inactive_backup() -> None:
    source = VERIFIER.read_text(encoding="utf-8")

    assert 'systemctl is-enabled --quiet "$TIMER"' in source
    assert 'systemctl is-active --quiet "$TIMER"' in source
    assert 'systemctl is-failed --quiet "$SERVICE"' in source
    assert '(( age <= MAX_AGE ))' in source
    assert "latest backup checksum verification failed" in source
    assert "NextElapseUSecRealtime" in source
    assert "TimersCalendar" in source
    assert "TimersCalendar" in source
    assert "LastTriggerUSec" in source
    assert "MAX_AGE=${BACKUP_MAX_AGE_SECONDS:-3600}" in source


def test_contention_is_recorded_as_skip_not_verified_backup() -> None:
    exporter = (ROOT / "deploy" / "vps" / "export_backup.sh").read_text(encoding="utf-8")
    runner = RUNNER.read_text(encoding="utf-8")
    verifier = VERIFIER.read_text(encoding="utf-8")

    assert "SHARIPOVAI_BACKUP_LOCK_BUSY_EXIT" in exporter
    assert "SKIPPED_ACTIVE_EXPORT" in exporter
    assert "SHARIPOVAI_BACKUP_LOCK_BUSY_EXIT=75 bash \"$EXPORTER\"" in runner
    assert "write_status SKIPPED_ACTIVE_EXPORT 75" in runner
    assert "write_status VERIFIED 0" in runner
    assert "timer_outcome" in verifier
    assert "latest backup timer run failed" in verifier
