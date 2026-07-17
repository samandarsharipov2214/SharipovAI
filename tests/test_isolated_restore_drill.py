from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from tools.backup_integrity import BackupIntegrityError, sha256, verify_snapshot
from tools.isolated_restore_drill import run_restore_drill


ROOT = Path(__file__).resolve().parents[1]


def make_snapshot(root: Path) -> Path:
    snapshot = root / "snapshot"
    data = snapshot / "data"
    data.mkdir(parents=True)

    database = data / "sharipovai_shared.db"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE events (id INTEGER PRIMARY KEY, value TEXT NOT NULL)")
        connection.execute("INSERT INTO events(value) VALUES (?)", ("restore-drill",))
        connection.commit()

    settings = data / "settings.json"
    settings.write_text(json.dumps({"live_trading": False}), encoding="utf-8")

    files = []
    for path in sorted(data.rglob("*")):
        if path.is_file():
            files.append(
                {
                    "path": path.relative_to(data).as_posix(),
                    "bytes": path.stat().st_size,
                    "sha256": sha256(path),
                }
            )
    manifest = {
        "schema": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "files": files,
        "file_count": len(files),
        "source": "test",
    }
    (snapshot / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return snapshot


def test_restore_drill_copies_and_reverifies_snapshot(tmp_path: Path) -> None:
    source = make_snapshot(tmp_path / "source")
    report = run_restore_drill(source, tmp_path / "drills")

    assert report["status"] == "ok"
    assert report["activation_performed"] is False
    assert report["network_services_started"] is False
    assert report["file_count"] == 2
    assert report["sqlite_checks"] == [
        {"path": "sharipovai_shared.db", "status": "ok", "result": ["ok"]}
    ]

    restored = Path(report["restored_snapshot"])
    restored_manifest = verify_snapshot(restored)
    assert restored_manifest["file_count"] == 2
    assert Path(report["report_path"]).is_file()


def test_restore_drill_rejects_tampered_source(tmp_path: Path) -> None:
    source = make_snapshot(tmp_path / "source")
    (source / "data" / "settings.json").write_text("tampered", encoding="utf-8")

    with pytest.raises(BackupIntegrityError, match="backup size mismatch|checksum mismatch"):
        run_restore_drill(source, tmp_path / "drills")


def test_restore_drill_rejects_destination_inside_source(tmp_path: Path) -> None:
    source = make_snapshot(tmp_path / "source")

    with pytest.raises(BackupIntegrityError, match="outside the source snapshot"):
        run_restore_drill(source, source / "restore-drills")


def test_windows_restore_wrapper_is_passive_retained_and_network_free() -> None:
    script = (ROOT / "scripts/windows/test_isolated_restore.ps1").read_text(encoding="utf-8-sig")
    for marker in (
        "-m tools.isolated_restore_drill",
        r"runtime\remote_backups\current",
        r"runtime\restore_drills",
        r"runtime\restore_drill_status.json",
        "[int]$RetainRuns = 12",
        "Select-Object -Skip $RetainRuns",
        "$report.activation_performed -ne $false",
        "$report.network_services_started -ne $false",
    ):
        assert marker in script
    for forbidden in ("bootstrap_pc_node", "Start-Process"):
        assert forbidden not in script
    assert "docker" not in script.lower()


def test_weekly_restore_installer_is_passive_and_start_when_available() -> None:
    script = (ROOT / "scripts/windows/install_weekly_restore_drill.ps1").read_text(encoding="utf-8-sig")
    for marker in (
        '$taskName = "SharipovAI Weekly Restore Drill"',
        "New-ScheduledTaskTrigger -Weekly",
        "-DaysOfWeek $scheduledDay",
        "-StartWhenAvailable",
        "-MultipleInstances IgnoreNew",
        "-RetainRuns $RetainRuns",
        '[string]$DayOfWeek = "Sunday"',
        '[string]$Time = "04:00"',
        r"runtime\restore_drill_status.json",
        "$status.activation_performed -ne $false",
        "$status.network_services_started -ne $false",
    ):
        assert marker in script
    assert "bootstrap_pc_node" not in script
    assert "docker" not in script.lower()
