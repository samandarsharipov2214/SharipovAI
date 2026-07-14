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
            observe_http(
                method=request.method,
                path=request.url.path,
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
                status_code=status_code,
                duration_ms=round(duration * 1_000.0, 3),
            )


__all__ = ["install_observability"]
