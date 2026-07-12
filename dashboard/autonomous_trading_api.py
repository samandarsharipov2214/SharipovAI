"""FastAPI integration for the canonical autonomous paper runtime."""
from __future__ import annotations

import os
from typing import Any

from fastapi import FastAPI

from autonomous_trading import (
    AutonomousCouncilProposalProvider,
    AutonomousTestnetBridge,
    CanonicalPaperDecisionRuntime,
    CouncilAuthorizedPaperLoop,
    SharedVerifiedMarketStream,
)
from exchange_connector.market_data import MarketDataService
from exchange_connector.multi_exchange_consensus import MultiExchangeConsensus
from storage import ProjectDatabase


def install_autonomous_trading_api(app: FastAPI) -> None:
    if getattr(app.state, "autonomous_trading_api_installed", False):
        return
    database = getattr(app.state, "project_database", None)
    if not isinstance(database, ProjectDatabase):
        raise RuntimeError("ProjectDatabase must be installed before autonomous trading")
    worker = getattr(app.state, "bybit_websocket_worker", None)
    market_data = getattr(app.state, "market_data_service", None)
    consensus = getattr(app.state, "multi_exchange_consensus", None)
    if worker is None:
        raise RuntimeError("canonical Bybit WebSocket worker must be installed before autonomous trading")
    if not isinstance(market_data, MarketDataService):
        raise RuntimeError("MarketDataService must be installed before autonomous trading")
    if not isinstance(consensus, MultiExchangeConsensus):
        raise RuntimeError("MultiExchangeConsensus must be installed before autonomous trading")

    app.state.autonomous_trading_api_installed = True
    stream = SharedVerifiedMarketStream(
        worker,
        market_data,
        consensus,
        database=database,
    )
    decision_runtime = CanonicalPaperDecisionRuntime(database)
    proposal_provider = AutonomousCouncilProposalProvider(database, stream)
    loop = CouncilAuthorizedPaperLoop(
        stream,
        decision_runtime=decision_runtime,
        proposal_provider=proposal_provider,
        database=database,
    )
    testnet_bridge = AutonomousTestnetBridge(database=database)
    app.state.market_stream = stream
    app.state.autonomous_council_provider = proposal_provider
    app.state.canonical_paper_decision_runtime = decision_runtime
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

    @app.get("/api/autonomous-paper/decision-runtime")
    def autonomous_paper_decision_runtime() -> dict[str, Any]:
        return {
            **decision_runtime.status(),
            "decision_mode": "CANONICAL_COUNCIL_REQUIRED",
            "entry_without_authorization_allowed": False,
            "shared_market_worker": True,
            "synthetic_fallback_used": False,
        }

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
