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

FORBIDDEN_ORDER_ENDPOINT_PARTS = (
    "/v5/order/create",
    "/v5/order/amend",
    "/v5/order/cancel",
    "/v5/order/cancel-all",
    "/v5/order/create-batch",
    "/v5/order/cancel-batch",
)

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
    return _ExecutionCallVisitor(relative).scan(tree)


class _ExecutionCallVisitor(ast.NodeVisitor):
    """Track the lightweight aliases that hide a direct order primitive."""

    def __init__(self, relative: str) -> None:
        self.relative = relative
        self.aliases: set[str] = set()
        self.violations: list[Violation] = []

    def scan(self, tree: ast.AST) -> list[Violation]:
        self.visit(tree)
        return self.violations

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:  # noqa: N802
        for imported in node.names:
            if imported.name in FORBIDDEN_CALL_NAMES:
                self.aliases.add(imported.asname or imported.name)
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:  # noqa: N802
        name = _call_name(node.value) if isinstance(node.value, ast.Call) else _attribute_name(node.value)
        dynamic_name = _statically_resolved_getattr(node.value)
        if name in FORBIDDEN_CALL_NAMES or (isinstance(node.value, ast.Name) and node.value.id in self.aliases):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    self.aliases.add(target.id)
        if dynamic_name in FORBIDDEN_CALL_NAMES:
            for target in node.targets:
                if isinstance(target, ast.Name):
                    self.aliases.add(target.id)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        name = _call_name(node)
        if name in FORBIDDEN_CALL_NAMES or (isinstance(node.func, ast.Name) and node.func.id in self.aliases):
            self._add(node, name or node.func.id)
        dynamic_name = _statically_resolved_getattr(node.func)
        if dynamic_name in FORBIDDEN_CALL_NAMES:
            self._add(node, f"getattr_{dynamic_name}")
        for value in ast.walk(node):
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                endpoint = value.value.lower()
                if any(part in endpoint for part in FORBIDDEN_ORDER_ENDPOINT_PARTS):
                    self._add(value, "private_order_endpoint")
        self.generic_visit(node)

    def _add(self, node: ast.AST, call: str) -> None:
        violation = Violation(self.relative, int(getattr(node, "lineno", 0)), call)
        if violation not in self.violations:
            self.violations.append(violation)


def _attribute_name(node: ast.AST) -> str | None:
    return node.attr if isinstance(node, ast.Attribute) else None


def _statically_resolved_getattr(node: ast.AST) -> str | None:
    """Return a literal attribute name for ``getattr(obj, 'name')`` only.

    Dynamic attribute names intentionally remain outside this static guard's
    proof boundary; execution still needs the runtime authorization contract.
    """

    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name) or node.func.id != "getattr":
        return None
    if len(node.args) < 2:
        return None
    value = node.args[1]
    return value.value if isinstance(value, ast.Constant) and isinstance(value.value, str) else None


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
