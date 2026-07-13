"""Helpers for replacing legacy FastAPI routes with canonical owners."""
from __future__ import annotations

from collections.abc import Iterable

from fastapi import FastAPI


def remove_legacy_routes(
    app: FastAPI,
    specifications: Iterable[tuple[str, str]],
    *,
    owner_module: str | None = None,
) -> int:
    """Remove exact method/path routes before a canonical owner is registered.

    Installers call this helper immediately before adding their canonical route,
    so every exact match present at this point is necessarily an older owner.
    Matching by method and path is more reliable than ``endpoint.__module__``:
    FastAPI wrappers and compatibility adapters may preserve a different module
    name even though they still shadow the canonical endpoint.
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
        owner_matches = owner_module is None or module_name == owner_module or module_name.startswith(f"{owner_module}.")
        if matches and owner_matches:
            removed += 1
            continue
        kept.append(route)
    app.router.routes[:] = kept
    return removed


__all__ = ["remove_legacy_routes"]
