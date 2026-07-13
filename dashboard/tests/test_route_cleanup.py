from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from dashboard.route_cleanup import remove_legacy_routes, retain_last_registered_routes


def test_exact_legacy_route_is_removed_before_canonical_registration() -> None:
    app = FastAPI()

    @app.get("/api/example")
    def first_legacy() -> dict[str, str]:
        return {"owner": "first"}

    @app.get("/api/example")
    def wrapped_legacy() -> dict[str, str]:
        return {"owner": "wrapped"}

    removed = remove_legacy_routes(app, (("GET", "/api/example"),))

    @app.get("/api/example")
    def canonical() -> dict[str, str]:
        return {"owner": "canonical"}

    assert removed == 2
    response = TestClient(app).get("/api/example")
    assert response.status_code == 200
    assert response.json() == {"owner": "canonical"}


def test_last_registered_canonical_route_replaces_reintroduced_legacy_owner() -> None:
    app = FastAPI()

    @app.get("/api/example")
    def legacy() -> dict[str, str]:
        return {"owner": "legacy"}

    @app.get("/api/example")
    def compatibility_wrapper() -> dict[str, str]:
        return {"owner": "compatibility"}

    @app.get("/api/example")
    def canonical() -> dict[str, str]:
        return {"owner": "canonical"}

    assert retain_last_registered_routes(app, (("GET", "/api/example"),)) == 2
    assert TestClient(app).get("/api/example").json() == {"owner": "canonical"}


def test_cleanup_does_not_remove_other_method_or_path() -> None:
    app = FastAPI()

    @app.post("/api/example")
    def post_route() -> dict[str, str]:
        return {"method": "post"}

    @app.get("/api/other")
    def other_route() -> dict[str, str]:
        return {"path": "other"}

    assert remove_legacy_routes(app, (("GET", "/api/example"),)) == 0
    client = TestClient(app)
    assert client.post("/api/example").status_code == 200
    assert client.get("/api/other").status_code == 200
