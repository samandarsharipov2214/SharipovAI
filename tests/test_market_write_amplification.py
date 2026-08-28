"""Regression contracts for bounded operational market persistence."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from autonomous_trading.shared_market_stream import SharedVerifiedMarketStream
from exchange_connector.bybit_websocket_state import BybitWebSocketState
from storage import ProjectDatabase


def _database(tmp_path: Path) -> ProjectDatabase:
    database = ProjectDatabase(f"sqlite:///{tmp_path / 'shared.db'}")
    database.initialize()
    return database


def _ticker(*, timestamp_ms: int, sequence: int, price: float) -> dict:
    return {
        "topic": "tickers.BTCUSDT",
        "type": "delta",
        "ts": timestamp_ms,
        "cs": sequence,
        "data": {
            "symbol": "BTCUSDT",
            "lastPrice": str(price),
            "price24hPcnt": "0.01",
        },
    }


def test_websocket_runtime_stays_fresh_while_kv_writes_are_sampled(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("BYBIT_WS_DB_PERSIST_INTERVAL_SECONDS", "10")
    database = _database(tmp_path)
    state = BybitWebSocketState(database=database, max_age_seconds=30)
    state.mark_connected(connected_at_ms=1_000)

    state.ingest_ticker(_ticker(timestamp_ms=1_000, sequence=1, price=100), received_at_ms=1_000)
    first = database.get_json("market_quotes", "BTCUSDT")
    assert first is not None
    assert first["version"] == 1
    assert first["value"]["price"] == 100

    state.ingest_ticker(_ticker(timestamp_ms=2_000, sequence=2, price=101), received_at_ms=2_000)
    latest_runtime = state.current_quote("BTCUSDT", now_ms=2_000)
    sampled = database.get_json("market_quotes", "BTCUSDT")
    assert latest_runtime.price == 101
    assert sampled is not None
    assert sampled["version"] == 1
    assert sampled["value"]["price"] == 100

    state.ingest_ticker(_ticker(timestamp_ms=11_000, sequence=3, price=102), received_at_ms=11_000)
    persisted = database.get_json("market_quotes", "BTCUSDT")
    assert persisted is not None
    assert persisted["version"] == 2
    assert persisted["value"]["price"] == 102
    assert persisted["value"]["persistence_class"] == "operational_latest_snapshot"
    assert persisted["value"]["persistence_interval_ms"] == 10_000


class _Worker:
    symbols = ("BTCUSDT",)

    def __init__(self) -> None:
        self.timestamp_ms = 1_000
        self.price = 100.0

    def start(self) -> None:
        return None

    def quote(self, symbol: str) -> dict:
        assert symbol == "BTCUSDT"
        return {
            "verified": True,
            "source": "bybit_public_websocket",
            "symbol": symbol,
            "price": self.price,
            "exchange_timestamp_ms": self.timestamp_ms,
            "received_at_ms": self.timestamp_ms,
        }

    def status(self) -> dict:
        return {
            "connected": True,
            "verified": True,
            "quote_ages_seconds": {"BTCUSDT": 0.0},
            "last_error": "",
        }


@dataclass
class _RestQuote:
    verified: bool = True
    change_24h_percent: float = 1.0
    volume_24h: float = 1_000.0
    source: str = "bybit"
    received_at_unix_ms: int = 1_000
    bid_price: float = 99.5
    ask_price: float = 100.5


class _Rest:
    def quote(self, symbol: str) -> _RestQuote:
        assert symbol == "BTCUSDT"
        return _RestQuote()


@dataclass
class _ConsensusQuote:
    price: float
    verified: bool = True
    source_count: int = 3
    sources: tuple[str, ...] = ("bybit", "binance", "okx")
    maximum_deviation_percent: float = 0.01


class _Consensus:
    def __init__(self, worker: _Worker) -> None:
        self.worker = worker

    def quote(self, symbol: str) -> _ConsensusQuote:
        assert symbol == "BTCUSDT"
        return _ConsensusQuote(price=self.worker.price)


def test_shared_stream_samples_raw_market_events_but_keeps_latest_decision_evidence(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("MARKET_QUOTE_EVENT_PERSIST_INTERVAL_SECONDS", "60")
    database = _database(tmp_path)
    worker = _Worker()
    stream = SharedVerifiedMarketStream(
        worker,
        _Rest(),  # type: ignore[arg-type]
        _Consensus(worker),  # type: ignore[arg-type]
        database=database,
        symbols=("BTCUSDT",),
    )

    assert stream.quote("BTCUSDT").price == 100.0
    assert len(database.list_events("market")) == 1

    worker.timestamp_ms = 2_000
    worker.price = 101.0
    assert stream.quote("BTCUSDT").price == 101.0
    evidence = stream.evidence("BTCUSDT")
    assert evidence["websocket_price"] == 101.0
    assert len(database.list_events("market")) == 1

    worker.timestamp_ms = 61_000
    worker.price = 102.0
    assert stream.quote("BTCUSDT").price == 102.0
    events = database.list_events("market")
    assert len(events) == 2
    assert events[0]["payload"]["last_price"] == 102.0
    assert events[0]["payload"]["persistence_class"] == "operational_sample"
    assert events[0]["payload"]["persistence_interval_ms"] == 60_000
