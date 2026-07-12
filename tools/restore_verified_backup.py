"""Verify a SharipovAI backup manifest and atomically restore its data directory."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
from pathlib import Path

from tools.backup_integrity import BackupIntegrityError, verify_snapshot


class RestoreError(BackupIntegrityError):
    pass


def restore(snapshot: Path, destination: Path) -> dict[str, object]:
    raw_destination = Path(destination)
    if raw_destination.is_symlink():
        raise RestoreError("restore destination must not be a symlink")
    try:
        manifest = verify_snapshot(Path(snapshot))
    except BackupIntegrityError as exc:
        raise RestoreError(str(exc)) from exc

    snapshot = Path(snapshot).resolve()
    source = snapshot / "data"
    destination = raw_destination.resolve()
    if destination == snapshot or destination.is_relative_to(snapshot):
        raise RestoreError("restore destination must be outside the snapshot")
    if snapshot.is_relative_to(destination):
        raise RestoreError("snapshot must be outside the restore destination")

    destination.parent.mkdir(parents=True, exist_ok=True)
    staging_root = Path(tempfile.mkdtemp(prefix="restore-", dir=destination.parent))
    envelope = staging_root / "snapshot"
    envelope.mkdir()
    rollback = destination.with_name(destination.name + ".rollback")
    moved_existing = False
    installed_new = False
    try:
        shutil.copytree(source, envelope / "data", dirs_exist_ok=False)
        (envelope / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        verify_snapshot(envelope)
        if rollback.exists():
            shutil.rmtree(rollback)
        if destination.exists():
            os.replace(destination, rollback)
            moved_existing = True
        os.replace(envelope / "data", destination)
        installed_new = True
    except Exception:
        if installed_new and destination.exists():
            shutil.rmtree(destination, ignore_errors=True)
        if moved_existing and rollback.exists() and not destination.exists():
            os.replace(rollback, destination)
        raise
    finally:
        shutil.rmtree(staging_root, ignore_errors=True)
    if rollback.exists():
        shutil.rmtree(rollback)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    try:
        manifest = restore(args.snapshot, args.destination)
    except (OSError, ValueError, KeyError, json.JSONDecodeError, BackupIntegrityError) as exc:
        print(f"restore failed: {exc}")
        return 1
    print(json.dumps({"status": "ok", "created_at": manifest.get("created_at"), "file_count": manifest.get("file_count")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
