"""Continuous verified Bybit spot market stream."""
from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from websockets.sync.client import connect


@dataclass(frozen=True, slots=True)
class StreamQuote:
    symbol: str
    price: float
    change_24h_percent: float | None
    volume_24h: float | None
    source: str
    received_at: str
    received_at_unix_ms: int
    verified: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class MarketStream:
    def __init__(self, symbols: list[str] | None = None) -> None:
        configured = os.getenv("MARKET_STREAM_SYMBOLS", "BTCUSDT,ETHUSDT,SOLUSDT")
        self.symbols = symbols or [x.strip().upper() for x in configured.split(",") if x.strip()]
        self.state_file = Path(os.getenv("MARKET_STREAM_STATE_FILE", "data/market_stream.json"))
        self.stale_after = max(float(os.getenv("MARKET_STREAM_STALE_SECONDS", "15")), 3.0)
        self._quotes: dict[str, StreamQuote] = {}
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._connected = False
        self._last_error = ""

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="market-stream", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def quote(self, symbol: str) -> StreamQuote:
        clean = symbol.strip().upper().replace("/", "").replace("-", "")
        with self._lock:
            quote = self._quotes.get(clean)
        if quote is None:
            raise RuntimeError(f"No streamed quote for {clean}")
        age = time.time() - quote.received_at_unix_ms / 1000
        if age > self.stale_after:
            raise RuntimeError(f"Streamed quote for {clean} is stale ({age:.1f}s)")
        return quote

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            quotes = {k: v.to_dict() for k, v in self._quotes.items()}
            newest = max((v.received_at_unix_ms for v in self._quotes.values()), default=0)
        age = None if not newest else max(0.0, time.time() - newest / 1000)
        verified = bool(quotes) and age is not None and age <= self.stale_after
        return {"status": "live" if self._connected and verified else "stale", "connected": self._connected,
                "verified": verified, "source": "bybit_websocket", "age_seconds": age,
                "symbols": self.symbols, "quotes": quotes, "last_error": self._last_error,
                "synthetic_fallback_used": False}

    def _run(self) -> None:
        delay = 1.0
        while not self._stop.is_set():
            try:
                self._consume()
                delay = 1.0
            except Exception as exc:
                self._connected = False
                self._last_error = f"{type(exc).__name__}: {exc}"
                self._persist()
                self._stop.wait(delay)
                delay = min(delay * 2, 30.0)

    def _consume(self) -> None:
        topics = [f"tickers.{symbol}" for symbol in self.symbols]
        with connect("wss://stream.bybit.com/v5/public/spot", open_timeout=10, close_timeout=5,
                     ping_interval=20, ping_timeout=10) as websocket:
            websocket.send(json.dumps({"op": "subscribe", "args": topics}))
            self._connected = True
            self._last_error = ""
            for raw in websocket:
                if self._stop.is_set():
                    return
                payload = json.loads(raw)
                data = payload.get("data")
                if not isinstance(data, dict):
                    continue
                symbol = str(data.get("symbol", "")).upper()
                price = float(data.get("lastPrice", 0) or 0)
                if symbol not in self.symbols or price <= 0:
                    continue
                now = datetime.now(UTC)
                change, turnover = data.get("price24hPcnt"), data.get("turnover24h")
                quote = StreamQuote(symbol, price,
                    None if change in (None, "") else float(change) * 100,
                    None if turnover in (None, "") else max(float(turnover), 0.0),
                    "bybit_websocket", now.isoformat(), int(now.timestamp() * 1000))
                with self._lock:
                    self._quotes[symbol] = quote
                self._persist()

    def _persist(self) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        temp = self.state_file.with_suffix(self.state_file.suffix + ".tmp")
        temp.write_text(json.dumps(self.snapshot(), ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(self.state_file)
