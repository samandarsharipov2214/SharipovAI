"""FastAPI runtime and diagnostics for verified news-to-market impact tracking."""
from __future__ import annotations

import os
import threading
from typing import Any

from fastapi import FastAPI

from news_monitor.market_impact_tracker import NewsMarketImpactTracker


def install_news_market_impact_api(app: FastAPI) -> None:
    if getattr(app.state, "news_market_impact_api_installed", False):
        return
    app.state.news_market_impact_api_installed = True
    tracker = NewsMarketImpactTracker()
    app.state.news_market_impact_tracker = tracker
    stop = threading.Event()
    thread: threading.Thread | None = None

    def loop() -> None:
        interval = max(10, int(os.getenv("NEWS_MARKET_IMPACT_TICK_SECONDS", "60")))
        while not stop.is_set():
            try:
                tracker.cycle()
            except Exception:
                # Runtime diagnostics remain available; one failed cycle must not
                # stop the dashboard or the existing News AI network.
                pass
            stop.wait(interval)

    @app.on_event("startup")
    def start_tracker() -> None:
        nonlocal thread
        enabled = os.getenv("NEWS_MARKET_IMPACT_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}
        if not enabled or (thread and thread.is_alive()):
            return
        tracker.cycle()
        thread = threading.Thread(target=loop, name="news-market-impact", daemon=True)
        thread.start()

    @app.on_event("shutdown")
    def stop_tracker() -> None:
        stop.set()

    @app.get("/api/news/market-impact/status")
    def impact_status() -> dict[str, Any]:
        return {**tracker.status(), "thread_alive": bool(thread and thread.is_alive())}

    @app.post("/api/news/market-impact/cycle")
    def impact_cycle() -> dict[str, Any]:
        return tracker.cycle()

    @app.get("/api/news/market-impact/pattern/{symbol}")
    def impact_pattern(symbol: str, title: str) -> dict[str, Any]:
        return tracker.pattern_for(title=title, symbol=symbol)
