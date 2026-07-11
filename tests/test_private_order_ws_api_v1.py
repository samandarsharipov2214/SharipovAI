from __future__ import annotations

import importlib
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from dashboard.private_order_ws_api import install_private_order_ws_api


class FakeWorker:
    def __init__(self, *, snapshot_error: bool = False, reconcile_error: bool = False) -> None:
        self.started = 0
        self.stopped = 0
        self.snapshot_error = snapshot_error
        self.reconcile_error = reconcile_error

    def start(self) -> None:
        self.started += 1

    def stop(self) -> None:
        self.stopped += 1

    def status(self) -> dict[str, Any]:
        return {
            "status": "disabled",
            "feature_enabled": False,
            "connected": False,
            "credentials_configured": False,
        }

    def snapshot(self) -> dict[str, Any]:
        if self.snapshot_error:
            raise RuntimeError("snapshot unavailable")
        return {"status": "ok", "tracked_orders": 0, "orders": []}

    def reconcile(self, journal: dict[str, Any]) -> dict[str, Any]:
        if self.reconcile_error:
            raise RuntimeError("journal unavailable")
        return {
            "status": "ok",
            "restart_safe": True,
            "accepted_journal_orders": len(journal.get("orders", [])),
            "unresolved": [],
        }


class FakeJournal:
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = rows or []

    def load(self) -> dict[str, Any]:
        return {"orders": list(self.rows)}


def patch_identity(monkeypatch, *, username: str | None, is_admin: bool) -> None:
    module = importlib.import_module("dashboard.app")
    monkeypatch.setattr(module, "_session_username", lambda request: username)
    monkeypatch.setattr(module, "_is_admin_request", lambda request: is_admin)
    monkeypatch.setenv("AUTH_SECRET", "test-auth-secret")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "test-admin-password")


def make_app(worker: FakeWorker, journal: FakeJournal | None = None) -> FastAPI:
    app = FastAPI()
    install_private_order_ws_api(app, worker=worker, journal=journal or FakeJournal())
    return app


def test_anonymous_requests_are_rejected_before_route_work(monkeypatch) -> None:
    patch_identity(monkeypatch, username=None, is_admin=False)
    worker = FakeWorker()
    with TestClient(make_app(worker)) as client:
        responses = [
            client.get("/api/exchange/private-order-ws/status"),
            client.get("/api/exchange/private-order-ws/snapshot"),
            client.post(
                "/api/exchange/private-order-ws/reconcile",
                content="{broken",
                headers={"content-type": "application/json"},
            ),
        ]
    assert all(response.status_code == 401 for response in responses)


def test_non_admin_is_forbidden(monkeypatch) -> None:
    patch_identity(monkeypatch, username="member", is_admin=False)
    with TestClient(make_app(FakeWorker())) as client:
        response = client.get("/api/exchange/private-order-ws/status")
    assert response.status_code == 403


def test_admin_status_is_read_only_and_redacted(monkeypatch) -> None:
    patch_identity(monkeypatch, username="admin", is_admin=True)
    worker = FakeWorker()
    with TestClient(make_app(worker)) as client:
        response = client.get("/api/exchange/private-order-ws/status")
    assert response.status_code == 200
    payload = response.json()
    assert payload["feature_enabled"] is False
    serialized = str(payload).lower()
    assert "api_secret" not in serialized
    assert "api_key" not in serialized
    assert worker.started == 1
    assert worker.stopped == 1


def test_admin_snapshot_and_reconciliation(monkeypatch) -> None:
    patch_identity(monkeypatch, username="admin", is_admin=True)
    worker = FakeWorker()
    journal = FakeJournal([{"status": "accepted", "order_id": "oid-1"}])
    with TestClient(make_app(worker, journal)) as client:
        snapshot = client.get("/api/exchange/private-order-ws/snapshot")
        reconciliation = client.post("/api/exchange/private-order-ws/reconcile")
    assert snapshot.status_code == 200
    assert snapshot.json()["tracked_orders"] == 0
    assert reconciliation.status_code == 200
    assert reconciliation.json()["restart_safe"] is True
    assert reconciliation.json()["accepted_journal_orders"] == 1


def test_worker_or_journal_failure_returns_503(monkeypatch) -> None:
    patch_identity(monkeypatch, username="admin", is_admin=True)
    with TestClient(make_app(FakeWorker(snapshot_error=True))) as client:
        snapshot = client.get("/api/exchange/private-order-ws/snapshot")
    assert snapshot.status_code == 503

    with TestClient(make_app(FakeWorker(reconcile_error=True))) as client:
        reconciliation = client.post("/api/exchange/private-order-ws/reconcile")
    assert reconciliation.status_code == 503


def test_installer_is_idempotent(monkeypatch) -> None:
    patch_identity(monkeypatch, username="admin", is_admin=True)
    worker = FakeWorker()
    app = make_app(worker)
    install_private_order_ws_api(app, worker=FakeWorker())
    paths = [route.path for route in app.routes]
    assert paths.count("/api/exchange/private-order-ws/status") == 1
    assert paths.count("/api/exchange/private-order-ws/snapshot") == 1
    assert paths.count("/api/exchange/private-order-ws/reconcile") == 1
