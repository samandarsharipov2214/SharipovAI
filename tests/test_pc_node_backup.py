from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.pc_node_backup import BackupError, atomic_snapshot


def test_snapshot_is_verified_and_rotated(tmp_path: Path) -> None:
    source = tmp_path / "data"
    source.mkdir()
    (source / "state.json").write_text('{"value": 1}', encoding="utf-8")
    root = tmp_path / "backups"

    first = atomic_snapshot(source, root)
    assert first["file_count"] == 1
    assert (root / "current" / "data" / "state.json").read_text(encoding="utf-8") == '{"value": 1}'

    (source / "state.json").write_text('{"value": 2}', encoding="utf-8")
    second = atomic_snapshot(source, root)
    assert second["file_count"] == 1
    assert (root / "current" / "data" / "state.json").read_text(encoding="utf-8") == '{"value": 2}'
    assert (root / "previous" / "data" / "state.json").read_text(encoding="utf-8") == '{"value": 1}'

    manifest = json.loads((root / "current" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["files"][0]["path"] == "state.json"
    assert len(manifest["files"][0]["sha256"]) == 64


def test_missing_source_fails_without_destroying_current(tmp_path: Path) -> None:
    root = tmp_path / "backups"
    current = root / "current"
    current.mkdir(parents=True)
    marker = current / "marker.txt"
    marker.write_text("keep", encoding="utf-8")

    with pytest.raises(BackupError, match="does not exist"):
        atomic_snapshot(tmp_path / "missing", root)

    assert marker.read_text(encoding="utf-8") == "keep"


def test_backup_root_inside_source_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "data"
    source.mkdir()
    with pytest.raises(BackupError, match="must not be inside"):
        atomic_snapshot(source, source / "backups")
