"""Helpers for replacing legacy FastAPI routes with canonical owners."""
from __future__ import annotations

from collections.abc import Iterable

from fastapi import FastAPI


def remove_legacy_routes(
    app: FastAPI,
    specifications: Iterable[tuple[str, str]],
    *,
    owner_module: str | None = "dashboard.routes",
) -> int:
    """Remove exact method/path routes before a canonical owner is installed.

    By default only endpoints from ``dashboard.routes`` are removed. A canonical
    installer may pass ``owner_module=None`` when it owns the exact route slot and
    runs before registering its replacement. This remains bounded by both HTTP
    method and exact path, so unrelated routes cannot be removed accidentally.
    """

    targets = {(method.upper(), path) for method, path in specifications}
    kept = []
    removed = 0
    for route in app.router.routes:
        path = str(getattr(route, "path", ""))
        methods = {str(item).upper() for item in (getattr(route, "methods", None) or ())}
        endpoint = getattr(route, "endpoint", None)
        module_name = str(getattr(endpoint, "__module__", ""))
        matches = any(target_path == path and target_method in methods for target_method, target_path in targets)
        owned = owner_module is None or module_name == owner_module
        if matches and owned:
            removed += 1
            continue
        kept.append(route)
    app.router.routes[:] = kept
    return removed


__all__ = ["remove_legacy_routes"]
