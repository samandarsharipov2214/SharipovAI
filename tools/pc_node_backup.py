"""Crash-tolerant rotating snapshots for the SharipovAI PC node.

This utility copies the persistent data directory into verified ``current`` and
``previous`` snapshots. It never touches secrets outside the configured source.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import signal
import tempfile
import time
from contextlib import AbstractContextManager
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO


class BackupError(RuntimeError):
    """Raised when a verified snapshot cannot be produced."""


class SingleInstanceLock(AbstractContextManager["SingleInstanceLock"]):
    """Hold an OS-level lock that is released automatically on process exit."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.handle: BinaryIO | None = None

    def __enter__(self) -> "SingleInstanceLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("a+b")
        try:
            if os.name == "nt":
                import msvcrt

                self.handle.seek(0)
                if self.handle.tell() == 0:
                    self.handle.write(b"0")
                    self.handle.flush()
                self.handle.seek(0)
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, BlockingIOError) as exc:
            self.handle.close()
            self.handle = None
            raise BackupError("another backup loop is already running") from exc
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.handle is None:
            return
        try:
            if os.name == "nt":
                import msvcrt

                self.handle.seek(0)
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        finally:
            self.handle.close()
            self.handle = None


def atomic_snapshot(source: str | Path, backup_root: str | Path) -> dict[str, object]:
    """Create and verify one rotating snapshot.

    ``current`` is always the newest completed snapshot and ``previous`` is the
    prior completed snapshot. A failed staging copy never replaces ``current``.
    """
    source_path = Path(source).resolve()
    root = Path(backup_root).resolve()
    if not source_path.exists() or not source_path.is_dir():
        raise BackupError(f"persistent data directory does not exist: {source_path}")
    if source_path == root or source_path in root.parents:
        raise BackupError("backup root must not be inside the source directory")

    root.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix="snapshot-", dir=root))
    files: list[dict[str, object]] = []
    total_bytes = 0
    try:
        for item in sorted(source_path.rglob("*")):
            if not item.is_file():
                continue
            relative = item.relative_to(source_path)
            destination = staging / "data" / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, destination)
            source_hash = _sha256(item)
            destination_hash = _sha256(destination)
            if source_hash != destination_hash:
                raise BackupError(f"snapshot verification failed: {relative}")
            size = destination.stat().st_size
            total_bytes += size
            files.append({"path": relative.as_posix(), "bytes": size, "sha256": destination_hash})

        manifest = {
            "schema": 1,
            "created_at": datetime.now(UTC).isoformat(),
            "source": str(source_path),
            "file_count": len(files),
            "total_bytes": total_bytes,
            "files": files,
        }
        (staging / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        current = root / "current"
        previous = root / "previous"
        retired = root / ".retired"
        if retired.exists():
            shutil.rmtree(retired)
        if previous.exists():
            previous.replace(retired)
        if current.exists():
            current.replace(previous)
        staging.replace(current)
        if retired.exists():
            shutil.rmtree(retired)
        return manifest
    except Exception:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        raise


def run_loop(source: Path, backup_root: Path, interval_seconds: float) -> None:
    if interval_seconds < 1:
        raise BackupError("interval must be at least 1 second")
    stopping = False

    def stop(_signum, _frame) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, stop)

    with SingleInstanceLock(backup_root / "backup.lock"):
        while not stopping:
            started = time.monotonic()
            manifest = atomic_snapshot(source, backup_root)
            print(
                f"backup ok: {manifest['created_at']} files={manifest['file_count']} "
                f"bytes={manifest['total_bytes']}",
                flush=True,
            )
            remaining = interval_seconds - (time.monotonic() - started)
            if remaining > 0:
                time.sleep(remaining)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="SharipovAI PC node backup loop")
    parser.add_argument("--source", default=os.getenv("SHARIPOVAI_DATA_DIR", "data"))
    parser.add_argument("--backup-root", default=os.getenv("SHARIPOVAI_BACKUP_DIR", "runtime/backups"))
    parser.add_argument("--interval", type=float, default=10.0)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()

    source = Path(args.source)
    backup_root = Path(args.backup_root)
    try:
        if args.once:
            manifest = atomic_snapshot(source, backup_root)
            print(json.dumps(manifest, ensure_ascii=False))
        else:
            run_loop(source, backup_root, args.interval)
    except (BackupError, OSError) as exc:
        print(f"backup failed: {exc}", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
