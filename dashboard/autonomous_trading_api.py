"""FastAPI integration for continuous market monitoring and autonomous staged trading."""
from __future__ import annotations

import os
from typing import Any

from fastapi import FastAPI

from autonomous_trading import (
    AutonomousPaperLoop,
    AutonomousTestnetBridge,
    MarketStream,
    PowerResilienceManager,
    bootstrap_storage,
)


def install_autonomous_trading_api(app: FastAPI) -> None:
    if getattr(app.state, "autonomous_trading_api_installed", False):
        return
    app.state.autonomous_trading_api_installed = True
    stream = MarketStream()
    loop = AutonomousPaperLoop(stream)
    testnet_bridge = AutonomousTestnetBridge()
    power_resilience = PowerResilienceManager()
    app.state.market_stream = stream
    app.state.autonomous_paper_loop = loop
    app.state.autonomous_testnet_bridge = testnet_bridge
    app.state.power_resilience = power_resilience
    app.state.startup_readiness = {"status": "not_started", "trading_ready": False}

    @app.on_event("startup")
    def start_autonomous_runtime() -> None:
        recovery_result = {"status": "disabled", "failed": []}
        if _truthy("POWER_RESILIENCE_ENABLED", default=True):
            power_start = power_resilience.start()
            app.state.power_recovery = power_start
            recovery_result = power_start.get("recovery", recovery_result)
        app.state.startup_readiness = bootstrap_storage(recovery_result)
        if _truthy("MARKET_STREAM_ENABLED", default=True):
            stream.start()
        if _truthy("AUTONOMOUS_PAPER_ENABLED", default=True):
            loop.start()
        if _truthy("AUTONOMOUS_TESTNET_BRIDGE_ENABLED", default=True):
            testnet_bridge.start()

    @app.on_event("shutdown")
    def stop_autonomous_runtime() -> None:
        testnet_bridge.stop()
        loop.stop()
        stream.stop()
        if _truthy("POWER_RESILIENCE_ENABLED", default=True):
            app.state.power_shutdown_checkpoint = power_resilience.stop()

    @app.get("/api/system/startup-readiness")
    def startup_readiness() -> dict[str, Any]:
        return dict(app.state.startup_readiness)

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

    @app.get("/api/system/power-resilience/status")
    def power_resilience_status() -> dict[str, Any]:
        return power_resilience.status()

    @app.post("/api/system/power-resilience/checkpoint")
    def power_resilience_checkpoint() -> dict[str, Any]:
        return power_resilience.checkpoint()

    @app.post("/api/system/power-resilience/recover")
    def power_resilience_recover() -> dict[str, Any]:
        recovery = power_resilience.recover_all()
        app.state.startup_readiness = bootstrap_storage(recovery)
        return {"recovery": recovery, "readiness": app.state.startup_readiness}


def _truthy(name: str, *, default: bool = False) -> bool:
    fallback = "1" if default else "0"
    return os.getenv(name, fallback).strip().lower() in {"1", "true", "yes", "on"}
