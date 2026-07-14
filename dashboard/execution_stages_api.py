"""Read-only execution stage status and explicit removal of raw order submission."""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Request

from autonomous_trading import ExecutionJournal, StageController
from exchange_connector.bybit_execution import BybitExecutionClient

from .admin_guard import install_sensitive_api_guard, require_admin


_RAW_EXECUTION_REMOVED = (
    "Raw manual Testnet order submission has been removed. "
    "Exchange writes are accepted only through the canonical "
    "TradingCandidate -> ApprovedExecutionRequest -> idempotency -> "
    "reconciliation pipeline."
)


def install_execution_stages_api(app: FastAPI) -> None:
    """Install execution observability without exposing a raw order primitive."""

    if getattr(app.state, "execution_stages_api_installed", False):
        return
    app.state.execution_stages_api_installed = True
    install_sensitive_api_guard(app)
    app.state.execution_client = BybitExecutionClient()
    app.state.execution_journal = ExecutionJournal()
    app.state.stage_controller = StageController(journal=app.state.execution_journal)

    @app.get("/api/execution/stage-status")
    def stage_status(request: Request) -> dict[str, Any]:
        require_admin(request)
        return {
            "status": "ok",
            "assessment": app.state.stage_controller.assess().to_dict(),
            "execution": app.state.execution_client.status(),
            "journal": app.state.execution_journal.summary(),
            "raw_manual_order_api": "removed",
            "canonical_write_path": "ApprovedExecutionRequest",
            "real_profit_guaranteed": False,
        }

    @app.post("/api/execution/testnet-order")
    def removed_testnet_order(
        request: Request,
        payload: dict[str, Any] | None = None,
    ) -> None:
        """Keep the old route as an authenticated tombstone, never an executor."""

        require_admin(request)
        candidate_id = ""
        if isinstance(payload, dict):
            candidate_id = str(payload.get("candidate_id", "")).strip()[:170]
        app.state.execution_journal.append(
            {
                "status": "blocked_or_error",
                "mode": app.state.execution_client.mode,
                "environment": "testnet",
                "candidate_id": candidate_id,
                "message": _RAW_EXECUTION_REMOVED,
                "origin": "removed_manual_api",
                "raw_order_fields_accepted": False,
            }
        )
        raise HTTPException(status_code=410, detail=_RAW_EXECUTION_REMOVED)


__all__ = ["install_execution_stages_api"]
