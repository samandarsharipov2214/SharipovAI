"""FastAPI runtime for verified news impact and five-exchange monitoring."""
from __future__ import annotations

import os
import threading
from typing import Any

from fastapi import FastAPI

from exchange_connector.market_data import MarketDataService
from exchange_connector.multi_exchange_monitor import MultiExchangeMonitor
from news_monitor.market_impact_tracker import NewsMarketImpactTracker


class _ConsensusMarketData(MarketDataService):
    """Make the tracker use consensus while preserving legacy quote callers."""

    def quote(self, symbol: str):
        return self.consensus_quote(symbol)


def install_news_market_impact_api(app: FastAPI) -> None:
    if getattr(app.state, "news_market_impact_api_installed", False):
        return
    app.state.news_market_impact_api_installed = True
    consensus_market = _ConsensusMarketData(
        minimum_consensus_sources=int(os.getenv("MARKET_CONSENSUS_MIN_SOURCES", "3")),
        maximum_deviation_percent=float(os.getenv("MARKET_MAX_DEVIATION_PERCENT", "0.75")),
    )
    tracker = NewsMarketImpactTracker(market_data=consensus_market)
    monitor = MultiExchangeMonitor(market_data=consensus_market)
    app.state.news_market_impact_tracker = tracker
    app.state.multi_exchange_monitor = monitor
    stop = threading.Event()
    thread: threading.Thread | None = None

    def loop() -> None:
        interval = max(10, int(os.getenv("NEWS_MARKET_IMPACT_TICK_SECONDS", "60")))
        while not stop.is_set():
            try:
                tracker.cycle()
            except Exception:
                pass
            stop.wait(interval)

    @app.on_event("startup")
    def start_tracker() -> None:
        nonlocal thread
        enabled = os.getenv("NEWS_MARKET_IMPACT_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}
        if enabled and not (thread and thread.is_alive()):
            tracker.cycle()
            thread = threading.Thread(target=loop, name="news-market-impact", daemon=True)
            thread.start()
        monitor_enabled = os.getenv("MULTI_EXCHANGE_MONITOR_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}
        if monitor_enabled:
            monitor.start()

    @app.on_event("shutdown")
    def stop_tracker() -> None:
        stop.set()
        monitor.stop()

    @app.get("/api/news/market-impact/status")
    def impact_status() -> dict[str, Any]:
        return {**tracker.status(), "thread_alive": bool(thread and thread.is_alive())}

    @app.post("/api/news/market-impact/cycle")
    def impact_cycle() -> dict[str, Any]:
        return tracker.cycle()

    @app.get("/api/news/market-impact/pattern/{symbol}")
    def impact_pattern(symbol: str, title: str) -> dict[str, Any]:
        return tracker.pattern_for(title=title, symbol=symbol)

    @app.get("/api/market/exchanges/status")
    def exchange_status() -> dict[str, Any]:
        return monitor.snapshot()

    @app.post("/api/market/exchanges/cycle")
    def exchange_cycle() -> dict[str, Any]:
        return monitor.cycle()

    @app.get("/api/market/exchanges/consensus/{symbol}")
    def exchange_consensus(symbol: str) -> dict[str, Any]:
        return consensus_market.consensus_quote(symbol).to_dict()
