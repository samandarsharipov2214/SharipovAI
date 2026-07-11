"""FastAPI integration for continuous market monitoring and autonomous staged trading."""
from __future__ import annotations

import os
from typing import Any

from fastapi import FastAPI

from autonomous_trading import AutonomousPaperLoop, AutonomousTestnetBridge, MarketStream
from storage import ProjectDatabase


def install_autonomous_trading_api(app: FastAPI) -> None:
    if getattr(app.state, "autonomous_trading_api_installed", False):
        return
    app.state.autonomous_trading_api_installed = True
    database = ProjectDatabase()
    database.initialize()
    stream = MarketStream()
    loop = AutonomousPaperLoop(stream, database=database)
    testnet_bridge = AutonomousTestnetBridge(database=database)
    app.state.market_stream = stream
    app.state.autonomous_paper_loop = loop
    app.state.autonomous_testnet_bridge = testnet_bridge

    @app.on_event("startup")
    def start_autonomous_runtime() -> None:
        if _truthy("MARKET_STREAM_ENABLED", default=True):
            stream.start()
        if _truthy("AUTONOMOUS_PAPER_ENABLED", default=True):
            loop.start()
        if _truthy("AUTONOMOUS_TESTNET_BRIDGE_ENABLED", default=False):
            testnet_bridge.start()

    @app.on_event("shutdown")
    def stop_autonomous_runtime() -> None:
        testnet_bridge.stop()
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

    @app.get("/api/autonomous-testnet/status")
    def autonomous_testnet_status() -> dict[str, Any]:
        return testnet_bridge.snapshot()

    @app.post("/api/autonomous-testnet/tick")
    def autonomous_testnet_tick() -> dict[str, Any]:
        testnet_bridge.tick()
        return testnet_bridge.snapshot()


def _truthy(name: str, *, default: bool = False) -> bool:
    fallback = "1" if default else "0"
    return os.getenv(name, fallback).strip().lower() in {"1", "true", "yes", "on"}
