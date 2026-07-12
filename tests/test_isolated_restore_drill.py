from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from tools.backup_integrity import BackupIntegrityError, sha256, verify_snapshot
from tools.isolated_restore_drill import run_restore_drill


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


def test_windows_restore_wrapper_stays_passive() -> None:
    script = (Path(__file__).resolve().parents[1] / "scripts/windows/test_isolated_restore.ps1").read_text(
        encoding="utf-8-sig"
    )
    assert "-m tools.isolated_restore_drill" in script
    assert "runtime\\remote_backups\\current" in script
    assert "runtime\\restore_drills" in script
    assert "bootstrap_pc_node" not in script
    assert "docker" not in script.lower()
    assert "Start-Process" not in script
