from __future__ import annotations

from collections import defaultdict

from fastapi import FastAPI

import dashboard


def _route_owners(app: FastAPI) -> list[tuple[str, str, str]]:
    owners: list[tuple[str, str, str]] = []
    for route in app.routes:
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None)
        endpoint = getattr(route, "endpoint", None)
        if not path or not methods or endpoint is None:
            continue
        module = getattr(endpoint, "__module__", type(endpoint).__module__)
        for method in methods:
            owners.append((method, path, module))
    return owners


def _duplicate_owners(app: FastAPI) -> dict[tuple[str, str], list[str]]:
    grouped: dict[tuple[str, str], list[str]] = defaultdict(list)
    for method, path, module in _route_owners(app):
        grouped[(method, path)].append(module)
    return {
        signature: modules
        for signature, modules in grouped.items()
        if len(modules) > 1
    }


def test_production_routes_have_single_method_path_owner() -> None:
    app = dashboard.create_production_app()

    assert _duplicate_owners(app) == {}


def test_critical_production_routes_have_exactly_one_owner() -> None:
    app = dashboard.create_production_app()
    owners = _route_owners(app)

    for signature in (
        ("GET", "/api/auth/me"),
        ("GET", "/api/system/release-truth"),
        ("POST", "/api/control-plane/commands/{action}"),
    ):
        matching = [module for method, path, module in owners if (method, path) == signature]
        assert len(matching) == 1, f"{signature} owners={matching}"
