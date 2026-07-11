"""Read-only synchronization of the owner's live Bybit account."""
from __future__ import annotations

import os
import threading
import time
from typing import Any, Callable

from fastapi import FastAPI, HTTPException, Request

from exchange_connector.bybit_account import BybitAccountClient


class BybitAccountSync:
    def __init__(self, client: BybitAccountClient | None = None) -> None:
        self.client = client or BybitAccountClient()
        self.interval = max(float(os.getenv("BYBIT_ACCOUNT_SYNC_SECONDS", "15")), 5.0)
        self._snapshot: dict[str, Any] | None = None
        self._last_error: str | None = None
        self._last_attempt_ms: int | None = None
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if not _truthy("BYBIT_ACCOUNT_SYNC_ENABLED", default=True):
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="bybit-account-sync", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=2.0)

    def sync_now(self) -> dict[str, Any]:
        self._last_attempt_ms = int(time.time() * 1000)
        try:
            snapshot = self.client.fetch_snapshot()
            self.client.save_snapshot(snapshot)
            data = snapshot.to_dict()
            with self._lock:
                self._snapshot = data
                self._last_error = None
            return data
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            with self._lock:
                self._last_error = error
            raise

    def status(self) -> dict[str, Any]:
        with self._lock:
            snapshot = dict(self._snapshot) if self._snapshot else None
            error = self._last_error
        age_seconds: float | None = None
        if snapshot:
            age_seconds = max((int(time.time() * 1000) - int(snapshot.get("received_at_ms", 0))) / 1000, 0.0)
        return {
            **self.client.status(),
            "worker_running": bool(self._thread and self._thread.is_alive()),
            "last_attempt_ms": self._last_attempt_ms,
            "last_error": error,
            "connected": bool(snapshot and snapshot.get("status") == "connected"),
            "snapshot_age_seconds": age_seconds,
            "snapshot_available": snapshot is not None,
        }

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            if self._snapshot is None:
                raise RuntimeError(self._last_error or "Bybit account snapshot is not available yet")
            return dict(self._snapshot)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.sync_now()
            except Exception:
                pass
            self._stop.wait(self.interval)


def install_bybit_account_api(app: FastAPI) -> None:
    if getattr(app.state, "bybit_account_api_installed", False):
        return
    app.state.bybit_account_api_installed = True
    app.state.bybit_account_sync = BybitAccountSync()

    _register_lifecycle_handler(app, "startup", app.state.bybit_account_sync.start)
    _register_lifecycle_handler(app, "shutdown", app.state.bybit_account_sync.stop)

    @app.get("/api/exchange/account/status")
    def account_status(request: Request) -> dict[str, Any]:
        _require_admin(request)
        return app.state.bybit_account_sync.status()

    @app.get("/api/exchange/account/snapshot")
    def account_snapshot(request: Request) -> dict[str, Any]:
        _require_admin(request)
        try:
            return app.state.bybit_account_sync.snapshot()
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail={"status": "unavailable", "message": str(exc)}) from exc

    @app.post("/api/exchange/account/sync")
    def account_sync_now(request: Request) -> dict[str, Any]:
        _require_admin(request)
        try:
            return app.state.bybit_account_sync.sync_now()
        except Exception as exc:
            raise HTTPException(status_code=503, detail={"status": "unavailable", "message": str(exc)}) from exc


def _require_admin(request: Request) -> str:
    """Allow private Bybit account data only to an authenticated admin."""
    # Lazy import avoids a circular import while dashboard.app is initialized.
    from .app import _is_admin_request, _session_username

    username = _session_username(request)
    if not username:
        raise HTTPException(status_code=401, detail={"status": "unauthorized"})
    if not _is_admin_request(request):
        raise HTTPException(status_code=403, detail={"status": "forbidden"})
    return username


def _register_lifecycle_handler(app: FastAPI, event: str, handler: Callable[[], None]) -> None:
    """Register startup/shutdown handlers across FastAPI/Starlette versions."""
    legacy = getattr(app, "add_event_handler", None)
    if callable(legacy):
        legacy(event, handler)
        return

    router = getattr(app, "router", None)
    handlers = getattr(router, f"on_{event}", None) if router is not None else None
    if isinstance(handlers, list):
        handlers.append(handler)
        return

    if event == "startup":
        handler()


def _truthy(name: str, *, default: bool = False) -> bool:
    return os.getenv(name, "1" if default else "0").strip().lower() in {"1", "true", "yes", "on"}
