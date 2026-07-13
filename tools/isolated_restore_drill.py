"""Run a non-destructive restore drill from a verified SharipovAI snapshot."""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tools.backup_integrity import BackupIntegrityError, verify_snapshot


def _new_drill_directory(destination_root: Path, source: Path) -> Path:
    raw_root = Path(destination_root)
    if raw_root.is_symlink():
        raise BackupIntegrityError("restore drill destination root must not be a symlink")
    raw_root.mkdir(parents=True, exist_ok=True)
    root = raw_root.resolve()
    source_root = source.resolve()
    if root == source_root or root.is_relative_to(source_root):
        raise BackupIntegrityError("restore drill destination must be outside the source snapshot")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    candidate = root / stamp
    suffix = 1
    while candidate.exists():
        candidate = root / f"{stamp}-{suffix}"
        suffix += 1
    candidate.mkdir()
    return candidate


def _sqlite_integrity(path: Path) -> dict[str, Any]:
    uri = path.resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        rows = [str(row[0]) for row in connection.execute("PRAGMA integrity_check")]
    ok = rows == ["ok"]
    return {
        "path": path.name,
        "status": "ok" if ok else "error",
        "result": rows[:20],
    }


def run_restore_drill(snapshot: Path, destination_root: Path) -> dict[str, Any]:
    source = Path(snapshot)
    manifest = verify_snapshot(source)
    drill_dir = _new_drill_directory(Path(destination_root), source)
    restored_snapshot = drill_dir / "snapshot"
    report_path = drill_dir / "restore_drill_report.json"

    try:
        restored_snapshot.mkdir()
        shutil.copy2(source / "manifest.json", restored_snapshot / "manifest.json")
        shutil.copytree(source / "data", restored_snapshot / "data")
        restored_manifest = verify_snapshot(restored_snapshot)

        sqlite_checks = []
        for entry in restored_manifest["files"]:
            relative = Path(*Path(entry["path"]).parts)
            if relative.suffix.lower() in {".db", ".sqlite", ".sqlite3"}:
                sqlite_checks.append(_sqlite_integrity(restored_snapshot / "data" / relative))
        if any(check["status"] != "ok" for check in sqlite_checks):
            raise BackupIntegrityError("restored SQLite integrity check failed")

        report = {
            "schema": 1,
            "status": "ok",
            "source_snapshot": str(source.resolve()),
            "restored_snapshot": str(restored_snapshot.resolve()),
            "report_path": str(report_path.resolve()),
            "source_created_at": manifest["created_at"],
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "file_count": restored_manifest["file_count"],
            "total_bytes": sum(int(entry["bytes"]) for entry in restored_manifest["files"]),
            "sqlite_checks": sqlite_checks,
            "activation_performed": False,
            "network_services_started": False,
        }
    except Exception as exc:
        report = {
            "schema": 1,
            "status": "error",
            "source_snapshot": str(source.resolve()),
            "restored_snapshot": str(restored_snapshot.resolve()),
            "report_path": str(report_path.resolve()),
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "error": str(exc),
            "activation_performed": False,
            "network_services_started": False,
        }
        report_path.write_text(json.dumps(report, ensure_ascii=True, indent=2), encoding="utf-8")
        raise

    report_path.write_text(json.dumps(report, ensure_ascii=True, indent=2), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--destination-root", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = run_restore_drill(args.snapshot, args.destination_root)
    except (OSError, ValueError, sqlite3.DatabaseError, BackupIntegrityError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=True, sort_keys=True))
        return 1
    print(json.dumps(report, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
