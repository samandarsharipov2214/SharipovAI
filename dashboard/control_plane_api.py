"""Dashboard 2.0 control-plane endpoints."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request

from control_plane import ControlPlane


def install_control_plane_api(app: FastAPI) -> None:
    if getattr(app.state, "control_plane_api_installed", False):
        return
    app.state.control_plane_api_installed = True

    def plane() -> ControlPlane:
        return ControlPlane(Path.cwd())

    @app.get("/api/control-plane/status")
    def control_plane_status() -> dict[str, Any]:
        return plane().snapshot()

    @app.get("/api/control-plane/ai-registry")
    def ai_registry() -> dict[str, Any]:
        snapshot = plane().snapshot()
        return {
            "status": "ok",
            "components": snapshot["components"],
            "manager": snapshot["manager"],
        }

    @app.post("/api/control-plane/commands/{action}")
    def queue_command(action: str, request: Request) -> dict[str, Any]:
        # Global auth guard protects this endpoint. Commands are strictly allow-listed;
        # arbitrary shell execution is intentionally impossible.
        requested_by = request.headers.get("x-sharipovai-user", "dashboard")
        try:
            command = plane().enqueue(action, requested_by=requested_by)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"status": "accepted", "command": command}
