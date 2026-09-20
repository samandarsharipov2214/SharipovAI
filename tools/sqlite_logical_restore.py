"""Restore a verified logical snapshot in an isolated, bounded directory.

The 20 GiB exporter floor is recovery workspace, not permission for persistent
backup growth. A restore requires an explicit raw-size reservation in addition
to a 2 GiB runtime reserve; the source and verified backup are never modified.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import shutil
import sqlite3
import time
from pathlib import Path

from tools.backup_integrity import BackupIntegrityError, MAX_TOTAL_BYTES, sha256


def restore_database(source: Path, target: Path, metadata: dict, *, reserve_bytes: int = 2 * 1024**3) -> None:
    if target.exists() or target.is_symlink():
        raise BackupIntegrityError("logical restore target already exists")
    # Rebuilding indexes can require temporary space as well as database pages.
    budget = min(MAX_TOTAL_BYTES, metadata["logical_bytes"] * 3 // 2 + 16 * 1024**2)
    if shutil.disk_usage(target.parent).free < reserve_bytes + budget:
        raise BackupIntegrityError("insufficient isolated restore workspace")
    deadline = time.monotonic() + 3600
    connection = sqlite3.connect(target)
    digest = hashlib.sha256()
    total = count = 0
    try:
        connection.execute("PRAGMA journal_mode=OFF")  # Disposable destination only.
        connection.execute("PRAGMA temp_store=FILE")
        connection.execute(f"PRAGMA max_page_count={budget // 4096}")
        def progress():
            return int(time.monotonic() > deadline or shutil.disk_usage(target.parent).free < reserve_bytes)
        connection.set_progress_handler(progress, 10000)
        def authorize(action, first, second, *_):
            if action in (sqlite3.SQLITE_ATTACH, sqlite3.SQLITE_DETACH):
                return sqlite3.SQLITE_DENY
            if action == sqlite3.SQLITE_FUNCTION and str(second).lower() == "load_extension":
                return sqlite3.SQLITE_DENY
            if action == sqlite3.SQLITE_PRAGMA and str(first).lower() not in {"writable_schema"}:
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK
        connection.set_authorizer(authorize)
        with gzip.open(source, "rb") as stream:
            while data := stream.readline(64 * 1024**2 + 1):
                total += len(data)
                count += 1
                if (len(data) > 64 * 1024**2 or total > metadata["uncompressed_bytes"]
                        or count > metadata["statements"]):
                    raise BackupIntegrityError("logical stream exceeds declared bounds")
                digest.update(data)
                statement = json.loads(data)
                if not isinstance(statement, str):
                    raise BackupIntegrityError("invalid logical statement")
                connection.execute(statement)
        if (total != metadata["uncompressed_bytes"] or count != metadata["statements"]
                or digest.hexdigest() != metadata["stream_sha256"] or connection.in_transaction):
            raise BackupIntegrityError("logical stream integrity failure")
        connection.close()
        # Reopen to load virtual-table definitions emitted by SQLite iterdump.
        connection = sqlite3.connect(target)
        connection.set_progress_handler(progress, 10000)
        if connection.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
            raise BackupIntegrityError("restored SQLite quick_check failed")
        connection.close()
        with target.open("rb") as handle:
            os.fsync(handle.fileno())
    except BaseException:
        connection.close()
        target.unlink(missing_ok=True)
        raise


def materialize(snapshot: Path, manifest: dict) -> dict:
    """Convert a verified schema-2 staging snapshot to ordinary schema 1."""
    if manifest["schema"] == 1:
        return manifest
    entries = {item["path"]: item for item in manifest["files"]}
    for item in manifest["sqlite_logical"]:
        source = snapshot / "data" / item["path"]
        target = snapshot / "data" / item["database_path"]
        restore_database(source, target, item)
        entries.pop(item["path"])
        entries[item["database_path"]] = {"path": item["database_path"],
            "bytes": target.stat().st_size, "sha256": sha256(target)}
        source.unlink()
    result = {**manifest, "schema": 1, "files": list(entries.values()), "sqlite_logical": []}
    result["file_count"] = len(result["files"])
    (snapshot / "manifest.json").write_text(json.dumps(result))
    return result
