"""Read-only Memory Layer API plus an internal owner-approved activation path."""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from memory_engine import ContextRequest, MemoryRuntime, MemoryService, MemorySettings
from storage import ProjectDatabase

from .internal_service_auth import require_internal_service


class MemoryActivationClaim(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    decision_id: str = Field(min_length=1, max_length=200)
    actor: str = Field(min_length=1, max_length=200)
    rationale: str = Field(min_length=1, max_length=2000)


def install_memory_api(app: FastAPI) -> None:
    if getattr(app.state, "memory_api_installed", False):
        return
    app.state.memory_api_installed = True
    settings = MemorySettings.from_env()
    database = getattr(app.state, "project_database", None) or ProjectDatabase()
    service = MemoryService(database, settings=settings)
    runtime = MemoryRuntime(service)
    app.state.memory_service = service
    app.state.memory_runtime = runtime

    @app.on_event("startup")
    def start_memory_runtime() -> None:
        runtime.start()

    @app.on_event("shutdown")
    def stop_memory_runtime() -> None:
        runtime.stop()

    @app.get("/api/memory/health")
    def memory_health() -> dict[str, Any]:
        return runtime.health()

    @app.get("/api/memory/stats")
    def memory_stats() -> dict[str, Any]:
        health = runtime.health()
        return {
            "status": health.get("status"),
            "flags": health.get("flags", {}),
            "stats": health.get("stats", {}),
            "worker_running": health.get("worker_running", False),
            "execution_authority": False,
        }

    @app.post("/api/memory/context")
    def memory_context(payload: ContextRequest) -> dict[str, Any]:
        items = service.get_context(
            agent_id=payload.agent_id,
            user_id=payload.user_id,
            query_text=payload.query_text,
            team_id=payload.team_id,
            limit=payload.limit,
        )
        return {
            "status": "ok" if items else "empty",
            "items": [item.model_dump(mode="json") for item in items],
            "count": len(items),
            "context_injection_enabled": service.context_enabled,
            "execution_authority": False,
        }

    @app.post("/internal/memory/facts/{fact_id}/activate", include_in_schema=False)
    def activate_memory_fact(
        fact_id: str,
        payload: MemoryActivationClaim,
        request: Request,
    ) -> dict[str, Any]:
        require_internal_service(request)
        if not service.settings.enabled:
            raise HTTPException(status_code=409, detail="Memory Layer is disabled")
        decision = database.get_agent_decision(payload.decision_id)
        if decision is None:
            raise HTTPException(status_code=404, detail="approval decision not found")
        metadata = decision.get("metadata") if isinstance(decision.get("metadata"), dict) else {}
        if (
            decision.get("kind") != "memory_fact_activation"
            or decision.get("status") != "approved"
            or decision.get("security_verdict") != "allow"
            or str(metadata.get("fact_id") or "") != fact_id
        ):
            raise HTTPException(status_code=409, detail="memory activation is not owner/security approved")
        fact = service.approve_fact(
            fact_id,
            actor=payload.actor,
            rationale=payload.rationale,
            manual_approval=True,
        )
        return {
            "status": "ok",
            "fact": fact.model_dump(mode="json"),
            "decision_id": payload.decision_id,
            "execution_authority": False,
        }


__all__ = ["MemoryActivationClaim", "install_memory_api"]
