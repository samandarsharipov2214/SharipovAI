from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from tools.standby_health_report import build_report


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _prepare(root: Path, *, age_seconds: int = 0, sync_status: str = "ok", files: int = 1) -> dict:
    created = datetime.now(UTC) - timedelta(seconds=age_seconds)
    snapshot = root / "runtime" / "remote_backups" / "current"
    data = snapshot / "data"
    data.mkdir(parents=True, exist_ok=True)
    entries = []
    for index in range(files):
        content = json.dumps({"index": index}, sort_keys=True).encode("utf-8")
        relative = f"file-{index}.json"
        (data / relative).write_bytes(content)
        entries.append(
            {
                "path": relative,
                "bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        )
    manifest = {
        "schema": 1,
        "source": "vps",
        "created_at": created.isoformat(),
        "file_count": files,
        "files": entries,
    }
    _write_json(snapshot / "manifest.json", manifest)
    _write_json(
        root / "runtime" / "vps_backup_sync_status.json",
        {
            "schema": 1,
            "status": sync_status,
            "completed_at": datetime.now(UTC).isoformat(),
            "manifest_created_at": manifest["created_at"],
            "file_count": files,
        },
    )
    return manifest


def test_ready_when_verified_sync_is_fresh(tmp_path: Path) -> None:
    _prepare(tmp_path, age_seconds=60)
    report = build_report(tmp_path, maximum_age_seconds=7200)
    assert report["status"] == "READY"
    assert report["failover_allowed"] is True
    assert report["backup"]["integrity_verified"] is True
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


def test_blocked_when_snapshot_bytes_are_tampered(tmp_path: Path) -> None:
    _prepare(tmp_path)
    target = tmp_path / "runtime" / "remote_backups" / "current" / "data" / "file-0.json"
    target.write_text("tampered", encoding="utf-8")

    report = build_report(tmp_path, maximum_age_seconds=7200)

    assert report["status"] == "BLOCKED"
    assert report["backup"]["integrity_verified"] is False
    assert any("integrity verification failed" in reason for reason in report["reasons"])


def test_blocked_when_sync_status_does_not_match_snapshot(tmp_path: Path) -> None:
    _prepare(tmp_path)
    status_path = tmp_path / "runtime" / "vps_backup_sync_status.json"
    status = json.loads(status_path.read_text(encoding="utf-8"))
    status["manifest_created_at"] = "2020-01-01T00:00:00+00:00"
    _write_json(status_path, status)

    report = build_report(tmp_path, maximum_age_seconds=7200)

    assert report["status"] == "BLOCKED"
    assert any("does not match" in reason for reason in report["reasons"])


def test_blocked_when_pc_is_already_marked_active(tmp_path: Path) -> None:
    _prepare(tmp_path)
    _write_json(tmp_path / "runtime" / "active_node.json", {"active_node": "pc"})

    report = build_report(tmp_path, maximum_age_seconds=7200)

    assert report["status"] == "BLOCKED"
    assert report["failover_allowed"] is False
    assert any("already marked active" in reason for reason in report["reasons"])
