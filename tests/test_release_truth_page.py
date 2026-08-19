from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from dashboard.release_truth_page import install_release_truth_page


def test_release_truth_page_is_read_only_no_store_and_uses_canonical_endpoint() -> None:
    app = FastAPI()
    install_release_truth_page(app)

    response = TestClient(app).get("/release-truth")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert "/api/system/release-truth" in response.text
    assert "Truth / Release Center" in response.text
    assert "UNKNOWN and STALE are preserved" in response.text
    assert "confirm_production_deploy" not in response.text
    assert "method=\"post\"" not in response.text.lower()
    assert "fetch('/api/system/release-truth'" in response.text


def test_release_truth_page_install_is_idempotent() -> None:
    app = FastAPI()
    install_release_truth_page(app)
    install_release_truth_page(app)

    routes = [route.path for route in app.routes if getattr(route, "path", None) == "/release-truth"]
    assert routes == ["/release-truth"]
