"""Hard market-data gate for real-money order execution.

Live orders require a fresh WebSocket quote plus recent cross-exchange agreement.
The guard is fail-closed: missing, stale, divergent, or malformed evidence blocks
execution. It does not enable live trading by itself.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

from persistence_paths import durable_data_path


@dataclass(frozen=True, slots=True)
class LiveMarketAssessment:
    allowed: bool
    symbol: str
    stream_price: float | None
    consensus_price: float | None
    stream_age_seconds: float | None
    consensus_age_seconds: float | None
    online_exchanges: int
    deviation_percent: float | None
    reference_slippage_percent: float | None
    blockers: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class LiveExecutionGuard:
    """Validate fresh market evidence immediately before a live order."""

    def __init__(self) -> None:
        self.stream_file = Path(os.getenv("MARKET_STREAM_STATE_FILE", "data/market_stream.json"))
        self.consensus_file = durable_data_path("MULTI_EXCHANGE_STATE_FILE", "data/multi_exchange_market.json")
        self.max_stream_age = max(float(os.getenv("LIVE_MAX_STREAM_AGE_SECONDS", "1.0")), 0.1)
        self.max_consensus_age = max(float(os.getenv("LIVE_MAX_CONSENSUS_AGE_SECONDS", "2.5")), 0.5)
        self.min_exchanges = max(int(os.getenv("LIVE_MIN_CONSENSUS_EXCHANGES", "3")), 3)
        self.max_deviation = max(float(os.getenv("LIVE_MAX_EXCHANGE_DEVIATION_PERCENT", "0.35")), 0.01)
        self.max_reference_slippage = max(float(os.getenv("LIVE_MAX_REFERENCE_SLIPPAGE_PERCENT", "0.20")), 0.01)

    def assess(self, *, symbol: str, reference_price: float) -> LiveMarketAssessment:
        symbol = symbol.strip().upper().replace("/", "").replace("-", "")
        now = time.time()
        blockers: list[str] = []
        stream_price: float | None = None
        consensus_price: float | None = None
        stream_age: float | None = None
        consensus_age: float | None = None
        online = 0
        deviation: float | None = None
        slippage: float | None = None

        stream = _load_json(self.stream_file)
        quote = (stream.get("quotes") or {}).get(symbol) if isinstance(stream, dict) else None
        if isinstance(quote, dict):
            try:
                stream_price = float(quote.get("price"))
                received_ms = int(quote.get("received_at_unix_ms", 0))
                stream_age = max(0.0, now - received_ms / 1000)
            except (TypeError, ValueError):
                blockers.append("stream quote is malformed")
        else:
            blockers.append("stream quote is missing")
        if stream_price is not None and stream_price <= 0:
            blockers.append("stream price is invalid")
        if stream_age is None or stream_age > self.max_stream_age:
            blockers.append("stream quote is stale")
        if not bool(stream.get("verified", False)):
            blockers.append("stream is not verified")

        snapshot = _load_json(self.consensus_file)
        row = (snapshot.get("symbols") or {}).get(symbol) if isinstance(snapshot, dict) else None
        if isinstance(row, dict):
            online = int(row.get("online_count", 0) or 0)
            consensus = row.get("consensus")
            if isinstance(consensus, dict):
                try:
                    consensus_price = float(consensus.get("price"))
                    deviation = float(consensus.get("deviation_percent", 0) or 0)
                except (TypeError, ValueError):
                    blockers.append("consensus quote is malformed")
            checked_at = snapshot.get("checked_at")
            consensus_age = _iso_age_seconds(checked_at, now)
        else:
            blockers.append("cross-exchange consensus is missing")

        if online < self.min_exchanges:
            blockers.append(f"only {online} exchanges online; minimum is {self.min_exchanges}")
        if consensus_price is None or consensus_price <= 0:
            blockers.append("consensus price is invalid")
        if consensus_age is None or consensus_age > self.max_consensus_age:
            blockers.append("cross-exchange consensus is stale")
        if deviation is None or deviation > self.max_deviation:
            blockers.append("cross-exchange deviation is too high")

        if consensus_price and reference_price > 0:
            slippage = abs(reference_price - consensus_price) / consensus_price * 100
            if slippage > self.max_reference_slippage:
                blockers.append("reference price differs from consensus beyond slippage limit")
        else:
            blockers.append("reference price cannot be validated")

        if stream_price and consensus_price:
            stream_vs_consensus = abs(stream_price - consensus_price) / consensus_price * 100
            if stream_vs_consensus > self.max_reference_slippage:
                blockers.append("WebSocket price diverges from exchange consensus")

        return LiveMarketAssessment(
            allowed=not blockers,
            symbol=symbol,
            stream_price=stream_price,
            consensus_price=consensus_price,
            stream_age_seconds=None if stream_age is None else round(stream_age, 6),
            consensus_age_seconds=None if consensus_age is None else round(consensus_age, 6),
            online_exchanges=online,
            deviation_percent=deviation,
            reference_slippage_percent=None if slippage is None else round(slippage, 6),
            blockers=tuple(blockers),
        )


def _load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _iso_age_seconds(value: Any, now: float) -> float | None:
    if not value:
        return None
    try:
        from datetime import datetime
        return max(0.0, now - datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp())
    except Exception:
        return None
