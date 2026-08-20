from __future__ import annotations

from fastapi import FastAPI

import dashboard

# Integrated-main regression probe: this branch intentionally runs the full CI suite
# against the exact post-merge application graph before any corrective change.


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


def _middleware_classes(app: FastAPI) -> tuple[type, ...]:
    return tuple(item.cls for item in app.user_middleware)


def test_production_factory_matches_production_route_graph() -> None:
    factory_app = dashboard.create_production_app()

    assert _route_signatures(factory_app) == _route_signatures(dashboard.app)


def test_production_factory_matches_production_middleware_graph() -> None:
    factory_app = dashboard.create_production_app()

    assert _middleware_classes(factory_app) == _middleware_classes(dashboard.app)


def test_production_factory_contains_critical_production_contracts() -> None:
    factory_app = dashboard.create_production_app()
    signatures = _route_signatures(factory_app)

    expected = {
        ("GET", "/api/auth/me"),
        ("GET", "/api/system/release-truth"),
        ("POST", "/api/control-plane/commands/{action}"),
    }
    assert expected <= signatures


def test_legacy_factory_remains_separate_during_migration() -> None:
    legacy_app = dashboard.create_app()
    production_app = dashboard.create_production_app()

    assert _route_signatures(legacy_app) != _route_signatures(production_app)
