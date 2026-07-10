"""Continuous health and price-consistency monitor for five spot exchanges."""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from persistence_paths import durable_data_path
from .market_data import MarketDataService, MarketDataUnavailable


class MultiExchangeMonitor:
    """Poll all configured exchanges and persist consensus/deviation evidence."""

    def __init__(self, market_data: MarketDataService | None = None) -> None:
        self.market_data = market_data or MarketDataService()
        configured = os.getenv("MULTI_EXCHANGE_SYMBOLS", "BTCUSDT,ETHUSDT,SOLUSDT")
        self.symbols = [item.strip().upper() for item in configured.split(",") if item.strip()]
        self.interval_seconds = max(float(os.getenv("MULTI_EXCHANGE_POLL_SECONDS", "5")), 2.0)
        self.state_path = durable_data_path("MULTI_EXCHANGE_STATE_FILE", "data/multi_exchange_market.json")
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="multi-exchange-monitor", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def cycle(self) -> dict[str, Any]:
        checked_at = datetime.now(UTC).isoformat()
        symbols: dict[str, Any] = {}
        for symbol in self.symbols:
            snapshot = self.market_data.all_quotes(symbol)
            quote_rows = [item.to_dict() for item in snapshot["quotes"]]
            try:
                consensus = self.market_data.consensus_quote(symbol).to_dict()
                status = "ok"
                alert = bool((consensus.get("deviation_percent") or 0) > 0.35)
                error = None
            except MarketDataUnavailable as exc:
                consensus = None
                status = "warning"
                alert = True
                error = str(exc)
            symbols[symbol] = {
                "status": status,
                "online_count": snapshot["online_count"],
                "offline_count": snapshot["offline_count"],
                "configured_sources": snapshot["configured_sources"],
                "quotes": quote_rows,
                "provider_errors": snapshot["errors"],
                "consensus": consensus,
                "deviation_alert": alert,
                "error": error,
            }
        state = {
            "status": "ok" if all(row["status"] == "ok" for row in symbols.values()) else "warning",
            "checked_at": checked_at,
            "poll_interval_seconds": self.interval_seconds,
            "minimum_exchange_count": 5,
            "thread_alive": bool(self._thread and self._thread.is_alive()),
            "symbols": symbols,
        }
        self._save(state)
        return state

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            if not self.state_path.exists():
                return {
                    "status": "not_started",
                    "minimum_exchange_count": 5,
                    "thread_alive": bool(self._thread and self._thread.is_alive()),
                    "symbols": {},
                }
            try:
                data = json.loads(self.state_path.read_text(encoding="utf-8"))
                data["thread_alive"] = bool(self._thread and self._thread.is_alive())
                return data
            except Exception as exc:
                return {"status": "error", "error": f"{type(exc).__name__}: {exc}", "symbols": {}}

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.cycle()
            except Exception as exc:
                self._save({
                    "status": "error",
                    "checked_at": datetime.now(UTC).isoformat(),
                    "error": f"{type(exc).__name__}: {exc}",
                    "minimum_exchange_count": 5,
                    "symbols": {},
                })
            self._stop.wait(self.interval_seconds)

    def _save(self, state: dict[str, Any]) -> None:
        with self._lock:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = Path(str(self.state_path) + ".tmp")
            temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(self.state_path)
