"""Admin runtime surface for automatic Paper/Testnet fill validation."""
from __future__ import annotations

from typing import Any, Callable

from fastapi import FastAPI, HTTPException, Request

from storage import ProjectDatabase
from validation import RuntimeFillHarvester

from .admin_guard import install_sensitive_api_guard, require_admin


def install_fill_harvester_api(app: FastAPI) -> None:
    if getattr(app.state, "fill_harvester_api_installed", False):
        return
    database = getattr(app.state, "project_database", None)
    if not isinstance(database, ProjectDatabase):
        raise RuntimeError("ProjectDatabase must be installed before fill harvester")
    app.state.fill_harvester_api_installed = True
    install_sensitive_api_guard(app)
    harvester = RuntimeFillHarvester(database=database)
    app.state.runtime_fill_harvester = harvester
    _register(app, "startup", harvester.start)
    _register(app, "shutdown", harvester.stop)

    @app.get("/api/validation/fill-harvester/status")
    def fill_harvester_status(request: Request) -> dict[str, Any]:
        require_admin(request)
        return harvester.snapshot()

    @app.post("/api/validation/fill-harvester/run")
    def run_fill_harvester(request: Request, experiment_id: str) -> dict[str, Any]:
        require_admin(request)
        try:
            return harvester.harvest(
                experiment_id=experiment_id,
                actor="dashboard-admin",
            )
        except Exception as exc:
            raise HTTPException(
                status_code=409,
                detail={"status": "blocked", "message": f"{type(exc).__name__}: {exc}"},
            ) from exc


def _register(app: FastAPI, event: str, handler: Callable[[], None]) -> None:
    legacy = getattr(app, "add_event_handler", None)
    if callable(legacy):
        legacy(event, handler)
        return
    handlers = getattr(getattr(app, "router", None), f"on_{event}", None)
    if isinstance(handlers, list):
        handlers.append(handler)
        return
    raise RuntimeError(f"FastAPI lifecycle registration unavailable for {event}")


__all__ = ["install_fill_harvester_api"]
