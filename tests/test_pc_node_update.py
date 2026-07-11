from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from tools.pc_node_update import apply_update


def _write_project(root: Path, marker: str, *, valid: bool = True) -> None:
    (root / "dashboard").mkdir(parents=True, exist_ok=True)
    (root / "dashboard" / "__init__.py").write_text(f"MARKER = {marker!r}\n", encoding="utf-8")
    if valid:
        (root / "requirements.txt").write_text("pytest>=9\n", encoding="utf-8")
    (root / "app.py").write_text(f"VALUE = {marker!r}\n", encoding="utf-8")


def _archive(source: Path, archive: Path, prefix: str = "SharipovAI-main") -> None:
    with zipfile.ZipFile(archive, "w") as bundle:
        for item in source.rglob("*"):
            if item.is_file():
                bundle.write(item, Path(prefix) / item.relative_to(source))


def test_update_preserves_local_state_and_creates_backup(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    _write_project(project, "old")
    (project / ".env.local").write_text("SECRET=keep\n", encoding="utf-8")
    (project / "data").mkdir()
    (project / "data" / "state.json").write_text("{}", encoding="utf-8")

    incoming = tmp_path / "incoming"
    incoming.mkdir()
    _write_project(incoming, "new")
    archive = tmp_path / "update.zip"
    _archive(incoming, archive)

    report = apply_update(archive, project)

    assert "new" in (project / "app.py").read_text(encoding="utf-8")
    assert (project / ".env.local").read_text(encoding="utf-8") == "SECRET=keep\n"
    assert (project / "data" / "state.json").exists()
    backup = Path(str(report["backup"]))
    assert "old" in (backup / "app.py").read_text(encoding="utf-8")
    assert (project / "runtime" / "last_update.json").exists()


def test_invalid_archive_does_not_modify_project(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    _write_project(project, "old")

    incoming = tmp_path / "incoming"
    incoming.mkdir()
    _write_project(incoming, "broken", valid=False)
    archive = tmp_path / "invalid.zip"
    _archive(incoming, archive)

    with pytest.raises(FileNotFoundError):
        apply_update(archive, project)

    assert "old" in (project / "app.py").read_text(encoding="utf-8")


def test_zip_slip_is_rejected(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    _write_project(project, "old")
    archive = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("../outside.txt", "bad")

    with pytest.raises(ValueError):
        apply_update(archive, project)

    assert not (tmp_path / "outside.txt").exists()
