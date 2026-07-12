from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI

from autonomous_trading.market_stream import MarketStream
from dashboard.autonomous_trading_api import install_autonomous_trading_api
from dashboard.database_api import install_database_api
from dashboard.market_data_api import install_market_data_api
from exchange_connector.bybit_websocket_state import BybitWebSocketState
from storage import ProjectDatabase


class Worker:
    url = "wss://stream.bybit.com/v5/public/spot"
    symbols = ("BTCUSDT", "ETHUSDT")

    def __init__(self, *, missing: str = ""):
        self.missing = missing
        self.started = 0
        self.stopped = 0

    def start(self):
        self.started += 1

    def stop(self):
        self.stopped += 1

    def status(self):
        return {
            "connected": True,
            "verified": True,
            "worker_running": True,
            "database_backed": True,
            "last_error": "",
        }

    def quote(self, symbol: str):
        if symbol == self.missing:
            raise RuntimeError("missing quote")
        return {
            "verified": True,
            "source": "bybit_public_websocket",
            "symbol": symbol,
            "price": 100.0 if symbol == "BTCUSDT" else 50.0,
            "change_24h_percent": 5.0,
            "exchange_timestamp_ms": 1_000,
            "received_at_ms": 1_000,
            "age_seconds": 0.1,
        }


def database(tmp_path: Path) -> ProjectDatabase:
    value = ProjectDatabase(f"sqlite:///{tmp_path / 'shared.db'}")
    value.initialize()
    return value


def test_verified_quote_and_change_are_saved_in_shared_database(tmp_path: Path) -> None:
    db = database(tmp_path)
    state = BybitWebSocketState(database=db, max_age_seconds=2)
    state.mark_connected(connected_at_ms=1_000)
    quote = state.ingest_ticker({
        "topic": "tickers.BTCUSDT",
        "type": "snapshot",
        "ts": 1_000,
        "cs": 1,
        "data": {"symbol": "BTCUSDT", "lastPrice": "100", "price24hPcnt": "0.05"},
    }, received_at_ms=1_000)
    assert quote.change_24h_percent == 5.0
    current = state.current_quote("BTCUSDT", now_ms=1_100)
    assert current["verified"] is True
    assert current["database_backed"] is True
    stored = db.get_json("market_quotes", "BTCUSDT")
    assert stored and stored["value"]["price"] == 100.0
    assert stored["value"]["change_24h_percent"] == 5.0


def test_nonfinite_change_and_disconnect_fail_closed(tmp_path: Path) -> None:
    state = BybitWebSocketState(database=database(tmp_path), max_age_seconds=2)
    state.mark_connected(connected_at_ms=1_000)
    with pytest.raises(ValueError, match="finite"):
        state.ingest_ticker({
            "topic": "tickers.BTCUSDT", "type": "snapshot", "ts": 1_000,
            "data": {"symbol": "BTCUSDT", "lastPrice": "100", "price24hPcnt": "NaN"},
        }, received_at_ms=1_000)
    state.ingest_ticker({
        "topic": "tickers.BTCUSDT", "type": "snapshot", "ts": 1_000, "cs": 1,
        "data": {"symbol": "BTCUSDT", "lastPrice": "100"},
    }, received_at_ms=1_000)
    state.mark_disconnected("network", disconnected_at_ms=1_100)
    with pytest.raises(RuntimeError, match="disconnected"):
        state.current_quote("BTCUSDT", now_ms=1_100)


def test_market_stream_reuses_worker_and_requires_all_symbols() -> None:
    worker = Worker()
    stream = MarketStream(worker=worker)  # type: ignore[arg-type]
    stream.start()
    stream.stop()
    assert worker.started == 1 and worker.stopped == 1
    snapshot = stream.snapshot()
    assert snapshot["verified"] is True
    assert snapshot["shared_worker"] is True
    assert len(snapshot["quotes"]) == 2

    incomplete = MarketStream(worker=Worker(missing="ETHUSDT"))  # type: ignore[arg-type]
    result = incomplete.snapshot()
    assert result["verified"] is False
    assert "ETHUSDT" in result["quote_errors"]


def test_dashboard_and_paper_share_exact_worker(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'shared.db'}")
    monkeypatch.setenv("SHARIPOVAI_DATABASE_REQUIRED", "1")
    monkeypatch.setenv("AUTONOMOUS_PAPER_STATE_FILE", str(tmp_path / "paper.json"))
    monkeypatch.setenv("TESTNET_BRIDGE_STATE_FILE", str(tmp_path / "bridge.json"))
    monkeypatch.setenv("EXECUTION_JOURNAL_FILE", str(tmp_path / "journal.json"))
    monkeypatch.setenv("BYBIT_WS_SYMBOLS", "BTCUSDT,ETHUSDT,SOLUSDT")
    monkeypatch.setenv("MARKET_STREAM_SYMBOLS", "BTCUSDT,ETHUSDT,SOLUSDT")
    app = FastAPI()
    install_database_api(app)
    install_market_data_api(app)
    install_autonomous_trading_api(app)
    assert app.state.market_stream.worker is app.state.bybit_websocket_worker
    assert app.state.autonomous_paper_loop.stream is app.state.market_stream
    assert app.state.autonomous_paper_loop.database is app.state.project_database
    assert app.state.autonomous_testnet_bridge.database is app.state.project_database
