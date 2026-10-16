"""Disposable real SQLite/archive fixtures; no production inputs or writes."""
from __future__ import annotations

import copy
import gzip
import hashlib
import io
import json
import sqlite3
import tarfile
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

import tools.streaming_restore_drill as drill
from tests.test_backup_phase_budget import embedded
from tools.backup_integrity import BackupIntegrityError, RESTORE_RESERVE_BYTES, sha256, verify_snapshot
from tools.sqlite_logical_restore import restore_budget

GIB = 1024**3


def _fixture(tmp_path: Path, schema: int = 2):
    source = tmp_path / "source.db"
    with sqlite3.connect(source) as connection:
        connection.executescript("CREATE TABLE history(id INTEGER PRIMARY KEY, value TEXT, data BLOB); CREATE INDEX history_idx ON history(value); CREATE VIRTUAL TABLE words USING fts5(content);")
        connection.execute("INSERT INTO history VALUES (1,?,?)", ("Learning\n世界\x00tail", b"\x00\xff"))
        connection.execute("INSERT INTO words VALUES ('preserved evidence')")
        connection.commit()
        manifest = {"schema": schema, "created_at": "2026-10-14T00:00:00+00:00", "files": []}
        if schema == 2:
            helper = embedded("LOGICAL_SNAPSHOT")
            compressed = tmp_path / "history.gz"
            info = helper["logical_snapshot"](connection, compressed, helper["StagingBudget"](tmp_path, 0))
            info.update(path="nested/history.db.sql.jsonl.gz", database_path="nested/history.db")
            manifest["sqlite_logical"] = [info]
            payloads = {info["path"]: compressed.read_bytes()}
        else:
            payloads = {"nested/history.db": source.read_bytes()}
    payloads["settings.json"] = b'{"live_trading":false}'
    for key, body in payloads.items():
        manifest["files"].append({"path": key, "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()})
    manifest["file_count"] = len(payloads)
    return manifest, payloads


def _archive(path: Path, manifest: dict, payloads: dict, extra=None) -> Path:
    with tarfile.open(path, "w:gz") as archive:
        body = json.dumps(manifest).encode()
        info = tarfile.TarInfo("manifest.json"); info.size = len(body)
        archive.addfile(info, io.BytesIO(body))
        for key, body in payloads.items():
            info = tarfile.TarInfo("data/" + key); info.size = len(body)
            archive.addfile(info, io.BytesIO(body))
        if extra:
            extra(archive)
    return path


def _run(path, destination):
    return drill.run_archive_restore_drill(path, destination, sha256(path))


def _error(destination):
    report = json.loads((destination / "restore_drill_report.json").read_text())
    assert report["status"] == "error"
    assert report["activation_performed"] is False
    return report


@pytest.mark.parametrize("schema", [1, 2])
def test_streaming_restores_real_history_without_compressed_copy(tmp_path, schema):
    manifest, payloads = _fixture(tmp_path, schema)
    archive = _archive(tmp_path / "source.tar.gz", manifest, payloads)
    before = archive.read_bytes()
    destination = tmp_path / "drill"
    result = _run(archive, destination)
    assert result["status"] == "ok"
    assert result["archive_verified_before_restore"] is True
    assert result["activation_performed"] is result["network_services_started"] is False
    assert result["source_archive_sha256"] == sha256(archive)
    assert archive.read_bytes() == before
    assert not list(destination.rglob("*.gz"))
    restored = Path(result["restored_snapshot"])
    assert verify_snapshot(restored)["schema"] == 1
    assert json.loads((destination / "source-manifest.json").read_text()) == manifest
    with sqlite3.connect(restored / "data/nested/history.db") as connection:
        assert connection.execute("SELECT * FROM history").fetchall() == [(1, "Learning\n世界\x00tail", b"\x00\xff")]
        assert connection.execute("SELECT content FROM words WHERE words MATCH 'evidence'").fetchall() == [("preserved evidence",)]
    assert result["sqlite_checks"] == [{"path": "nested/history.db", "status": "ok", "result": ["ok"]}]


@pytest.mark.parametrize("attack", ["traversal", "symlink", "hardlink", "duplicate", "extra", "manifest", "checksum", "missing", "truncated", "target_collision"])
def test_entire_archive_is_verified_before_any_sql(tmp_path, monkeypatch, attack):
    manifest, payloads = _fixture(tmp_path)
    extra = None
    if attack in {"traversal", "symlink", "hardlink", "duplicate", "extra"}:
        def extra(archive):
            name = {"traversal": "../outside", "duplicate": "data/settings.json"}.get(attack, "data/extra")
            info = tarfile.TarInfo(name)
            if attack in {"symlink", "hardlink"}:
                info.type = tarfile.SYMTYPE if attack == "symlink" else tarfile.LNKTYPE
                info.linkname = "../../outside"
            archive.addfile(info, io.BytesIO())
    elif attack == "manifest":
        manifest["file_count"] += 1
    elif attack == "checksum":
        manifest["files"][0]["sha256"] = "0" * 64
    elif attack == "missing":
        payloads.pop("settings.json")
    elif attack == "target_collision":
        manifest["sqlite_logical"][0]["database_path"] = "settings.json/history.db"
    archive = _archive(tmp_path / "source.tar.gz", manifest, payloads, extra)
    if attack == "truncated":
        archive.write_bytes(archive.read_bytes()[:-5])
    calls = []
    monkeypatch.setattr(drill, "restore_database_stream", lambda *a, **kw: calls.append(True))
    before = archive.read_bytes()
    destination = tmp_path / "drill"
    with pytest.raises((BackupIntegrityError, EOFError)):
        _run(archive, destination)
    assert calls == []
    assert archive.read_bytes() == before
    assert not (destination / "snapshot").exists()
    assert not (tmp_path / "outside").exists()
    assert _error(destination)["phase"] == "verify_archive"


def test_archive_digest_mismatch_never_starts_restore(tmp_path, monkeypatch):
    manifest, payloads = _fixture(tmp_path)
    archive = _archive(tmp_path / "source.tar.gz", manifest, payloads)
    monkeypatch.setattr(drill, "restore_database_stream", lambda *a, **kw: pytest.fail("SQL before verification"))
    with pytest.raises(BackupIntegrityError, match="SHA-256"):
        drill.run_archive_restore_drill(archive, tmp_path / "drill", "0" * 64)
    _error(tmp_path / "drill")


@pytest.mark.parametrize("attack", ["logical_digest", "gzip_crc", "statement_bounds", "sql_attach"])
def test_logical_stream_validation_remains_mandatory(tmp_path, attack):
    manifest, payloads = _fixture(tmp_path)
    metadata = manifest["sqlite_logical"][0]
    if attack == "logical_digest":
        metadata["stream_sha256"] = "0" * 64
    elif attack == "statement_bounds":
        metadata["statements"] = 1
    elif attack == "gzip_crc":
        body = bytearray(payloads[metadata["path"]]); body[-8] ^= 0xFF
        payloads[metadata["path"]] = bytes(body)
        manifest["files"][0]["sha256"] = hashlib.sha256(body).hexdigest()
    else:
        raw = (json.dumps("ATTACH DATABASE '/tmp/forbidden' AS outside") + "\n").encode()
        body = gzip.compress(raw)
        metadata.update(stream_sha256=hashlib.sha256(raw).hexdigest(), statements=1, uncompressed_bytes=len(raw))
        payloads[metadata["path"]] = body
        manifest["files"][0].update(bytes=len(body), sha256=hashlib.sha256(body).hexdigest())
    archive = _archive(tmp_path / "source.tar.gz", manifest, payloads)
    before = archive.read_bytes()
    destination = tmp_path / "drill"
    with pytest.raises((BackupIntegrityError, OSError, sqlite3.DatabaseError)):
        _run(archive, destination)
    assert archive.read_bytes() == before
    assert not (destination / "snapshot/data/nested/history.db").exists()
    assert _error(destination)["phase"] == "materialize"


def test_workspace_estimate_preserves_all_database_admission_budgets(tmp_path):
    manifest, _ = _fixture(tmp_path)
    manifest["sqlite_logical"][0]["logical_bytes"] = 24 * GIB
    second = copy.deepcopy(manifest["sqlite_logical"][0])
    second.update(path="small.gz", database_path="small.db", logical_bytes=1024**2)
    manifest["sqlite_logical"].append(second)
    manifest["files"].append({"path": "small.gz", "bytes": 1, "sha256": "0" * 64})
    manifest["file_count"] += 1
    estimate = drill.estimate_restore_workspace(manifest)
    assert restore_budget(manifest["sqlite_logical"][0]) == 32 * GIB
    assert estimate["logical_database_budget_bytes"] == 32 * GIB + 1024**2 * 3 // 2 + 16 * 1024**2
    assert estimate["runtime_reserve_bytes"] == 2 * GIB
    assert estimate["other_output_bytes"] == len(b'{"live_trading":false}')
    assert estimate["required_free_bytes"] > 34 * GIB + restore_budget(second)


@pytest.mark.parametrize("pressure", ["initial", "logical", "nonlogical"])
def test_insufficient_or_concurrent_capacity_never_passes(tmp_path, monkeypatch, pressure):
    manifest, payloads = _fixture(tmp_path)
    archive = _archive(tmp_path / "source.tar.gz", manifest, payloads)
    required = drill.estimate_restore_workspace(manifest)["required_free_bytes"]
    free = [required - 1 if pressure == "initial" else required + GIB]
    monkeypatch.setattr(drill.shutil, "disk_usage", lambda _: SimpleNamespace(free=free[0]))
    if pressure != "initial":
        original = drill.restore_database_stream
        def consume(*args, **kwargs):
            if pressure == "logical":
                free[0] = RESTORE_RESERVE_BYTES - 1
            result = original(*args, **kwargs)
            free[0] = RESTORE_RESERVE_BYTES - 1
            return result
        monkeypatch.setattr(drill, "restore_database_stream", consume)
    before = archive.read_bytes()
    destination = tmp_path / "drill"
    with pytest.raises(BackupIntegrityError, match="workspace|reserve"):
        _run(archive, destination)
    assert archive.read_bytes() == before
    _error(destination)
    if pressure == "initial":
        assert not (destination / "snapshot").exists()


@pytest.mark.parametrize("kind", ["existing", "symlink", "ancestor_symlink"])
def test_destination_is_exclusive_and_never_follows_symlinks(tmp_path, kind):
    manifest, payloads = _fixture(tmp_path)
    archive = _archive(tmp_path / "source.tar.gz", manifest, payloads)
    kept = tmp_path / "kept"; kept.mkdir(); (kept / "keep").write_text("unchanged")
    destination = tmp_path / "drill"
    if kind == "existing":
        destination = kept
    elif kind == "symlink":
        destination.symlink_to(kept, target_is_directory=True)
    else:
        link = tmp_path / "link"; link.symlink_to(kept, target_is_directory=True)
        destination = link / "drill"
    with pytest.raises(BackupIntegrityError, match="exists|symlink"):
        _run(archive, destination)
    assert sorted(p.name for p in kept.iterdir()) == ["keep"]
    assert (kept / "keep").read_text() == "unchanged"


def test_source_change_between_passes_is_not_accepted(tmp_path, monkeypatch):
    manifest, payloads = _fixture(tmp_path)
    archive = _archive(tmp_path / "source.tar.gz", manifest, payloads)
    original = drill._scan_archive
    calls = []
    def mutate(*args, **kwargs):
        if calls:
            archive.write_bytes(archive.read_bytes() + b"changed")
        calls.append(True)
        return original(*args, **kwargs)
    monkeypatch.setattr(drill, "_scan_archive", mutate)
    with pytest.raises(BackupIntegrityError, match="source archive changed"):
        _run(archive, tmp_path / "drill")
    _error(tmp_path / "drill")


def test_full_integrity_check_cannot_be_replaced_with_healthy_status(tmp_path, monkeypatch):
    manifest, payloads = _fixture(tmp_path, 1)
    payloads["nested/history.db"] = b"not a sqlite database"
    manifest["files"][0].update(bytes=len(payloads["nested/history.db"]), sha256=hashlib.sha256(payloads["nested/history.db"]).hexdigest())
    archive = _archive(tmp_path / "source.tar.gz", manifest, payloads)
    with pytest.raises(sqlite3.DatabaseError):
        _run(archive, tmp_path / "drill")
    assert _error(tmp_path / "drill")["phase"] == "verify_restored"


def test_deadline_is_bounded_and_reported(tmp_path, monkeypatch):
    manifest, payloads = _fixture(tmp_path)
    archive = _archive(tmp_path / "source.tar.gz", manifest, payloads)
    original = drill._scan_archive
    def expired(handle, expected, identity, deadline, *args, **kwargs):
        return original(handle, expected, identity, time.monotonic() - 1, *args, **kwargs)
    monkeypatch.setattr(drill, "_scan_archive", expired)
    with pytest.raises(BackupIntegrityError, match="deadline"):
        _run(archive, tmp_path / "drill")
    _error(tmp_path / "drill")


def test_validated_path_aliases_cannot_skip_logical_materialization(tmp_path):
    manifest, payloads = _fixture(tmp_path)
    metadata = manifest["sqlite_logical"][0]
    metadata["path"] = " nested/./history.db.sql.jsonl.gz "
    metadata["database_path"] = " nested/./history.db "
    estimate = drill.estimate_restore_workspace(manifest)
    assert estimate["other_output_bytes"] == len(payloads["settings.json"])
    archive = _archive(tmp_path / "source.tar.gz", manifest, payloads)
    report = _run(archive, tmp_path / "drill")
    restored = Path(report["restored_snapshot"])
    assert not list(restored.rglob("*.gz"))
    assert report["sqlite_checks"][0]["path"] == "nested/history.db"
    with sqlite3.connect(restored / "data/nested/history.db") as connection:
        assert connection.execute("SELECT count(*) FROM history").fetchone() == (1,)


def test_late_disk_consumption_cannot_publish_success(tmp_path, monkeypatch):
    manifest, payloads = _fixture(tmp_path)
    archive = _archive(tmp_path / "source.tar.gz", manifest, payloads)
    free = [10 * GIB]
    monkeypatch.setattr(drill.shutil, "disk_usage", lambda _: SimpleNamespace(free=free[0]))
    original = drill.verify_snapshot
    def pressure_after_verification(snapshot):
        result = original(snapshot)
        free[0] = RESTORE_RESERVE_BYTES - 1
        return result
    monkeypatch.setattr(drill, "verify_snapshot", pressure_after_verification)
    with pytest.raises((BackupIntegrityError, sqlite3.DatabaseError)):
        _run(archive, tmp_path / "drill")
    _error(tmp_path / "drill")
