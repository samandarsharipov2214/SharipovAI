"""Middleware that blocks risky dashboard actions when policy advice requires it."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from fastapi.responses import JSONResponse
from starlette.requests import Request

from .policy_guard import check_dashboard_action, guarded_response


RISKY_ENDPOINTS: dict[tuple[str, str], dict[str, str]] = {
    ("GET", "/api/run"): {"action_type": "trade", "actor": "dashboard_runner", "topic": "trading"},
    ("POST", "/api/trade-gate"): {"action_type": "trade", "actor": "trade_gate", "topic": "trading"},
    ("GET", "/api/trade-gate"): {"action_type": "trade", "actor": "trade_gate", "topic": "trading"},
    ("POST", "/api/learning-v2/propose"): {"action_type": "bot_learning", "actor": "learning_engine", "topic": "bot_learning"},
}


class PolicyGuardMiddleware:
    """Block risky actions before they reach endpoint handlers."""

    def __init__(self, app: Callable[[Any, Any, Any], Awaitable[None]]) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        request = Request(scope, receive=receive)
        endpoint = RISKY_ENDPOINTS.get((request.method.upper(), request.url.path))
        if endpoint:
            decision = check_dashboard_action(request=request, **endpoint)
            if decision.get("allowed") is False:
                response = JSONResponse(status_code=403, content=guarded_response(decision))
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


def install_policy_guard_middleware(app_instance: Any) -> None:
    """Install middleware once."""

    if getattr(app_instance.state, "policy_guard_middleware_installed", False):
        return
    app_instance.state.policy_guard_middleware_installed = True
    app_instance.add_middleware(PolicyGuardMiddleware)
