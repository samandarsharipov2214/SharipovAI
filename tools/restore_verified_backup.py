"""Verify a SharipovAI backup manifest and atomically restore its data directory."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path


class RestoreError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def restore(snapshot: Path, destination: Path) -> dict[str, object]:
    snapshot = snapshot.resolve()
    destination = destination.resolve()
    manifest_path = snapshot / "manifest.json"
    source = snapshot / "data"
    if not manifest_path.is_file() or not source.is_dir():
        raise RestoreError("snapshot must contain manifest.json and data/")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = manifest.get("files")
    if not isinstance(entries, list):
        raise RestoreError("invalid backup manifest")
    for entry in entries:
        relative = Path(str(entry["path"]))
        if relative.is_absolute() or ".." in relative.parts:
            raise RestoreError(f"unsafe backup path: {relative}")
        path = source / relative
        if not path.is_file():
            raise RestoreError(f"backup file missing: {relative}")
        if sha256(path) != str(entry["sha256"]).lower():
            raise RestoreError(f"checksum mismatch: {relative}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix="restore-", dir=destination.parent))
    rollback = destination.with_name(destination.name + ".rollback")
    try:
        shutil.copytree(source, staging / "data", dirs_exist_ok=True)
        if rollback.exists():
            shutil.rmtree(rollback)
        if destination.exists():
            os.replace(destination, rollback)
        os.replace(staging / "data", destination)
        if rollback.exists():
            shutil.rmtree(rollback)
    except Exception:
        if not destination.exists() and rollback.exists():
            os.replace(rollback, destination)
        raise
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    try:
        manifest = restore(args.snapshot, args.destination)
    except (OSError, ValueError, KeyError, json.JSONDecodeError, RestoreError) as exc:
        print(f"restore failed: {exc}")
        return 1
    print(json.dumps({"status": "ok", "created_at": manifest.get("created_at"), "file_count": manifest.get("file_count")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
