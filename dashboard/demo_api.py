"""Dashboard API endpoints for persistent demo trading."""

from __future__ import annotations

from typing import Any

from fastapi import Body, FastAPI

from .demo_state import public_state, reset_state, run_ai_command, set_balance


def install_demo_api(app: FastAPI) -> None:
    """Install persistent demo account endpoints."""

    if getattr(app.state, "demo_api_installed", False):
        return
    app.state.demo_api_installed = True

    @app.get("/api/demo/state")
    def demo_state() -> dict[str, object]:
        """Return current persistent demo state."""

        return {"status": "ok", "state": public_state()}

    @app.post("/api/demo/chat")
    def demo_chat(payload: dict[str, Any] | None = Body(default=None)) -> dict[str, object]:
        """Run an AI-like command against the persistent demo account."""

        message = str((payload or {}).get("message", ""))
        result = run_ai_command(message)
        return {"status": "ok", **result}

    @app.post("/api/demo/balance")
    def demo_balance(payload: dict[str, Any] | None = Body(default=None)) -> dict[str, object]:
        """Set demo balance and clear positions."""

        amount = (payload or {}).get("balance", 10_000.0)
        state = set_balance(float(amount))
        return {"status": "ok", "state": public_state(), "message": state.get("message", "Demo balance updated.")}

    @app.post("/api/demo/reset")
    def demo_reset(payload: dict[str, Any] | None = Body(default=None)) -> dict[str, object]:
        """Reset demo state."""

        amount = (payload or {}).get("balance", 10_000.0)
        state = reset_state(float(amount))
        return {"status": "ok", "state": public_state(), "message": state.get("message", "Demo account reset.")}
