"""Canonical fail-closed integrity rules for SharipovAI backup snapshots."""
from __future__ import annotations

import hashlib
import json
import os
import re
import tarfile
import tempfile
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

MAX_BACKUP_FILES = 20_000
MAX_FILE_BYTES = 5 * 1024 * 1024 * 1024
MAX_TOTAL_BYTES = 20 * 1024 * 1024 * 1024
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class BackupIntegrityError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_snapshot(snapshot: Path) -> dict[str, Any]:
    """Verify that snapshot contents exactly match a bounded manifest."""

    raw_snapshot = Path(snapshot)
    if raw_snapshot.is_symlink():
        raise BackupIntegrityError("snapshot directory must not be a symlink")
    snapshot = raw_snapshot.resolve()
    manifest_path = snapshot / "manifest.json"
    source = snapshot / "data"
    if manifest_path.is_symlink() or source.is_symlink():
        raise BackupIntegrityError("snapshot manifest and data directory must not be symlinks")
    if not manifest_path.is_file() or not source.is_dir():
        raise BackupIntegrityError("snapshot must contain manifest.json and data/")

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BackupIntegrityError(f"invalid backup manifest: {exc}") from exc
    if not isinstance(manifest, dict) or manifest.get("schema") != 1:
        raise BackupIntegrityError("unsupported backup manifest schema")
    entries = manifest.get("files")
    if not isinstance(entries, list):
        raise BackupIntegrityError("invalid backup manifest files")
    if len(entries) > MAX_BACKUP_FILES:
        raise BackupIntegrityError("backup contains too many files")
    if manifest.get("file_count") != len(entries):
        raise BackupIntegrityError("backup manifest file_count mismatch")
    _validate_created_at(manifest.get("created_at"))

    expected: set[str] = set()
    total_bytes = 0
    source_root = source.resolve()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise BackupIntegrityError(f"invalid backup entry at index {index}")
        relative = _safe_relative_path(entry.get("path"))
        key = relative.as_posix()
        if key in expected:
            raise BackupIntegrityError(f"duplicate backup path: {key}")
        expected.add(key)

        expected_bytes = entry.get("bytes")
        if isinstance(expected_bytes, bool) or not isinstance(expected_bytes, int) or expected_bytes < 0:
            raise BackupIntegrityError(f"invalid backup size: {key}")
        if expected_bytes > MAX_FILE_BYTES:
            raise BackupIntegrityError(f"backup file exceeds size limit: {key}")
        total_bytes += expected_bytes
        if total_bytes > MAX_TOTAL_BYTES:
            raise BackupIntegrityError("backup exceeds total size limit")

        expected_hash = str(entry.get("sha256") or "").strip().lower()
        if not _SHA256_RE.fullmatch(expected_hash):
            raise BackupIntegrityError(f"invalid backup checksum: {key}")

        path = source.joinpath(*relative.parts)
        _reject_symlink_chain(source, path)
        if not path.is_file():
            raise BackupIntegrityError(f"backup file missing: {key}")
        resolved = path.resolve()
        if not resolved.is_relative_to(source_root):
            raise BackupIntegrityError(f"unsafe backup path: {key}")
        if path.stat().st_size != expected_bytes:
            raise BackupIntegrityError(f"backup size mismatch: {key}")
        if sha256(path) != expected_hash:
            raise BackupIntegrityError(f"checksum mismatch: {key}")

    actual: set[str] = set()
    for path in source.rglob("*"):
        relative = path.relative_to(source).as_posix()
        if path.is_symlink():
            raise BackupIntegrityError(f"backup symlink is forbidden: {relative}")
        if path.is_file():
            actual.add(relative)
        elif not path.is_dir():
            raise BackupIntegrityError(f"unsupported backup entry: {relative}")
    if actual != expected:
        extra = sorted(actual - expected)
        missing = sorted(expected - actual)
        raise BackupIntegrityError(f"backup manifest set mismatch: extra={extra[:10]}, missing={missing[:10]}")
    return manifest


