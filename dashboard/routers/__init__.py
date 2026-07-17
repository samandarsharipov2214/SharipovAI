"""Operational dashboard routers with explicit auth dependencies."""
from __future__ import annotations

from fastapi import FastAPI

from .execution_status import router as execution_status_router
from .experiments import router as experiments_router
from .leadership import router as leadership_router
from .metrics import router as metrics_router


def install_operational_routers(app: FastAPI) -> None:
    if getattr(app.state, "operational_routers_installed", False):
        return
    app.state.operational_routers_installed = True
    app.include_router(execution_status_router)
    app.include_router(experiments_router)
    app.include_router(leadership_router)
    app.include_router(metrics_router)


__all__ = ["install_operational_routers"]
