from __future__ import annotations

from fastapi import FastAPI

import dashboard


def _route_signatures(app: FastAPI) -> set[tuple[str, str]]:
    signatures: set[tuple[str, str]] = set()
    for route in app.routes:
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None)
        if not path or not methods:
            continue
        for method in methods:
            signatures.add((method, path))
    return signatures


def test_fresh_production_factory_matches_runtime_route_graph() -> None:
    fresh = dashboard.create_production_app()
    assert _route_signatures(fresh) == _route_signatures(dashboard.app)


def test_fresh_production_factory_preserves_auth_and_release_routes() -> None:
    fresh = dashboard.create_production_app()
    runtime_routes = _route_signatures(dashboard.app)
    fresh_routes = _route_signatures(fresh)

    for signature in (("GET", "/api/auth/me"), ("GET", "/api/system/release-truth")):
        assert signature in runtime_routes
        assert signature in fresh_routes
