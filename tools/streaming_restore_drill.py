"""Verify an immutable archive, then restore it without duplicate gzip trees.

Only a new isolated destination is written. The original logical restore's
capacity, SQL, deadline and integrity gates remain mandatory.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import re
import shutil
import sqlite3
import stat
import tarfile
import time
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Callable

from tools.backup_integrity import (
    BackupIntegrityError, MAX_ARCHIVE_MEMBERS, MAX_BACKUP_FILES, MAX_FILE_BYTES,
    MAX_TOTAL_BYTES, RESTORE_RESERVE_BYTES, RestoreWorkspace, _reject_symlink_chain,
    _safe_archive_member, _safe_relative_path, sha256, validate_manifest, verify_snapshot,
)
from tools.sqlite_logical_restore import restore_budget, restore_database_stream

CHUNK = 1024**2
MAX_MANIFEST_BYTES = 16 * CHUNK
# Bounded tar headers, padding and compression overhead, not a larger data budget.
MAX_CONTAINER_BYTES = MAX_TOTAL_BYTES + 64 * CHUNK


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _identity(handle: BinaryIO) -> tuple[int, ...]:
    info = os.fstat(handle.fileno())
    if not stat.S_ISREG(info.st_mode):
        raise BackupIntegrityError("backup archive must be a regular file")
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def _check_source_path(path: Path, identity: tuple[int, ...]) -> None:
    info = path.lstat()
    observed = info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns
    if not stat.S_ISREG(info.st_mode) or observed != identity:
        raise BackupIntegrityError("source archive path changed")


class _Reader:
    """A bounded forward reader; hashes bytes exactly once as they are consumed."""

    def __init__(self, source: BinaryIO, limit: int, deadline: float, *, digest: bool = True):
        self.source, self.limit, self.deadline = source, limit, deadline
        self.count = 0
        self.digest = hashlib.sha256() if digest else None

    def read(self, size: int = -1) -> bytes:
        if time.monotonic() > self.deadline:
            raise BackupIntegrityError("isolated restore deadline exceeded")
        # No unbounded allocation, including when a caller requests read(-1).
        size = min(CHUNK, self.limit - self.count + 1) if size < 0 else min(size, self.limit - self.count + 1)
        data = self.source.read(size)
        self.count += len(data)
        if self.count > self.limit:
            raise BackupIntegrityError("archive stream exceeds declared bounds")
        if self.digest is not None:
            self.digest.update(data)
        return data

    def drain(self) -> None:
        while self.read(CHUNK):
            pass


def _entries(manifest: dict) -> dict[str, dict]:
    return {_safe_relative_path(entry["path"]).as_posix(): entry for entry in manifest["files"]}


def _logical_entries(manifest: dict) -> dict[str, dict]:
    # Use the same canonical paths as manifest validation. Otherwise accepted
    # aliases (e.g. nested/./history.gz) could silently skip materialization.
    if manifest["schema"] != 2:
        return {}
    return {_safe_relative_path(item["path"]).as_posix(): {
        **item, "database_path": _safe_relative_path(item["database_path"]).as_posix(),
    } for item in manifest["sqlite_logical"]}


def _output_paths(manifest: dict) -> set[str]:
    logical = {key: item["database_path"] for key, item in _logical_entries(manifest).items()}
    paths = {logical.get(key, key) for key in _entries(manifest)}
    for key in paths:
        if any(parent.as_posix() in paths for parent in PurePosixPath(key).parents):
            raise BackupIntegrityError("restore target path collision")
    return paths


def estimate_restore_workspace(manifest: dict) -> dict[str, int]:
    """Conservative full assembly admission; this does NOT verify an archive."""
    validate_manifest(manifest)
    _output_paths(manifest)
    logical = _logical_entries(manifest)
    sources = set(logical)
    database_budget = sum(restore_budget(item) for item in logical.values())
    other_bytes = sum(entry["bytes"] for key, entry in _entries(manifest).items() if key not in sources)
    # Original manifest, materialized manifest, report and write slack.
    metadata_bytes = 3 * len(json.dumps(manifest, ensure_ascii=True, sort_keys=True, indent=2).encode()) + CHUNK
    return {"logical_database_budget_bytes": database_budget, "other_output_bytes": other_bytes,
            "metadata_and_slack_bytes": metadata_bytes, "runtime_reserve_bytes": RESTORE_RESERVE_BYTES,
            "required_free_bytes": database_budget + other_bytes + metadata_bytes + RESTORE_RESERVE_BYTES}


def _scan_archive(handle: BinaryIO, expected_hash: str, identity: tuple[int, ...], deadline: float,
                  visitor: Callable[[str, _Reader, dict], None] | None = None,
                  approved_manifest: dict | None = None) -> dict:
    if _identity(handle) != identity:
        raise BackupIntegrityError("source archive changed")
    handle.seek(0)
    raw = _Reader(handle, identity[2], deadline)
    names: set[str] = set()
    files: set[str] = set()
    directories: set[str] = set()
    total = 0
    manifest = None
    expected: dict[str, dict] = {}
    outputs: set[str] = set()
    with gzip.GzipFile(fileobj=raw, mode="rb") as decompressed:
        decoded = _Reader(decompressed, MAX_CONTAINER_BYTES, deadline, digest=False)
        with tarfile.open(fileobj=decoded, mode="r|") as archive:
            for member in archive:
                key = _safe_archive_member(member.name).as_posix()
                if key in names:
                    raise BackupIntegrityError(f"duplicate archive member: {key}")
                names.add(key)
                if len(names) > MAX_ARCHIVE_MEMBERS:
                    raise BackupIntegrityError("backup archive contains too many members")
                if not (member.isdir() or member.isfile()):
                    raise BackupIntegrityError(f"unsafe archive member type: {key}")
                if manifest is None and key != "manifest.json":
                    raise BackupIntegrityError("streaming archive must start with manifest.json")
                parents = {parent.as_posix() for parent in PurePosixPath(key).parents}
                if parents & files or (member.isfile() and key in directories):
                    raise BackupIntegrityError("archive file/directory path collision")
                directories.update(parents)
                if member.isdir():
                    if key == "manifest.json" or (key.startswith("data/") and key.removeprefix("data/") in outputs):
                        raise BackupIntegrityError("restore target path collision")
                    directories.add(key)
                    continue
                files.add(key)
                if len(files) > MAX_BACKUP_FILES + 1:
                    raise BackupIntegrityError("backup archive contains too many files")
                if member.size < 0 or member.size > MAX_FILE_BYTES:
                    raise BackupIntegrityError(f"archive member exceeds size limit: {key}")
                total += member.size
                if total > MAX_TOTAL_BYTES:
                    raise BackupIntegrityError("backup archive exceeds total size limit")
                incoming = archive.extractfile(member)
                if incoming is None:
                    raise BackupIntegrityError(f"cannot read archive member: {key}")
                with incoming:
                    reader = _Reader(incoming, member.size, deadline)
                    if key == "manifest.json":
                        if member.size > MAX_MANIFEST_BYTES:
                            raise BackupIntegrityError("backup manifest exceeds size limit")
                        body = bytearray()
                        while chunk := reader.read(CHUNK):
                            body.extend(chunk)
                        manifest = validate_manifest(json.loads(body))
                        if approved_manifest is not None and manifest != approved_manifest:
                            raise BackupIntegrityError("source archive manifest changed")
                        expected, outputs = _entries(manifest), _output_paths(manifest)
                    else:
                        relative = key.removeprefix("data/")
                        entry = expected.get(relative)
                        if entry is None or key == relative:
                            raise BackupIntegrityError(f"backup manifest set mismatch: extra={key}")
                        if entry["bytes"] != member.size:
                            raise BackupIntegrityError(f"backup size mismatch: {relative}")
                        if visitor is not None:
                            visitor(relative, reader, entry)
                        reader.drain()
                        if reader.digest.hexdigest() != str(entry["sha256"]).strip().lower():
                            raise BackupIntegrityError(f"checksum mismatch: {relative}")
                    if reader.count != member.size:
                        raise BackupIntegrityError(f"archive member size mismatch: {key}")
        # Validate the outer gzip footer/CRC and include all raw bytes in SHA.
        decoded.drain()
    raw.drain()
    if manifest is None or files != {"manifest.json", *("data/" + key for key in expected)}:
        raise BackupIntegrityError("backup manifest set mismatch: missing files")
    if raw.count != identity[2] or raw.digest.hexdigest() != expected_hash:
        raise BackupIntegrityError("source archive SHA-256 mismatch")
    if _identity(handle) != identity:
        raise BackupIntegrityError("source archive changed")
    return manifest


def _write_json(path: Path, value: dict) -> None:
    temporary = path.with_name(path.name + ".partial")
    with temporary.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=True, sort_keys=True, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def run_archive_restore_drill(archive: Path, destination: Path, expected_sha256: str, *,
                              timeout_seconds: int = 7200) -> dict:
    """Restore once into a NEW directory; never activate or alter the source."""
    if not re.fullmatch(r"[0-9a-fA-F]{64}", expected_sha256):
        raise BackupIntegrityError("expected archive SHA-256 is required")
    if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 10800:
        raise BackupIntegrityError("restore deadline must be between 1 and 10800 seconds")
    archive, destination = Path(archive).absolute(), Path(destination).absolute()
    _reject_symlink_chain(Path(archive.anchor), archive)
    _reject_symlink_chain(Path(destination.anchor), destination)
    if destination.exists() or destination.is_symlink():
        raise BackupIntegrityError("isolated restore destination already exists")
    if archive == destination or archive.is_relative_to(destination):
        raise BackupIntegrityError("restore destination must be outside source archive")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.mkdir(mode=0o700)
    report_path = destination / "restore_drill_report.json"
    report = {
        "schema": 1, "status": "in_progress", "method": "verified_archive_stream_v1",
        "source_archive": str(archive), "source_archive_sha256": expected_sha256.lower(),
        "started_at": _now(), "report_path": str(report_path), "phase": "verify_archive",
        "activation_performed": False, "network_services_started": False,
    }
    _write_json(report_path, report)
    deadline = time.monotonic() + timeout_seconds
    try:
        descriptor = os.open(archive, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as handle:
            identity = _identity(handle)
            if not 0 < identity[2] <= MAX_CONTAINER_BYTES:
                raise BackupIntegrityError("backup archive exceeds size limit")
            manifest = _scan_archive(handle, expected_sha256.lower(), identity, deadline)
            _check_source_path(archive, identity)
            _write_json(destination / "source-manifest.json", manifest)
            workspace = estimate_restore_workspace(manifest)
            report["workspace"] = workspace
            report["free_bytes_at_admission"] = shutil.disk_usage(destination).free
            if report["free_bytes_at_admission"] < workspace["required_free_bytes"]:
                raise BackupIntegrityError("insufficient complete isolated restore workspace")
            report["phase"] = "materialize"
            _write_json(report_path, report)
            snapshot = destination / "snapshot"
            data = snapshot / "data"
            data.mkdir(parents=True)
            logical = _logical_entries(manifest)
            restored = {}
            budget = RestoreWorkspace(data, sum(entry["bytes"] for key, entry in _entries(manifest).items() if key not in logical))

            def consume(key: str, incoming: _Reader, entry: dict) -> None:
                metadata = logical.get(key)
                relative = metadata["database_path"] if metadata else key
                target = data.joinpath(*PurePosixPath(relative).parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                if metadata:
                    restore_database_stream(incoming, target, metadata, deadline=deadline)
                    restored[relative] = {"path": relative, "bytes": target.stat().st_size,
                                          "sha256": sha256(target)}
                else:
                    with target.open("xb") as output:
                        while chunk := incoming.read(CHUNK):
                            budget.write(output, chunk)
                        output.flush()
                        os.fsync(output.fileno())
                    restored[relative] = {**entry, "path": relative}

            _scan_archive(handle, expected_sha256.lower(), identity, deadline, consume, manifest)
            result_manifest = {**manifest, "schema": 1, "files": list(restored.values()),
                               "file_count": len(restored), "sqlite_logical": []}
            _write_json(snapshot / "manifest.json", result_manifest)
            report["phase"] = "verify_restored"
            _write_json(report_path, report)
            verify_snapshot(snapshot)
            checks = []
            for entry in result_manifest["files"]:
                path = data.joinpath(*PurePosixPath(entry["path"]).parts)
                if path.suffix.lower() not in {".db", ".sqlite", ".sqlite3"}:
                    continue
                with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as connection:
                    connection.set_progress_handler(lambda: int(time.monotonic() > deadline or
                        shutil.disk_usage(data).free < RESTORE_RESERVE_BYTES), 10000)
                    rows = [str(row[0]) for row in connection.execute("PRAGMA integrity_check")]
                if rows != ["ok"]:
                    raise BackupIntegrityError(f"restored SQLite integrity check failed: {entry['path']}")
                checks.append({"path": entry["path"], "status": "ok", "result": rows})
            if time.monotonic() > deadline or _identity(handle) != identity:
                raise BackupIntegrityError("source changed or isolated restore deadline exceeded")
            _check_source_path(archive, identity)
            if shutil.disk_usage(data).free < RESTORE_RESERVE_BYTES + CHUNK:
                raise BackupIntegrityError("insufficient final restore workspace; runtime reserve protected")
            report.update(status="ok", phase="complete", source_created_at=manifest["created_at"],
                          restored_snapshot=str(snapshot), file_count=len(restored),
                          total_bytes=sum(entry["bytes"] for entry in restored.values()),
                          sqlite_checks=checks, completed_at=_now(), archive_verified_before_restore=True)
    except BaseException as exc:
        report.update(status="error", completed_at=_now(), error=str(exc))
        _write_json(report_path, report)
        raise
    _write_json(report_path, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--timeout-seconds", type=int, default=7200)
    args = parser.parse_args()
    try:
        report = run_archive_restore_drill(args.archive, args.destination, args.expected_sha256,
                                          timeout_seconds=args.timeout_seconds)
    except (OSError, ValueError, BackupIntegrityError, sqlite3.DatabaseError, tarfile.TarError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}))
        return 1
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
