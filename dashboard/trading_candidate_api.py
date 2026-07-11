"""Read-only API for validating structured trading candidates."""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI

from trading_candidate import validate_trading_candidate


def install_trading_candidate_api(app: FastAPI) -> None:
    if getattr(app.state, "trading_candidate_api_installed", False):
        return
    app.state.trading_candidate_api_installed = True

    @app.post("/api/trading/candidate/validate")
    def validate_candidate(payload: dict[str, Any]) -> dict[str, Any]:
        return validate_trading_candidate(payload).to_dict()
