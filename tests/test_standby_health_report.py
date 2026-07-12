from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from tools.standby_health_report import build_report


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _prepare(root: Path, *, age_seconds: int = 0, sync_status: str = "ok", files: int = 1) -> None:
    created = datetime.now(UTC) - timedelta(seconds=age_seconds)
    entries = [
        {"path": f"file-{index}.json", "bytes": 2, "sha256": "0" * 64}
        for index in range(files)
    ]
    _write_json(
        root / "runtime" / "remote_backups" / "current" / "manifest.json",
        {
            "schema": 1,
            "source": "vps",
            "created_at": created.isoformat(),
            "file_count": files,
            "files": entries,
        },
    )
    _write_json(
        root / "runtime" / "vps_backup_sync_status.json",
        {"schema": 1, "status": sync_status, "completed_at": datetime.now(UTC).isoformat()},
    )


def test_ready_when_verified_sync_is_fresh(tmp_path: Path) -> None:
    _prepare(tmp_path, age_seconds=60)
    report = build_report(tmp_path, maximum_age_seconds=7200)
    assert report["status"] == "READY"
    assert report["failover_allowed"] is True
    assert report["reasons"] == []


def test_stale_when_verified_backup_is_too_old(tmp_path: Path) -> None:
    _prepare(tmp_path, age_seconds=7201)
    report = build_report(tmp_path, maximum_age_seconds=7200)
    assert report["status"] == "STALE"
    assert report["failover_allowed"] is False
    assert "verified VPS backup is stale" in report["reasons"]


def test_blocked_when_sync_failed(tmp_path: Path) -> None:
    _prepare(tmp_path, sync_status="error")
    report = build_report(tmp_path, maximum_age_seconds=7200)
    assert report["status"] == "BLOCKED"
    assert report["failover_allowed"] is False
    assert any("synchronization" in reason for reason in report["reasons"])


def test_blocked_without_manifest(tmp_path: Path) -> None:
    _write_json(tmp_path / "runtime" / "vps_backup_sync_status.json", {"status": "ok"})
    report = build_report(tmp_path, maximum_age_seconds=7200)
    assert report["status"] == "BLOCKED"
    assert report["backup"]["age_seconds"] is None


def test_blocked_for_empty_backup(tmp_path: Path) -> None:
    _prepare(tmp_path, files=0)
    report = build_report(tmp_path, maximum_age_seconds=7200)
    assert report["status"] == "BLOCKED"
    assert "verified backup contains no files" in report["reasons"]
