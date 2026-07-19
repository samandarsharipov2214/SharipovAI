"""Admin-only Phase 12 self-learning status and bounded research-cycle API."""
from __future__ import annotations

from typing import Any, Callable

from fastapi import FastAPI, HTTPException, Request

from learning_engine import OutcomeAttributionService, ResearchChallengerService, SelfLearningSupervisor
from storage import ProjectDatabase

from .admin_guard import install_sensitive_api_guard, require_admin


def install_self_learning_api(app: FastAPI) -> None:
    if getattr(app.state, "self_learning_api_installed", False):
        return
    database = getattr(app.state, "project_database", None)
    if not isinstance(database, ProjectDatabase):
        raise RuntimeError("ProjectDatabase must be installed before self-learning API")
    install_sensitive_api_guard(app)
    attribution = OutcomeAttributionService(database)
    challengers = ResearchChallengerService(database)
    supervisor = SelfLearningSupervisor(database, attribution=attribution, challengers=challengers)
    app.state.self_learning_attribution = attribution
    app.state.self_learning_challengers = challengers
    app.state.self_learning_supervisor = supervisor
    app.state.self_learning_api_installed = True
    _register_event(app, "startup", supervisor.start)
    _register_event(app, "shutdown", supervisor.stop)

    @app.get("/api/learning/phase12/status")
    def self_learning_status(request: Request, scope: str = "global.paper") -> dict[str, Any]:
        require_admin(request)
        try:
            return {
                "status": "ok",
                "supervisor": supervisor.status(),
                "summary": attribution.summary(),
                "agents": attribution.agent_metrics(limit=500),
                "challengers": challengers.list_challengers(limit=200),
                "paper_research_leadership": challengers.leadership(scope),
                "execution_authority": False,
                "automatic_execution_promotion": False,
                "runtime_flags_changed": False,
            }
        except Exception as exc:
            raise _service_error(exc) from exc

    @app.get("/api/learning/phase12/outcomes")
    def self_learning_outcomes(request: Request, limit: int = 200) -> dict[str, Any]:
        require_admin(request)
        try:
            return {
                "status": "ok",
                "outcomes": attribution.list_outcomes(limit=min(max(int(limit), 1), 1_000)),
                "execution_authority": False,
                "runtime_flags_changed": False,
            }
        except Exception as exc:
            raise _service_error(exc) from exc

    @app.post("/api/learning/phase12/run")
    def self_learning_run(request: Request) -> dict[str, Any]:
        actor = require_admin(request)
        try:
            result = supervisor.run_once()
            return {
                "status": result.get("status", "unknown"),
                "actor": actor,
                "result": result,
                "execution_authority": False,
                "automatic_execution_promotion": False,
                "runtime_flags_changed": False,
            }
        except Exception as exc:
            raise _service_error(exc) from exc


def _register_event(app: FastAPI, event: str, handler: Callable[[], None]) -> None:
    add_event_handler = getattr(app, "add_event_handler", None)
    if callable(add_event_handler):
        add_event_handler(event, handler)
        return
    handlers = getattr(getattr(app, "router", None), f"on_{event}", None)
    if isinstance(handlers, list):
        handlers.append(handler)
        return
    raise RuntimeError(f"FastAPI lifecycle handler registration unavailable for {event}")


def _service_error(exc: Exception) -> HTTPException:
    status = 404 if isinstance(exc, KeyError) else 409 if isinstance(exc, ValueError) else 503
    return HTTPException(status_code=status, detail={"status": "unavailable", "message": f"{type(exc).__name__}: {exc}"})


__all__ = ["install_self_learning_api"]
