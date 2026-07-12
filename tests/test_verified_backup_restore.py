from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from tools.restore_verified_backup import RestoreError, restore


def _snapshot(root: Path, content: bytes = b"valid-db") -> Path:
    snapshot = root / "snapshot"
    data = snapshot / "data"
    data.mkdir(parents=True)
    target = data / "sharipovai_shared.db"
    target.write_bytes(content)
    manifest = {
        "schema": 1,
        "created_at": "2026-07-12T00:00:00+00:00",
        "file_count": 1,
        "files": [
            {
                "path": target.name,
                "bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        ],
    }
    (snapshot / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return snapshot


def test_restore_replaces_destination_and_removes_rollback(tmp_path: Path) -> None:
    snapshot = _snapshot(tmp_path)
    destination = tmp_path / "data"
    destination.mkdir()
    (destination / "old.txt").write_text("old", encoding="utf-8")

    manifest = restore(snapshot, destination)

    assert manifest["file_count"] == 1
    assert (destination / "sharipovai_shared.db").read_bytes() == b"valid-db"
    assert not (destination / "old.txt").exists()
    assert not (tmp_path / "data.rollback").exists()


def test_restore_rejects_tampered_snapshot_without_touching_destination(tmp_path: Path) -> None:
    snapshot = _snapshot(tmp_path)
    destination = tmp_path / "data"
    destination.mkdir()
    original = destination / "keep.txt"
    original.write_text("keep", encoding="utf-8")
    (snapshot / "data" / "sharipovai_shared.db").write_bytes(b"tampered")

    with pytest.raises(RestoreError, match="checksum mismatch"):
        restore(snapshot, destination)

    assert original.read_text(encoding="utf-8") == "keep"


def test_restore_rejects_path_traversal(tmp_path: Path) -> None:
    snapshot = _snapshot(tmp_path)
    manifest_path = snapshot / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"][0]["path"] = "../outside"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(RestoreError, match="unsafe backup path"):
        restore(snapshot, tmp_path / "data")
