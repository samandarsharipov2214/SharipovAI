"""Status endpoints for testnet, guarded live execution, and scaling eligibility."""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException

from autonomous_trading import StageController
from exchange_connector.bybit_execution import BybitExecutionClient


def install_execution_stages_api(app: FastAPI) -> None:
    if getattr(app.state, "execution_stages_api_installed", False):
        return
    app.state.execution_stages_api_installed = True
    app.state.execution_client = BybitExecutionClient()
    app.state.stage_controller = StageController()

    @app.get("/api/execution/stage-status")
    def stage_status() -> dict[str, Any]:
        return {
            "status": "ok",
            "assessment": app.state.stage_controller.assess().to_dict(),
            "execution": app.state.execution_client.status(),
            "real_profit_guaranteed": False,
        }

    @app.post("/api/execution/testnet-order")
    def testnet_order(payload: dict[str, Any]) -> dict[str, Any]:
        client: BybitExecutionClient = app.state.execution_client
        if client.mode != "sandbox":
            raise HTTPException(status_code=409, detail="Endpoint is available only in sandbox mode")
        try:
            result = client.place_market_order(
                symbol=str(payload.get("symbol", "")),
                side=str(payload.get("side", "")),
                quantity=float(payload.get("quantity", 0)),
                reference_price=float(payload.get("reference_price", 0)),
            )
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return result.to_dict()
