"""Security headers that do not change dashboard routing or execution authority."""
from __future__ import annotations

import os

from fastapi import FastAPI, Request


def install_security_headers(app: FastAPI) -> None:
    if getattr(app.state, "security_headers_installed", False):
        return
    app.state.security_headers_installed = True

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault(
            "Permissions-Policy",
            "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
        )
        response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        response.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
        content_type = response.headers.get("content-type", "").lower()
        if request.url.path.startswith("/api/") or "text/html" in content_type:
            response.headers.setdefault(
                "Cache-Control",
                "no-store, max-age=0, must-revalidate",
            )
            response.headers.setdefault("Pragma", "no-cache")
        forwarded_proto = request.headers.get("x-forwarded-proto", "").split(",", 1)[0].strip().lower()
        is_https = request.url.scheme == "https" or forwarded_proto == "https"
        if is_https and _truthy(os.getenv("SHARIPOVAI_HSTS_ENABLED", "1")):
            response.headers.setdefault(
                "Strict-Transport-Security",
                "max-age=31536000; includeSubDomains",
            )
        return response


def _truthy(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


__all__ = ["install_security_headers"]
