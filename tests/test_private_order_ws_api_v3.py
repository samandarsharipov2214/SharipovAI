from __future__ import annotations

import importlib

from fastapi import FastAPI
from fastapi.testclient import TestClient

from dashboard.private_order_ws_api import install_private_order_ws_api


dashboard_app = importlib.import_module("dashboard.app")


class Worker:
    def __init__(self, fail_snapshot=False):
        self.started = 0
        self.stopped = 0
        self.fail_snapshot = fail_snapshot

    def start(self):
        self.started += 1

    def stop(self):
        self.stopped += 1

    def status(self):
        return {"enabled": False, "connected": False, "credential_profile": "testnet_execution"}

    def snapshot(self):
        if self.fail_snapshot:
            raise RuntimeError("corrupt state")
        return {"status": "unverified", "orders": []}

    def reconcile(self, journal):
        return {"status": "blocked", "restart_safe": False, "errors": ["not verified"], "journal": journal}


class Journal:
    def load(self):
        return {"orders": [{"order_link_id": "sai_x"}]}


def configured(monkeypatch):
    monkeypatch.setenv("AUTH_SECRET", "secret")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "password")


def test_anonymous_non_admin_and_admin_paths(monkeypatch) -> None:
    configured(monkeypatch)
    app = FastAPI()
    worker = Worker()
    install_private_order_ws_api(app, worker=worker, journal=Journal())
    monkeypatch.setattr(dashboard_app, "_session_username", lambda request: None)
    monkeypatch.setattr(dashboard_app, "_is_admin_request", lambda request: False)
    assert TestClient(app).get("/api/exchange/private-order-ws/status").status_code == 401
    monkeypatch.setattr(dashboard_app, "_session_username", lambda request: "user")
    assert TestClient(app).get("/api/exchange/private-order-ws/status").status_code == 403
    monkeypatch.setattr(dashboard_app, "_session_username", lambda request: "admin")
    monkeypatch.setattr(dashboard_app, "_is_admin_request", lambda request: True)
    with TestClient(app) as client:
        status = client.get("/api/exchange/private-order-ws/status")
        assert status.status_code == 200 and "secret" not in status.text
        assert client.get("/api/exchange/private-order-ws/snapshot").status_code == 200
        result = client.post("/api/exchange/private-order-ws/reconcile")
        assert result.status_code == 200 and result.json()["restart_safe"] is False
        assert worker.started == 1
    assert worker.stopped == 1


def test_snapshot_error_and_idempotent_installer(monkeypatch) -> None:
    configured(monkeypatch)
    monkeypatch.setattr(dashboard_app, "_session_username", lambda request: "admin")
    monkeypatch.setattr(dashboard_app, "_is_admin_request", lambda request: True)
    app = FastAPI()
    install_private_order_ws_api(app, worker=Worker(True), journal=Journal())
    install_private_order_ws_api(app, worker=Worker(), journal=Journal())
    response = TestClient(app).get("/api/exchange/private-order-ws/snapshot")
    assert response.status_code == 503 and "corrupt state" in response.text
    assert [route.path for route in app.routes].count("/api/exchange/private-order-ws/status") == 1
