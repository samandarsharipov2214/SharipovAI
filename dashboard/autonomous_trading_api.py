"""FastAPI integration for the canonical autonomous paper runtime."""
from __future__ import annotations

import math
import os
from collections.abc import Callable
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
from storage import ProjectDatabase, list_json_items

_NEWS_GROUPS = {
    "crypto_ai": ("crypto", "exchange", "token", "blockchain", "regulation"),
    "finance_ai": ("finance", "market", "liquidity", "bank"),
    "economy_ai": ("economy", "macro", "inflation", "rate", "central"),
    "security_ai": ("security", "cyber", "hack", "exploit"),
    "world_ai": ("world", "politic", "international", "war", "government"),
}


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
    stream = SharedVerifiedMarketStream(worker, market_data, consensus, database=database)
    decision_runtime = CanonicalPaperDecisionRuntime(database)
    proposal_provider = AutonomousCouncilProposalProvider(
        database,
        stream,
        news_reader=_database_news_reader(database),
    )
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
            "news_source": "project_database.news_memory",
            "synthetic_fallback_used": False,
        }

    @app.get("/api/autonomous-testnet/status")
    def autonomous_testnet_status() -> dict[str, Any]:
        return testnet_bridge.snapshot()

    @app.post("/api/autonomous-testnet/tick")
    def autonomous_testnet_tick() -> dict[str, Any]:
        testnet_bridge.tick()
        return testnet_bridge.snapshot()


def _database_news_reader(database: ProjectDatabase) -> Callable[..., dict[str, Any]]:
    """Expose DB-backed NewsHub evidence in the narrow council-reader contract."""

    def read(agent_id: str, *, run_now: bool = False) -> dict[str, Any]:
        del run_now
        keywords = _NEWS_GROUPS.get(str(agent_id), ())
        rows = list_json_items(database, "news_memory", limit=1000, newest_first=True)
        memory: list[dict[str, Any]] = []
        for row in rows:
            value = row.get("value")
            if not isinstance(value, dict):
                continue
            article = value.get("article") if isinstance(value.get("article"), dict) else {}
            haystack = " ".join(
                str(item or "").lower()
                for item in (
                    value.get("category"),
                    value.get("agent_id"),
                    article.get("category"),
                    article.get("title"),
                    article.get("summary"),
                )
            )
            if keywords and not any(keyword in haystack for keyword in keywords):
                continue
            reliability = _percentage(value.get("reliability"))
            fetched = value.get("fetched") if isinstance(value.get("fetched"), dict) else {}
            memory.append(
                {
                    "key": str(row.get("key") or ""),
                    "created_at": int(row.get("updated_at_ms") or 0) // 1000,
                    "impact": str(value.get("impact") or "neutral"),
                    "impact_score": _finite(value.get("score"), 0.0),
                    "credibility_percent": reliability,
                    "urgency": str(value.get("urgency") or "low"),
                    "needs_confirmation": fetched.get("verified") is not True or reliability < 60.0,
                }
            )
        return {
            "status": "ok",
            "agent": {
                "id": str(agent_id),
                "status": "active" if memory else "stale",
                "database_backed": True,
            },
            "memory": memory,
        }

    return read


def _percentage(value: Any) -> float:
    parsed = _finite(value, 0.0)
    if 0.0 <= parsed <= 1.0:
        parsed *= 100.0
    return min(max(parsed, 0.0), 100.0)


def _finite(value: Any, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


def _truthy(name: str, *, default: bool = False) -> bool:
    fallback = "1" if default else "0"
    return os.getenv(name, fallback).strip().lower() in {"1", "true", "yes", "on"}
