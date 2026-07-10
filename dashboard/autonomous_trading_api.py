"""FastAPI integration for continuous market monitoring and autonomous paper trading."""
from __future__ import annotations

import os
from typing import Any

from fastapi import FastAPI

from autonomous_trading import AutonomousPaperLoop, MarketStream


def install_autonomous_trading_api(app: FastAPI) -> None:
    if getattr(app.state, "autonomous_trading_api_installed", False):
        return
    app.state.autonomous_trading_api_installed = True
    stream = MarketStream()
    loop = AutonomousPaperLoop(stream)
    app.state.market_stream = stream
    app.state.autonomous_paper_loop = loop

    @app.on_event("startup")
    def start_autonomous_runtime() -> None:
        if os.getenv("MARKET_STREAM_ENABLED", "1").strip().lower() in {"1", "true", "yes", "on"}:
            stream.start()
        if os.getenv("AUTONOMOUS_PAPER_ENABLED", "1").strip().lower() in {"1", "true", "yes", "on"}:
            loop.start()

    @app.on_event("shutdown")
    def stop_autonomous_runtime() -> None:
        loop.stop()
        stream.stop()

    @app.get("/api/market/stream/status")
    def market_stream_status() -> dict[str, Any]:
        return stream.snapshot()

    @app.get("/api/autonomous-paper/status")
    def autonomous_paper_status() -> dict[str, Any]:
        return loop.snapshot()

    @app.post("/api/autonomous-paper/tick")
    def autonomous_paper_tick() -> dict[str, Any]:
        loop.tick()
        return loop.snapshot()