def extract_verified_archive(archive: Path, destination: Path) -> dict[str, Any]:
    """Safely extract an archive and verify its exact snapshot manifest."""

    archive = Path(archive)
    destination = Path(destination)
    if archive.is_symlink() or not archive.is_file():
        raise BackupIntegrityError("backup archive must be a regular file")
    if destination.is_symlink():
        raise BackupIntegrityError("backup destination must not be a symlink")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and any(destination.iterdir()):
        raise BackupIntegrityError("backup destination must be empty")

    staging = Path(tempfile.mkdtemp(prefix="backup-extract-", dir=destination.parent))
    try:
        _extract_archive_members(archive, staging)
        manifest = verify_snapshot(staging)
        if destination.exists():
            destination.rmdir()
        os.replace(staging, destination)
        return manifest
    except Exception:
        _remove_tree(staging)
        raise


def _extract_archive_members(archive: Path, destination: Path) -> None:
    names: set[str] = set()
    file_count = 0
    total_bytes = 0
    try:
        opened = tarfile.open(archive, mode="r:gz")
    except (OSError, tarfile.TarError) as exc:
        raise BackupIntegrityError(f"invalid backup archive: {exc}") from exc
    with opened:
        for member in opened:
            relative = _safe_archive_member(member.name)
            key = relative.as_posix()
            if key in names:
                raise BackupIntegrityError(f"duplicate archive member: {key}")
            names.add(key)
            if member.issym() or member.islnk() or member.isdev() or member.isfifo():
                raise BackupIntegrityError(f"unsafe archive member type: {key}")
            target = destination.joinpath(*relative.parts)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if not member.isfile():
                raise BackupIntegrityError(f"unsupported archive member type: {key}")
            file_count += 1
            if file_count > MAX_BACKUP_FILES + 1:
                raise BackupIntegrityError("backup archive contains too many files")
            if member.size < 0 or member.size > MAX_FILE_BYTES:
                raise BackupIntegrityError(f"archive member exceeds size limit: {key}")
            total_bytes += member.size
            if total_bytes > MAX_TOTAL_BYTES:
                raise BackupIntegrityError("backup archive exceeds total size limit")
            target.parent.mkdir(parents=True, exist_ok=True)
            stream = opened.extractfile(member)
            if stream is None:
                raise BackupIntegrityError(f"cannot read archive member: {key}")
            remaining = member.size
            with stream, target.open("xb") as output:
                while remaining:
                    chunk = stream.read(min(1024 * 1024, remaining))
                    if not chunk:
                        raise BackupIntegrityError(f"truncated archive member: {key}")
                    output.write(chunk)
                    remaining -= len(chunk)
                if stream.read(1):
                    raise BackupIntegrityError(f"archive member size mismatch: {key}")
    if "manifest.json" not in names or not any(name.startswith("data/") for name in names):
        raise BackupIntegrityError("backup archive must contain manifest.json and data/")


def _safe_relative_path(value: Any) -> PurePosixPath:
    text = str(value or "").strip()
    if not text or "\\" in text or "\x00" in text:
        raise BackupIntegrityError(f"unsafe backup path: {text!r}")
    relative = PurePosixPath(text)
    if relative.is_absolute() or relative == PurePosixPath(".") or any(part in {"", ".", ".."} for part in relative.parts):
        raise BackupIntegrityError(f"unsafe backup path: {text}")
    first = relative.parts[0]
    if ":" in first:
        raise BackupIntegrityError(f"unsafe backup path: {text}")
    return relative


def _safe_archive_member(value: str) -> PurePosixPath:
    relative = _safe_relative_path(value.rstrip("/"))
    key = relative.as_posix()
    if key != "manifest.json" and not key.startswith("data/") and key != "data":
        raise BackupIntegrityError(f"unexpected archive member: {key}")
    return relative


def _reject_symlink_chain(root: Path, path: Path) -> None:
    current = root
    for part in path.relative_to(root).parts:
        current = current / part
        if current.is_symlink():
            raise BackupIntegrityError(f"backup symlink is forbidden: {current.relative_to(root)}")


def _validate_created_at(value: Any) -> None:
    text = str(value or "").strip()
    if not text:
        raise BackupIntegrityError("backup created_at is missing")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise BackupIntegrityError("backup created_at is invalid") from exc
    if parsed.tzinfo is None:
        raise BackupIntegrityError("backup created_at must include timezone")


def _remove_tree(path: Path) -> None:
    import shutil

    shutil.rmtree(path, ignore_errors=True)


__all__ = [
    "BackupIntegrityError",
    "extract_verified_archive",
    "sha256",
    "verify_snapshot",
]
