from __future__ import annotations

import tomllib
from pathlib import Path


_IGNORED_PARTS = {".git", ".venv", "venv", "node_modules", "build", "dist"}


def test_every_repository_regression_test_is_collected() -> None:
    root = Path(__file__).resolve().parents[2]
    config = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    configured = tuple(
        Path(str(item).strip())
        for item in config["tool"]["pytest"]["ini_options"]["testpaths"]
        if str(item).strip()
    )
    assert Path("tests") in configured

    uncovered: list[str] = []
    for test_file in root.rglob("test_*.py"):
        relative = test_file.relative_to(root)
        if any(part in _IGNORED_PARTS for part in relative.parts):
            continue
        if not any(relative.is_relative_to(base) for base in configured):
            uncovered.append(str(relative))

    assert not uncovered, f"Regression tests excluded from full pytest: {sorted(uncovered)}"
