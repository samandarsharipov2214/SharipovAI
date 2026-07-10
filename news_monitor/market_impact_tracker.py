"""Track verified market reactions after real news events.

The tracker reuses the existing MarketDataService. It never creates synthetic
prices: an unavailable quote leaves the observation pending for a later retry.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Callable

from exchange_connector.market_data import MarketDataService, MarketDataUnavailable, MarketQuote
from persistence_paths import durable_data_path
from .storage import load_news_state

SIX_MONTHS_SECONDS = 183 * 86400
ONE_YEAR_SECONDS = 365 * 86400


def _default_state_path() -> Path:
    explicit = os.getenv("NEWS_MARKET_IMPACT_STATE_FILE")
    if explicit:
        return Path(explicit)
    if os.name == "nt":
        return Path(r"D:\SharipovAI\data\news_market_impact.json")
    return durable_data_path("NEWS_MARKET_IMPACT_STATE_FILE", "data/news_market_impact.json")


@dataclass(frozen=True, slots=True)
class PendingObservation:
    observation_id: str
    news_id: str
    title: str
    source_id: str
    symbol: str
    tags: tuple[str, ...]
    price_before: float
    quote_source_before: str
    captured_at: int
    due_at: int
    horizon_minutes: int
    attempts: int = 0
    last_error: str = ""


class NewsMarketImpactTracker:
    """Capture before/after quotes and build evidence-backed news patterns."""

    def __init__(
        self,
        *,
        market_data: MarketDataService | None = None,
        state_path: str | Path | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.market_data = market_data or MarketDataService()
        self.state_path = Path(state_path) if state_path else _default_state_path()
        self.clock = clock
        self.horizon_minutes = max(1, int(os.getenv("NEWS_IMPACT_HORIZON_MINUTES", "60")))
        self.material_threshold = max(0.1, float(os.getenv("NEWS_IMPACT_MATERIAL_PERCENT", "1.0")))
        self._lock = threading.RLock()

    def scan_new_news(self) -> dict[str, Any]:
        """Capture a verified before-price for every new symbol-bearing news item."""
        state = self._load()
        news_state = load_news_state()
        news = news_state.get("news", {}) if isinstance(news_state.get("news"), dict) else {}
        items = [item for item in news.get("items", []) if isinstance(item, dict)]
        captured = 0
        skipped_no_symbol = 0
        quote_errors: list[str] = []
        known_news = set(state.get("seen_news_ids", []))
        now = int(self.clock())

        for item in items:
            news_id = _news_id(item)
            if news_id in known_news:
                continue
            symbols = infer_symbols(item)
            if not symbols:
                skipped_no_symbol += 1
                known_news.add(news_id)
                continue
            for symbol in symbols:
                observation_id = f"{news_id}:{symbol}"
                if observation_id in state.get("pending", {}) or observation_id in state.get("history", {}):
                    continue
                try:
                    quote = self.market_data.quote(symbol)
                except (MarketDataUnavailable, ValueError) as exc:
                    quote_errors.append(f"{symbol}: {exc}")
                    continue
                if not quote.verified or quote.price <= 0:
                    quote_errors.append(f"{symbol}: unverified quote")
                    continue
                pending = PendingObservation(
                    observation_id=observation_id,
                    news_id=news_id,
                    title=str(item.get("title") or item.get("headline") or "").strip(),
                    source_id=str(item.get("source_id") or item.get("source") or "unknown"),
                    symbol=symbol,
                    tags=tuple(sorted(_tags(item))),
                    price_before=quote.price,
                    quote_source_before=quote.source,
                    captured_at=now,
                    due_at=now + self.horizon_minutes * 60,
                    horizon_minutes=self.horizon_minutes,
                )
                state.setdefault("pending", {})[observation_id] = asdict(pending)
                captured += 1
            known_news.add(news_id)

        state["seen_news_ids"] = list(known_news)[-10000:]
        state["last_scan_at"] = now
        state["last_scan_errors"] = quote_errors[-50:]
        self._cleanup(state, now)
        self._save(state)
        return {"status": "ok", "captured": captured, "skipped_no_symbol": skipped_no_symbol, "quote_errors": quote_errors}

    def finalize_due(self) -> dict[str, Any]:
        """Fetch verified after-prices for observations whose horizon elapsed."""
        state = self._load()
        now = int(self.clock())
        completed = 0
        retries = 0
        pending = dict(state.get("pending", {}))
        for observation_id, raw in pending.items():
            if int(raw.get("due_at", 0)) > now:
                continue
            try:
                quote = self.market_data.quote(str(raw["symbol"]))
                if not quote.verified or quote.price <= 0:
                    raise MarketDataUnavailable("unverified after quote")
            except (MarketDataUnavailable, ValueError) as exc:
                raw["attempts"] = int(raw.get("attempts", 0)) + 1
                raw["last_error"] = f"{type(exc).__name__}: {exc}"
                raw["due_at"] = now + min(300 * raw["attempts"], 3600)
                state.setdefault("pending", {})[observation_id] = raw
                retries += 1
                continue

            before = float(raw["price_before"])
            change = ((quote.price - before) / before) * 100
            material = abs(change) >= self.material_threshold
            record = {
                **raw,
                "price_after": quote.price,
                "quote_source_after": quote.source,
                "completed_at": now,
                "change_percent": round(change, 6),
                "direction": "up" if change > 0 else "down" if change < 0 else "flat",
                "material": material,
                "expires_at": now + (ONE_YEAR_SECONDS if material else SIX_MONTHS_SECONDS),
                "verified_before": True,
                "verified_after": True,
                "synthetic_fallback_used": False,
            }
            state.setdefault("history", {})[observation_id] = record
            state.setdefault("pending", {}).pop(observation_id, None)
            completed += 1

        state["last_finalize_at"] = now
        self._cleanup(state, now)
        self._save(state)
        return {"status": "ok", "completed": completed, "retries": retries, "pending": len(state.get("pending", {}))}

    def pattern_for(self, *, title: str, symbol: str, tags: list[str] | None = None) -> dict[str, Any]:
        """Return a pattern only after at least two similar material outcomes."""
        query = _tokens(title, tags or [])
        matches: list[dict[str, Any]] = []
        for record in self._load().get("history", {}).values():
            if str(record.get("symbol", "")).upper() != symbol.upper() or not record.get("material"):
                continue
            similarity = _jaccard(query, _tokens(str(record.get("title", "")), record.get("tags", [])))
            if similarity >= 0.30:
                matches.append({"title": record.get("title"), "similarity": round(similarity, 4), "direction": record.get("direction"), "change_percent": record.get("change_percent")})
        up = sum(item["direction"] == "up" for item in matches)
        down = sum(item["direction"] == "down" for item in matches)
        dominant = max(up, down)
        usable = len(matches) >= 2 and dominant >= 2
        direction = "up" if usable and up > down else "down" if usable and down > up else "unknown"
        return {
            "symbol": symbol.upper(),
            "match_count": len(matches),
            "expected_direction": direction,
            "pattern_confidence": round(dominant / len(matches), 4) if matches else 0.0,
            "usable_for_decision": usable,
            "matches": sorted(matches, key=lambda item: item["similarity"], reverse=True),
            "warning": "Historical reaction is a risk factor, not a guaranteed forecast.",
        }

    def status(self) -> dict[str, Any]:
        state = self._load()
        return {"status": "ok", "path": str(self.state_path), "pending": len(state.get("pending", {})), "history": len(state.get("history", {})), "last_scan_at": state.get("last_scan_at"), "last_finalize_at": state.get("last_finalize_at"), "last_scan_errors": state.get("last_scan_errors", [])}

    def cycle(self) -> dict[str, Any]:
        return {"scan": self.scan_new_news(), "finalize": self.finalize_due(), "status": self.status()}

    def _load(self) -> dict[str, Any]:
        with self._lock:
            if not self.state_path.exists():
                return {"pending": {}, "history": {}, "seen_news_ids": []}
            try:
                payload = json.loads(self.state_path.read_text(encoding="utf-8"))
                return payload if isinstance(payload, dict) else {"pending": {}, "history": {}, "seen_news_ids": []}
            except Exception:
                return {"pending": {}, "history": {}, "seen_news_ids": []}

    def _save(self, state: dict[str, Any]) -> None:
        with self._lock:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
            temp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
            temp.replace(self.state_path)

    @staticmethod
    def _cleanup(state: dict[str, Any], now: int) -> None:
        state["history"] = {key: value for key, value in state.get("history", {}).items() if int(value.get("expires_at", now + 1)) > now}


def infer_symbols(item: dict[str, Any]) -> list[str]:
    """Infer only explicit supported crypto symbols; never assume an asset."""
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    explicit = item.get("symbol") or metadata.get("symbol")
    if explicit:
        clean = str(explicit).upper().replace("/", "").replace("-", "")
        return [clean] if clean.endswith("USDT") else [f"{clean}USDT"]
    text = " ".join(str(item.get(field, "")) for field in ("title", "content", "summary")).lower()
    aliases = {
        "BTCUSDT": ("bitcoin", " btc ", "btc/", "btc-"),
        "ETHUSDT": ("ethereum", " ether", " eth ", "eth/", "eth-"),
        "SOLUSDT": ("solana", " sol ", "sol/", "sol-"),
    }
    padded = f" {text} "
    return [symbol for symbol, words in aliases.items() if any(word in padded for word in words)]


def _news_id(item: dict[str, Any]) -> str:
    raw = "|".join(str(item.get(key, "")) for key in ("source_id", "url", "title", "published_at"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _tags(item: dict[str, Any]) -> set[str]:
    raw = item.get("tags", [])
    values = raw if isinstance(raw, list) else [raw]
    values.extend([item.get("category", ""), item.get("impact", "")])
    return {str(value).strip().lower().replace(" ", "_") for value in values if str(value).strip()}


def _tokens(title: str, tags: list[str] | tuple[str, ...]) -> set[str]:
    text = " ".join([title, *[str(tag) for tag in tags]]).lower()
    return {token for token in re.findall(r"[\w-]+", text) if len(token) > 2}


def _jaccard(left: set[str], right: set[str]) -> float:
    return len(left & right) / len(left | right) if left and right else 0.0
