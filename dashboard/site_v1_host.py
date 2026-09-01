"""Serve version-controlled Site V1 from the canonical FastAPI service."""
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse

SITE_INDEX = Path(__file__).resolve().parent / "static" / "site-v1" / "index.html"


def install_site_v1_host(app: FastAPI) -> None:
    if getattr(app.state, "site_v1_host_installed", False):
        return
    app.state.site_v1_host_installed = True

    @app.middleware("http")
    async def site_v1_host(request: Request, call_next):
        if request.method in {"GET", "HEAD"} and request.url.path in {"/login", "/register"}:
            mode = "register" if request.url.path == "/register" else "login"
            suffix = "&next=/app" if request.query_params.get("next") == "/app" else ""
            return RedirectResponse(url=f"/?mode={mode}{suffix}", status_code=303)
        is_site_entry = request.method in {"GET", "HEAD"} and request.url.path.rstrip("/") in {"", "/app"}
        if is_site_entry and not SITE_INDEX.is_file():
            # `/` is public only when this versioned public host owns it.  Never
            # fall through to the legacy operational dashboard on a bad package.
            return JSONResponse(
                {"status": "site_v1_unavailable"}, status_code=503,
                headers={"Cache-Control": "no-store"},
            )
        if is_site_entry:
            return FileResponse(
                SITE_INDEX,
                media_type="text/html",
                headers={"Cache-Control": "no-store, max-age=0, must-revalidate"},
            )
        return await call_next(request)
