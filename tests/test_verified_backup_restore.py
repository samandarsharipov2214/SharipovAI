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


def _manifest(snapshot: Path) -> tuple[Path, dict]:
    path = snapshot / "manifest.json"
    return path, json.loads(path.read_text(encoding="utf-8"))


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


@pytest.mark.parametrize("operation", ["extract", "restore", "drill"])
@pytest.mark.parametrize("pressure", ["initial", "concurrent"])
def test_native_restore_paths_preserve_runtime_reserve(tmp_path, monkeypatch, operation, pressure):
    from types import SimpleNamespace
    import tools.backup_integrity as integrity
    from tools.isolated_restore_drill import run_restore_drill
    snapshot = _snapshot(tmp_path, b"x" * (2 * 1024**2))
    archive = _archive(snapshot, tmp_path / "source.tar.gz")
    destination = tmp_path / "destination"
    if operation == "restore":
        destination.mkdir()
        (destination / "keep").write_text("unchanged")
    floor = integrity.RESTORE_RESERVE_BYTES + 1024**2
    free = [floor - 1 if pressure == "initial" else floor + 8 * 1024**2]
    monkeypatch.setattr(integrity.shutil, "disk_usage", lambda _: SimpleNamespace(free=free[0]))
    if pressure == "concurrent":
        original = integrity.RestoreWorkspace.write
        def competing_writer(self, output, chunk):
            original(self, output, chunk)
            free[0] = floor - 1
        monkeypatch.setattr(integrity.RestoreWorkspace, "write", competing_writer)
    action = {"extract": lambda: extract_verified_archive(archive, destination),
              "restore": lambda: restore(snapshot, destination),
              "drill": lambda: run_restore_drill(snapshot, destination)}[operation]
    with pytest.raises(BackupIntegrityError, match="runtime reserve protected"):
        action()
    assert (snapshot / "data/sharipovai_shared.db").stat().st_size == 2 * 1024**2
    if operation == "restore":
        assert (destination / "keep").read_text() == "unchanged"
        assert not (destination / "sharipovai_shared.db").exists()
    elif operation == "extract":
        assert not destination.exists()


def test_native_large_envelope_requires_full_capacity_without_allocating_it(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import tools.backup_integrity as integrity
    required = 22 * 1024**3
    floor = integrity.RESTORE_RESERVE_BYTES + 1024**2
    free = [floor + required - 1]
    monkeypatch.setattr(integrity.shutil, "disk_usage", lambda _: SimpleNamespace(free=free[0]))
    with pytest.raises(BackupIntegrityError, match="insufficient restore workspace"):
        integrity.RestoreWorkspace(tmp_path, required)
    free[0] += 1
    assert integrity.RestoreWorkspace(tmp_path, required).remaining == required


def test_restore_rejects_path_traversal(tmp_path: Path) -> None:
    snapshot = _snapshot(tmp_path)
    manifest_path, manifest = _manifest(snapshot)
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
    manifest_path, manifest = _manifest(snapshot)
    manifest["files"].append(dict(manifest["files"][0]))
    manifest["file_count"] = 2
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(BackupIntegrityError, match="duplicate backup path"):
        verify_snapshot(snapshot)


def test_snapshot_rejects_size_mismatch(tmp_path: Path) -> None:
    snapshot = _snapshot(tmp_path)
    manifest_path, manifest = _manifest(snapshot)
    manifest["files"][0]["bytes"] += 1
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(BackupIntegrityError, match="size mismatch"):
        verify_snapshot(snapshot)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("schema", True, "schema"),
        ("schema", "1", "schema"),
        ("file_count", True, "file_count"),
        ("file_count", "1", "file_count"),
    ],
)
def test_snapshot_rejects_ambiguous_manifest_integer_types(
    tmp_path: Path,
    field: str,
    value: object,
    message: str,
) -> None:
    snapshot = _snapshot(tmp_path)
    manifest_path, manifest = _manifest(snapshot)
    manifest[field] = value
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(BackupIntegrityError, match=message):
        verify_snapshot(snapshot)


@pytest.mark.parametrize("unsafe", ["CON", "aux.txt", "folder/name. ", "folder/file:stream"])
def test_snapshot_rejects_windows_ambiguous_paths(tmp_path: Path, unsafe: str) -> None:
    snapshot = _snapshot(tmp_path)
    manifest_path, manifest = _manifest(snapshot)
    manifest["files"][0]["path"] = unsafe
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(BackupIntegrityError, match="unsafe backup path"):
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


@pytest.mark.parametrize("size", [6_700_000_000, 22 * 1024**3])
def test_large_canonical_database_fits_bounded_total_envelope(tmp_path, monkeypatch, size):
    # Sparse file exercises real stat/manifest size handling without allocating
    # gigabytes in CI. Hash correctness is covered by the tampering/restore tests.
    import tools.backup_integrity as integrity

    snapshot = _snapshot(tmp_path)
    target = snapshot / "data/sharipovai_shared.db"
    with target.open("r+b") as stream:
        stream.truncate(size)
    manifest_path, manifest = _manifest(snapshot)
    manifest["files"][0]["bytes"] = size
    manifest_path.write_text(json.dumps(manifest))
    monkeypatch.setattr(integrity, "sha256", lambda _: manifest["files"][0]["sha256"])
    assert verify_snapshot(snapshot)["files"][0]["bytes"] == size


def test_total_snapshot_limit_still_rejects_multiple_large_files(tmp_path, monkeypatch):
    import tools.backup_integrity as integrity

    snapshot = _snapshot(tmp_path)
    manifest_path, manifest = _manifest(snapshot)
    size = integrity.MAX_TOTAL_BYTES // 2 + 1
    for name in ("sharipovai_shared.db", "sharipovai_saas.sqlite3"):
        with (snapshot / "data" / name).open("wb") as stream:
            stream.truncate(size)
    manifest["files"][0]["bytes"] = size
    manifest["files"].append(manifest["files"][0] | {"path": "sharipovai_saas.sqlite3"})
    manifest["file_count"] = 2
    manifest_path.write_text(json.dumps(manifest))
    monkeypatch.setattr(integrity, "sha256", lambda _: manifest["files"][0]["sha256"])
    with pytest.raises(BackupIntegrityError, match="total size limit"):
        verify_snapshot(snapshot)
