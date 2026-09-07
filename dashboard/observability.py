"""HTTP observability middleware for metrics and structured logs."""
from __future__ import annotations

import logging
import secrets
import time

from fastapi import FastAPI, Request

from observability import (
    configure_structured_logging,
    get_structured_logger,
    log_event,
    observe_http,
)
from observability.metrics import resolve_http_route_label


def _canonical_http_route_label(request: Request) -> str:
    """Prometheus path label: matched route template, else fixed /unmatched.

    Never use request.url.path — arbitrary user-controlled segments would explode
    cardinality. FastAPI/Starlette expose the template on scope['route'] after
    routing (e.g. /api/foo/{id}).
    """
    route = request.scope.get("route")
    route_path = getattr(route, "path", None) if route is not None else None
    if not route_path:
        route_path = getattr(route, "path_format", None) if route is not None else None
    return resolve_http_route_label(route_path if isinstance(route_path, str) else None)


def install_observability(app: FastAPI) -> None:
    if getattr(app.state, "observability_installed", False):
        return
    app.state.observability_installed = True
    configure_structured_logging()
    logger = get_structured_logger("sharipovai.http")

    @app.middleware("http")
    async def observe_request(request: Request, call_next):
        started = time.perf_counter()
        request_id = (
            request.headers.get("x-request-id", "").strip()[:128]
            or secrets.token_hex(12)
        )
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers["X-Request-ID"] = request_id
            return response
        except Exception:
            log_event(
                logger,
                logging.ERROR,
                "http_request_failed",
                event="http_request_failed",
                request_id=request_id,
                method=request.method,
                path=request.url.path,
                status_code=500,
            )
            raise
        finally:
            duration = time.perf_counter() - started
            # Metrics labels use the canonical route template only — never the
            # raw URL. Structured logs may still record the concrete path.
            route_label = _canonical_http_route_label(request)
            observe_http(
                method=request.method,
                path=route_label,
                status_code=status_code,
                duration_seconds=duration,
            )
            log_event(
                logger,
                logging.INFO,
                "http_request_completed",
                event="http_request_completed",
                request_id=request_id,
                method=request.method,
                path=request.url.path,
                route=route_label,
                status_code=status_code,
                duration_ms=round(duration * 1_000.0, 3),
            )


__all__ = ["install_observability"]
