"""Fail-closed static guard for direct exchange execution paths.

The guard is intentionally narrow: only canonical execution modules may contain
known private order submission primitives. Tests may contain fixture strings but
not executable calls. New execution adapters must be explicitly allowlisted in
code review instead of silently creating a second order path.
"""
from __future__ import annotations

import argparse
import ast
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

CANONICAL_EXECUTION_FILES = {
    "exchange_connector/bybit_execution.py",
}

FORBIDDEN_CALL_NAMES = {
    "create_order",
    "place_order",
    "submit_order",
    "amend_order",
    "cancel_order",
    "batch_place_order",
    "batch_cancel_order",
}

SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", "artifacts"}


@dataclass(frozen=True)
class Violation:
    path: str
    line: int
    call: str


def _call_name(node: ast.Call) -> str | None:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def scan_file(path: Path, *, root: Path) -> list[Violation]:
    relative = path.relative_to(root).as_posix()
    if relative in CANONICAL_EXECUTION_FILES or relative.startswith("tests/") or "/tests/" in relative:
        return []
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
    except (UnicodeDecodeError, SyntaxError):
        return []
    violations: list[Violation] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node)
        if name in FORBIDDEN_CALL_NAMES:
            violations.append(Violation(relative, int(getattr(node, "lineno", 0)), name))
    return violations


def iter_python_files(root: Path) -> Iterable[Path]:
    for path in root.rglob("*.py"):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        yield path


def scan_repository(root: Path) -> list[Violation]:
    root = root.resolve()
    violations: list[Violation] = []
    for path in iter_python_files(root):
        violations.extend(scan_file(path, root=root))
    return sorted(violations, key=lambda item: (item.path, item.line, item.call))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", nargs="?", default=".")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    violations = scan_repository(Path(args.root))
    payload = {"status": "blocked" if violations else "ok", "violations": [asdict(v) for v in violations]}
    if args.json:
        print(json.dumps(payload, sort_keys=True))
    else:
        for violation in violations:
            print(f"{violation.path}:{violation.line}: forbidden execution call {violation.call}")
        print(f"execution-path-guard: {payload['status']}")
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
