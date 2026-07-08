"""Best-effort Evidence Vault recorder for dashboard decisions."""

from __future__ import annotations

import json
import os
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from starlette.datastructures import MutableHeaders
from starlette.requests import Request

from learning.evidence_vault import EvidenceVault


RECORDED_ENDPOINTS = {"/api/run", "/api/trade-gate"}


class EvidenceRecorderMiddleware:
    """Record successful risky endpoint responses as Evidence Vault decisions."""

    def __init__(self, app: Callable[[Any, Any, Any], Awaitable[None]]) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        request = Request(scope, receive=receive)
        if request.url.path not in RECORDED_ENDPOINTS:
            await self.app(scope, receive, send)
            return

        body_parts: list[bytes] = []
        status_code = 200
        headers: list[tuple[bytes, bytes]] = []

        async def send_wrapper(message: dict[str, Any]) -> None:
            nonlocal status_code, headers
            if message["type"] == "http.response.start":
                status_code = int(message.get("status", 200))
                headers = list(message.get("headers", []))
            elif message["type"] == "http.response.body":
                body_parts.append(message.get("body", b""))
            await send(message)

        await self.app(scope, receive, send_wrapper)
        if 200 <= status_code < 300:
            _record_response(request, b"".join(body_parts), headers)


def install_evidence_recorder_middleware(app_instance: Any) -> None:
    """Install middleware once."""

    if getattr(app_instance.state, "evidence_recorder_middleware_installed", False):
        return
    app_instance.state.evidence_recorder_middleware_installed = True
    app_instance.add_middleware(EvidenceRecorderMiddleware)


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
        evidence = _evidence_from_payload(payload)
        EvidenceVault(Path(os.getenv("EVIDENCE_VAULT_DB", "data/evidence_vault.sqlite3"))).record_decision(
            actor=actor,
            decision=decision,
            topic="trading",
            confidence=confidence,
            risk_level=risk_level,
            reason=reason,
            evidence=evidence,
            policy_status=str(payload.get("policy_status", "unknown")),
            metadata={"path": request.url.path, "method": request.method},
        )
    except Exception:
        return


def _evidence_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    regime = payload.get("market_regime")
    if isinstance(regime, dict):
        evidence.append(
            {
                "title": "Market regime snapshot",
                "source_domain": "internal.market_regime",
                "source_type": "internal_signal",
                "trust_score": 70,
                "summary": str(regime),
            }
        )
    blockers = payload.get("blockers")
    if isinstance(blockers, list) and blockers:
        evidence.append(
            {
                "title": "Trade blockers",
                "source_domain": "internal.trade_gate",
                "source_type": "internal_rule",
                "trust_score": 80,
                "summary": "; ".join(str(item) for item in blockers[:5]),
            }
        )
    return evidence
