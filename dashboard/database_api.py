"""Canonical database, readiness and shared project-memory endpoints."""
from __future__ import annotations

import os
import time
import uuid
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from storage import ProjectDatabase


class ProjectMessageInput(BaseModel):
    project_id: str = Field(default="SharipovAI", min_length=1, max_length=200)
    chat_id: str = Field(min_length=1, max_length=200)
    message_id: str | None = Field(default=None, max_length=200)
    role: str
    content: str = Field(min_length=1, max_length=200_000)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at_ms: int | None = None


def install_database_api(app: FastAPI, *, database: ProjectDatabase | None = None) -> None:
    if getattr(app.state, "database_api_installed", False):
        return
    app.state.database_api_installed = True
    app.state.project_database = database or ProjectDatabase()
    _register_startup(app, app.state.project_database.initialize)

    @app.get("/health")
    def health() -> JSONResponse:
        payload = readiness_status(app.state.project_database)
        return JSONResponse(payload, status_code=200 if payload["status"] == "ok" else 503)

    @app.get("/api/system/database/status")
    def database_status(request: Request) -> dict[str, Any]:
        _require_admin(request)
        return readiness_status(app.state.project_database)

    @app.post("/api/project-memory/messages")
    def append_project_message(message: ProjectMessageInput, request: Request) -> dict[str, Any]:
        _require_authenticated(request)
        message_id = message.message_id or str(uuid.uuid4())
        app.state.project_database.append_message(
            project_id=message.project_id,
            chat_id=message.chat_id,
            message_id=message_id,
            role=message.role,
            content=message.content,
            metadata=message.metadata,
            created_at_ms=message.created_at_ms,
        )
        return {"status": "stored", "message_id": message_id}

    @app.get("/api/project-memory/messages")
    def list_project_messages(
        request: Request,
        project_id: str = "SharipovAI",
        chat_id: str | None = None,
        limit: int = 200,
    ) -> dict[str, Any]:
        _require_authenticated(request)
        items = app.state.project_database.list_messages(project_id=project_id, chat_id=chat_id, limit=limit)
        return {"status": "ok", "project_id": project_id, "messages": items}


def readiness_status(database: ProjectDatabase) -> dict[str, Any]:
    db = database.health()
    missing = _missing_required_configuration()
    status = "ok" if db.get("status") == "ok" and not missing else "error"
    return {
        "status": status,
        "service": "SharipovAI OS",
        "time_ms": int(time.time() * 1000),
        "database": db,
        "configuration": {
            "status": "ok" if not missing else "error",
            "missing": missing,
            "auth_enabled": os.getenv("SHARIPOVAI_DISABLE_AUTH", "0").strip().lower() not in {"1", "true", "yes", "on"},
            "kill_switch": os.getenv("EXECUTION_KILL_SWITCH", "1").strip().lower() in {"1", "true", "yes", "on"},
            "testnet_execution_enabled": os.getenv("TESTNET_EXECUTION_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"},
            "live_execution_enabled": os.getenv("EXCHANGE_LIVE_TRADING_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"},
        },
    }


def _missing_required_configuration() -> list[str]:
    required = ["AUTH_SECRET", "ADMIN_USERNAME", "ADMIN_PASSWORD"]
    if os.getenv("SHARIPOVAI_DATABASE_REQUIRED", "0").strip().lower() in {"1", "true", "yes", "on"}:
        required.append("DATABASE_URL")
    return [name for name in required if not os.getenv(name, "").strip()]


def _require_authenticated(request: Request) -> str:
    from .app import _session_username

    username = _session_username(request)
    if not username:
        raise HTTPException(status_code=401, detail="authentication required")
    return username


def _require_admin(request: Request) -> str:
    from .app import _is_admin_request, _session_username

    username = _session_username(request)
    if not username:
        raise HTTPException(status_code=401, detail="authentication required")
    if not _is_admin_request(request):
        raise HTTPException(status_code=403, detail="administrator access required")
    return username


def _register_startup(app: FastAPI, handler: Any) -> None:
    add_event_handler = getattr(app, "add_event_handler", None)
    if callable(add_event_handler):
        add_event_handler("startup", handler)
        return
    handlers = getattr(getattr(app, "router", None), "on_startup", None)
    if isinstance(handlers, list):
        handlers.append(handler)


__all__ = ["ProjectMessageInput", "install_database_api", "readiness_status"]
