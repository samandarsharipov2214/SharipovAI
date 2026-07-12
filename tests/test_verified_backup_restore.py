from __future__ import annotations

import hashlib
import io
import json
import os
import tarfile
from pathlib import Path

import pytest

from tools.backup_integrity import BackupIntegrityError, extract_verified_archive, verify_snapshot
from tools.restore_verified_backup import RestoreError, restore


def _snapshot(root: Path, content: bytes = b"valid-db") -> Path:
    snapshot = root / "snapshot"
    data = snapshot / "data"
    data.mkdir(parents=True)
    target = data / "sharipovai_shared.db"
    target.write_bytes(content)
    manifest = {
        "schema": 1,
        "source": "vps",
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


def _archive(snapshot: Path, path: Path) -> Path:
    with tarfile.open(path, "w:gz") as output:
        output.add(snapshot / "manifest.json", arcname="manifest.json")
        output.add(snapshot / "data", arcname="data")
    return path


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

    with pytest.raises(RestoreError, match="mismatch"):
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


def test_snapshot_rejects_unlisted_extra_file(tmp_path: Path) -> None:
    snapshot = _snapshot(tmp_path)
    (snapshot / "data" / "unlisted.txt").write_text("not in manifest", encoding="utf-8")

    with pytest.raises(BackupIntegrityError, match="manifest set mismatch"):
        verify_snapshot(snapshot)


def test_snapshot_rejects_duplicate_manifest_path(tmp_path: Path) -> None:
    snapshot = _snapshot(tmp_path)
    manifest_path = snapshot / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"].append(dict(manifest["files"][0]))
    manifest["file_count"] = 2
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(BackupIntegrityError, match="duplicate backup path"):
        verify_snapshot(snapshot)


def test_snapshot_rejects_size_mismatch(tmp_path: Path) -> None:
    snapshot = _snapshot(tmp_path)
    manifest_path = snapshot / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"][0]["bytes"] += 1
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(BackupIntegrityError, match="size mismatch"):
        verify_snapshot(snapshot)


def test_snapshot_rejects_symlink(tmp_path: Path) -> None:
    snapshot = _snapshot(tmp_path)
    target = snapshot / "data" / "sharipovai_shared.db"
    external = tmp_path / "external.db"
    external.write_bytes(target.read_bytes())
    target.unlink()
    try:
        os.symlink(external, target)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is unavailable")

    with pytest.raises(BackupIntegrityError, match="symlink"):
        verify_snapshot(snapshot)


def test_valid_archive_is_extracted_and_verified(tmp_path: Path) -> None:
    snapshot = _snapshot(tmp_path)
    archive = _archive(snapshot, tmp_path / "backup.tar.gz")
    destination = tmp_path / "extracted"

    manifest = extract_verified_archive(archive, destination)

    assert manifest["file_count"] == 1
    assert (destination / "data" / "sharipovai_shared.db").read_bytes() == b"valid-db"


def test_archive_rejects_path_traversal_without_writing_outside(tmp_path: Path) -> None:
    archive = tmp_path / "unsafe.tar.gz"
    payload = b"escape"
    with tarfile.open(archive, "w:gz") as output:
        member = tarfile.TarInfo("../escape.txt")
        member.size = len(payload)
        output.addfile(member, io.BytesIO(payload))

    with pytest.raises(BackupIntegrityError, match="unsafe backup path"):
        extract_verified_archive(archive, tmp_path / "extracted")
    assert not (tmp_path / "escape.txt").exists()


def test_archive_rejects_symlink_member(tmp_path: Path) -> None:
    archive = tmp_path / "unsafe-link.tar.gz"
    with tarfile.open(archive, "w:gz") as output:
        manifest = tarfile.TarInfo("manifest.json")
        body = b"{}"
        manifest.size = len(body)
        output.addfile(manifest, io.BytesIO(body))
        data = tarfile.TarInfo("data")
        data.type = tarfile.DIRTYPE
        output.addfile(data)
        link = tarfile.TarInfo("data/link")
        link.type = tarfile.SYMTYPE
        link.linkname = "../../outside"
        output.addfile(link)

    with pytest.raises(BackupIntegrityError, match="unsafe archive member type"):
        extract_verified_archive(archive, tmp_path / "extracted")
