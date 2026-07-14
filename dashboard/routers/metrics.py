"""Prometheus text endpoint with token/admin protection."""
from __future__ import annotations

from fastapi import APIRouter, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from dashboard.auth import require_metrics_access

router = APIRouter(tags=["observability"])


@router.get("/metrics", include_in_schema=False)
def prometheus_metrics(request: Request) -> Response:
    require_metrics_access(request)
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
        headers={"Cache-Control": "no-store"},
    )


__all__ = ["prometheus_metrics", "router"]
