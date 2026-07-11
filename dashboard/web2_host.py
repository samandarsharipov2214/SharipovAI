"""Serve the exported SharipoAI Web2 UI from the existing FastAPI service."""
from __future__ import annotations

from pathlib import Path
from typing import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

WEB2_OUT = Path(__file__).resolve().parents[1] / "web2" / "out"
WEB2_INDEX = WEB2_OUT / "index.html"
_UI_PATHS = {
    "/", "/market", "/news", "/ai-decision", "/portfolio", "/paper-trading",
    "/learning", "/self-analysis", "/stress-lab", "/ai-improvement", "/reports",
    "/settings", "/ai-bots", "/ai-control-center", "/general-control",
    "/learning-os", "/evidence-vault", "/virtual-account", "/control",
}


def install_web2_host(app: FastAPI) -> None:
    if getattr(app.state, "web2_host_installed", False):
        return
    app.state.web2_host_installed = True

    next_dir = WEB2_OUT / "_next"
    if next_dir.is_dir():
        app.mount("/_next", StaticFiles(directory=str(next_dir)), name="web2-next")

    @app.middleware("http")
    async def web2_shell(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        path = request.url.path.rstrip("/") or "/"
        if request.method in {"GET", "HEAD"} and WEB2_INDEX.is_file():
            if path in _UI_PATHS:
                return FileResponse(WEB2_INDEX, media_type="text/html")
            if path == "/sharipoai-logo.svg":
                logo = WEB2_OUT / "sharipoai-logo.svg"
                if logo.is_file():
                    return FileResponse(logo, media_type="image/svg+xml")
        return await call_next(request)
