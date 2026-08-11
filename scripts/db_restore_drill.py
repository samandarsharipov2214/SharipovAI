"""Validate a SharipovAI SQLite backup by restoring it into an isolated temp copy.

The drill is read-only with respect to the source backup. It copies the file,
runs SQLite integrity_check, verifies schema_migrations, and optionally initializes
ProjectDatabase against the restored copy to detect incompatible schema state.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import tempfile
from pathlib import Path

from storage.project_database import ProjectDatabase


def validate_sqlite_backup(source: Path) -> dict[str, object]:
    source = source.resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    if source.stat().st_size <= 0:
        raise ValueError("backup is empty")

    with tempfile.TemporaryDirectory(prefix="sharipovai-restore-drill-") as tmp:
        restored = Path(tmp) / "restored.db"
        # A filesystem copy can miss committed WAL pages.  SQLite's backup API
        # reads a consistent snapshot without changing the source backup.
        source_connection = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
        destination_connection = sqlite3.connect(restored)
        try:
            source_connection.backup(destination_connection)
        finally:
            destination_connection.close()
            source_connection.close()
        connection = sqlite3.connect(restored)
        try:
            integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
            if integrity.lower() != "ok":
                raise RuntimeError(f"integrity_check failed: {integrity}")
            tables = {
                str(row[0])
                for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            }
            if "schema_migrations" not in tables:
                raise RuntimeError("schema_migrations table missing")
            version_row = connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
            schema_version = int(version_row[0] or 0)
        finally:
            connection.close()

        db = ProjectDatabase(f"sqlite:///{restored}")
        db.initialize()
        health = db.health()
        if health.get("status") != "ok":
            raise RuntimeError(f"restored database health failed: {health}")
        return {
            "status": "ok",
            "backend": "sqlite",
            "source_bytes": source.stat().st_size,
            "integrity_check": "ok",
            "restore_method": "sqlite_backup_api",
            "schema_version": schema_version,
            "health": health,
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("backup", type=Path)
    args = parser.parse_args()
    print(json.dumps(validate_sqlite_backup(args.backup), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
