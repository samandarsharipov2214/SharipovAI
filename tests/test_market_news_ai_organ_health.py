from __future__ import annotations

import os
import threading
import time

from dashboard.market_data_api import _configure_public_stream_feature
from news_intelligence.network import NewsAgentNetwork


def test_public_market_stream_requires_opt_in_and_explicit_disable_wins(monkeypatch) -> None:
    monkeypatch.delenv("FEATURE_BYBIT_WEBSOCKET", raising=False)
    monkeypatch.delenv("MARKET_STREAM_ENABLED", raising=False)
    _configure_public_stream_feature()
    assert "FEATURE_BYBIT_WEBSOCKET" not in os.environ

    monkeypatch.delenv("FEATURE_BYBIT_WEBSOCKET", raising=False)
    monkeypatch.setenv("MARKET_STREAM_ENABLED", "0")
    _configure_public_stream_feature()
    assert "FEATURE_BYBIT_WEBSOCKET" not in os.environ


def test_news_collection_workers_can_collect_sources_concurrently() -> None:
    class Definition:
        def __init__(self, source_id: str) -> None:
            self.source_id = source_id

    class Agent:
        def __init__(self, source_id: str) -> None:
            self.definition = Definition(source_id)

    class Collector:
        def __init__(self) -> None:
            self.active = 0
            self.maximum = 0
            self.lock = threading.Lock()

        def collect(self, definition):
            with self.lock:
                self.active += 1
                self.maximum = max(self.maximum, self.active)
            time.sleep(0.03)
            with self.lock:
                self.active -= 1
            return [], object()

    collector = Collector()
    network = NewsAgentNetwork.__new__(NewsAgentNetwork)
    network.collector = collector
    network.collection_workers = 4
    agents = [Agent(str(index)) for index in range(4)]

    results = network._collect_sources(agents)

    assert len(results) == 4
    assert collector.maximum >= 2
