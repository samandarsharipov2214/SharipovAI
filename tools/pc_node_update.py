"""Safe offline updater for a SharipovAI PC node.

The updater accepts a GitHub ZIP (or any ZIP with the repository contents),
creates a rollback snapshot, preserves local secrets/data, overlays the new
code, validates Python syntax, and restores the previous code on failure.
"""
from __future__ import annotations

import argparse
import compileall
import json
import shutil
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path

PROTECTED_TOP_LEVEL = {
    ".env",
    ".env.local",
    ".git",
    ".venv",
    "data",
    "runtime",
}
REQUIRED_FILES = {"requirements.txt", "dashboard/__init__.py"}


def _safe_extract(archive: Path, destination: Path) -> None:
    destination = destination.resolve()
    with zipfile.ZipFile(archive) as bundle:
        for member in bundle.infolist():
            target = (destination / member.filename).resolve()
            if destination != target and destination not in target.parents:
                raise ValueError(f"Unsafe archive member: {member.filename}")
        bundle.extractall(destination)


def _find_source_root(extracted: Path) -> Path:
    candidates = [extracted, *[p for p in extracted.iterdir() if p.is_dir()]]
    for candidate in candidates:
        if all((candidate / relative).exists() for relative in REQUIRED_FILES):
            return candidate
    raise FileNotFoundError("Archive does not contain a valid SharipovAI repository")


def _is_protected(relative: Path) -> bool:
    return bool(relative.parts) and relative.parts[0] in PROTECTED_TOP_LEVEL


def _copy_tree(source: Path, destination: Path) -> int:
    copied = 0
    for item in source.rglob("*"):
        relative = item.relative_to(source)
        if _is_protected(relative):
            continue
        target = destination / relative
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, target)
        copied += 1
    return copied


def _snapshot(project_root: Path, backup_root: Path) -> int:
    backup_root.mkdir(parents=True, exist_ok=False)
    return _copy_tree(project_root, backup_root)


def _clear_unprotected(project_root: Path) -> None:
    for item in list(project_root.iterdir()):
        if item.name in PROTECTED_TOP_LEVEL:
            continue
        if item.is_dir():
            shutil.rmtree(item)
        else:
            item.unlink()


def _validate(project_root: Path) -> None:
    for relative in REQUIRED_FILES:
        if not (project_root / relative).exists():
            raise FileNotFoundError(f"Required file missing after update: {relative}")
    if not compileall.compile_dir(project_root, quiet=1, force=True):
        raise RuntimeError("Python syntax validation failed")


def apply_update(archive: Path, project_root: Path) -> dict[str, object]:
    archive = archive.resolve()
    project_root = project_root.resolve()
    if not archive.is_file():
        raise FileNotFoundError(f"Update archive not found: {archive}")
    if not project_root.is_dir():
        raise FileNotFoundError(f"Project root not found: {project_root}")

    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    backup_root = project_root / "runtime" / "update_backups" / stamp
    report_path = project_root / "runtime" / "last_update.json"

    with tempfile.TemporaryDirectory(prefix="sharipovai-update-") as temp_dir:
        extracted = Path(temp_dir)
        _safe_extract(archive, extracted)
        source_root = _find_source_root(extracted)
        backup_files = _snapshot(project_root, backup_root)
        try:
            _clear_unprotected(project_root)
            copied_files = _copy_tree(source_root, project_root)
            _validate(project_root)
        except Exception:
            _clear_unprotected(project_root)
            _copy_tree(backup_root, project_root)
            raise

    report = {
        "status": "success",
        "archive": str(archive),
        "project_root": str(project_root),
        "backup": str(backup_root),
        "backup_files": backup_files,
        "copied_files": copied_files,
        "updated_at": datetime.now(UTC).isoformat(),
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Safely update a SharipovAI PC node from a ZIP archive")
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--project-root", required=True, type=Path)
    args = parser.parse_args()

    report = apply_update(args.archive, args.project_root)
    print("SharipovAI update completed successfully.")
    print(f"Backup: {report['backup']}")
    print(f"Copied files: {report['copied_files']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
