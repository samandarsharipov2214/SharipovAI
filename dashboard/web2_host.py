"""Serve SharipovAI Web2 from the existing FastAPI service."""
from __future__ import annotations

from pathlib import Path
from typing import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse

WEB2_DIR = Path(__file__).resolve().parent / "static" / "web2"
WEB2_INDEX = WEB2_DIR / "index.html"
_UI_PATHS = {
    "/", "/market", "/news", "/ai-decision", "/portfolio", "/paper-trading",
    "/learning", "/self-analysis", "/stress-lab", "/ai-improvement", "/reports",
    "/settings", "/ai-bots", "/ai-control-center", "/general-control",
    "/learning-os", "/evidence-vault", "/virtual-account", "/control",
}

_NO_CACHE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
}


def install_web2_host(app: FastAPI) -> None:
    if getattr(app.state, "web2_host_installed", False):
        return
    app.state.web2_host_installed = True

    @app.middleware("http")
    async def web2_shell(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        path = request.url.path.rstrip("/") or "/"
        if request.method in {"GET", "HEAD"} and WEB2_INDEX.is_file() and path in _UI_PATHS:
            return FileResponse(WEB2_INDEX, media_type="text/html", headers=_NO_CACHE_HEADERS)
        return await call_next(request)
