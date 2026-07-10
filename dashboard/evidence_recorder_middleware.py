"""Evidence recorder plus baseline web security hardening for SharipovAI."""
from __future__ import annotations

import json
import os
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from starlette.datastructures import MutableHeaders
from starlette.requests import Request
from starlette.responses import JSONResponse

from learning.evidence_vault import EvidenceVault

RECORDED_ENDPOINTS = {"/api/run", "/api/trade-gate"}
ADMIN_ONLY_PREFIXES = ("/api/security/access-requests",)
LOGIN_WINDOW_SECONDS = 15 * 60
LOGIN_MAX_FAILURES = int(os.getenv("LOGIN_MAX_FAILURES", "8"))
_LOGIN_FAILURES: dict[str, list[float]] = {}


class EvidenceRecorderMiddleware:
    """Apply security policy to every request and record selected AI decisions."""

    def __init__(self, app: Callable[[Any, Any, Any], Awaitable[None]]) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive=receive)
        blocked = _preflight_block(request)
        if blocked is not None:
            await blocked(scope, receive, send)
            return

        body_parts: list[bytes] = []
        status_code = 200
        response_headers: list[tuple[bytes, bytes]] = []

        async def send_wrapper(message: dict[str, Any]) -> None:
            nonlocal status_code, response_headers
            if message["type"] == "http.response.start":
                status_code = int(message.get("status", 200))
                headers = MutableHeaders(raw=list(message.get("headers", [])))
                _apply_security_headers(headers, request)
                message["headers"] = headers.raw
                response_headers = list(headers.raw)
            elif message["type"] == "http.response.body" and request.url.path in RECORDED_ENDPOINTS:
                body_parts.append(message.get("body", b""))
            await send(message)

        await self.app(scope, receive, send_wrapper)
        _update_login_throttle(request, status_code)
        if request.url.path in RECORDED_ENDPOINTS and 200 <= status_code < 300:
            _record_response(request, b"".join(body_parts), response_headers)


def install_evidence_recorder_middleware(app_instance: Any) -> None:
    if getattr(app_instance.state, "evidence_recorder_middleware_installed", False):
        return
    app_instance.state.evidence_recorder_middleware_installed = True
    app_instance.add_middleware(EvidenceRecorderMiddleware)


def _preflight_block(request: Request) -> JSONResponse | None:
    path = request.url.path
    ip = request.client.host if request.client else "unknown"
    if request.method == "POST" and path == "/login" and _too_many_login_failures(ip):
        return JSONResponse(status_code=429, content={"status": "rate_limited", "retry_after_seconds": LOGIN_WINDOW_SECONDS})
    if any(path.startswith(prefix) for prefix in ADMIN_ONLY_PREFIXES) and not _is_admin(request):
        return JSONResponse(status_code=403, content={"status": "forbidden", "detail": "admin_required"})
    if request.method in {"POST", "PUT", "PATCH", "DELETE"} and path != "/telegram/webhook":
        origin = request.headers.get("origin")
        if origin and not _same_origin(origin, request):
            return JSONResponse(status_code=403, content={"status": "forbidden", "detail": "cross_origin_request_blocked"})
    return None


def _is_admin(request: Request) -> bool:
    try:
        from dashboard.app import _clean_username, _load_users, _session_username

        username = _session_username(request)
        if not username:
            return False
        if _clean_username(username) == _clean_username(os.getenv("ADMIN_USERNAME", "admin")):
            return True
        user = _load_users().get(_clean_username(username), {})
        return str(user.get("role", "")).lower() == "admin"
    except Exception:
        return False


def _same_origin(origin: str, request: Request) -> bool:
    try:
        parsed = urlparse(origin)
        origin_host = parsed.netloc.lower()
        request_host = request.headers.get("host", "").lower()
        return bool(origin_host and request_host and origin_host == request_host)
    except Exception:
        return False


def _too_many_login_failures(ip: str) -> bool:
    now = time.time()
    recent = [stamp for stamp in _LOGIN_FAILURES.get(ip, []) if now - stamp < LOGIN_WINDOW_SECONDS]
    _LOGIN_FAILURES[ip] = recent
    return len(recent) >= LOGIN_MAX_FAILURES


