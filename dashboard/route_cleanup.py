"""Helpers for replacing legacy FastAPI routes with canonical owners."""
from __future__ import annotations

from collections.abc import Iterable

from fastapi import FastAPI


def _targets(specifications: Iterable[tuple[str, str]]) -> set[tuple[str, str]]:
    return {(method.upper(), path) for method, path in specifications}


def _matches(route: object, targets: set[tuple[str, str]]) -> bool:
    path = str(getattr(route, "path", ""))
    methods = {str(item).upper() for item in (getattr(route, "methods", None) or ())}
    return any(target_path == path and target_method in methods for target_method, target_path in targets)


def remove_legacy_routes(
    app: FastAPI,
    specifications: Iterable[tuple[str, str]],
    *,
    owner_module: str | None = None,
) -> int:
    """Remove exact method/path routes before a canonical owner is registered."""

    targets = _targets(specifications)
    kept = []
    removed = 0
    for route in app.router.routes:
        endpoint = getattr(route, "endpoint", None)
        module_name = str(getattr(endpoint, "__module__", ""))
        owner_matches = owner_module is None or module_name == owner_module or module_name.startswith(f"{owner_module}.")
        if _matches(route, targets) and owner_matches:
            removed += 1
            continue
        kept.append(route)
    app.router.routes[:] = kept
    return removed


def retain_last_registered_routes(
    app: FastAPI,
    specifications: Iterable[tuple[str, str]],
) -> int:
    """Keep only the last registered route for each exact method/path.

    Canonical installers call this after defining their endpoints. This protects
    route ownership even when a compatibility installer registered the same path
    earlier in the application factory.
    """

    targets = _targets(specifications)
    last_index: dict[tuple[str, str], int] = {}
    for index, route in enumerate(app.router.routes):
        path = str(getattr(route, "path", ""))
        methods = {str(item).upper() for item in (getattr(route, "methods", None) or ())}
        for target in targets:
            if target[1] == path and target[0] in methods:
                last_index[target] = index

    kept = []
    removed = 0
    for index, route in enumerate(app.router.routes):
        path = str(getattr(route, "path", ""))
        methods = {str(item).upper() for item in (getattr(route, "methods", None) or ())}
        matching_targets = [target for target in targets if target[1] == path and target[0] in methods]
        if matching_targets and any(last_index.get(target) != index for target in matching_targets):
            removed += 1
            continue
        kept.append(route)
    app.router.routes[:] = kept
    return removed


__all__ = ["remove_legacy_routes", "retain_last_registered_routes"]