def _update_login_throttle(request: Request, status_code: int) -> None:
    if request.method != "POST" or request.url.path != "/login":
        return
    ip = request.client.host if request.client else "unknown"
    if status_code == 401:
        _LOGIN_FAILURES.setdefault(ip, []).append(time.time())
    elif 200 <= status_code < 400:
        _LOGIN_FAILURES.pop(ip, None)


def _apply_security_headers(headers: MutableHeaders, request: Request) -> None:
    headers.setdefault("x-content-type-options", "nosniff")
    headers.setdefault("x-frame-options", "SAMEORIGIN")
    headers.setdefault("referrer-policy", "strict-origin-when-cross-origin")
    headers.setdefault("permissions-policy", "camera=(), microphone=(), geolocation=(), payment=()")
    headers.setdefault("cross-origin-opener-policy", "same-origin-allow-popups")
    headers.setdefault("strict-transport-security", "max-age=31536000; includeSubDomains")
    headers.setdefault(
        "content-security-policy",
        "default-src 'self'; script-src 'self' 'unsafe-inline' https://telegram.org; style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; connect-src 'self' https://api.telegram.org; font-src 'self' data:; frame-ancestors 'self' https://web.telegram.org https://*.telegram.org",
    )
    if request.url.path.startswith(("/login", "/change-password", "/api/auth")):
        headers.setdefault("cache-control", "no-store")
    _secure_session_cookie(headers, request)


def _secure_session_cookie(headers: MutableHeaders, request: Request) -> None:
    values = headers.getlist("set-cookie")
    if not values:
        return
    secure_transport = request.url.scheme == "https" or request.headers.get("x-forwarded-proto", "").lower() == "https" or bool(os.getenv("RENDER"))
    rewritten: list[str] = []
    for value in values:
        if "sharipovai_session=" not in value:
            rewritten.append(value)
            continue
        cookie = value
        if "Path=" not in cookie:
            cookie += "; Path=/"
        if "HttpOnly" not in cookie:
            cookie += "; HttpOnly"
        if "SameSite=" not in cookie:
            cookie += "; SameSite=Lax"
        if secure_transport and "Secure" not in cookie:
            cookie += "; Secure"
        rewritten.append(cookie)
    del headers["set-cookie"]
    for value in rewritten:
        headers.append("set-cookie", value)


def _record_response(request: Request, body: bytes, headers: list[tuple[bytes, bytes]]) -> None:
    try:
        content_type = MutableHeaders(raw=headers).get("content-type", "")
        if "application/json" not in content_type:
            return
        payload = json.loads(body.decode("utf-8"))
        if not isinstance(payload, dict):
            return
        actor = "dashboard_runner" if request.url.path == "/api/run" else "trade_gate"
        decision = str(payload.get("decision", payload.get("status", "WATCH")))
        confidence = float(payload.get("confidence", payload.get("confidence_percent", 50.0)) or 50.0)
        risk_level = str(payload.get("risk_level", payload.get("risk", "MEDIUM")))
        reason = str(payload.get("reason", payload.get("human_answer", "dashboard response recorded")))
        EvidenceVault(Path(os.getenv("EVIDENCE_VAULT_DB", "data/evidence_vault.sqlite3"))).record_decision(
            actor=actor,
            decision=decision,
            topic="trading",
            confidence=confidence,
            risk_level=risk_level,
            reason=reason,
            evidence=_evidence_from_payload(payload),
            policy_status=str(payload.get("policy_status", "unknown")),
            metadata={"path": request.url.path, "method": request.method},
        )
    except Exception:
        return


def _evidence_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    regime = payload.get("market_regime")
    if isinstance(regime, dict):
        evidence.append({"title": "Market regime snapshot", "source_domain": "internal.market_regime", "source_type": "internal_signal", "trust_score": 70, "summary": str(regime)})
    blockers = payload.get("blockers")
    if isinstance(blockers, list) and blockers:
        evidence.append({"title": "Trade blockers", "source_domain": "internal.trade_gate", "source_type": "internal_rule", "trust_score": 80, "summary": "; ".join(str(item) for item in blockers[:5])})
    return evidence
